"""Agent memory inspection and management across claw types.

Dispatches per-agent memory operations to the appropriate
``memory_<op>`` playbook. The set of memory-capable claws is driven by
each manifest's ``features.memory: true`` flag — see
``clawrium.core.registry.AgentManifest``. The on-disk workspace path is
encoded in each claw's own playbooks (e.g. ``~/.openclaw/workspace`` for
openclaw, ``~/.hermes/memories`` for hermes); the manifest's
``workspace.memory_path`` is surfaced to users for display.

Public functions:
    - get_memory_info(hostname, agent_name) -> MemoryStats | None
    - read_memory_file(hostname, agent_name, filename) -> str | None
    - write_memory_file(hostname, agent_name, filename, content) -> tuple[bool, str | None]
    - delete_memory_files(hostname, agent_name, files) -> tuple[bool, str | None]

All operations degrade gracefully on transport errors: read/info return
``None`` and write/delete return ``(False, error_message)`` so callers can
present an "unavailable" state instead of raising.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import ansible_runner

from clawrium.core import keys as core_keys
from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host
from clawrium.core.registry import (
    ManifestNotFoundError,
    ManifestParseError,
    load_manifest,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_MEMORY_CONTENT_BYTES",
    "MEMORY_TOP_LEVEL_FILES",
    "MemoryFileInfo",
    "MemoryStats",
    "MemoryOpError",
    "claw_supports_memory",
    "get_memory_info",
    "read_memory_file",
    "write_memory_file",
    "delete_memory_files",
]

# Maximum bytes accepted by write_memory_file. Memory files are intended for
# short-form context (soul, identity, daily notes), and Ansible extravars are
# loaded entirely into memory on both ends — bound the input to prevent a
# bogus megabytes-of-content write from exhausting the runner.
MAX_MEMORY_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MiB

# Top-level workspace files surfaced to the user, keyed by claw type.
# Daily files under ``memory/`` are discovered dynamically by get_memory_info.
#
# The authoritative file list is the one each claw's ``memory_info.yaml``
# playbook iterates; this mapping documents the same set on the Python side
# for tests and any future cross-claw inspection that needs to know "what
# files does claw X surface as memory?" before reaching the daemon.
#
# Zeroclaw deliberately omits ``BOOTSTRAP.md``: the runtime generates it on
# first boot and self-deletes after use, so it must never appear in the
# operator-facing memory list (issue #358 W8).
MEMORY_TOP_LEVEL_FILES: dict[str, tuple[str, ...]] = {
    "openclaw": (
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "TOOLS.md",
    ),
    "hermes": (
        "MEMORY.md",
        "USER.md",
        "SOUL.md",
    ),
    "zeroclaw": (
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "AGENTS.md",
        "TOOLS.md",
        "MEMORY.md",
        "HEARTBEAT.md",
    ),
}

# Per-claw character limits applied during memory_write. None = no limit.
# Hermes enforces strict caps for its two-file memory model; openclaw uses
# the global MAX_MEMORY_CONTENT_BYTES cap only.
_MEMORY_WRITE_CHAR_LIMITS: dict[str, dict[str, int]] = {
    "hermes": {
        "MEMORY.md": 2200,
        "USER.md": 1375,
        "SOUL.md": 3000,
    },
}

# Per-claw filename allowlists for memory_write. None = any valid filename
# (subject to filename pattern + traversal rejection). Hermes restricts to
# its fixed two-file model.
_MEMORY_WRITE_ALLOWED_FILES: dict[str, tuple[str, ...]] = {
    "hermes": ("MEMORY.md", "USER.md", "SOUL.md"),
}

# Workspace-relative path validation: filename or memory/<filename>.
# Mirrors the pattern enforced in the playbooks.
_MEMORY_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?$")

# Agent-name validation matches the rule used elsewhere in lifecycle.py.
_AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

_REGISTRY_DIR = Path(__file__).parent.parent / "platform" / "registry"

# Backward-compatible default playbook dir (openclaw). Existing tests patch
# this symbol to inject a temporary playbook directory; the new
# ``_get_playbook_dir`` helper falls back here for the openclaw claw type so
# those patches continue to work without modification.
_PLAYBOOK_DIR = _REGISTRY_DIR / "openclaw" / "playbooks"


class MemoryFileInfo(TypedDict):
    name: str
    exists: bool
    size_bytes: int
    relative_path: str  # workspace-relative, e.g. "SOUL.md" or "memory/2026-05-09.md"


class MemoryStats(TypedDict):
    workspace_path: str
    total_bytes: int
    files: list[MemoryFileInfo]


class MemoryOpError(Exception):
    """Raised when memory operation arguments are invalid."""


def _validate_agent_name(agent_name: str) -> None:
    if not _AGENT_NAME_PATTERN.match(agent_name):
        raise MemoryOpError(
            f"Invalid agent_name format: '{agent_name}'. Must start with "
            "lowercase letter and contain only lowercase letters, digits, "
            "hyphens, underscores (max 32 chars)."
        )


def _validate_memory_filename(filename: str) -> None:
    safe_repr = repr(filename)[:64]
    if not _MEMORY_FILENAME_PATTERN.match(filename):
        raise MemoryOpError(
            f"Invalid memory filename: {safe_repr}. Allowed: <name> or "
            "memory/<name> with [A-Za-z0-9._-] components."
        )
    # The pattern alone allows '..' (any sequence of dot/dash/underscore/
    # alphanumeric). Reject path-traversal components explicitly.
    for component in filename.split("/"):
        if component in {"", ".", ".."}:
            raise MemoryOpError(
                f"Invalid memory filename: {safe_repr}. Path traversal "
                "components ('.', '..') are not allowed."
            )


def claw_supports_memory(claw_type: str) -> bool:
    """Return True iff the claw_type's manifest declares features.memory: true.

    Used by the CLI layer to emit a friendly error before attempting any
    Ansible dispatch on an unsupported agent type. Treats manifest-missing
    or parse-error cases as "no" so a partially-installed registry does
    not appear memory-capable.
    """
    try:
        manifest = load_manifest(claw_type)
    except (ManifestNotFoundError, ManifestParseError) as e:
        # Expected: unknown claw type or malformed manifest. Treat as
        # unsupported so the caller surfaces a friendly "type X not memory-
        # capable" error rather than crashing.
        logger.debug(
            "Memory support check: manifest load failed for '%s': %s",
            claw_type,
            e,
        )
        return False
    except Exception as e:  # pragma: no cover — defensive
        # Unexpected: a bug inside load_manifest (e.g. TypeError) should NOT
        # silently mask all memory ops. Log loudly so it shows up in
        # operator output, then conservatively treat the type as
        # unsupported. The previous `except Exception` clause swallowed
        # these without a warning, which made debugging hard.
        logger.warning(
            "Memory support check: unexpected error loading manifest for "
            "'%s': %s",
            claw_type,
            e,
        )
        return False
    features = manifest.get("features") or {}
    return bool(features.get("memory") is True)


def _get_playbook_dir(claw_type: str) -> Path:
    """Resolve the registry playbook dir for a claw type.

    Returns ``_PLAYBOOK_DIR`` for openclaw so legacy tests that patch the
    module-global ``_PLAYBOOK_DIR`` continue to work. For other claw types
    the path is computed from the registry layout.
    """
    if claw_type == "openclaw":
        return _PLAYBOOK_DIR
    return _REGISTRY_DIR / claw_type / "playbooks"


def _resolve_agent_with_memory(
    hostname: str, agent_name: str
) -> tuple[dict, str, str] | tuple[None, str, None]:
    """Resolve agent identifier to (host_record, unix_agent_name, claw_type).

    Filters candidates by manifest features.memory == true rather than by a
    hard-coded claw type. On miss, returns ``(None, reason, None)`` so
    callers can distinguish "not found" / "not ready" / "unsupported" and
    emit accurate messages.
    """
    host = get_host(hostname)
    if not host:
        logger.warning("Memory op: host '%s' not found", hostname)
        return None, f"host '{hostname}' not found", None

    agents = host.get("agents", {})
    if not isinstance(agents, dict):
        return None, f"host '{hostname}' has no agents registry", None

    # Build (key, record) candidates whose stored type advertises memory.
    memory_capable_records: list[tuple[str, dict]] = []
    for key, record in agents.items():
        if not isinstance(record, dict):
            continue
        record_type = record.get("type")
        if not isinstance(record_type, str) or not record_type:
            continue
        if not claw_supports_memory(record_type):
            continue
        memory_capable_records.append((key, record))

    matches: list[tuple[str, dict]] = []
    direct = agents.get(agent_name)
    if isinstance(direct, dict):
        direct_type = direct.get("type")
        if isinstance(direct_type, str) and claw_supports_memory(direct_type):
            matches.append((agent_name, direct))

    if not matches:
        for key, record in memory_capable_records:
            if (
                key == agent_name
                or record.get("agent_name") == agent_name
                or record.get("name") == agent_name
            ):
                matches.append((key, record))

    if not matches:
        logger.warning(
            "Memory op: memory-capable agent '%s' not found on '%s'",
            agent_name,
            hostname,
        )
        return None, (
            f"memory-capable agent '{agent_name}' not found on '{hostname}'"
        ), None

    if len({k for k, _ in matches}) > 1:
        keys = sorted({k for k, _ in matches})
        logger.warning(
            "Memory op: multiple memory-capable agents match '%s' on '%s': %s",
            agent_name,
            hostname,
            keys,
        )
        return None, (
            f"multiple memory-capable agents match '{agent_name}' on '{hostname}': "
            f"{', '.join(keys)}"
        ), None

    key, record = matches[0]
    claw_type = record.get("type")
    # Allowlist: only records with status='installed' or no status field run
    # memory ops. install.py writes status='installing' before Ansible runs and
    # 'installed' on success — None means a pre-convention legacy record, not
    # a partial new install. Treating None as installed keeps backward compat
    # while a future status (e.g. 'removing') is rejected by default rather
    # than silently passing through a blocklist gap.
    status = record.get("status")
    if status is not None and status != "installed":
        logger.warning(
            "Memory op: agent '%s' on '%s' has status '%s' (must be 'installed')",
            agent_name,
            hostname,
            status,
        )
        return None, (
            f"agent '{agent_name}' on '{hostname}' is not ready "
            f"(status='{status}', expected 'installed')"
        ), None

    unix_name = record.get("agent_name") or key
    return host, unix_name, claw_type


def _resolve_openclaw_agent(
    hostname: str, agent_name: str
) -> tuple[dict, str] | tuple[None, str]:
    """Legacy two-tuple resolver constrained to the openclaw claw type.

    Kept for backward compatibility with code/tests that pre-date the
    cross-claw memory dispatcher. New code should use
    ``_resolve_agent_with_memory``.
    """
    host = get_host(hostname)
    if not host:
        logger.warning("Memory op: host '%s' not found", hostname)
        return None, f"host '{hostname}' not found"

    agents = host.get("agents", {})
    if not isinstance(agents, dict):
        return None, f"host '{hostname}' has no agents registry"

    matches: list[str] = []
    direct = agents.get(agent_name)
    if isinstance(direct, dict) and direct.get("type") == "openclaw":
        matches.append(agent_name)
    else:
        for key, record in agents.items():
            if not isinstance(record, dict) or record.get("type") != "openclaw":
                continue
            if (
                key == agent_name
                or record.get("agent_name") == agent_name
                or record.get("name") == agent_name
            ):
                matches.append(key)

    if not matches:
        logger.warning(
            "Memory op: openclaw agent '%s' not found on '%s'", agent_name, hostname
        )
        return None, f"openclaw agent '{agent_name}' not found on '{hostname}'"
    if len(matches) > 1:
        logger.warning(
            "Memory op: multiple openclaw agents match '%s' on '%s': %s",
            agent_name,
            hostname,
            matches,
        )
        return None, (
            f"multiple openclaw agents match '{agent_name}' on '{hostname}': "
            f"{', '.join(matches)}"
        )

    record = agents[matches[0]]
    status = record.get("status")
    if status is not None and status != "installed":
        logger.warning(
            "Memory op: agent '%s' on '%s' has status '%s' (must be 'installed')",
            agent_name,
            hostname,
            status,
        )
        return None, (
            f"agent '{agent_name}' on '{hostname}' is not ready "
            f"(status='{status}', expected 'installed')"
        )

    unix_name = record.get("agent_name") or matches[0]
    return host, unix_name


def _get_logs_dir() -> Path:
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _cleanup_artifacts(operation_log_dir: Path) -> None:
    """Remove ansible-runner artifacts that may contain inventory secrets.

    Mirrors the cleanup used in lifecycle._cleanup_ansible_artifacts so memory
    operations do not leak SSH key paths, extravars, or inventory contents on
    disk. ``inventory/`` is included alongside ``artifacts/`` and ``env/``
    because ansible-runner writes ``memory_content_b64`` and other extravars
    there; without this, the security justification for removing ``no_log``
    from the read playbook would only hold partway.
    """
    for sub in ("artifacts", "env", "inventory"):
        target = operation_log_dir / sub
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as e:
                logger.warning("Failed to clean up %s: %s", target, e)


def _build_inventory(
    host: dict, ssh_key: Path, extra_vars: dict
) -> dict:
    return {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": extra_vars,
        }
    }


def _run_memory_playbook(
    host: dict,
    claw_type: str,
    operation: str,
    extra_vars: dict,
    timeout: int = 30,
):
    """Run a memory-* playbook and return the ansible-runner result.

    Returns ``(result, log_dir, error)``. On any setup failure the result
    is ``None`` and ``error`` is populated. Callers own artifact cleanup
    via their ``finally`` block — this function never calls
    ``_cleanup_artifacts`` to avoid double-fire on exception paths.
    """
    playbook_dir = _get_playbook_dir(claw_type)
    playbook_path = playbook_dir / f"{operation}.yaml"
    if not playbook_path.exists():
        return None, None, f"Playbook not found: {playbook_path}"

    key_id = host.get("key_id") or host["hostname"]
    ssh_key = core_keys.get_host_private_key(key_id)
    if not ssh_key:
        return None, None, (
            f"SSH key for host '{key_id}' not found. "
            f"Run 'clm host init {host['hostname']}' to provision it."
        )

    # Pre-flight setup must also degrade gracefully: a malformed XDG_CONFIG_HOME
    # or read-only logs/ dir would otherwise raise OSError out of the public
    # function, breaking the offline-tolerant contract.
    try:
        inventory = _build_inventory(host, ssh_key, extra_vars)
        logs_dir = _get_logs_dir()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        host_display = host.get("alias") or host.get("key_id") or host["hostname"]
        log_dir = logs_dir / f"{operation}-{claw_type}-{host_display}-{timestamp}"
        log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(log_dir, 0o700)
    except OSError as e:
        return None, None, f"Failed to set up runner workdir: {e}"

    try:
        result = ansible_runner.run(
            private_data_dir=str(log_dir),
            inventory=inventory,
            playbook=str(playbook_path),
            quiet=True,
            timeout=timeout,
        )
        return result, log_dir, None
    except Exception as e:
        # Do NOT cleanup here — caller's finally block owns cleanup. We
        # still surface the log_dir so the caller can clean it up exactly
        # once.
        return None, log_dir, str(e)


def _extract_failure_message(result, default: str) -> str:
    # SSH/network failures land as runner_on_unreachable, not runner_on_failed.
    # Prefer that signal so the user sees "Host unreachable: <reason>" rather
    # than the generic playbook status string.
    for event in result.events:
        if event.get("event") == "runner_on_unreachable":
            res = event.get("event_data", {}).get("res", {})
            msg = res.get("msg")
            if msg:
                return f"Host unreachable: {msg}"
            return "Host unreachable"
    for event in result.events:
        if event.get("event") == "runner_on_failed":
            res = event.get("event_data", {}).get("res", {})
            if "msg" in res:
                return res["msg"]
            if "stderr" in res:
                return res["stderr"]
    return default


def _parse_memory_info_stdout(stdout: str) -> dict:
    """Parse the WORKSPACE_PATH / TOP / DAILY lines from memory_info playbook."""
    workspace_path = ""
    top: list[tuple[str, int]] = []
    daily: list[tuple[str, int]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("WORKSPACE_PATH="):
            workspace_path = line.split("=", 1)[1]
        elif line.startswith("TOP "):
            parts = line.split(None, 2)
            if len(parts) == 3:
                _, name, size_str = parts
                try:
                    top.append((name, int(size_str)))
                except ValueError:
                    continue
        elif line.startswith("DAILY "):
            parts = line.split(None, 2)
            if len(parts) == 3:
                _, name, size_str = parts
                try:
                    daily.append((name, int(size_str)))
                except ValueError:
                    continue
    return {"workspace_path": workspace_path, "top": top, "daily": daily}


def _manifest_workspace_path(claw_type: str, unix_name: str) -> str:
    """Return the workspace path from the manifest, with `~` expanded for the
    agent's home directory. Falls back to an empty string on lookup failure;
    callers substitute a sensible default.
    """
    try:
        manifest = load_manifest(claw_type)
    except (ManifestNotFoundError, ManifestParseError) as e:
        logger.debug(
            "Memory workspace lookup: manifest load failed for '%s': %s",
            claw_type,
            e,
        )
        return ""
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "Memory workspace lookup: unexpected error for '%s': %s",
            claw_type,
            e,
        )
        return ""
    workspace = manifest.get("workspace") or {}
    raw = workspace.get("memory_path") or ""
    if not raw:
        return ""
    if raw.startswith("~/"):
        return f"/home/{unix_name}/{raw[2:]}"
    if raw == "~":
        return f"/home/{unix_name}"
    return raw


def get_memory_info(hostname: str, agent_name: str) -> MemoryStats | None:
    """Return memory stats for a memory-capable agent or None if unavailable."""
    host, unix_name, claw_type = _resolve_agent_with_memory(hostname, agent_name)
    if host is None:
        return None

    try:
        _validate_agent_name(unix_name)
    except MemoryOpError as e:
        logger.warning("Memory info: %s", e)
        return None

    extra_vars = {"agent_name": unix_name}
    result, log_dir, setup_error = _run_memory_playbook(
        host, claw_type, "memory_info", extra_vars, timeout=30
    )
    if log_dir is None and setup_error:
        logger.warning("Memory info setup error: %s", setup_error)
        return None

    try:
        if setup_error:
            return None
        if result.status == "timeout":
            logger.warning("Memory info timed out for %s", unix_name)
            return None
        if result.status != "successful":
            logger.warning(
                "Memory info playbook failed: %s",
                _extract_failure_message(result, result.status),
            )
            return None

        # The memory_info playbook emits structured lines via the debug
        # module. Standalone debug tasks surface as runner_on_ok events;
        # debug tasks under a loop surface as runner_item_on_ok per
        # iteration (the runner_on_ok aggregate just says "All items
        # completed"). Collect msg from both.
        lines: list[str] = []
        for event in result.events:
            if event.get("event") not in {"runner_on_ok", "runner_item_on_ok"}:
                continue
            res = event.get("event_data", {}).get("res", {})
            msg = res.get("msg")
            if isinstance(msg, str):
                lines.append(msg)
            elif isinstance(msg, list):
                for item in msg:
                    if isinstance(item, str):
                        lines.append(item)

        parsed = _parse_memory_info_stdout("\n".join(lines))

        files: list[MemoryFileInfo] = []
        total = 0
        for name, size in parsed["top"]:
            exists = size >= 0
            entry: MemoryFileInfo = {
                "name": name,
                "exists": exists,
                "size_bytes": size if exists else 0,
                "relative_path": name,
            }
            files.append(entry)
            if exists:
                total += size
        for name, size in parsed["daily"]:
            entry = {
                "name": name,
                "exists": True,
                "size_bytes": size,
                "relative_path": f"memory/{name}",
            }
            files.append(entry)
            total += size

        # Workspace path precedence:
        #   1. Playbook-emitted WORKSPACE_PATH= line (authoritative)
        #   2. Manifest workspace.memory_path expanded against agent home
        #   3. Empty string — UI renders a placeholder
        fallback = _manifest_workspace_path(claw_type, unix_name)
        return {
            "workspace_path": parsed["workspace_path"] or fallback,
            "total_bytes": total,
            "files": files,
        }
    finally:
        if log_dir is not None:
            _cleanup_artifacts(log_dir)


def read_memory_file(
    hostname: str, agent_name: str, filename: str
) -> str | None:
    """Read content of a single memory file. Returns None if unavailable."""
    try:
        _validate_memory_filename(filename)
    except MemoryOpError as e:
        logger.warning("Memory read: %s", e)
        return None

    host, unix_name, claw_type = _resolve_agent_with_memory(hostname, agent_name)
    if host is None:
        return None

    try:
        _validate_agent_name(unix_name)
    except MemoryOpError:
        return None

    extra_vars = {"agent_name": unix_name, "memory_filename": filename}
    result, log_dir, setup_error = _run_memory_playbook(
        host, claw_type, "memory_read", extra_vars, timeout=30
    )
    if log_dir is None and setup_error:
        logger.warning("Memory read setup error: %s", setup_error)
        return None

    try:
        if setup_error:
            return None
        if result.status == "timeout":
            logger.warning("Memory read timed out for %s", filename)
            return None
        if result.status != "successful":
            logger.warning(
                "Memory read playbook failed: %s",
                _extract_failure_message(result, result.status),
            )
            return None

        for event in result.events:
            if event.get("event") == "runner_on_ok":
                res = event.get("event_data", {}).get("res", {})
                content_b64 = res.get("content")
                if content_b64:
                    try:
                        return base64.b64decode(content_b64).decode("utf-8")
                    except (ValueError, UnicodeDecodeError) as e:
                        logger.warning("Failed to decode memory content: %s", e)
                        return None
        return None
    finally:
        if log_dir is not None:
            _cleanup_artifacts(log_dir)


def write_memory_file(
    hostname: str, agent_name: str, filename: str, content: str
) -> tuple[bool, str | None]:
    """Write content to a memory file. Returns (success, error)."""
    try:
        _validate_memory_filename(filename)
    except MemoryOpError as e:
        return False, str(e)

    encoded_size = len(content.encode("utf-8"))
    if encoded_size > MAX_MEMORY_CONTENT_BYTES:
        return False, (
            f"Memory content exceeds maximum size "
            f"({encoded_size} > {MAX_MEMORY_CONTENT_BYTES} bytes)"
        )

    host, unix_name, claw_type = _resolve_agent_with_memory(hostname, agent_name)
    if host is None:
        return False, unix_name

    # Per-claw filename allowlist (e.g. hermes accepts only MEMORY.md and
    # USER.md) — enforce before SSH so the user gets an immediate, clear
    # error rather than an Ansible failure.
    allowed = _MEMORY_WRITE_ALLOWED_FILES.get(claw_type)
    if allowed is not None and filename not in allowed:
        return False, (
            f"{claw_type} memory accepts only {' and '.join(allowed)}"
        )

    # Per-claw per-file character limit (hermes: MEMORY.md ≤ 2200, USER.md ≤ 1375).
    char_limits = _MEMORY_WRITE_CHAR_LIMITS.get(claw_type) or {}
    char_cap = char_limits.get(filename)
    if char_cap is not None and len(content) > char_cap:
        return False, (
            f"{claw_type} memory file '{filename}' exceeds character limit "
            f"({len(content)} > {char_cap} chars)"
        )

    try:
        _validate_agent_name(unix_name)
    except MemoryOpError as e:
        return False, str(e)

    # Pass content as base64 so user-supplied bytes are never interpreted
    # as Jinja2 by the playbook. Pairs with the b64decode filter in
    # memory_write.yaml.
    extra_vars = {
        "agent_name": unix_name,
        "memory_filename": filename,
        "memory_content_b64": base64.b64encode(
            content.encode("utf-8")
        ).decode("ascii"),
    }
    result, log_dir, setup_error = _run_memory_playbook(
        host, claw_type, "memory_write", extra_vars, timeout=60
    )
    if log_dir is None and setup_error:
        return False, setup_error

    try:
        if setup_error:
            return False, setup_error
        if result.status == "timeout":
            return False, "Memory write timed out"
        if result.status != "successful":
            return False, _extract_failure_message(result, result.status)
        return True, None
    finally:
        if log_dir is not None:
            _cleanup_artifacts(log_dir)


def delete_memory_files(
    hostname: str, agent_name: str, files: list[str]
) -> tuple[bool, str | None]:
    """Delete a list of memory files. Returns (success, error).

    Each file is workspace-relative (e.g. "SOUL.md" or "memory/2026-05-09.md").
    """
    if not files:
        return True, None

    for f in files:
        try:
            _validate_memory_filename(f)
        except MemoryOpError as e:
            return False, str(e)

    host, unix_name, claw_type = _resolve_agent_with_memory(hostname, agent_name)
    if host is None:
        return False, unix_name

    try:
        _validate_agent_name(unix_name)
    except MemoryOpError as e:
        return False, str(e)

    extra_vars = {"agent_name": unix_name, "memory_files": list(files)}
    result, log_dir, setup_error = _run_memory_playbook(
        host, claw_type, "memory_delete", extra_vars, timeout=30
    )
    if log_dir is None and setup_error:
        return False, setup_error

    try:
        if setup_error:
            return False, setup_error
        if result.status == "timeout":
            return False, "Memory delete timed out"
        if result.status != "successful":
            return False, _extract_failure_message(result, result.status)
        return True, None
    finally:
        if log_dir is not None:
            _cleanup_artifacts(log_dir)

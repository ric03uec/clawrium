"""Agent memory inspection and management for openclaw agents.

Operations target the openclaw workspace at
``/home/<agent_name>/.openclaw/workspace/`` and run via ansible-runner.

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

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_MEMORY_CONTENT_BYTES",
    "MEMORY_TOP_LEVEL_FILES",
    "MemoryFileInfo",
    "MemoryStats",
    "MemoryOpError",
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

# Top-level workspace files surfaced to the user.
# Daily files under ``memory/`` are discovered dynamically by get_memory_info.
MEMORY_TOP_LEVEL_FILES: tuple[str, ...] = (
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "TOOLS.md",
)

# Workspace-relative path validation: filename or memory/<filename>.
# Mirrors the pattern enforced in the playbooks.
_MEMORY_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?$")

# Agent-name validation matches the rule used elsewhere in lifecycle.py.
_AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

_PLAYBOOK_DIR = (
    Path(__file__).parent.parent
    / "platform"
    / "registry"
    / "openclaw"
    / "playbooks"
)


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


def _resolve_openclaw_agent(
    hostname: str, agent_name: str
) -> tuple[dict, str] | tuple[None, str]:
    """Resolve agent identifier to (host_record, unix_agent_name).

    On miss, returns ``(None, reason)`` so callers can distinguish
    "not found" from "not ready" and emit accurate messages — a user
    debugging a visible agent that's still installing should not see
    "agent not found".
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
    playbook_path = _PLAYBOOK_DIR / f"{operation}.yaml"
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
        log_dir = logs_dir / f"{operation}-openclaw-{host_display}-{timestamp}"
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


def get_memory_info(hostname: str, agent_name: str) -> MemoryStats | None:
    """Return memory stats for the openclaw agent or None if unavailable."""
    host, unix_name = _resolve_openclaw_agent(hostname, agent_name)
    if host is None:
        return None

    try:
        _validate_agent_name(unix_name)
    except MemoryOpError as e:
        logger.warning("Memory info: %s", e)
        return None

    extra_vars = {"agent_name": unix_name}
    result, log_dir, setup_error = _run_memory_playbook(
        host, "memory_info", extra_vars, timeout=30
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

        return {
            "workspace_path": parsed["workspace_path"]
            or f"/home/{unix_name}/.openclaw/workspace",
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

    host, unix_name = _resolve_openclaw_agent(hostname, agent_name)
    if host is None:
        return None

    try:
        _validate_agent_name(unix_name)
    except MemoryOpError:
        return None

    extra_vars = {"agent_name": unix_name, "memory_filename": filename}
    result, log_dir, setup_error = _run_memory_playbook(
        host, "memory_read", extra_vars, timeout=30
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

    host, unix_name = _resolve_openclaw_agent(hostname, agent_name)
    if host is None:
        return False, unix_name

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
        host, "memory_write", extra_vars, timeout=60
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

    host, unix_name = _resolve_openclaw_agent(hostname, agent_name)
    if host is None:
        return False, unix_name

    try:
        _validate_agent_name(unix_name)
    except MemoryOpError as e:
        return False, str(e)

    extra_vars = {"agent_name": unix_name, "memory_files": list(files)}
    result, log_dir, setup_error = _run_memory_playbook(
        host, "memory_delete", extra_vars, timeout=30
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

"""Agent lifecycle management for agent instances.

This module handles start, stop, and restart operations for agent instances
running on remote hosts via systemd service management.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

import ansible_runner
import paramiko

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host, update_host, remove_agent_from_host
from clawrium.core import keys as core_keys
from clawrium.core import provider_attachments as _pa
from clawrium.core.onboarding import OnboardingState
from clawrium.core.providers import storage as _provider_storage
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
    remove_instance_secrets,
    set_instance_secret,
)
from clawrium.core.skills_state import cleanup_agent_state

logger = logging.getLogger(__name__)

__all__ = [
    "start_agent",
    "stop_agent",
    "restart_agent",
    "remove_agent",
    "configure_agent",
    "sync_agent",
    "LifecycleError",
    "LifecycleResult",
]


class LifecycleError(Exception):
    """Raised when lifecycle operation fails."""

    pass


class LifecycleResult(TypedDict):
    """Result of lifecycle operation."""

    success: bool
    agent: str
    host: str
    operation: str
    pid: int | None
    started_at: str | None
    error: str | None


ALIAS_TO_CANONICAL = {
    "opc": "openclaw",
    "zc": "zeroclaw",
    "nc": "nemoclaw",
    "ethos": "ethos",
}


def _token_prefix(token: str | None) -> str:
    """Return first 8 chars of a token for logging; "" if absent."""
    if not isinstance(token, str):
        return ""
    return token.strip()[:8]


def _emit_gateway_token_rotated(
    on_event: Callable[[str, str], None] | None,
    agent_key: str,
    old_token: str | None,
    new_token: str | None,
    reason: str,
) -> None:
    """Emit a structured `gateway_token_rotated` event.

    Issue #437: single emit site whenever any lifecycle op writes a new
    value to hosts.json.gateway.auth. Suppressed on first mint (no prior
    token) because that's an install, not a rotation.
    """
    if not isinstance(new_token, str) or not new_token.strip():
        return
    old_clean = old_token.strip() if isinstance(old_token, str) else ""
    new_clean = new_token.strip()
    if not old_clean or old_clean == new_clean:
        return
    payload = json.dumps(
        {
            "agent_key": agent_key,
            "old_token_prefix": _token_prefix(old_clean),
            "new_token_prefix": _token_prefix(new_clean),
            "reason": reason,
        }
    )
    if on_event is not None:
        on_event("gateway_token_rotated", payload)
    # ATX W6: do NOT log the 8-char token prefixes — that's 50% of the
    # 16-char minimum bearer secret and application logs may be shipped
    # to centralized aggregators or readable by accounts without
    # hosts.json access. Log only the audit-relevant fields.
    logger.info("gateway_token_rotated agent=%s reason=%s", agent_key, reason)


def get_host_private_key(key_id: str) -> Path | None:
    """Resolve host SSH key path.

    Wrapper kept in this module to preserve patch points in tests.
    """
    return core_keys.get_host_private_key(key_id)


def _resolve_agent_type(agent_type: str) -> str:
    """Resolve agent alias to canonical name."""
    return ALIAS_TO_CANONICAL.get(agent_type, agent_type)


def _get_lifecycle_playbook_path(claw_name: str, operation: str) -> Path:
    canonical_name = _resolve_agent_type(claw_name)
    return (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / canonical_name
        / "playbooks"
        / f"{operation}.yaml"
    )


def _get_logs_dir() -> Path:
    """Get logs directory, creating if needed."""
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _summarize_ansible_configure_failure(
    result: object, log_dir: str
) -> str:
    """Turn an ansible-runner failed `result` into an actionable error string.

    Three failure shapes are handled, in priority order:
      1. A `runner_on_failed` event with uncensored `res.msg` or
         `res.stderr` → surface task name + the underlying message.
      2. Every failing task had `no_log: true` (res is `{"censored": ...}`)
         → surface task name + a hint on how to see the real error
         without leaking whatever the censored res contains (bearer
         tokens, API keys).
      3. ansible-runner failed before any task ran (playbook parse error,
         inventory load error, connection error) → surface the recap
         stats / verbose stdout / stderr instead of the useless
         `"failed"` literal.

    A pure function over the runner result so it can be unit-tested
    without spinning a real Ansible job. #583.
    """
    status = getattr(result, "status", "failed")
    rc = getattr(result, "rc", "?")
    error_msg = f"Configure playbook failed: {status}"
    found_task_failure = False
    censored_failure_task: str | None = None
    # `result.events` is consumed-on-iteration in ansible-runner ≥ 2.x
    # — capture into a list once so the multi-pass walks below all see
    # the same events. Defensive against both list and generator
    # implementations.
    events = list(getattr(result, "events", []) or [])
    for event in events:
        if event.get("event") != "runner_on_failed":
            continue
        event_data = event.get("event_data", {}) or {}
        res = event_data.get("res", {}) or {}
        if res.get("censored"):
            # Remember the FIRST censored failure for the hint branch;
            # subsequent ones don't add information.
            if censored_failure_task is None:
                censored_failure_task = event_data.get(
                    "task", "<unknown task>"
                )
            continue
        task_name = event_data.get("task", "<unknown task>")
        # ATX #445 iter-3 NW4: `is not None` so a `{"msg": None}` entry
        # doesn't short-circuit error_msg to None and leak an empty
        # string up the stack.
        msg = res.get("msg")
        if msg is not None:
            error_msg = f"task {task_name!r}: {msg}"
            found_task_failure = True
            break
        stderr = res.get("stderr")
        if stderr is not None:
            error_msg = f"task {task_name!r}: {stderr}"
            found_task_failure = True
            break

    if found_task_failure:
        return error_msg

    if censored_failure_task is not None:
        return (
            f"task {censored_failure_task!r} failed but output was "
            f"suppressed by `no_log: true`. Re-run with "
            f"ANSIBLE_NO_LOG=False in the environment, or "
            f"temporarily set `no_log: false` on the task, to see "
            f"the underlying error."
        )

    # Pre-task failure — no task events fired. Pull together whatever
    # ansible-runner did emit so the operator has something to debug.
    pre_task_errors: list[str] = []
    for event in events:
        etype = event.get("event")
        if etype in ("error", "verbose"):
            stdout = event.get("stdout") or ""
            if stdout.strip():
                pre_task_errors.append(stdout.strip())
        elif etype == "playbook_on_stats":
            event_data = event.get("event_data", {}) or {}
            if event_data:
                pre_task_errors.append(f"recap: {event_data}")

    # `result.stdout` / `result.stderr` are file-like — read at most
    # ~4KB so a stack trace fits but a giant playbook dump doesn't.
    def _safe_read(stream) -> str:
        if stream is None:
            return ""
        try:
            return stream.read(4096) or ""
        except Exception:
            return ""

    stdout_blob = _safe_read(getattr(result, "stdout", None))
    stderr_blob = _safe_read(getattr(result, "stderr", None))

    detail_parts: list[str] = []
    if pre_task_errors:
        detail_parts.append(" | ".join(pre_task_errors))
    if stderr_blob.strip():
        detail_parts.append(f"stderr: {stderr_blob.strip()}")
    if stdout_blob.strip() and not pre_task_errors:
        # Trim to last 1KB so a parse traceback is visible without
        # flooding the CLI with the full playbook dump.
        tail = stdout_blob.strip()[-1024:]
        detail_parts.append(f"stdout: {tail}")

    if detail_parts:
        return (
            f"Configure playbook failed before any task ran "
            f"(status={status}, rc={rc}): " + "; ".join(detail_parts)
        )
    return (
        f"Configure playbook failed (status={status}, "
        f"rc={rc}) — ansible-runner produced no events "
        f"or output. Check {log_dir} for artifacts."
    )


def _safe_host_display(host: dict, hostname: str) -> str:
    """Return a filesystem-safe host display string for log dir naming.

    ATX W-SEC-3: an alias like `../etc` or `my/box` would otherwise turn
    the operation log directory into a traversal target. Substitute any
    char outside `[A-Za-z0-9_.-]` with `_`. Empty / all-bad-char (i.e.
    sanitized to only `_`) input falls back to "host".
    """
    raw = host.get("alias") or host.get("key_id") or hostname or ""
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", raw)
    if not sanitized or set(sanitized) == {"_"}:
        return "host"
    return sanitized


def _cleanup_ansible_artifacts(operation_log_dir: Path) -> None:
    """Clean up ansible-runner artifacts that may contain secrets.

    B3 fix: ansible-runner stores inventory and vars in artifacts/,
    which can contain API keys and tokens. We preserve non-sensitive log
    files (stdout, rc, status) for post-run diagnostics while removing
    secret-bearing subdirectories (fact_cache/) and the inventory/env dirs.
    """
    artifacts_dir = operation_log_dir / "artifacts"
    if artifacts_dir.exists() and artifacts_dir.is_dir():
        # Preserve stdout/rc/status from each run UUID subdir, then remove
        # the sensitive fact_cache/ and job_events/ (which may echo vars).
        try:
            entries = list(artifacts_dir.iterdir())
        except (OSError, FileNotFoundError):
            entries = []
        for run_dir in entries:
            if not run_dir.is_dir():
                continue
            # Remove secret-bearing subdirs
            for sensitive_subdir in ("fact_cache",):
                target = run_dir / sensitive_subdir
                if target.exists():
                    try:
                        shutil.rmtree(target)
                        logger.debug(
                            "Cleaned up sensitive subdir %s", target
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to clean up %s: %s", target, e
                        )
        logger.debug(
            "Preserved ansible artifacts (stdout/rc/status) at %s",
            artifacts_dir,
        )

    # Also clean up env/ directory which may contain inventory with secrets
    env_dir = operation_log_dir / "env"
    if env_dir.exists():
        try:
            shutil.rmtree(env_dir)
            logger.debug("Cleaned up ansible env at %s", env_dir)
        except Exception as e:
            logger.warning("Failed to clean up ansible env: %s", e)

    # ansible-runner serializes the inventory dict (which contains provider
    # API keys, AWS credentials, Discord/Slack tokens, etc. as extravars) to
    # inventory/hosts.json on every run. Without cleanup these accumulate on
    # disk indefinitely. Strip alongside artifacts/ and env/.
    inventory_dir = operation_log_dir / "inventory"
    if inventory_dir.exists():
        try:
            shutil.rmtree(inventory_dir)
            logger.debug("Cleaned up ansible inventory at %s", inventory_dir)
        except Exception as e:
            logger.warning("Failed to clean up ansible inventory: %s", e)


def _resolve_agent_record(
    host: dict,
    identifier: str,
    expected_type: str | None = None,
) -> tuple[str, str, dict] | None:
    """Resolve an agent instance in host.agents.

    Agents must have an explicit 'type' field. Records without 'type' are skipped.
    Raises LifecycleError if multiple agents of the same type are found.
    """
    agents = host.get("agents", {})
    if not isinstance(agents, dict):
        return None

    # Direct key lookup
    direct = agents.get(identifier)
    if isinstance(direct, dict):
        direct_type = direct.get("type")
        if not isinstance(direct_type, str) or not direct_type:
            # Skip records without explicit type field
            return None
        if expected_type and direct_type != expected_type:
            return None
        return identifier, direct_type, direct

    # Search by type
    matches: list[tuple[str, str, dict]] = []
    for agent_key, record in agents.items():
        if not isinstance(record, dict):
            continue
        agent_type = record.get("type")
        # Skip records without explicit type field
        if not isinstance(agent_type, str) or not agent_type:
            continue
        if expected_type:
            if agent_type == expected_type:
                matches.append((agent_key, agent_type, record))
        elif agent_type == identifier:
            matches.append((agent_key, agent_type, record))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        instance_names = ", ".join(m[0] for m in matches)
        raise LifecycleError(
            f"Multiple {expected_type or identifier} agents found. "
            f"Specify instance name: {instance_names}"
        )
    return None


def _update_agent_runtime(hostname: str, agent_key: str, runtime_data: dict) -> bool:
    """Update agent runtime information in hosts.json.

    Args:
        hostname: The hostname of the host
        agent_key: Instance key for the agent
        runtime_data: Runtime data to store (pid, started_at, status, etc.)

    Returns:
        True if update succeeded
    """

    def updater(h: dict) -> dict:
        if "agents" not in h:
            h["agents"] = {}
        if agent_key not in h["agents"]:
            h["agents"][agent_key] = {}
        h["agents"][agent_key]["runtime"] = runtime_data
        return h

    return update_host(hostname, updater)


def _run_lifecycle_playbook(
    agent_type: str,
    agent_name: str,
    hostname: str,
    operation: str,
    host: dict,
    timeout: int = 60,
) -> tuple[bool, str | None]:
    """Run a lifecycle playbook on a host.

    Args:
        agent_type: Type of agent
        agent_name: Instance name
        hostname: Target hostname
        operation: Operation to perform ("start" or "stop")
        host: Host record dict
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, error_message)
    """
    playbook_path = _get_lifecycle_playbook_path(agent_type, operation)

    if not playbook_path.exists():
        return False, f"Playbook not found: {playbook_path}"

    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return False, "SSH key not found"

    # Validate agent_name to prevent path traversal/injection in Ansible playbooks
    # Use the same validation as agent name validation
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", agent_name):
        return (
            False,
            f"Invalid agent_name format: '{agent_name}'. Must start with lowercase letter and contain only lowercase letters, digits, hyphens, underscores (max 32 chars)",
        )

    instance_key = None
    secret_vars = {}
    try:
        # Key by host["key_id"] (immutable, #448), falling back to the
        # `hostname` parameter for hand-edited legacy records where
        # `key_id` is absent. This guarantees secret lookups still
        # resolve after operators mutate `hostname` (IP → DNS).
        instance_host_key = host.get("key_id") or hostname
        instance_key = get_instance_key(instance_host_key, agent_type, agent_name)
        instance_secrets = get_instance_secrets(instance_key)
        for key, entry in instance_secrets.items():
            secret_vars[key.lower()] = entry.get("value", "")
    except Exception:
        pass

    extra_vars: dict[str, object] = {}

    # Issue #478 phase 2: hermes start/stop/remove playbooks need to re-render
    # the dashboard systemd unit, which requires the per-instance loopback
    # port persisted at install time. Pull it from hosts.json on every
    # lifecycle op so the unit stays consistent if `clm` is upgraded
    # between install and the next restart. Absent for agents installed
    # before this change — the playbook guards on `dashboard_port is defined`.
    if _resolve_agent_type(agent_type) == "hermes":
        agent_record = host.get("agents", {}).get(agent_name, {})
        dashboard = (
            agent_record.get("config", {}).get("dashboard", {})
            if isinstance(agent_record, dict)
            else {}
        )
        dashboard_port = dashboard.get("port") if isinstance(dashboard, dict) else None
        # ATX W5: restrict to the documented allocation window so a
        # tampered hosts.json cannot inject a privileged or third-party
        # port into the ansible inventory.
        if (
            isinstance(dashboard_port, int)
            and not isinstance(dashboard_port, bool)
            and 45000 <= dashboard_port <= 46999
        ):
            extra_vars["dashboard_port"] = dashboard_port

    inventory = {
        "all": {
            "hosts": {
                hostname: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                    "ansible_become_timeout": 120,
                    "ansible_pipelining": True,
                    "ansible_ssh_extra_args": "-o ServerAliveInterval=30 -o ServerAliveCountMax=10 -o ConnectTimeout=60",
                }
            },
            "vars": {
                "agent_name": agent_name,
                "agent_type": agent_type,
                **extra_vars,
                **secret_vars,
            },
        }
    }

    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = _safe_host_display(host, hostname)
    operation_log_dir = (
        logs_dir / f"{operation}-{agent_type}-{host_display}-{timestamp}"
    )
    operation_log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(operation_log_dir, 0o700)

    try:
        result = ansible_runner.run(
            private_data_dir=str(operation_log_dir),
            inventory=inventory,
            playbook=str(playbook_path),
            quiet=True,
            timeout=timeout,
        )

        if result.status == "timeout":
            return False, f"{operation.capitalize()} operation timed out"

        if result.status != "successful":
            error_msg = f"{operation.capitalize()} playbook failed: {result.status}"
            for event in result.events:
                if event.get("event") == "runner_on_failed":
                    event_data = event.get("event_data", {})
                    res = event_data.get("res", {})
                    # ATX #445 W1: a `no_log: true` task that fails surfaces
                    # `{"censored": "..."}` in res; skip it so we don't read
                    # `msg`/`stderr` keys that may carry the bearer if a
                    # debug-mode daemon echoes the Authorization header back
                    # in its 401 body.
                    if res.get("censored"):
                        continue
                    # ATX #445 iter-3 NW4: `if "msg" in res` would fire on a
                    # `{"msg": None}` entry and set error_msg = None, leaking
                    # an empty error string up the stack. Use `is not None`
                    # so the loop falls through to stderr / generic prefix.
                    # ATX iter-4 S-F: symmetric `.get` access on both lines.
                    msg = res.get("msg")
                    if msg is not None:
                        error_msg = msg
                        break
                    stderr = res.get("stderr")
                    if stderr is not None:
                        error_msg = stderr
                        break
            return False, error_msg

        return True, None

    except Exception as e:
        return False, str(e)
    finally:
        # W4 fix: Always clean up artifacts containing secrets (success, failure, or exception)
        _cleanup_ansible_artifacts(operation_log_dir)


def _hermes_env_token_matches_secrets(
    host: dict, agent_name: str
) -> tuple[bool, str | None]:
    """Check on-host hermes .env API_SERVER_KEY against secrets.json.

    Issue #448: ``secrets.json`` is the authoritative source for the
    hermes bearer. If an operator (or a prior install on a different
    machine) wrote the on-host ``.env`` from a different key, every
    ``clawctl agent chat`` will 401 because the daemon enforces the
    on-host value while the client reads the secrets.json value.

    Returns:
        (matches, error). ``matches`` is True when the on-host token
        equals secrets.json. On any probe failure (host unreachable,
        file missing, malformed line) returns ``(True, error)`` so the
        caller does NOT redundantly reconfigure on transient issues —
        the start playbook will surface the real error.
    """
    try:
        import shlex

        key_id = host.get("key_id") or host.get("hostname")
        if not key_id:
            return True, "host record missing key_id/hostname"
        private_key = get_host_private_key(key_id)
        if not private_key:
            return True, "no SSH key for host"

        os_family = host.get("os_family") or "linux"
        home_root = "/Users" if os_family == "darwin" else "/home"
        env_path = f"{home_root}/{agent_name}/.hermes/.env"

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        # ATX W1: after an IP→DNS migration the new hostname is unlikely
        # to be in `known_hosts` yet, so the default RejectPolicy would
        # raise and the outer except would silently return matches=True
        # — defeating the entire reconcile invariant this helper exists
        # for. WarningPolicy connects on unknown keys while logging,
        # which is appropriate here because this is a *probe* whose
        # only output is a string comparison against a value we already
        # hold locally (no command execution, no payload). We do NOT
        # use AutoAddPolicy — that would persist the new key without
        # an MITM check.
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            client.connect(
                hostname=host.get("hostname"),
                port=int(host.get("port", 22)),
                username=host.get("user", "xclm"),
                key_filename=str(private_key),
                timeout=10,
            )
            # xclm cannot read `/home/<agent>/.hermes/.env` directly
            # (the agent home is typically 0700). xclm has passwordless
            # sudo from `clawctl host create`, so `sudo -n` succeeds in
            # the non-TTY paramiko exec channel; `-n` ensures we never
            # block waiting for a password and surface a clean failure
            # the outer except will swallow non-fatally.
            cmd = (
                "sudo -n grep -E '^API_SERVER_KEY=' "
                f"{shlex.quote(env_path)} 2>/dev/null || true"
            )
            _, stdout, _ = client.exec_command(cmd, timeout=10)
            raw = stdout.read().decode().strip()
        finally:
            client.close()

        if not raw:
            return True, "API_SERVER_KEY not present in .env (will be rendered on configure)"

        # Format: API_SERVER_KEY='<value>'  (rendered via shell_quote)
        # Strip the leading key= and any surrounding single/double quotes.
        value = raw.split("=", 1)[1].strip()
        if (len(value) >= 2) and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]

        host_key = host.get("key_id") or host.get("hostname", "")
        instance_key = get_instance_key(host_key, "hermes", agent_name)
        secret_entry = get_instance_secrets(instance_key).get("HERMES_API_SERVER_KEY")
        expected = secret_entry.get("value") if isinstance(secret_entry, dict) else None
        if not expected:
            return True, "no HERMES_API_SERVER_KEY in secrets.json"

        return value == expected, None
    except Exception as exc:
        # Probe failures are non-fatal: let the start playbook surface
        # the real error rather than synthesizing a configure loop.
        return True, str(exc)


def start_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    force: bool = False,
    on_event: Callable[[str, str], None] | None = None,
    repair_reason: str = "start",
) -> LifecycleResult:
    """Start an agent instance on a remote host.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of agent to start (e.g., "openclaw")
        force: Bypass onboarding check (not recommended)
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("validate", f"Checking {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, agent_type, claw_record = resolved

    onboarding = claw_record.get("onboarding", {})
    state_value = onboarding.get("state", "pending")

    try:
        state = OnboardingState(state_value)
    except ValueError:
        state = OnboardingState.PENDING

    if state != OnboardingState.READY and not force:
        agent_display_name = agent_key
        raise LifecycleError(
            f"Cannot start {agent_key}: onboarding incomplete (state={state_value}). "
            f"Run 'clm agent configure {agent_display_name}' first."
        )

    # Issue #448: env-file consistency invariant. For hermes, the
    # daemon enforces the API_SERVER_KEY written into ~/.hermes/.env at
    # configure time, while `clawctl agent chat` reads the bearer from
    # secrets.json. If those drifted (e.g. the host's `hostname` was
    # mutated after install and an older write left a stale .env), the
    # next chat request returns 401 with no clear remediation.
    # secrets.json is authoritative — reconcile by running configure
    # before the start playbook.
    if _resolve_agent_type(claw_name) == "hermes":
        matches, probe_error = _hermes_env_token_matches_secrets(host, agent_key)
        if not matches:
            emit(
                "start",
                "API_SERVER_KEY drift detected between .env and "
                "secrets.json; reconfiguring before start",
            )
            # Reuse the agent's persisted config so reconfigure
            # re-renders .env with the canonical secrets.json bearer
            # without altering any other field the operator set.
            persisted_config = (
                claw_record.get("config", {})
                if isinstance(claw_record, dict)
                else {}
            )
            cfg_success, cfg_error = configure_agent(
                hostname,
                claw_name,
                persisted_config if isinstance(persisted_config, dict) else {},
                agent_name=agent_key,
                on_event=on_event,
                reason="start-precheck",
            )
            if not cfg_success:
                return {
                    "success": False,
                    "agent": agent_key,
                    "host": hostname,
                    "operation": "start",
                    "pid": None,
                    "started_at": None,
                    "error": f"Pre-start reconfigure failed: {cfg_error}",
                }
        elif probe_error:
            logger.debug(
                "Hermes env-token probe inconclusive for %s: %s",
                agent_key,
                probe_error,
            )

    emit("start", f"Starting {agent_key} on {hostname}...")

    success, error = _run_lifecycle_playbook(
        agent_type, agent_key, host["hostname"], "start", host
    )

    if not success:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "start",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    now = datetime.now(timezone.utc).isoformat()
    _update_agent_runtime(
        host["hostname"],
        agent_key,
        {
            "status": "running",
            "started_at": now,
            "last_check": now,
        },
    )

    # Issue #437 / ATX W1: zeroclaw daemon does not persist bearer state
    # across systemd starts. Always re-pair after a cold start so
    # hosts.json.gateway.auth agrees with the token the daemon will
    # enforce on the next request. restart_agent reuses this path via
    # its stop -> start sequence (repair_reason="restart").
    if _resolve_agent_type(claw_name) == "zeroclaw":
        # ATX W-SEC-2: do NOT emit "Started successfully" until the
        # repair completes. An operator who ctrl-C's between the success
        # line and the silent-but-still-running repair would otherwise
        # be left with a stale hosts.json bearer.
        emit("start", f"Daemon started; pairing {agent_key}...")
        # ATX W-NEW-2: pass the resolved agent_key, not the raw caller
        # parameter, so the helper's _resolve_agent_record always sees a
        # canonical instance key.
        repair_success, repair_error = _zeroclaw_repair_after_start(
            hostname,
            agent_name=agent_key,
            on_event=on_event,
            reason=repair_reason,
        )
        if not repair_success:
            return {
                "success": False,
                "agent": agent_key,
                "host": hostname,
                "operation": "start",
                "pid": None,
                "started_at": now,
                "error": f"Re-pair after start failed: {repair_error}",
            }

    if _resolve_agent_type(claw_name) == "ethos":
        emit("start", f"Daemon started; waiting for {agent_key} gateway...")
        health_ok, health_err = _ethos_health_check_after_start(
            hostname, agent_key, claw_record, on_event=on_event
        )
        if not health_ok:
            return {
                "success": False,
                "agent": agent_key,
                "host": hostname,
                "operation": "start",
                "pid": None,
                "started_at": now,
                "error": f"Ethos gateway health check failed: {health_err}",
            }

    emit("start", f"Started {agent_key} successfully")

    return {
        "success": True,
        "agent": agent_key,
        "host": hostname,
        "operation": "start",
        "pid": None,
        "started_at": now,
        "error": None,
    }


def stop_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    timeout: int = 30,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Stop an agent instance on a remote host.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of agent to stop (e.g., "openclaw")
        timeout: Seconds to wait for graceful shutdown
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("validate", f"Checking {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, agent_type, _ = resolved

    emit("stop", f"Stopping {agent_key} on {hostname}...")

    success, error = _run_lifecycle_playbook(
        agent_type, agent_key, host["hostname"], "stop", host, timeout=timeout + 30
    )

    if not success:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "stop",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    now = datetime.now(timezone.utc).isoformat()
    _update_agent_runtime(
        host["hostname"],
        agent_key,
        {
            "status": "stopped",
            "started_at": None,
            "stopped_at": now,
            "last_check": now,
        },
    )

    emit("stop", f"Stopped {agent_key} successfully")

    return {
        "success": True,
        "agent": agent_key,
        "host": hostname,
        "operation": "stop",
        "pid": None,
        "started_at": None,
        "error": None,
    }


def restart_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Restart an agent instance on a remote host.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of agent to restart (e.g., "openclaw")
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("restart", f"Restarting {target} on {hostname}...")

    stop_result = stop_agent(
        hostname, claw_name, agent_name=agent_name, on_event=on_event
    )
    if not stop_result["success"]:
        return {
            "success": False,
            "agent": target,
            "host": hostname,
            "operation": "restart",
            "pid": None,
            "started_at": None,
            "error": f"Stop failed: {stop_result['error']}",
        }

    # Issue #437: pass repair_reason="restart" so the structured rotation
    # event identifies the originating op. start_agent re-pairs for
    # zeroclaw on every cold start; restart inherits that for free.
    start_result = start_agent(
        hostname,
        claw_name,
        agent_name=agent_name,
        on_event=on_event,
        repair_reason="restart",
    )
    start_result["operation"] = "restart"
    if not start_result["success"] and start_result.get("error"):
        start_result["error"] = start_result["error"].replace(
            "Re-pair after start failed", "Re-pair after restart failed"
        )
    return start_result


def _extract_zeroclaw_gateway_facts(
    artifacts_dir: Path,
) -> tuple[str | None, str | None]:
    """Read `zeroclaw_gateway_token` and `zeroclaw_gateway_url` out of an
    ansible-runner fact_cache directory.

    Returns (token, url); either may be None if the playbook did not emit
    the fact (e.g. it failed before reaching the set_fact task).
    """
    fact_cache_dir = artifacts_dir / "fact_cache"
    if not fact_cache_dir.exists():
        return None, None

    for fact_file in fact_cache_dir.glob("*"):
        try:
            with open(fact_file) as fh:
                facts = json.load(fh)
        except (json.JSONDecodeError, IOError) as exc:
            logger.debug("Skipping fact file %s: %s", fact_file, exc)
            continue
        payload = facts.get("__payload__")
        if not isinstance(payload, str) or not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue

        token_raw = parsed.get("zeroclaw_gateway_token")
        url_raw = parsed.get("zeroclaw_gateway_url")
        if isinstance(token_raw, dict):
            token_raw = token_raw.get("value")
        if isinstance(url_raw, dict):
            url_raw = url_raw.get("value")
        if isinstance(token_raw, str):
            token_raw = token_raw.strip()
        if isinstance(url_raw, str):
            url_raw = url_raw.strip()
        if token_raw and url_raw:
            return token_raw, url_raw
    return None, None


def _create_ethos_chat_token(
    host: dict,
    agent_name: str,
    ssh_key: "Path | None",
    on_event: "Callable[[str, str], None] | None" = None,
) -> str | None:
    """Create an ethos API key via SSH and return the sk-ethos-... token.

    Runs `ethos api-key create --name clawctl` as the agent Linux user.
    Returns None if SSH is unreachable or the command fails.
    """
    import re
    import subprocess

    hostname = host.get("hostname", "")
    user = host.get("user", "xclm")
    port = host.get("port", 22)

    # Probe candidate binary paths in the same order as configure.yaml and
    # exec.yaml. The NodeSource install places the binary under the npm global
    # prefix (often /opt/clawrium-node24/bin/); a system-level install lands
    # it at /usr/local/bin/ethos. The first executable found wins.
    _probe = (
        "for p in /opt/clawrium-node24/bin/ethos /usr/local/bin/ethos; do "
        '[ -x "$p" ] && echo "$p" && break; done'
    )

    ssh_base = ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=15"]
    if port and port != 22:
        ssh_base += ["-p", str(port)]
    if ssh_key:
        ssh_base += ["-i", str(ssh_key)]

    try:
        probe_result = subprocess.run(
            ssh_base + [f"{user}@{hostname}", _probe],
            capture_output=True, text=True, timeout=15,
        )
        ethos_bin = probe_result.stdout.strip()
    except Exception:
        ethos_bin = ""

    if not ethos_bin:
        logger.warning("ethos binary not found on %s; skipping ETHOS_CHAT_TOKEN creation", hostname)
        return None

    cmd = ssh_base + [
        f"{user}@{hostname}",
        f"sudo -u {agent_name} {ethos_bin} api-key create --name clawctl 2>&1",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        match = re.search(r"sk-ethos-[a-f0-9]{64}", output)
        if match:
            token = match.group(0)
            if on_event:
                on_event("configure", f"Created ETHOS_CHAT_TOKEN for {agent_name}")
            return token
        logger.warning("ethos api-key create ran but no sk-ethos- token found in output")
    except Exception as exc:
        logger.warning("Failed to create ethos API key via SSH: %s", exc)
    return None


def _zeroclaw_repair_after_start(
    hostname: str,
    agent_name: str | None,
    on_event: Callable[[str, str], None] | None,
    reason: str = "start",
) -> tuple[bool, str | None]:
    """Run the zeroclaw restart playbook to re-pair and persist the new
    bearer to hosts.json. Called from `start_agent` (and thus `restart_agent`,
    which goes through start).

    Returns (success, error_message). Emits a `gateway_token_rotated`
    event with the given `reason` (default "start", "restart" when
    invoked via restart_agent) only after the disk write succeeds.
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    host = get_host(hostname)
    if not host:
        return False, f"Host '{hostname}' not found"

    target = agent_name or "zeroclaw"
    resolved = _resolve_agent_record(host, target, expected_type="zeroclaw")
    if not resolved:
        return False, f"Agent '{target}' not installed on '{hostname}'"
    agent_key, _agent_type, agent_record = resolved
    unix_agent_name = agent_record.get("agent_name") or agent_key

    # ATX W4: parity with configure_agent's validation guard. Defends
    # against future Ansible tasks that exec shell/command from
    # agent_name; current pair.yaml uses only uri/fail/set_fact so this
    # is preventative, not currently exploitable.
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", unix_agent_name):
        return (
            False,
            f"Invalid agent_name format: '{unix_agent_name}'. Must start "
            "with lowercase letter and contain only lowercase letters, "
            "digits, hyphens, underscores (max 32 chars)",
        )

    gateway_cfg = agent_record.get("config", {}).get("gateway") or {}
    gateway_port = gateway_cfg.get("port")
    if not isinstance(gateway_port, int) or gateway_port <= 0:
        return (
            False,
            f"Gateway port missing from hosts.json for {agent_key}. "
            f"Re-run `clm agent configure {agent_key}`.",
        )
    # Issue #445: the playbook's locked-pair branch (tasks/pair.yaml) calls
    # POST /api/pairing/initiate with this bearer when /pair/code returns
    # null. Empty string is acceptable on the fresh-boot branch since
    # /pair/code will return a usable code and the locked branch never fires.
    existing_gateway_auth = gateway_cfg.get("auth") or ""

    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return False, "SSH key not found"

    playbook_path = _get_lifecycle_playbook_path("zeroclaw", "restart")
    if not playbook_path.exists():
        return False, f"Restart playbook not found: {playbook_path}"

    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                    "ansible_become_timeout": 120,
                    "ansible_pipelining": True,
                    "ansible_ssh_extra_args": "-o ServerAliveInterval=30 -o ServerAliveCountMax=10 -o ConnectTimeout=60",
                }
            },
            "vars": {
                "agent_name": unix_agent_name,
                "agent_type": "zeroclaw",
                "config": {
                    "gateway": {
                        "port": gateway_port,
                        "auth": existing_gateway_auth,
                    }
                },
            },
        }
    }

    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = _safe_host_display(host, hostname)
    operation_log_dir = logs_dir / f"restart-pair-zeroclaw-{host_display}-{timestamp}"
    operation_log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(operation_log_dir, 0o700)

    # ATX W-NEW-1: stage uses the actual reason so the start/restart
    # CLI handlers (which dispatch by stage name) render the progress
    # line instead of silently swallowing a hardcoded "restart" stage
    # during a "start" op.
    emit(reason, f"Re-pairing zeroclaw after {reason}...")

    try:
        result = ansible_runner.run(
            private_data_dir=str(operation_log_dir),
            inventory=inventory,
            playbook=str(playbook_path),
            quiet=True,
            timeout=180,
        )

        if result.status == "timeout":
            return False, "Re-pair after restart timed out"
        if result.status != "successful":
            error_msg = f"Re-pair playbook failed: {result.status}"
            for event in result.events:
                if event.get("event") == "runner_on_failed":
                    event_data = event.get("event_data", {})
                    res = event_data.get("res", {})
                    # ATX #445 W1: a `no_log: true` task that fails surfaces
                    # `{"censored": "..."}` in res; skip it so we don't read
                    # `msg`/`stderr` keys that may carry the bearer if a
                    # debug-mode daemon echoes the Authorization header back
                    # in its 401 body.
                    if res.get("censored"):
                        continue
                    # ATX #445 iter-3 NW4: `if "msg" in res` would fire on a
                    # `{"msg": None}` entry and set error_msg = None, leaking
                    # an empty error string up the stack. Use `is not None`
                    # so the loop falls through to stderr / generic prefix.
                    # ATX iter-4 S-F: symmetric `.get` access on both lines.
                    msg = res.get("msg")
                    if msg is not None:
                        error_msg = msg
                        break
                    stderr = res.get("stderr")
                    if stderr is not None:
                        error_msg = stderr
                        break
            return False, error_msg

        artifacts_dir = Path(result.config.artifact_dir)
        new_token, new_url = _extract_zeroclaw_gateway_facts(artifacts_dir)
        if not new_token or not new_url:
            return (
                False,
                "Re-pair playbook succeeded but pairing token was not "
                f"captured. Re-run `clm agent configure {agent_key}` and "
                f"check `journalctl --unit zeroclaw-{agent_key}`.",
            )

        old_token = agent_record.get("config", {}).get("gateway", {}).get("auth")

        def updater(h: dict) -> dict:
            agents = h.setdefault("agents", {})
            record = agents.setdefault(agent_key, {})
            config = record.setdefault("config", {})
            gateway = config.setdefault("gateway", {})
            gateway["auth"] = new_token
            gateway["url"] = new_url
            return h

        if not update_host(host["hostname"], updater):
            return (
                False,
                f"Re-pair succeeded but failed to update hosts.json for "
                f"{agent_key} on {hostname}",
            )

        _emit_gateway_token_rotated(on_event, agent_key, old_token, new_token, reason)
        emit(reason, "Pairing token refreshed")
        return True, None

    except Exception as exc:
        return False, str(exc)
    finally:
        _cleanup_ansible_artifacts(operation_log_dir)


def _ethos_health_check_after_start(
    hostname: str,
    agent_key: str,
    agent_record: dict,
    on_event: Callable[[str, str], None] | None = None,
    *,
    timeout: int = 90,
) -> tuple[bool, str | None]:
    """Poll the ethos web-api health endpoint via SSH until it responds 200.

    ethos web-api binds to 127.0.0.1:3000 on the remote host, so we probe
    via SSH. `run-all` starts multiple sub-processes; boot can take 30-60s.

    Probe order per iteration:
      1. /health  — documented in manifest validate task
      2. /healthz — alternative used by some ethos builds
      3. /v1/models — OpenAI-compat liveness if both /health paths are absent
    """
    import time
    import subprocess

    # ethos run-all exposes its own health aggregator on port 3003
    # (visible in journal as "health: http://127.0.0.1:3003/healthz").
    # Port 3000 (serve) also has /healthz but starts serving immediately
    # even before adapters load, so it's not a reliable readiness signal.
    port = 3003
    _HEALTH_PATHS = ["/healthz"]
    deadline = time.monotonic() + timeout

    from clawrium.core.hosts import get_host
    from clawrium.core.keys import get_host_private_key

    host = get_host(hostname)
    if not host:
        return False, f"Host {hostname!r} not found"
    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return False, "SSH key not found for health check"

    ssh_user = host.get("user", "xclm")
    ssh_port = host.get("port", 22)

    def _ssh(cmd: str) -> int:
        try:
            r = subprocess.run(
                [
                    "ssh", "-i", str(ssh_key),
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=3",
                    "-p", str(ssh_port),
                    f"{ssh_user}@{hostname}",
                    cmd,
                ],
                capture_output=True,
                timeout=6,
            )
            return r.returncode
        except (subprocess.TimeoutExpired, OSError):
            return 1

    agent_name = agent_record.get("agent_name", agent_key)
    service_unit = f"ethos-{agent_name}"

    while time.monotonic() < deadline:
        # Fast gate: systemd unit must be active before we bother with HTTP.
        if _ssh(f"systemctl is-active --quiet {service_unit}") != 0:
            time.sleep(3)
            continue
        # HTTP probe — try each candidate path; first 200 wins.
        for path in _HEALTH_PATHS:
            if _ssh(f"curl -sf http://127.0.0.1:{port}{path}") == 0:
                return True, None
        time.sleep(3)

    return False, (
        f"Ethos service {service_unit} did not become ready within {timeout}s. "
        f"Check logs: sudo journalctl -u {service_unit} -n 50 --no-pager"
    )


def sync_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    workspace_only: bool = False,
    on_event: Callable[[str, str], None] | None = None,
    playbook_path_override: Path | None = None,
    defer_state_transition: bool = False,
) -> LifecycleResult:
    """Sync configuration to an agent instance.

    Issue #437: sync now equals configure. The previous configure → restart
    orchestration created token divergence on every sync because restart did
    not re-pair. Now configure always re-pairs (and the playbook's
    notify-driven restart fires whenever config.toml or the systemd drop-in
    actually changed), so the explicit restart step is redundant and unsafe.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of agent to sync (e.g., "openclaw")
        agent_name: Optional specific instance name
        workspace_only: Accepted for backwards compat; sync no longer
            performs a separate restart, so the flag is informational
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("sync", f"Syncing {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, agent_type, claw_record = resolved

    # Issue #426: bridge `agent.providers` (the attach list written by
    # `clawctl agent provider attach`) → `config.provider` (the dict the
    # Ansible templates render). The Pattern A surface from #509 records
    # attachments as metadata only; sync is the declarative reconcile
    # point that materializes those attachments into the agent's config
    # before pushing to the remote. `detach` intentionally does NOT strip
    # `config.provider` — once a provider lands in config it is
    # last-known-good across subsequent syncs (design decision on #426).
    #
    # Issue #501: hermes alone supports N attachments (primary + 9
    # auxiliary slots); zeroclaw/openclaw keep the singleton invariant.
    # Normalization handles both legacy list-of-strings and the new
    # list-of-objects shape transparently.
    raw_attachments = claw_record.get("providers") or []
    attachments = _pa.normalize(raw_attachments, agent_type)
    try:
        _pa.validate(attachments, agent_type)
    except _pa.AttachmentError as exc:
        raise LifecycleError(
            f"agent '{agent_key}' has invalid provider attachments: {exc}. "
            f"Inspect with 'clawctl agent provider get --agent {agent_key}'."
        ) from exc

    provider_overlay: dict | None = None
    provider_overlays: list[dict] | None = None
    provider_name_for_state: str | None = None

    def _build_overlay(provider_name: str) -> dict:
        provider_record = _provider_storage.get_provider(provider_name)
        if provider_record is None:
            raise LifecycleError(
                f"attached provider '{provider_name}' not registered. "
                f"Run 'clawctl provider registry get' to list available providers."
            )
        overlay = {
            "name": provider_record.get("name", ""),
            "type": provider_record.get("type", "ollama"),
            "endpoint": provider_record.get("endpoint", ""),
            "default_model": provider_record.get("default_model", ""),
        }
        # `is not None` instead of truthy: max_tokens=0 / context_window=0
        # are meaningful (no-limit signals on some APIs); a falsy check
        # would silently drop them. ATX iter-1 S1.
        if provider_record.get("context_window") is not None:
            overlay["context_window"] = provider_record["context_window"]
        if provider_record.get("max_tokens") is not None:
            overlay["max_tokens"] = provider_record["max_tokens"]
        return overlay

    if attachments and _pa.supports_multi_provider(agent_type):
        # Hermes path: build a config.providers list (one overlay per
        # attachment, carrying role + per-attachment model) and also
        # populate config.provider from the primary so the bridge
        # contract with downstream readers (templates, validators) is
        # preserved unchanged for back-compat. Phase 1 wires the data
        # model; template rewrites land in Phase 3.
        provider_overlays = []
        for entry in attachments:
            # ATX W5: validate() above guarantees every hermes entry is
            # a dict — but if normalize() ever regresses, silently
            # skipping non-dicts would leave the agent with no primary,
            # no state-machine walk, and a config rendered with empty
            # provider fields that Ansible would happily push. Fail loud.
            if not isinstance(entry, dict):
                raise LifecycleError(
                    f"agent '{agent_key}' has non-dict provider attachment "
                    f"after normalization: {entry!r}. Inspect with "
                    f"'clawctl agent provider get --agent {agent_key}'."
                )
            overlay = _build_overlay(entry["name"])
            overlay["role"] = entry.get("role", "")
            # Per-attachment model override; falls back to provider's
            # default_model when the attachment didn't specify one.
            # Always set `model` explicitly so template authors can
            # read a single field regardless of whether the operator
            # supplied an override.
            attachment_model = entry.get("model") or overlay.get("default_model", "")
            overlay["model"] = attachment_model
            provider_overlays.append(overlay)
            if entry.get("role") == _pa.PRIMARY_ROLE:
                provider_overlay = {
                    k: v for k, v in overlay.items() if k not in ("role",)
                }
                provider_name_for_state = entry["name"]
    elif attachments:
        # Singleton path (zeroclaw/openclaw). normalize() guarantees
        # list-of-strings shape here; validate() guarantees len<=1.
        provider_name = attachments[0]
        if not isinstance(provider_name, str):
            raise LifecycleError(
                f"agent '{agent_key}' provider attachment shape unexpected"
            )
        provider_overlay = _build_overlay(provider_name)
        provider_name_for_state = provider_name

    onboarding = claw_record.get("onboarding", {})
    state_value = onboarding.get("state", "pending")

    try:
        state = OnboardingState(state_value)
    except ValueError:
        state = OnboardingState.PENDING

    # Issue #426 + #523: drive the onboarding state machine forward when
    # a provider attachment is present. Option D semantics: advance as
    # far as the per-agent manifest's `auto_skip` flags allow, completing
    # stages that have no remaining declarative input to gather, and
    # refusing loudly when a required stage has no clawctl declarative
    # surface yet (today only `identity` for openclaw — tracked in #523).
    #
    # This mirrors the legacy `clm agent configure` driver loop
    # (cli/agent.py:2110-2211): transition_state INTO each stage,
    # complete_stage on it, transition_state to the NEXT stage. The
    # difference: we never prompt — anything that would require user
    # input either has a Pattern A attachment behind it or raises.
    #
    # Gate is `state != READY` (not just `== PENDING`) so a re-sync
    # after a previous failed configure_agent (which leaves state at
    # VALIDATE or earlier) can advance the agent the rest of the way.
    # Idempotent operations inside the walk swallow InvalidTransitionError
    # when state is already past a given stage. ATX iter-2 B-ITER2-1.
    # Pre-initialize `walk_completed` so a future refactor adding an
    # early-return path can't cause a NameError at the PENDING gate.
    # ATX iter-3 S2.
    walk_completed = False
    if provider_name_for_state and state != OnboardingState.READY:
        from clawrium.core.onboarding import (
            InvalidTransitionError,
            OnboardingState as _OS,
            StageStatus,
            can_skip_stage,
            complete_stage,
            transition_state,
            update_stage_metadata,
        )

        def _safe_update_metadata(stage: str, meta: dict) -> None:
            # ATX iter-1 W2: `update_stage_metadata` itself raises
            # InvalidTransitionError if the stage record is not in
            # `complete` status. Wrap so any failure here surfaces as a
            # LifecycleError (operator-actionable) rather than escaping
            # as a raw InvalidTransitionError.
            try:
                update_stage_metadata(hostname, agent_key, stage, meta)
            except Exception as exc:
                raise LifecycleError(
                    f"could not update {stage!r} metadata for "
                    f"{agent_key!r}: {exc}. "
                    f"Onboarding state may be corrupt; "
                    f"inspect with 'clawctl agent describe {agent_key}'."
                ) from exc

        def _safe_transition(target: _OS) -> None:
            # InvalidTransitionError on a forward transition we expect
            # to be permissible means state is already at-or-past the
            # target (idempotent re-sync). Swallow; that's the legacy
            # behaviour in cli/agent.py:2165-2168.
            try:
                transition_state(hostname, agent_key, target)
            except InvalidTransitionError:
                pass

        # --- providers stage --------------------------------------
        try:
            complete_stage(
                hostname,
                agent_key,
                "providers",
                StageStatus.COMPLETE,
                {"provider_id": provider_name_for_state},
            )
        except InvalidTransitionError:
            _safe_update_metadata(
                "providers", {"provider_id": provider_name_for_state}
            )
        _safe_transition(_OS.PROVIDERS)

        # --- remaining stages (Option D walk) ---------------------
        # Per #523 audit: openclaw identity lacks a clawctl declarative
        # surface (requires user prompts). Hermes/zeroclaw mark identity
        # `auto_skip: true`. Ethos identity is configure-playbook-owned:
        # configure.yaml renders SOUL.md + toolset.yaml + personality
        # config.yaml, so the stage is legitimately COMPLETE after configure.
        # Channels and validate are completed as state-machine bookkeeping —
        # channels' actual content comes from the separate
        # `clawctl agent channel attach` surface (#509), and validate's
        # health check is implicit in configure_agent's Ansible exit code.
        _NO_DECLARATIVE_SURFACE_YET = {"identity"}
        # Stages that configure.yaml handles directly — mark COMPLETE even
        # without an interactive declarative surface.
        _CONFIGURE_PLAYBOOK_OWNED: set[tuple[str, str]] = {("ethos", "identity")}
        _STAGE_NEXT_STATE = {
            "identity": _OS.IDENTITY,
            "channels": _OS.CHANNELS,
            "validate": _OS.VALIDATE,
        }

        for stage_name in ("identity", "channels", "validate"):
            _safe_transition(_STAGE_NEXT_STATE[stage_name])
            if can_skip_stage(agent_type, stage_name):
                try:
                    complete_stage(
                        hostname, agent_key, stage_name, StageStatus.SKIPPED
                    )
                except InvalidTransitionError:
                    pass
                continue
            if (agent_type, stage_name) in _CONFIGURE_PLAYBOOK_OWNED:
                try:
                    complete_stage(
                        hostname, agent_key, stage_name, StageStatus.COMPLETE
                    )
                except InvalidTransitionError:
                    pass
                continue
            if stage_name in _NO_DECLARATIVE_SURFACE_YET:
                # Issue #577: consult the onboarding ledger (the same
                # source `clawctl agent describe` reads) before raising.
                # If the operator already ran `clawctl agent configure
                # <name> --stage <stage>`, the stage record will be
                # `complete` (or `skipped`) on disk — treat this walk as
                # an idempotent no-op for that stage instead of blocking
                # the providers / sync path forever with a stale gate.
                stage_record = (
                    onboarding.get("stages", {}).get(stage_name, {})
                )
                stage_status = stage_record.get("status")
                if stage_status in (
                    StageStatus.COMPLETE.value,
                    StageStatus.SKIPPED.value,
                ):
                    # ATX #577 W1: emit a breadcrumb so an operator
                    # debugging an unexpectedly-quiet sync can see that
                    # the gate was honored from ledger state rather than
                    # silently bypassed.
                    emit(
                        "sync",
                        f"stage {stage_name!r} already {stage_status} in "
                        f"onboarding ledger for {agent_key}; skipping "
                        f"manual-configure gate",
                    )
                    continue
                raise LifecycleError(
                    f"agent '{agent_key}' (type={agent_type}) requires manual "
                    f"{stage_name} configuration: no clawctl declarative "
                    f"surface exists for the {stage_name} stage yet "
                    f"(tracked in #523). Workaround: complete this stage via "
                    f"'clawctl agent configure {agent_key} --stage {stage_name}', "
                    f"then retry this command."
                )
            try:
                complete_stage(
                    hostname, agent_key, stage_name, StageStatus.COMPLETE
                )
            except InvalidTransitionError:
                pass

        # NOTE: READY transition is deferred until AFTER configure_agent
        # succeeds. Writing state=READY before the Ansible push lands
        # would leave hosts.json showing READY for an agent whose
        # systemd unit was never written if configure_agent then fails.
        # `clawctl agent start` only gates on state==READY, so deferring
        # is the safety boundary. ATX iter-2 B-ITER2-1.
        walk_completed = True
        state = _OS.VALIDATE  # furthest the pre-configure walk advances

    if state == OnboardingState.PENDING and not walk_completed:
        raise LifecycleError(
            f"Cannot sync {agent_key}: onboarding not started (state={state_value}). "
            f"Attach a provider first: 'clawctl agent provider attach <name> "
            f"--agent {agent_key}'."
        )

    # Apply the overlay first so a freshly attached provider can rescue
    # an otherwise-empty config (which would normally be a pathological
    # state — install.py writes config.gateway). ATX iter-1 W5.
    existing_config = claw_record.get("config", {})
    if provider_overlay is not None:
        existing_config = dict(existing_config)
        existing_config["provider"] = provider_overlay
    if provider_overlays is not None:
        # Issue #501: hermes-only multi-provider overlay. Carries
        # per-attachment role + model so the configure playbook can
        # render `auxiliary.<slot>` in hermes-config.yaml.j2 (Phase 3).
        # `config.provider` stays populated above from the primary so
        # existing readers continue to function unchanged in Phase 1.
        #
        # TODO(#501 Phase 3): when hermes-config.yaml.j2 renders
        # `auxiliary.<slot>` per non-primary attachment, configure_agent
        # must also hydrate per-attachment API keys into ansible_vars.
        # Today only the primary's `provider_api_key` is loaded
        # (lifecycle.py configure path), so every auxiliary slot would
        # render with an empty key. Block the Phase 3 template work on
        # this hydration to avoid a silent misconfigure at first use.
        existing_config = dict(existing_config)
        existing_config["providers"] = provider_overlays

    if not existing_config:
        # install.py always writes config.gateway, so this branch
        # implies a corrupt agent record (hand-edited hosts.json) — the
        # only honest remediation is re-create. ATX iter-1 W1 +
        # iter-2 W1 (full --type/--host placeholders).
        raise LifecycleError(
            f"No configuration found for {agent_key}. Agent record is "
            f"incomplete (missing gateway config); re-create the agent: "
            f"'clawctl agent delete {agent_key}' then "
            f"'clawctl agent create {agent_key} --type <type> --host <host>'."
        )

    emit("sync", f"Configuring {agent_key}...")
    config_success, config_error = configure_agent(
        hostname,
        agent_type,
        existing_config,
        agent_name=agent_key,
        on_event=on_event,
        reason="sync",
        playbook_path_override=playbook_path_override,
    )

    if not config_success:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": f"Configure failed: {config_error}",
        }

    # ATX iter-2 B-ITER2-1: only NOW commit READY to disk. Ansible
    # succeeded, so the remote agent is actually configured and
    # `clawctl agent start` is safe to gate on this. Try
    # unconditionally — TRANSITIONS allows VALIDATE→READY and
    # READY→READY (idempotent), the other states reject (in which case
    # the post-configure cosmetic step is skipped without failing
    # sync; state can be repaired by a subsequent sync after manual
    # configure of stuck stages).
    from clawrium.core.onboarding import (
        AgentNotFoundError as _ANF_post,
        InvalidTransitionError as _ITE_post,
        OnboardingNotFoundError as _ONF_post,
        OnboardingState as _OS_post,
        transition_state as _transition_post,
    )

    # B-NEW-2 (ATX #555 polish round 4): mirror
    # `lifecycle_canonical.py:sync_agent_canonical`'s success/error
    # return contract. Only InvalidTransitionError represents a
    # non-failure (mid-walk agent — start_agent will surface the stage).
    # Registry-incoherence and generic IO/permission failures must
    # surface as `success=False` so a CLI handler does not print
    # "✓ sync complete" while the agent is stuck non-READY.
    state_write_ok = True
    state_write_err: str | None = None
    if defer_state_transition:
        # Caller (e.g. lifecycle_macos.sync_agent) owns the READY write
        # so it can gate the transition on a post-configure restart
        # actually succeeding. Skip the write here without failing sync.
        emit(
            "sync",
            "defer_state_transition=true: caller will write state=READY "
            "after its post-configure step completes.",
        )
        return {
            "success": True,
            "agent": agent_key,
            "host": hostname,
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": None,
        }
    try:
        _transition_post(hostname, agent_key, _OS_post.READY)
    except _ITE_post as exc:
        # Stuck mid-walk at PROVIDERS/IDENTITY/CHANNELS, or idempotent
        # READY→READY. No recovery via re-sync; agent is configured
        # remotely, only the local state pointer is stale. Don't fail
        # the sync (configure_agent already succeeded) but emit so the
        # CLI does not print "✓ sync complete" without context — next
        # `clawctl agent start` will otherwise fail with no breadcrumb.
        # W1 (ATX #555 polish round 5) mirrors
        # lifecycle_canonical.py's _ITE branch.
        emit(
            "sync",
            f"note: skipped state=READY transition for {agent_key} "
            f"(agent is mid-walk: {exc!s}). `clawctl agent start` will "
            f"surface the current onboarding stage.",
        )
    except (_ANF_post, _ONF_post) as exc:
        # Registry incoherence: the agent or onboarding record vanished
        # between configure_agent succeeding and the READY write. No
        # recovery via re-sync (same error will fire) — distinct
        # remediation from the IO-failure branch below. ATX iter-5
        # W2-NEW carry-forward.
        state_write_err = (
            f"registry record missing for {agent_key} after configure: "
            f"{exc!s}. Inspect hosts.json manually before running "
            f"clawctl agent start."
        )
        emit("sync", f"warning: {state_write_err}")
        state_write_ok = False
    except Exception as exc:
        # Storage / IO failure (PermissionError, etc.) writing the
        # READY pointer. ATX iter-3 W-NEW-1. Emit raw exception string;
        # rendering-library escaping is the consumer's job (see
        # clawctl/agent/sync.py:on_event and cli/agent.py:on_event for
        # the boundary).
        state_write_err = (
            f"could not write state=READY to hosts.json: {exc!s}. "
            f"Agent is configured remotely; re-run sync to commit state."
        )
        emit("sync", f"warning: {state_write_err}")
        state_write_ok = False

    emit("sync", f"Sync complete for {agent_key}")

    return {
        "success": state_write_ok,
        "agent": agent_key,
        "host": hostname,
        "operation": "sync",
        "pid": None,
        "started_at": None,
        "error": state_write_err,
    }


def _hydrate_channels_from_canonical(
    config_data: dict,
    *,
    host: dict,
    agent_key: str,
    agent_record: dict,
    resolved_type: str,
    include_slack: bool,
) -> tuple[bool, str | None]:
    """Populate `config_data["channels"]` from canonical channels.json + secrets.

    Replaces the legacy hosts.json `agent_record.config.channels.<type>`
    read (the original #555 silent-wipe surface) with a canonical-sourced
    assembly that mirrors what `core/render.build_render_inputs` produces.
    The ansible configure playbook consumes the same legacy dict shape it
    always did (`channels.discord = {enabled, bot_token, ...}` and
    `channels.slack = {enabled, bot_token, app_token, ...}`); only the
    *source* of the data changes.

    For each attached channel (via `get_agent_channels`), we read its
    record from `channels.json`, hydrate the secret from secrets.json,
    and reshape into the legacy dict. Discord and Slack are the only
    types currently supported; other types are ignored at this layer
    (the canonical renderer in `core/render.py` validates the broader
    surface).

    Caller-passed `config_data["channels"]` is overwritten for Discord
    and (when `include_slack`) Slack to keep canonical channels.json as
    the single source of truth — there is no merge path that could
    silently re-introduce the deprecated shape.
    """
    from clawrium.core.channels import (
        get_channel,
        get_channel_token,
    )

    discord_record: dict | None = None
    discord_token: str | None = None
    slack_record: dict | None = None
    slack_bot_token: str | None = None
    slack_app_token: str | None = None

    # Read attached channels off the already-loaded agent_record. This
    # avoids a redundant hosts.json read (which `get_agent_channels`
    # does) and keeps the helper test-friendly: the existing test
    # harnesses for configure_agent mock the agent_record dict but do
    # NOT always materialize hosts.json on disk.
    attached = agent_record.get("channels", [])
    if not isinstance(attached, list):
        attached = []

    for channel_name in attached:
        if not isinstance(channel_name, str):
            continue
        record = get_channel(channel_name)
        if not isinstance(record, dict):
            continue
        ctype = record.get("type") or ""
        if ctype == "discord" and discord_record is None:
            discord_record = record
            discord_token = get_channel_token(channel_name, "BOT_TOKEN")
        elif ctype == "slack" and include_slack and slack_record is None:
            slack_record = record
            slack_bot_token = get_channel_token(channel_name, "BOT_TOKEN")
            slack_app_token = get_channel_token(channel_name, "APP_TOKEN")

    current_channels = config_data.get("channels")
    if not isinstance(current_channels, dict):
        current_channels = {}

    if discord_record is not None:
        cfg = discord_record.get("config") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        if not isinstance(discord_token, str) or len(discord_token) < 50:
            return (
                False,
                "Discord channel attached to this agent but BOT_TOKEN "
                "is missing or invalid in secrets.json. Re-run "
                "'clm channel set-secret <channel> BOT_TOKEN <token>'.",
            )
        current_channels["discord"] = {
            **cfg,
            "enabled": True,
            "bot_token": discord_token,
        }

    if slack_record is not None:
        cfg = slack_record.get("config") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        # Same prefix validation as the legacy block (xoxb-, xapp-).
        if not isinstance(slack_bot_token, str) or not slack_bot_token.startswith(
            "xoxb-"
        ):
            return (
                False,
                "Slack channel attached to this agent but SLACK_BOT_TOKEN is "
                "missing or invalid in secrets.json (expected `xoxb-...`).",
            )
        if not isinstance(slack_app_token, str) or not slack_app_token.startswith(
            "xapp-"
        ):
            return (
                False,
                "Slack channel attached to this agent but SLACK_APP_TOKEN is "
                "missing or invalid in secrets.json (expected `xapp-...`).",
            )
        slack_dict = {
            **cfg,
            "enabled": True,
            "bot_token": slack_bot_token,
            "app_token": slack_app_token,
        }
        current_channels["slack"] = slack_dict

    if discord_record is not None or slack_record is not None:
        config_data["channels"] = current_channels

    # Resolved_type is captured for future per-type branching; not used yet.
    _ = resolved_type
    return True, None


def configure_agent(
    hostname: str,
    claw_name: str,
    config_data: dict,
    agent_name: str | None = None,
    extra_vars: dict | None = None,
    on_event: Callable[[str, str], None] | None = None,
    reason: str = "configure",
    playbook_path_override: Path | None = None,
) -> tuple[bool, str | None]:
    """Configure an agent instance on a remote host.

    Updates the agent configuration in hosts.json and applies the configuration
    to the remote host via Ansible playbook. This is the single source of truth
    for configuration management.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of agent to configure (e.g., "zeroclaw", "openclaw")
        config_data: Configuration dictionary containing gateway and provider settings
        agent_name: Optional specific instance name
        extra_vars: Optional extra Ansible vars (not persisted to hosts.json)
        on_event: Optional callback for progress events

    Returns:
        Tuple of (success, error_message)

    Raises:
        LifecycleError: If host not found or agent not installed
    """
    from clawrium.core.providers import (
        get_provider_api_key,
        get_provider_aws_credentials,
    )
    from clawrium.core.integrations import (
        INTEGRATION_TYPES,
        get_agent_integrations,
        get_integration,
        get_integration_credentials,
    )

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("configure", f"Configuring {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, resolved_type, agent_record = resolved
    # Use inner agent_name (Unix username) if available, otherwise fall back to dict key
    unix_agent_name = agent_record.get("agent_name") or agent_key

    # Hermes: hydrate the persisted api_server block (non-sensitive shape from
    # hosts.json) PLUS the bearer token from secrets.json into config_data so
    # the configure playbook can render API_SERVER_KEY into ~/.hermes/.env.
    # Reconfigure flows reuse the persisted token verbatim (idempotency
    # contract — clients reading the gateway don't see rotation).
    if resolved_type == "hermes":
        from clawrium.core.install import _is_valid_hermes_api_server_key

        persisted_api_server = agent_record.get("config", {}).get("api_server")
        # Use canonical hostname (host['hostname']) instead of the raw hostname
        # parameter so the lookup matches install.py's instance_key even when
        # callers pass an alias. CLI paths today always resolve canonical, but
        # programmatic callers may not.
        instance_key = get_instance_key(
            host.get("key_id") or host["hostname"],
            resolved_type,
            unix_agent_name,
        )
        secret_entry = get_instance_secrets(instance_key).get("HERMES_API_SERVER_KEY")
        # `.get("value")` not `["value"]`: a truthy-but-malformed entry (no
        # "value" field) would otherwise raise KeyError out of configure
        # instead of routing through the validity check below.
        api_server_key = secret_entry.get("value") if secret_entry else None

        if not _is_valid_hermes_api_server_key(api_server_key):
            return (
                False,
                "Hermes agent missing or invalid HERMES_API_SERVER_KEY in "
                "secrets.json (expected 64-char lowercase hex). "
                "Re-run 'clm agent install --type hermes ...' to generate one.",
            )

        if isinstance(persisted_api_server, dict):
            # Opportunistic migration: legacy hermes installs persisted
            # host="127.0.0.1". The OpenAI-compatible gateway must bind a
            # reachable interface so `clm chat <hermes>` works from any clm
            # machine. Hermes' own startup check (api_server.py:3150) refuses
            # to bind non-loopback unless a strong API_SERVER_KEY is set; we
            # always generate a 64-char hex key, so the safety check passes.
            # Rewrite in-memory and persist before merging.
            if persisted_api_server.get("host") == "127.0.0.1":
                persisted_api_server = {**persisted_api_server, "host": "0.0.0.0"}

                def _migrate_bind(h: dict) -> dict:
                    agents = h.get("agents") or {}
                    record = agents.get(agent_key)
                    if not isinstance(record, dict):
                        return h
                    config = record.get("config")
                    if not isinstance(config, dict):
                        return h
                    api_server = config.get("api_server")
                    if (
                        isinstance(api_server, dict)
                        and api_server.get("host") == "127.0.0.1"
                    ):
                        api_server["host"] = "0.0.0.0"
                    return h

                update_host(host["hostname"], _migrate_bind)

            existing_api_server = config_data.get("api_server") or {}
            if not isinstance(existing_api_server, dict):
                existing_api_server = {}
            merged_api_server = {**existing_api_server, **persisted_api_server}
            # ATX iter-1 W6: range-validate the port before forwarding to
            # Ansible. A hand-edited hosts.json with `port: 22` would
            # otherwise propagate into the systemd ExecStart.
            persisted_port = merged_api_server.get("port")
            if not (
                isinstance(persisted_port, int)
                and not isinstance(persisted_port, bool)
                and 8600 <= persisted_port <= 8699
            ):
                logger.warning(
                    "Hermes api_server port %r outside documented window "
                    "8600..8699 — picking a fresh per-instance port.",
                    persisted_port,
                )
                from clawrium.core.install import _pick_per_instance_port

                fresh = _pick_per_instance_port(
                    host,
                    unix_agent_name,
                    base=8600,
                    span=100,
                    port_field_path=("api_server", "port"),
                    preserved_port=None,
                )
                merged_api_server["port"] = fresh
            merged_api_server["key"] = api_server_key
            config_data["api_server"] = merged_api_server
        else:
            # hosts.json shape missing (legacy/corrupted); reconstruct defaults
            # alongside the token from secrets.json so the playbook can run.
            # ATX iter-1 W1: legacy pre-#533 hermes daemons are actually bound
            # to 8642 (the old hardcoded port). Prefer 8642 if it's free on
            # this host so the running daemon is what `clm chat` reaches;
            # only fall through to picking a fresh port when 8642 is taken
            # by a co-tenant. Emit a warning either way so the operator
            # knows a port assignment happened outside the install flow.
            from clawrium.core.install import _pick_per_instance_port

            # 8642 is in the 8600..8699 window, so passing it as
            # preserved_port returns it verbatim when free.
            reconstructed_port = _pick_per_instance_port(
                host,
                unix_agent_name,
                base=8600,
                span=100,
                port_field_path=("api_server", "port"),
                preserved_port=8642,
            )
            logger.warning(
                "Hermes %s on %s has no api_server block in hosts.json — "
                "reconstructing with port %d. If the live daemon is bound "
                "to a different port, `clm chat` will fail until the daemon "
                "is restarted on this port.",
                unix_agent_name,
                host["hostname"],
                reconstructed_port,
            )
            config_data["api_server"] = {
                "enabled": True,
                "host": "0.0.0.0",
                "port": reconstructed_port,
                "key": api_server_key,
            }

            def _persist_reconstructed_api_server(h: dict) -> dict:
                agents = h.get("agents") or {}
                record = agents.get(agent_key)
                if not isinstance(record, dict):
                    return h
                cfg = record.setdefault("config", {})
                cfg["api_server"] = {
                    "enabled": True,
                    "host": "0.0.0.0",
                    "port": reconstructed_port,
                }
                return h

            update_host(host["hostname"], _persist_reconstructed_api_server)

    # Ethos: hydrate the persisted gateway block (non-sensitive shape from
    # hosts.json) PLUS the bearer token from secrets.json into config_data so
    # the configure playbook can render ETHOS_GATEWAY_API_KEY into ~/.ethos/.env.
    # Reconfigure flows reuse the persisted token verbatim (idempotency
    # contract — clients reading the gateway don't see rotation).
    if resolved_type == "ethos":
        persisted_gateway = agent_record.get("config", {}).get("gateway")
        instance_key = get_instance_key(
            host["hostname"], resolved_type, unix_agent_name
        )
        secret_entry = get_instance_secrets(instance_key).get("ETHOS_GATEWAY_API_KEY")
        ethos_api_key = secret_entry.get("value") if secret_entry else None

        if not (
            isinstance(ethos_api_key, str)
            and len(ethos_api_key) == 64
            and all(c in "0123456789abcdef" for c in ethos_api_key)
        ):
            return (
                False,
                "Ethos agent missing or invalid ETHOS_GATEWAY_API_KEY in "
                "secrets.json (expected 64-char lowercase hex). "
                "Re-run 'clawctl agent install --type ethos ...' to generate one.",
            )

        if isinstance(persisted_gateway, dict):
            existing_gateway = config_data.get("gateway") or {}
            if not isinstance(existing_gateway, dict):
                existing_gateway = {}
            merged_gateway = {**existing_gateway, **persisted_gateway}
            # gateway.port = 3000 (ethos web-api, hardcoded upstream).
            # Accept any valid port (1-65535); the 43000-44999 window is for
            # gateway.internal_port (ETHOS_GATEWAY_PORT), not the web-api port.
            persisted_port = merged_gateway.get("port")
            if not (
                isinstance(persisted_port, int)
                and not isinstance(persisted_port, bool)
                and 0 < persisted_port <= 65535
            ):
                logger.warning(
                    "Ethos gateway port %r is not a valid port number — "
                    "falling back to 3000 (ethos web-api default).",
                    persisted_port,
                )
                merged_gateway["port"] = 3000
            merged_gateway["api_key"] = ethos_api_key
            config_data["gateway"] = merged_gateway
        else:
            # hosts.json shape missing; reconstruct with the fixed web-api port.
            logger.warning(
                "Ethos %s on %s has no gateway block in hosts.json — "
                "reconstructing with port 3000 (ethos web-api default).",
                unix_agent_name,
                host["hostname"],
            )
            config_data["gateway"] = {
                "port": 3000,
                "api_key": ethos_api_key,
            }

    # #560: Discord/Slack channel hydration now reads from the canonical
    # `channels.json` store via `_hydrate_channels_from_canonical` rather
    # than the deprecated `agent_record.config.channels.<type>` shape.
    # Ethos supports Discord + Slack (same as hermes), so include_slack=True.
    if resolved_type in ("hermes", "zeroclaw", "ethos"):
        ok, err = _hydrate_channels_from_canonical(
            config_data,
            host=host,
            agent_key=agent_key,
            agent_record=agent_record,
            resolved_type=resolved_type,
            include_slack=(resolved_type in ("hermes", "ethos")),
        )
        if not ok:
            return False, err

    # Validate config data before running Ansible
    # Validate required provider fields (must check dict type first)
    required_provider_fields = ["name", "type", "default_model"]
    if config_data.get("provider"):
        if not isinstance(config_data["provider"], dict):
            return False, "Invalid provider config - expected dict"
        missing = [
            f for f in required_provider_fields if not config_data["provider"].get(f)
        ]
        if missing:
            return False, f"Incomplete provider config - missing: {', '.join(missing)}"

        # Validate model names to prevent template injection
        if config_data["provider"].get("default_model"):
            model_name = config_data["provider"]["default_model"]
            if not re.match(r"^[a-zA-Z0-9_.:/+-]+$", model_name):
                return (
                    False,
                    f"Invalid model name: '{model_name}'. Model names must contain only alphanumeric characters, dots, colons, slashes, underscores, plus, and hyphens.",
                )

        # Ollama providers require endpoint
        if config_data["provider"].get("type") == "ollama":
            if not config_data["provider"].get("endpoint"):
                return False, "Ollama provider requires 'endpoint' field"

    # Issue #445 B1: defensive bearer injection for zeroclaw configure. The
    # CLI paths in cli/agent.py already copy `existing_gateway["auth"]` into
    # config_data when present, but callers that build config_data from
    # scratch (e.g. _run_identity_stage at agent.py:639) won't. Mirror the
    # pattern from _zeroclaw_repair_after_start (line 739) so the playbook's
    # locked-pair branch in tasks/pair.yaml has a Bearer to authenticate
    # /api/pairing/initiate with, instead of sending `Bearer ` (empty) and
    # getting a 401 the operator can't decode.
    #
    # ATX iter-2 NS1 (clarified in iter-3 S1): runs BEFORE the gateway port
    # validation below. The injection populates config_data["gateway"] so
    # the `if config_data.get("gateway")` guard at the validation block
    # becomes truthy and the port check FIRES with a clean
    # "Incomplete gateway config — missing: port" error. In the old
    # position (after validation), a caller that omitted the gateway key
    # left that guard falsy — the port check was silently skipped and the
    # failure surfaced later as a confusing Ansible error.
    if resolved_type == "zeroclaw":
        gw_block = config_data.setdefault("gateway", {})
        if not gw_block.get("auth"):
            record_auth = (
                agent_record.get("config", {}).get("gateway", {}).get("auth") or ""
            )
            gw_block["auth"] = record_auth

    # Validate required gateway fields
    required_gateway_fields = ["port"]
    if config_data.get("gateway"):
        if not isinstance(config_data["gateway"], dict):
            return False, "Invalid gateway config - expected dict"
        missing = [
            f for f in required_gateway_fields if not config_data["gateway"].get(f)
        ]
        if missing:
            return False, f"Incomplete gateway config - missing: {', '.join(missing)}"

    # Load provider API key from secrets if provider is configured
    provider_api_key = ""
    aws_access_key = ""
    aws_secret_key = ""
    if config_data.get("provider") and config_data["provider"].get("name"):
        provider_name = config_data["provider"]["name"]
        provider_type = config_data["provider"].get("type", "")
        if provider_type == "bedrock":
            # Bedrock uses AWS credentials instead of API key
            access_key, secret_key = get_provider_aws_credentials(provider_name)
            if access_key and secret_key:
                aws_access_key = access_key
                aws_secret_key = secret_key
                emit("configure", "Loaded AWS credentials from secrets")
        else:
            provider_api_key = get_provider_api_key(provider_name) or ""
            if provider_api_key:
                emit("configure", "Loaded provider API key from secrets")

    # Load channel secrets (Discord bot token)
    discord_bot_token = ""
    try:
        instance_key = get_instance_key(
            host.get("key_id") or host["hostname"],
            resolved_type,
            unix_agent_name,
        )
        instance_secrets = get_instance_secrets(instance_key)
        # ATX Round 2 W4: match the safe `.get("value")` pattern used
        # by the Hermes API-server-key path (line ~762). A malformed
        # secrets.json entry (truthy dict without a "value" field)
        # otherwise raises KeyError, which the outer `except Exception`
        # silently swallows into an empty token and the user can't tell
        # why Discord/Slack stopped working.
        discord_entry = instance_secrets.get("DISCORD_BOT_TOKEN")
        if isinstance(discord_entry, dict):
            discord_value = discord_entry.get("value")
            if isinstance(discord_value, str):
                discord_bot_token = discord_value
                emit("configure", "Loaded Discord bot token from secrets")
    except Exception as e:
        logger.warning("Failed to load Discord bot token for %s: %s", agent_key, e)

    # Load channel secrets (Slack bot token)
    slack_bot_token = ""
    slack_app_token = ""
    try:
        instance_key = get_instance_key(
            host.get("key_id") or host["hostname"],
            resolved_type,
            unix_agent_name,
        )
        instance_secrets = get_instance_secrets(instance_key)
        # ATX Round 2 W4: same safe-indexing pattern as Discord above.
        slack_bot_entry = instance_secrets.get("SLACK_BOT_TOKEN")
        if isinstance(slack_bot_entry, dict):
            slack_bot_value = slack_bot_entry.get("value")
            if isinstance(slack_bot_value, str):
                slack_bot_token = slack_bot_value
                emit("configure", "Loaded Slack bot token from secrets")
        slack_app_entry = instance_secrets.get("SLACK_APP_TOKEN")
        if isinstance(slack_app_entry, dict):
            slack_app_value = slack_app_entry.get("value")
            if isinstance(slack_app_value, str):
                slack_app_token = slack_app_value
                emit("configure", "Loaded Slack app token from secrets")
    except Exception as e:
        logger.warning("Failed to load Slack tokens for %s: %s", agent_key, e)

    # Load integrations assigned to this agent
    # Key by integration_name to avoid collisions when multiple integrations
    # of the same type are assigned (e.g., work-github and personal-github)
    integrations_data: dict[str, dict] = {}
    assigned_integrations = get_agent_integrations(hostname, agent_key)
    for integration_name in assigned_integrations:
        integration = get_integration(integration_name)
        if not integration:
            logger.warning(
                "Integration '%s' assigned to %s not found, skipping",
                integration_name,
                agent_key,
            )
            continue
        integration_type = integration.get("type", "")
        # Surface unknown types (e.g., a stale `jira`/`confluence` record from
        # before this PR, or a missing/empty `type` from a hand-edited file)
        # so the user knows MCP wiring will be a no-op rather than silently
        # shipping a green configure with no Atlassian access. Empty string is
        # not a key in INTEGRATION_TYPES, so the same branch catches both.
        if integration_type not in INTEGRATION_TYPES:
            valid = ", ".join(sorted(INTEGRATION_TYPES.keys()))
            warning_msg = (
                f"WARNING: integration '{integration_name}' has unknown type "
                f"'{integration_type}' — skipping. Valid types: {valid}. "
                f"Run `clm integration remove {integration_name}` and "
                f"`clm integration add {integration_name} --type <valid-type>` "
                "to recover."
            )
            emit("configure", warning_msg)
            logger.warning(warning_msg)
            continue
        credentials = get_integration_credentials(integration_name)
        if credentials:
            # Store by integration_name with type and credentials
            # Templates access via: integrations.<name>.type and integrations.<name>.<key>
            integrations_data[integration_name] = {
                "type": integration_type,
                **credentials,
            }
            emit(
                "configure",
                f"Loaded {integration_name} ({integration_type}) credentials",
            )
        else:
            logger.warning(
                "No credentials found for integration '%s', skipping",
                integration_name,
            )

    # Get template path for this agent type
    canonical_name = _resolve_agent_type(resolved_type)
    template_path = (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / canonical_name
        / "templates"
    )

    if not template_path.exists():
        return False, f"Template directory not found: {template_path}"

    # Shared cross-claw templates (e.g. gitconfig.j2 — issue #531).
    # Referenced from per-claw playbooks via `{{ shared_template_path }}`.
    shared_template_path = Path(__file__).parent.parent / "platform" / "templates"

    # Get playbook path. The `playbook_path_override` hook lets the
    # caller (e.g. `lifecycle_macos.configure_agent`) supply a different
    # playbook without core/lifecycle.py needing to know which OS it is.
    if playbook_path_override is not None:
        playbook_path = playbook_path_override
    else:
        playbook_path = _get_lifecycle_playbook_path(resolved_type, "configure")
    if not playbook_path.exists():
        return False, f"Configure playbook not found: {playbook_path}"

    # Get SSH key
    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return False, "SSH key not found"

    if not unix_agent_name:
        return False, f"No agent name recorded for '{claw_name}' on '{hostname}'"

    # Validate agent_name to prevent path traversal/injection in Ansible playbooks
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", unix_agent_name):
        return (
            False,
            f"Invalid agent_name format: '{unix_agent_name}'. Must start with lowercase letter and contain only lowercase letters, digits, hyphens, underscores (max 32 chars)",
        )

    # #583: pre-render canonical config files via `clawrium.core.render`
    # and hand them to the Ansible playbook as plain string vars. The
    # playbook then deploys with `copy: content: ...` instead of
    # `ansible.builtin.template:`. This collapses the dual-render path
    # (Jinja-in-Python AND Jinja-in-Ansible against the same template
    # file) into a single source of truth — closing the same class of
    # bug as #555/#582, where one render path silently diverges from
    # the other.
    #
    # Today only zeroclaw config.toml is pre-rendered (it uses the
    # custom `toq` filter that Ansible's Jinja env can't discover
    # reliably under ansible-runner's private_data_dir layout). Hermes
    # and openclaw playbook templates still render via Ansible's
    # template module — they don't use custom filters, so the dual
    # path doesn't bite them yet. Extending to them is a follow-up.
    prerendered_files: dict[str, str] = {}
    if resolved_type == "zeroclaw":
        try:
            from clawrium.core.render import build_render_inputs, render_zeroclaw

            render_inputs = build_render_inputs(unix_agent_name)
            rendered = render_zeroclaw(render_inputs)
            # Key matches the rendered.files dict from render_zeroclaw —
            # the playbook references this by its full key so the var
            # name and the file path stay locked together.
            prerendered_files[".zeroclaw/config.toml"] = (
                rendered.files[".zeroclaw/config.toml"]
            )
        except Exception as exc:
            # Surface the render failure with the same error shape the
            # Ansible reporter uses, so the operator sees a single
            # consistent failure mode instead of two.
            logger.warning(
                "Pre-render of zeroclaw config.toml failed for %s: %s — "
                "configure will fall back to the playbook template task "
                "and likely fail with the same error.",
                unix_agent_name,
                exc,
            )
    elif resolved_type == "hermes":
        # #622: pre-render canonical hermes config + env via render_hermes
        # so the playbook can `copy: content:` the bytes instead of
        # templating server-side. Collapses the dual-render path (legacy
        # hermes-config.yaml.j2 vs canonical hermes-config.canonical.yaml.j2)
        # into a single source of truth and unbreaks multi-provider on
        # `clawctl agent configure` — see #622.
        from clawrium.core.render import (
            AgentConfigError,
            build_render_inputs,
            render_hermes,
        )

        try:
            render_inputs = build_render_inputs(unix_agent_name)
            rendered = render_hermes(render_inputs)
            prerendered_files[".hermes/.env"] = rendered.files[".hermes/.env"]
            prerendered_files[".hermes/config.yaml"] = (
                rendered.files[".hermes/config.yaml"]
            )
        except AgentConfigError as exc:
            # Loud failure at assembly time: same-type provider conflicts,
            # >1 bedrock attachment, etc. Nothing pushed to host.
            return False, f"Hermes render failed: {exc}"
        except Exception as exc:
            # ATX iter-1 B1 (#622): match the zeroclaw block's broad
            # except. TemplateError from a malformed canonical .j2,
            # KeyError on an unexpected hosts.json shape, IOError on the
            # importlib.resources read — all must surface as a clean
            # (False, msg) instead of an unhandled traceback that leaves
            # the lifecycle state machine half-walked.
            return False, f"Hermes render failed: {exc}"

    # Build Ansible inventory with API key passed directly
    ansible_vars = {
        "agent_name": unix_agent_name,
        "agent_type": resolved_type,
        "config": config_data,
        "template_path": str(template_path),
        "shared_template_path": str(shared_template_path),
        "provider_api_key": provider_api_key,
        "aws_access_key": aws_access_key,
        "aws_secret_key": aws_secret_key,
        "discord_bot_token": discord_bot_token,
        "slack_bot_token": slack_bot_token,
        "slack_app_token": slack_app_token,
        "integrations": integrations_data,
        "prerendered_zeroclaw_config_toml": prerendered_files.get(
            ".zeroclaw/config.toml", ""
        ),
        "prerendered_hermes_env": prerendered_files.get(".hermes/.env", ""),
        "prerendered_hermes_config_yaml": prerendered_files.get(
            ".hermes/config.yaml", ""
        ),
    }

    # Issue #437: zeroclaw always re-pairs on configure. No skip path,
    # no existing_gateway_token, no force_repair. The token in hosts.json
    # is overwritten with whatever the playbook's pair handshake mints.

    # Merge extra_vars (not persisted to hosts.json)
    if extra_vars:
        ansible_vars.update(extra_vars)

    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_host": host["hostname"],
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                    "ansible_become_timeout": 120,
                    "ansible_pipelining": True,
                    "ansible_ssh_extra_args": "-o ServerAliveInterval=30 -o ServerAliveCountMax=10 -o ConnectTimeout=60",
                }
            },
            "vars": ansible_vars,
        }
    }

    # Set up logging
    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = _safe_host_display(host, hostname)
    operation_log_dir = (
        logs_dir / f"configure-{resolved_type}-{host_display}-{timestamp}"
    )
    operation_log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(operation_log_dir, 0o700)

    emit("configure", "Running Ansible playbook...")

    # Hermes' configure flow restarts the service and probes /health with up
    # to 20×3s retries (60s) — leave generous headroom for slow first-startup
    # path that loads the agent venv. Zeroclaw's configure does a pairing
    # handshake + /health/providers probe (30×2s = 60s upper bound) plus 7
    # workspace template renders after #358 — 60s leaves no margin, so the
    # claw gets a 180s budget. Other claws keep the legacy 60s budget.
    if resolved_type == "hermes":
        configure_timeout = 240
    elif resolved_type == "zeroclaw":
        configure_timeout = 180
    elif resolved_type == "ethos":
        configure_timeout = 120
    else:
        configure_timeout = 60

    # #583: per-claw `filter_plugins/` directory adjacent to the playbook.
    # Ansible's auto-discovery does not find it reliably under
    # ansible-runner's private_data_dir layout, so we plumb it as an
    # explicit env var. Mirrors the Jinja filters registered in
    # `clawrium.core.render` (e.g. `toq`) so both render paths agree.
    filter_plugin_dir = playbook_path.parent / "filter_plugins"
    ansible_runner_envvars: dict[str, str] = {
        "ANSIBLE_HOST_KEY_CHECKING": "False",
        "ANSIBLE_PIPELINING": "True",
    }
    if filter_plugin_dir.is_dir():
        ansible_runner_envvars["ANSIBLE_FILTER_PLUGINS"] = str(
            filter_plugin_dir
        )

    try:
        result = ansible_runner.run(
            private_data_dir=str(operation_log_dir),
            inventory=inventory,
            playbook=str(playbook_path),
            envvars=ansible_runner_envvars,
            quiet=True,
            timeout=configure_timeout,
        )

        if result.status == "timeout":
            return False, "Configure operation timed out"

        if result.status != "successful":
            return False, _summarize_ansible_configure_failure(
                result, str(operation_log_dir)
            )

        # ZeroClaw: extract the bearer token + gateway URL the configure
        # playbook minted via the pairing handshake. configure.yaml emits
        # them as cacheable host facts (`zeroclaw_gateway_token` and
        # `zeroclaw_gateway_url`); we read them out of the fact cache and
        # surface them via `config_data["gateway"]` so the updater below
        # persists them to hosts.json under
        # `agents.<n>.config.gateway.{auth,url}`. Mirrors the OpenClaw fact
        # extraction in install.py:688-794. Done outside the updater closure
        # so any read failure surfaces as a configure-time error rather than
        # corrupting hosts.json silently.
        zc_gateway_token: str | None = None
        zc_gateway_url: str | None = None
        prior_zc_token: str | None = None
        if resolved_type == "zeroclaw":
            try:
                artifacts_dir = Path(result.config.artifact_dir)
                fact_cache_dir = artifacts_dir / "fact_cache"
                if fact_cache_dir.exists():
                    for fact_file in fact_cache_dir.glob("*"):
                        try:
                            with open(fact_file) as fh:
                                facts = json.load(fh)
                        except (json.JSONDecodeError, IOError) as file_err:
                            logger.debug(
                                "Skipping fact file %s: %s", fact_file, file_err
                            )
                            continue
                        payload = facts.get("__payload__")
                        if not isinstance(payload, str) or not payload:
                            continue
                        try:
                            parsed = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(parsed, dict):
                            continue

                        token_raw = parsed.get("zeroclaw_gateway_token")
                        url_raw = parsed.get("zeroclaw_gateway_url")
                        health_warn_raw = parsed.get("zeroclaw_provider_health_warning")

                        # Tolerate Ansible's occasional `{"value": "..."}`
                        # wrapping for cacheable string facts.
                        if isinstance(token_raw, dict):
                            token_raw = token_raw.get("value")
                        if isinstance(url_raw, dict):
                            url_raw = url_raw.get("value")
                        if isinstance(health_warn_raw, dict):
                            health_warn_raw = health_warn_raw.get("value")
                        if isinstance(token_raw, str):
                            token_raw = token_raw.strip()
                        if isinstance(url_raw, str):
                            url_raw = url_raw.strip()

                        # ATX Round 2 W1: when the playbook recorded a
                        # 401 from /health/providers, surface a one-shot
                        # warning to the CLI event stream. Without this
                        # the operator finishes configure with exit 0
                        # and a silently-misconfigured provider — they
                        # only learn at the next `clm chat` invocation.
                        if health_warn_raw is True or health_warn_raw == "true":
                            # ATX Round 4 B1: same "WARNING:" /
                            # stage="configure" pattern as the
                            # short-token re-pair warning above —
                            # ensures `_print_configure_warnings`
                            # actually surfaces this to the user
                            # instead of silently emitting at INFO.
                            health_warning_msg = (
                                f"WARNING: /health/providers returned "
                                f"401 — gateway is reachable but "
                                f"provider "
                                f"'{config_data.get('provider', {}).get('type', '?')}' "
                                f"credentials may be invalid. Verify "
                                f"the API key and re-run "
                                f"`clm agent configure {agent_key}` "
                                f"if needed."
                            )
                            emit("configure", health_warning_msg)
                            logger.warning(health_warning_msg)

                        if (
                            isinstance(token_raw, str)
                            and token_raw
                            and isinstance(url_raw, str)
                            and url_raw
                        ):
                            zc_gateway_token = token_raw
                            zc_gateway_url = url_raw
                            emit("configure", "Pairing token captured")
                            break
            except Exception as exc:
                logger.warning(
                    "Failed to extract zeroclaw gateway facts: %s",
                    exc,
                    exc_info=True,
                )

            if not zc_gateway_token or not zc_gateway_url:
                # The playbook succeeded but the token did not surface in
                # the fact cache. Fail fast — without a bearer token, the
                # later `clm chat` call has nothing to authenticate with
                # and would dead-end at the gateway.
                return (
                    False,
                    "Configure playbook succeeded but the pairing token "
                    "was not captured. Re-run `clm agent configure "
                    f"{agent_key}` and check daemon logs at "
                    f"`journalctl --unit zeroclaw-{agent_key}` for the "
                    "pairing handshake.",
                )

            # Surface to the updater via config_data so the gateway block
            # round-trips into hosts.json on the same write that persists
            # everything else from this configure call.
            existing_gateway = config_data.get("gateway")
            if not isinstance(existing_gateway, dict):
                existing_gateway = {}
            existing_gateway = dict(existing_gateway)
            existing_gateway["auth"] = zc_gateway_token
            existing_gateway["url"] = zc_gateway_url
            config_data["gateway"] = existing_gateway

            # Capture the prior token now; the rotation event is emitted
            # AFTER `update_host` succeeds below (ATX W2 — emitting before
            # the write means a failed write would still surface the
            # yellow "rotated" notice while hosts.json still holds the
            # old bearer, contradicting the invariant).
            prior_zc_token = (
                agent_record.get("config", {}).get("gateway", {}).get("auth")
            )

        # B2: Only update hosts.json after Ansible succeeds
        emit("configure", "Saving configuration to hosts.json...")

        def updater(h: dict) -> dict:
            if "agents" not in h:
                h["agents"] = {}
            if agent_key not in h["agents"]:
                h["agents"][agent_key] = {}
            h["agents"][agent_key]["type"] = resolved_type

            # Preserve device credentials when updating config
            existing_config = h["agents"][agent_key].get("config", {})
            existing_gateway = existing_config.get("gateway", {})
            device_creds = existing_gateway.get("device")

            # Strip the hermes bearer token before persisting to hosts.json.
            # The token was hydrated into config_data['api_server']['key']
            # earlier in this call (line ~752) so the ansible playbook could
            # render it, but the canonical store is secrets.json. Keeping it
            # in hosts.json after configure would defeat the B3 migration.
            persisted_config = dict(config_data)
            if resolved_type == "hermes":
                if "api_server" in persisted_config:
                    api_server_persisted = dict(persisted_config["api_server"])
                    api_server_persisted.pop("key", None)
                    persisted_config["api_server"] = api_server_persisted

            # B3 invariant for Discord: bot_token lives in secrets.json only,
            # never in hosts.json. Applies to both hermes (DISCORD_BOT_TOKEN
            # hydrated into .env via .env.j2) and zeroclaw (#422 — token
            # hydrated into config.toml's [channels.discord]). Without this
            # strip, the bot_token roundtrips: hydrated → persisted → read
            # back into existing_config on next configure → re-hydrated, etc.
            # ATX B1 finding. Slack inclusion is hermes-only in practice but
            # the pop is idempotent on absent keys so leaving it covers both
            # agent types in one branch.
            if resolved_type in ("hermes", "zeroclaw"):
                if "channels" in persisted_config:
                    channels_persisted = persisted_config.get("channels")
                    if isinstance(channels_persisted, dict):
                        channels_persisted = dict(channels_persisted)
                        discord_persisted = channels_persisted.get("discord")
                        if isinstance(discord_persisted, dict):
                            discord_persisted = dict(discord_persisted)
                            discord_persisted.pop("bot_token", None)
                            channels_persisted["discord"] = discord_persisted
                        slack_persisted = channels_persisted.get("slack")
                        if isinstance(slack_persisted, dict):
                            slack_persisted = dict(slack_persisted)
                            slack_persisted.pop("bot_token", None)
                            slack_persisted.pop("app_token", None)
                            channels_persisted["slack"] = slack_persisted
                        persisted_config["channels"] = channels_persisted
                    else:
                        # Unexpected shape (string/list/etc.) — drop rather
                        # than risk persisting a token via an unknown path.
                        logger.warning(
                            "Dropping unexpected channels block (type=%s) for "
                            "agent %s during persist to avoid B3 violation.",
                            type(channels_persisted).__name__,
                            agent_key,
                        )
                        persisted_config.pop("channels", None)

            h["agents"][agent_key]["config"] = persisted_config

            # Restore device credentials if they existed
            if device_creds:
                if "gateway" not in h["agents"][agent_key]["config"]:
                    h["agents"][agent_key]["config"]["gateway"] = {}
                h["agents"][agent_key]["config"]["gateway"]["device"] = device_creds

            return h

        if not update_host(host["hostname"], updater):
            logger.warning(
                "Ansible succeeded but failed to update hosts.json for %s on %s",
                claw_name,
                hostname,
            )
            return (
                False,
                f"Configuration applied but failed to update local state for {agent_key} on {hostname}",
            )

        # ATX W2: rotation event fires only after the disk write
        # succeeded. Suppressed on first mint (prior token absent).
        if resolved_type == "zeroclaw" and zc_gateway_token:
            _emit_gateway_token_rotated(
                on_event,
                agent_key,
                prior_zc_token,
                zc_gateway_token,
                reason,
            )

        # Ethos: create an API key via SSH and store as ETHOS_CHAT_TOKEN.
        # Done post-configure (service is running) via a direct SSH call so
        # we don't depend on Ansible fact-cache persistence.
        if resolved_type == "ethos":
            ethos_chat_token = _create_ethos_chat_token(
                host, agent_key, ssh_key, on_event
            )
            if ethos_chat_token:
                instance_key = get_instance_key(host["hostname"], "ethos", agent_key)
                set_instance_secret(
                    instance_key,
                    "ETHOS_CHAT_TOKEN",
                    ethos_chat_token,
                    description="Ethos /v1 chat bearer token (clm-managed)",
                )
                emit("configure", f"Stored ETHOS_CHAT_TOKEN for {agent_key}")

        emit("configure", f"Successfully configured {agent_key}")
        return True, None

    except Exception as e:
        return False, str(e)
    finally:
        # W4 fix: Always clean up artifacts containing secrets (success, failure, or exception)
        _cleanup_ansible_artifacts(operation_log_dir)


def remove_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    force: bool = False,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Remove an agent instance from a remote host.

    Stops the agent if running, removes all artifacts from the remote host,
    and removes the agent from local configuration.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of agent to remove (e.g., "openclaw")
        force: Skip confirmation prompts (not used here, handled by CLI)
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("validate", f"Checking {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, agent_type, claw_record = resolved

    # Check if agent is running and stop it first
    runtime = claw_record.get("runtime", {})
    status = runtime.get("status", "stopped")

    if status == "running":
        emit("remove", f"Stopping {agent_key} before removal...")
        try:
            stop_result = stop_agent(
                hostname, claw_name, agent_name=agent_key, on_event=on_event
            )
            if not stop_result["success"]:
                logger.warning(
                    "Failed to stop %s cleanly: %s", agent_key, stop_result["error"]
                )
                emit(
                    "remove",
                    "Warning: Failed to stop cleanly, continuing with removal...",
                )
        except Exception as e:
            logger.warning("Error stopping %s: %s", agent_key, e)
            emit("remove", "Warning: Error stopping, continuing with removal...")

    emit("remove", f"Removing {agent_key} from {hostname}...")

    success, error = _run_lifecycle_playbook(
        agent_type, agent_key, host["hostname"], "remove", host, timeout=120
    )

    if not success:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    emit("remove", "Removing from local configuration...")

    # Resolve the Unix agent name once — used by both secrets cleanup
    # and state cleanup below. Previously computed independently in each
    # try-block, risking drift.
    unix_agent_name = claw_record.get("agent_name") or agent_key

    # Clean up per-instance secrets (Discord bot token, etc.)
    try:
        instance_key = get_instance_key(
            host.get("key_id") or host["hostname"], agent_type, unix_agent_name
        )
        remove_instance_secrets(instance_key)
        emit("remove", "Cleaned up instance secrets")
    except Exception as e:
        logger.warning("Failed to clean up instance secrets for %s: %s", agent_key, e)

    # Clean up agent state directory (skills.json, etc.)
    try:
        cleaned = cleanup_agent_state(unix_agent_name)
        if cleaned:
            emit("remove", "Cleaned up agent state directory")
        else:
            emit("remove", "Agent state directory already absent")
    except Exception as e:
        logger.warning("Failed to clean up agent state for %s: %s", agent_key, e)

    # Remove agent from hosts.json
    # NOTE: remove_agent_from_host returns True if host was found (not if agent was found)
    # An exception here means the local config could not be updated after remote cleanup
    try:
        removed = remove_agent_from_host(host["hostname"], agent_key)
        if not removed:
            # Host not found - this shouldn't happen since we validated it earlier
            logger.error(
                "Host %s not found in configuration after remote cleanup", hostname
            )
            return {
                "success": False,
                "agent": agent_key,
                "host": hostname,
                "operation": "remove",
                "pid": None,
                "started_at": None,
                "error": f"Remote removal succeeded but host '{hostname}' not found in local config. State may be inconsistent.",
            }
    except Exception as e:
        logger.error("Failed to update local configuration after remote cleanup: %s", e)
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": f"Remote removal succeeded but local config update failed: {e}. Run 'clm host ps {hostname}' to verify or manually edit hosts.json.",
        }

    emit("remove", f"Removed {agent_key} successfully")

    return {
        "success": True,
        "agent": agent_key,
        "host": hostname,
        "operation": "remove",
        "pid": None,
        "started_at": None,
        "error": None,
    }

"""Agent lifecycle management for claw instances.

This module handles start, stop, and restart operations for claw instances
running on remote hosts via systemd service management.
"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

import ansible_runner

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host, update_host, remove_claw_from_host
from clawrium.core import keys as core_keys
from clawrium.core.onboarding import OnboardingState
from clawrium.core.secrets import get_instance_key, get_instance_secrets

logger = logging.getLogger(__name__)

__all__ = [
    "start_claw",
    "stop_claw",
    "restart_claw",
    "remove_claw",
    "LifecycleError",
    "LifecycleResult",
]


class LifecycleError(Exception):
    """Raised when lifecycle operation fails."""

    pass


class LifecycleResult(TypedDict):
    """Result of lifecycle operation."""

    success: bool
    claw: str
    host: str
    operation: str
    pid: int | None
    started_at: str | None
    error: str | None


ALIAS_TO_CANONICAL = {
    "opc": "openclaw",
    "zc": "zeroclaw",
    "nc": "nemoclaw",
}


def get_host_private_key(key_id: str) -> Path | None:
    """Resolve host SSH key path.

    Wrapper kept in this module to preserve patch points in tests.
    """
    return core_keys.get_host_private_key(key_id)


def _resolve_claw_name(claw_name: str) -> str:
    """Resolve claw alias to canonical name."""
    return ALIAS_TO_CANONICAL.get(claw_name, claw_name)


def _get_lifecycle_playbook_path(claw_name: str, operation: str) -> Path:
    canonical_name = _resolve_claw_name(claw_name)
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


def _update_claw_runtime(hostname: str, claw_name: str, runtime_data: dict) -> bool:
    """Update claw runtime information in hosts.json.

    Args:
        hostname: The hostname of the host
        claw_name: Name of the claw
        runtime_data: Runtime data to store (pid, started_at, status, etc.)

    Returns:
        True if update succeeded
    """

    def updater(h: dict) -> dict:
        if "claws" not in h:
            h["claws"] = {}
        if claw_name not in h["claws"]:
            h["claws"][claw_name] = {}
        h["claws"][claw_name]["runtime"] = runtime_data
        return h

    return update_host(hostname, updater)


def _run_lifecycle_playbook(
    claw_name: str,
    hostname: str,
    operation: str,
    host: dict,
    timeout: int = 60,
) -> tuple[bool, str | None]:
    """Run a lifecycle playbook on a host.

    Args:
        claw_name: Type of claw
        hostname: Target hostname
        operation: Operation to perform ("start" or "stop")
        host: Host record dict
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, error_message)
    """
    playbook_path = _get_lifecycle_playbook_path(claw_name, operation)

    if not playbook_path.exists():
        return False, f"Playbook not found: {playbook_path}"

    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return False, "SSH key not found"

    claw_record = host.get("claws", {}).get(claw_name, {})
    claw_user = claw_record.get("user", f"{claw_name[:3]}-{hostname}")

    # Validate claw_user to prevent path traversal/injection in Ansible playbooks
    # Expected format: <prefix>-<identifier> where prefix is 2-3 lowercase letters
    if not re.match(r"^[a-z]{2,3}-[a-z0-9_-]+$", claw_user):
        return (
            False,
            f"Invalid claw_user format: '{claw_user}'. Expected pattern: <prefix>-<identifier>",
        )

    instance_key = None
    secret_vars = {}
    try:
        instance_key = get_instance_key(
            hostname,
            claw_name,
            claw_user.split("-")[1] if "-" in claw_user else "default",
        )
        instance_secrets = get_instance_secrets(instance_key)
        for key, entry in instance_secrets.items():
            secret_vars[key.lower()] = entry.get("value", "")
    except Exception:
        pass

    inventory = {
        "all": {
            "hosts": {
                hostname: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": {
                "claw_user": claw_user,
                "claw_name": claw_name,
                "service_name": f"{claw_name}-{claw_user.split('-', 1)[1] if '-' in claw_user else hostname}",
                **secret_vars,
            },
        }
    }

    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = host.get("alias") or host.get("key_id") or hostname
    operation_log_dir = logs_dir / f"{operation}-{claw_name}-{host_display}-{timestamp}"
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
                    if "msg" in res:
                        error_msg = res["msg"]
                        break
                    if "stderr" in res:
                        error_msg = res["stderr"]
                        break
            return False, error_msg

        return True, None

    except Exception as e:
        return False, str(e)


def start_claw(
    hostname: str,
    claw_name: str,
    force: bool = False,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Start a claw instance on a remote host.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of claw to start (e.g., "openclaw")
        force: Bypass onboarding check (not recommended)
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    emit("validate", f"Checking {claw_name} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    claw_record = host.get("claws", {}).get(claw_name)
    if not claw_record:
        raise LifecycleError(f"Claw '{claw_name}' not installed on '{hostname}'")

    onboarding = claw_record.get("onboarding", {})
    state_value = onboarding.get("state", "pending")

    try:
        state = OnboardingState(state_value)
    except ValueError:
        state = OnboardingState.PENDING

    if state != OnboardingState.READY and not force:
        raise LifecycleError(
            f"Cannot start {claw_name}: onboarding incomplete (state={state_value}). "
            f"Run 'clm agent configure {claw_name[:3]}-{hostname}' first."
        )

    emit("start", f"Starting {claw_name} on {hostname}...")

    success, error = _run_lifecycle_playbook(claw_name, host["hostname"], "start", host)

    if not success:
        return {
            "success": False,
            "claw": claw_name,
            "host": hostname,
            "operation": "start",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    now = datetime.now(timezone.utc).isoformat()
    _update_claw_runtime(
        host["hostname"],
        claw_name,
        {
            "status": "running",
            "started_at": now,
            "last_check": now,
        },
    )

    emit("start", f"Started {claw_name} successfully")

    return {
        "success": True,
        "claw": claw_name,
        "host": hostname,
        "operation": "start",
        "pid": None,
        "started_at": now,
        "error": None,
    }


def stop_claw(
    hostname: str,
    claw_name: str,
    timeout: int = 30,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Stop a claw instance on a remote host.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of claw to stop (e.g., "openclaw")
        timeout: Seconds to wait for graceful shutdown
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    emit("validate", f"Checking {claw_name} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    claw_record = host.get("claws", {}).get(claw_name)
    if not claw_record:
        raise LifecycleError(f"Claw '{claw_name}' not installed on '{hostname}'")

    emit("stop", f"Stopping {claw_name} on {hostname}...")

    success, error = _run_lifecycle_playbook(
        claw_name, host["hostname"], "stop", host, timeout=timeout + 30
    )

    if not success:
        return {
            "success": False,
            "claw": claw_name,
            "host": hostname,
            "operation": "stop",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    now = datetime.now(timezone.utc).isoformat()
    _update_claw_runtime(
        host["hostname"],
        claw_name,
        {
            "status": "stopped",
            "started_at": None,
            "stopped_at": now,
            "last_check": now,
        },
    )

    emit("stop", f"Stopped {claw_name} successfully")

    return {
        "success": True,
        "claw": claw_name,
        "host": hostname,
        "operation": "stop",
        "pid": None,
        "started_at": None,
        "error": None,
    }


def restart_claw(
    hostname: str,
    claw_name: str,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Restart a claw instance on a remote host.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of claw to restart (e.g., "openclaw")
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    emit("restart", f"Restarting {claw_name} on {hostname}...")

    stop_result = stop_claw(hostname, claw_name, on_event=on_event)
    if not stop_result["success"]:
        return {
            "success": False,
            "claw": claw_name,
            "host": hostname,
            "operation": "restart",
            "pid": None,
            "started_at": None,
            "error": f"Stop failed: {stop_result['error']}",
        }

    start_result = start_claw(hostname, claw_name, on_event=on_event)
    start_result["operation"] = "restart"

    return start_result


def remove_claw(
    hostname: str,
    claw_name: str,
    force: bool = False,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Remove a claw instance from a remote host.

    Stops the claw if running, removes all artifacts from the remote host,
    and removes the claw from local configuration.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of claw to remove (e.g., "openclaw")
        force: Skip confirmation prompts (not used here, handled by CLI)
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    emit("validate", f"Checking {claw_name} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    claw_record = host.get("claws", {}).get(claw_name)
    if not claw_record:
        raise LifecycleError(f"Claw '{claw_name}' not installed on '{hostname}'")

    # Check if claw is running and stop it first
    runtime = claw_record.get("runtime", {})
    status = runtime.get("status", "stopped")

    if status == "running":
        emit("remove", f"Stopping {claw_name} before removal...")
        try:
            stop_result = stop_claw(hostname, claw_name, on_event=on_event)
            if not stop_result["success"]:
                logger.warning(
                    "Failed to stop %s cleanly: %s", claw_name, stop_result["error"]
                )
                emit(
                    "remove",
                    "Warning: Failed to stop cleanly, continuing with removal...",
                )
        except Exception as e:
            logger.warning("Error stopping %s: %s", claw_name, e)
            emit("remove", "Warning: Error stopping, continuing with removal...")

    emit("remove", f"Removing {claw_name} from {hostname}...")

    success, error = _run_lifecycle_playbook(
        claw_name, host["hostname"], "remove", host, timeout=120
    )

    if not success:
        return {
            "success": False,
            "claw": claw_name,
            "host": hostname,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    emit("remove", "Removing from local configuration...")

    # Remove claw from hosts.json
    # NOTE: remove_claw_from_host returns True if host was found (not if claw was found)
    # An exception here means the local config could not be updated after remote cleanup
    try:
        removed = remove_claw_from_host(host["hostname"], claw_name)
        if not removed:
            # Host not found - this shouldn't happen since we validated it earlier
            logger.error(
                "Host %s not found in configuration after remote cleanup", hostname
            )
            return {
                "success": False,
                "claw": claw_name,
                "host": hostname,
                "operation": "remove",
                "pid": None,
                "started_at": None,
                "error": f"Remote removal succeeded but host '{hostname}' not found in local config. State may be inconsistent.",
            }
    except Exception as e:
        logger.error(
            "Failed to update local configuration after remote cleanup: %s", e
        )
        return {
            "success": False,
            "claw": claw_name,
            "host": hostname,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": f"Remote removal succeeded but local config update failed: {e}. Run 'clm host ps {hostname}' to verify or manually edit hosts.json.",
        }

    emit("remove", f"Removed {claw_name} successfully")

    return {
        "success": True,
        "claw": claw_name,
        "host": hostname,
        "operation": "remove",
        "pid": None,
        "started_at": None,
        "error": None,
    }

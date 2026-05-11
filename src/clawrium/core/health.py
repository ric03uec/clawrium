"""Live health checking for claw instances.

This module provides functions to check if claw processes are running
on remote hosts via SSH. Per D-13, this performs live checks, not cached data.
"""

import logging
import os
import re
import tempfile
from enum import Enum
from typing import TypedDict

import ansible_runner

from clawrium.core.keys import get_host_private_key
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
    InvalidInstanceKeyComponentError,
    SecretsFileCorruptedError,
)
from clawrium.core.registry import get_required_secrets

logger = logging.getLogger(__name__)

# Valid Linux username pattern: starts with lowercase letter, followed by
# lowercase letters, digits, underscores, or hyphens. Max 32 chars total.
VALID_USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _collect_system_info(
    inventory: dict,
    hostname: str,
    tmpdir: str,
) -> tuple[int | None, int | None]:
    """Collect CPU count and total memory from remote host.

    Runs nproc and reads /proc/meminfo to get system specifications.

    Args:
        inventory: Ansible inventory dict
        hostname: Target host
        tmpdir: Temporary directory for ansible_runner

    Returns:
        Tuple of (cpu_count, memory_total_mb), both may be None on failure.
    """
    # Run nproc and grep MemTotal in a single shell command
    cmd = "nproc && grep MemTotal /proc/meminfo | awk '{print $2}'"

    result = ansible_runner.run(
        private_data_dir=tmpdir,
        inventory=inventory,
        host_pattern=hostname,
        module="shell",
        module_args=cmd,
        quiet=True,
        timeout=10,
    )

    cpu_count = None
    memory_total_mb = None

    for event in result.events:
        if event.get("event") == "runner_on_ok":
            stdout = event.get("event_data", {}).get("res", {}).get("stdout", "")
            lines = stdout.strip().split("\n")
            if len(lines) >= 2:
                try:
                    cpu_count = int(lines[0])
                    mem_kb = int(lines[1])
                    memory_total_mb = mem_kb // 1024
                except (ValueError, IndexError):
                    pass
            break

    return cpu_count, memory_total_mb

# Onboarding state to step mapping for display
ONBOARDING_STEP_MAP: dict[str, str] = {
    "providers": "1/4",
    "identity": "2/4",
    "channels": "3/4",
    "validate": "4/4",
}


class ClawStatus(str, Enum):
    """Status of a claw instance."""

    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"
    NOT_INSTALLED = "not_installed"
    DEGRADED = "degraded"  # Running but missing required secrets
    PENDING_ONBOARD = "pending_onboard"  # Installed but onboarding not started
    ONBOARDING = "onboarding"  # Onboarding in progress
    READY = "ready"  # Onboarding complete, can be started


class HealthResult(TypedDict):
    """Result of health check for an agent on a host."""

    agent: str
    host: str
    status: ClawStatus
    user: str | None
    error: str | None
    missing_secrets: list[str] | None
    onboarding_step: str | None
    process_running: bool | None
    onboarding_stages: dict[str, dict[str, str | None]] | None
    cpu_count: int | None
    memory_total_mb: int | None


def get_onboarding_status(claw_record: dict) -> tuple[ClawStatus, str | None]:
    """Determine claw status based on onboarding state.

    Args:
        claw_record: Claw installation record from host

    Returns:
        Tuple of (ClawStatus, onboarding_step or None)

    Note:
        Missing onboarding record returns PENDING_ONBOARD for backward compatibility.
        This conflates "never initialized" with "not yet started" - a deliberate
        tradeoff to avoid breaking existing installations during migration.
    """
    onboarding = claw_record.get("onboarding")
    if onboarding is None:
        # No onboarding record - treat as pending onboard for backward compatibility
        return ClawStatus.PENDING_ONBOARD, None

    # B3 fix: Type guard for corrupted records (non-dict values)
    if not isinstance(onboarding, dict):
        logger.warning("Invalid onboarding record type: %s", type(onboarding).__name__)
        return ClawStatus.PENDING_ONBOARD, None

    # B4 fix: Handle explicit null state - use `or` to treat None as "pending"
    state = onboarding.get("state") or "pending"

    if state == "pending":
        return ClawStatus.PENDING_ONBOARD, None
    elif state == "ready":
        return ClawStatus.READY, None
    else:
        # In progress - map state to step
        step = ONBOARDING_STEP_MAP.get(state)
        if step is None:
            # W1 fix: Log unknown states
            logger.warning("Unknown onboarding state: %s", state)
        return ClawStatus.ONBOARDING, step


def count_completed_stages(claw_record: dict) -> tuple[int, int]:
    """Count completed onboarding stages.

    Args:
        claw_record: Claw installation record from host

    Returns:
        Tuple of (completed_count, total_stages)
    """
    onboarding = claw_record.get("onboarding")
    if not onboarding or not isinstance(onboarding, dict):
        return 0, 4

    stages = onboarding.get("stages", {})
    # Ensure stages is a dict (handle corrupted data gracefully)
    if not stages or not isinstance(stages, dict):
        return 0, 4

    completed = sum(
        1
        for s in stages.values()
        if isinstance(s, dict) and s.get("status") in ("complete", "skipped")
    )
    return completed, len(stages)


def get_missing_secrets(claw_type: str, host: dict, claw_record: dict) -> list[str]:
    """Check which required secrets are missing for a claw instance.

    Args:
        claw_type: Type of claw (e.g., "openclaw")
        host: Host record dict
        claw_record: Claw installation record from host

    Returns:
        List of missing required secret keys
    """
    # Cannot check secrets without a valid claw type
    if not claw_type:
        return []

    # Use canonical instance name.
    # For current installs this is stored in `user`; `name` is supported as fallback.
    claw_name = claw_record.get("agent_name") or claw_record.get("name", "")

    if not claw_name:
        # Cannot determine claw name - return empty (no secrets can be checked)
        return []

    try:
        instance_key = get_instance_key(host["hostname"], claw_type, claw_name)
    except InvalidInstanceKeyComponentError:
        logger.warning(
            "Invalid instance key component for %s/%s/%s - skipping secret check",
            host.get("hostname"),
            claw_type,
            claw_name,
        )
        return []

    # Let SecretsFileCorruptedError propagate to caller for proper error handling
    instance_secrets = get_instance_secrets(instance_key)

    required = get_required_secrets(claw_type)
    missing = [s["key"] for s in required if s["key"] not in instance_secrets]

    return missing


def check_claw_health(
    claw_name: str,
    host: dict,
) -> HealthResult:
    """Check if a claw process is running on a host.

    Performs live SSH check per D-13. Does not use cached data.

    Args:
        claw_name: Name of claw to check (e.g., "openclaw")
        host: Host record dict with hostname, port, user, key_id, claws

    Returns:
        HealthResult with status and any error message
    """
    # Validate required host fields
    hostname = host.get("hostname")
    if not hostname:
        return {
            "agent": claw_name,
            "host": "unknown",
            "status": ClawStatus.UNKNOWN,
            "agent_name": None,
            "error": "Host record missing required 'hostname' field",
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
            "cpu_count": None,
            "memory_total_mb": None,
        }

    port = host.get("port", 22)
    user = host.get("user", "xclm")

    # Get claw record from host
    agents = host.get("agents", {})
    claw_record = agents.get(claw_name)

    if not claw_record:
        return {
            "agent": claw_name,
            "host": hostname,
            "status": ClawStatus.NOT_INSTALLED,
            "agent_name": None,
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
            "cpu_count": None,
            "memory_total_mb": None,
        }

    claw_user = claw_record.get("agent_name") or claw_record.get("name")
    if not claw_user:
        return {
            "agent": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "agent_name": None,
            "error": "No claw user recorded",
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
            "cpu_count": None,
            "memory_total_mb": None,
        }

    if not VALID_USERNAME_PATTERN.match(claw_user):
        return {
            "agent": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "agent_name": claw_user,
            "error": f"Invalid claw user format: {claw_user}",
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
            "cpu_count": None,
            "memory_total_mb": None,
        }

    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return {
            "agent": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "agent_name": claw_user,
            "error": "SSH key not found",
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
            "cpu_count": None,
            "memory_total_mb": None,
        }

    # Build inventory
    inventory = {
        "all": {
            "hosts": {
                hostname: {
                    "ansible_user": user,
                    "ansible_port": port,
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            }
        }
    }

    # Build the pgrep command per agent type.
    # openclaw sets process title to "openclaw"; hermes runs as python3 invoking
    # `hermes gateway run`, so match the full command line via -f.
    agent_type = claw_record.get("type", "")
    if agent_type == "openclaw":
        check_cmd = f"pgrep -u {claw_user} openclaw"
    elif agent_type == "hermes":
        # Quote the -f pattern so ansible's command module shlex-splits it into a
        # single argument; otherwise pgrep would treat 'gateway run' as extra args.
        check_cmd = f'pgrep -u {claw_user} -f "hermes gateway run"'
    else:
        check_cmd = f"pgrep -u {claw_user} node"

    with tempfile.TemporaryDirectory() as tmpdir:
        os.chmod(tmpdir, 0o700)

        result = ansible_runner.run(
            private_data_dir=tmpdir,
            inventory=inventory,
            host_pattern=hostname,
            module="command",
            module_args=check_cmd,
            quiet=True,
            timeout=15,
        )

        if result.status == "timeout":
            return {
                "agent": claw_name,
                "host": hostname,
                "status": ClawStatus.UNKNOWN,
                "agent_name": claw_user,
                "error": "Health check timed out",
                "missing_secrets": None,
                "onboarding_step": None,
                "process_running": None,
                "onboarding_stages": None,
                "cpu_count": None,
                "memory_total_mb": None,
            }

        # Parse events to determine process state.
        # runner_on_ok  → pgrep found the process (rc=0) → RUNNING
        # runner_on_failed rc=1 → pgrep found nothing → STOPPED
        # runner_on_failed rc!=1 → unexpected pgrep error → UNKNOWN
        # runner_on_unreachable → SSH unreachable → UNKNOWN
        # no relevant event → SSH-level failure → UNKNOWN
        process_running: bool | None = None
        error_msg: str | None = None

        for event in result.events:
            event_type = event.get("event")
            if event_type == "runner_on_unreachable":
                return {
                    "agent": claw_name,
                    "host": hostname,
                    "status": ClawStatus.UNKNOWN,
                    "agent_name": claw_user,
                    "error": "Host unreachable",
                    "missing_secrets": None,
                    "onboarding_step": None,
                    "process_running": None,
                    "onboarding_stages": None,
                    "cpu_count": None,
                    "memory_total_mb": None,
                }
            if event_type == "runner_on_ok":
                process_running = True
                break
            if event_type == "runner_on_failed":
                rc = event.get("event_data", {}).get("res", {}).get("rc", -1)
                if rc == 1:
                    process_running = False
                else:
                    error_msg = f"Unexpected exit code: {rc}"
                break

        # Collect system info (CPU count, total memory) if we successfully
        # connected to the host (process_running is not None)
        cpu_count = None
        memory_total_mb = None
        if process_running is not None:
            cpu_count, memory_total_mb = _collect_system_info(
                inventory, hostname, tmpdir
            )

        if process_running is None:
            return {
                "agent": claw_name,
                "host": hostname,
                "status": ClawStatus.UNKNOWN,
                "agent_name": claw_user,
                "error": error_msg or f"SSH failed: {result.status}",
                "missing_secrets": None,
                "onboarding_step": None,
                "process_running": None,
                "onboarding_stages": None,
                "cpu_count": None,
                "memory_total_mb": None,
            }

        if process_running:
            try:
                claw_type = claw_record.get("type", "")
                missing = get_missing_secrets(claw_type, host, claw_record)
            except SecretsFileCorruptedError as e:
                return {
                    "agent": claw_name,
                    "host": hostname,
                    "status": ClawStatus.DEGRADED,
                    "agent_name": claw_user,
                    "error": f"Secrets file corrupted: {str(e)}",
                    "missing_secrets": None,
                    "onboarding_step": None,
                    "process_running": True,
                    "onboarding_stages": None,
                    "cpu_count": cpu_count,
                    "memory_total_mb": memory_total_mb,
                }

            if missing:
                return {
                    "agent": claw_name,
                    "host": hostname,
                    "status": ClawStatus.DEGRADED,
                    "agent_name": claw_user,
                    "error": None,
                    "missing_secrets": missing,
                    "onboarding_step": None,
                    "process_running": True,
                    "onboarding_stages": None,
                    "cpu_count": cpu_count,
                    "memory_total_mb": memory_total_mb,
                }
            else:
                return {
                    "agent": claw_name,
                    "host": hostname,
                    "status": ClawStatus.RUNNING,
                    "agent_name": claw_user,
                    "error": None,
                    "missing_secrets": None,
                    "onboarding_step": None,
                    "process_running": True,
                    "onboarding_stages": None,
                    "cpu_count": cpu_count,
                    "memory_total_mb": memory_total_mb,
                }
        else:
            status, step = get_onboarding_status(claw_record)
            onboarding_stages = None
            if status in (
                ClawStatus.ONBOARDING,
                ClawStatus.READY,
            ):
                onboarding = claw_record.get("onboarding")
                if onboarding and isinstance(onboarding, dict):
                    onboarding_stages = onboarding.get("stages")
            return {
                "agent": claw_name,
                "host": hostname,
                "status": status,
                "agent_name": claw_user,
                "error": None,
                "missing_secrets": None,
                "onboarding_step": step,
                "process_running": False,
                "onboarding_stages": onboarding_stages,
                "cpu_count": cpu_count,
                "memory_total_mb": memory_total_mb,
            }


def check_all_claws_on_host(host: dict) -> list[HealthResult]:
    """Check health of all installed claws on a host.

    Args:
        host: Host record dict

    Returns:
        List of HealthResult for each installed claw
    """
    results = []
    agents = host.get("agents", {})

    for claw_name in agents:
        result = check_claw_health(claw_name, host)
        results.append(result)

    return results

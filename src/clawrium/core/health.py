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
)
from clawrium.core.registry import get_required_secrets

logger = logging.getLogger(__name__)

# Valid Linux username pattern: starts with lowercase letter, followed by
# lowercase letters, digits, underscores, or hyphens. Max 32 chars total.
VALID_USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

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
    """Result of health check for a claw on a host."""

    claw: str
    host: str
    status: ClawStatus
    user: str | None
    error: str | None
    missing_secrets: list[str] | None
    onboarding_step: str | None
    process_running: bool | None
    onboarding_stages: dict[str, dict[str, str | None]] | None


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
    if not stages:
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
    # Use claw name directly from record (set during installation)
    # Falls back to deriving from user field for backward compatibility
    claw_name = claw_record.get("name")
    if not claw_name:
        # Backward compatibility: extract from user field (e.g., "opc-work" -> "work")
        claw_user = claw_record.get("user", "")
        claw_name = claw_user.split("-", 1)[1] if "-" in claw_user else claw_user

    if not claw_name:
        # Cannot determine claw name - return empty (no secrets can be checked)
        return []

    try:
        instance_key = get_instance_key(host["hostname"], claw_type, claw_name)
    except InvalidInstanceKeyComponentError:
        logger.warning(
            "Invalid instance key component for %s/%s/%s — skipping secret check",
            host.get("hostname"),
            claw_type,
            claw_name,
        )
        return []

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
    hostname = host["hostname"]
    port = host.get("port", 22)
    user = host.get("user", "xclm")

    # Get claw record from host
    claws = host.get("claws", {})
    claw_record = claws.get(claw_name)

    if not claw_record:
        return {
            "claw": claw_name,
            "host": hostname,
            "status": ClawStatus.NOT_INSTALLED,
            "user": None,
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
        }

    claw_user = claw_record.get("user")
    if not claw_user:
        return {
            "claw": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "user": None,
            "error": "No claw user recorded",
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
        }

    if not VALID_USERNAME_PATTERN.match(claw_user):
        return {
            "claw": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "user": claw_user,
            "error": f"Invalid claw user format: {claw_user}",
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
        }

    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return {
            "claw": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "user": claw_user,
            "error": "SSH key not found",
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
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

    # Check for node process owned by claw user using pgrep.
    # claw_user is already validated by VALID_USERNAME_PATTERN (alphanumeric/hyphen/underscore).
    # Using module='command' avoids shell interpretation entirely.
    # pgrep exits 0 (process found) → runner_on_ok; exits 1 (not found) → runner_on_failed rc=1.
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
                "claw": claw_name,
                "host": hostname,
                "status": ClawStatus.UNKNOWN,
                "user": claw_user,
                "error": "Health check timed out",
                "missing_secrets": None,
                "onboarding_step": None,
                "process_running": None,
                "onboarding_stages": None,
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
                    "claw": claw_name,
                    "host": hostname,
                    "status": ClawStatus.UNKNOWN,
                    "user": claw_user,
                    "error": "Host unreachable",
                    "missing_secrets": None,
                    "onboarding_step": None,
                    "process_running": None,
                    "onboarding_stages": None,
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

        if process_running is None:
            return {
                "claw": claw_name,
                "host": hostname,
                "status": ClawStatus.UNKNOWN,
                "user": claw_user,
                "error": error_msg or f"SSH failed: {result.status}",
                "missing_secrets": None,
                "onboarding_step": None,
                "process_running": None,
                "onboarding_stages": None,
            }

        if process_running:
            missing = get_missing_secrets(claw_name, host, claw_record)
            if missing:
                return {
                    "claw": claw_name,
                    "host": hostname,
                    "status": ClawStatus.DEGRADED,
                    "user": claw_user,
                    "error": None,
                    "missing_secrets": missing,
                    "onboarding_step": None,
                    "process_running": True,
                    "onboarding_stages": None,
                }
            else:
                return {
                    "claw": claw_name,
                    "host": hostname,
                    "status": ClawStatus.RUNNING,
                    "user": claw_user,
                    "error": None,
                    "missing_secrets": None,
                    "onboarding_step": None,
                    "process_running": True,
                    "onboarding_stages": None,
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
                "claw": claw_name,
                "host": hostname,
                "status": status,
                "user": claw_user,
                "error": None,
                "missing_secrets": None,
                "onboarding_step": step,
                "process_running": False,
                "onboarding_stages": onboarding_stages,
            }


def check_all_claws_on_host(host: dict) -> list[HealthResult]:
    """Check health of all installed claws on a host.

    Args:
        host: Host record dict

    Returns:
        List of HealthResult for each installed claw
    """
    results = []
    claws = host.get("claws", {})

    for claw_name in claws:
        result = check_claw_health(claw_name, host)
        results.append(result)

    return results

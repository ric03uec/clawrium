"""Live health checking for claw instances.

This module provides functions to check if claw processes are running
on remote hosts via SSH. Per D-13, this performs live checks, not cached data.
"""

import logging
import os
import re
import shlex
import tempfile
from enum import Enum
from typing import TypedDict

import ansible_runner

from clawrium.core.keys import get_host_private_key
from clawrium.core.secrets import get_instance_key, get_instance_secrets
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
    missing_secrets: list[str] | None  # List of missing required secret keys
    onboarding_step: str | None  # Current onboarding step (e.g., "1/4", "2/4")


def get_onboarding_status(claw_record: dict) -> tuple[ClawStatus, str | None]:
    """Determine claw status based on onboarding state.

    Args:
        claw_record: Claw installation record from host

    Returns:
        Tuple of (ClawStatus, onboarding_step or None)
    """
    onboarding = claw_record.get("onboarding")
    if onboarding is None:
        # No onboarding record - treat as pending onboard for backward compatibility
        return ClawStatus.PENDING_ONBOARD, None

    state = onboarding.get("state", "pending")

    if state == "pending":
        return ClawStatus.PENDING_ONBOARD, None
    elif state == "ready":
        return ClawStatus.READY, None
    else:
        # In progress - map state to step
        step = ONBOARDING_STEP_MAP.get(state)
        return ClawStatus.ONBOARDING, step


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

    instance_key = get_instance_key(host["hostname"], claw_type, claw_name)
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
        }

    claw_user = claw_record.get("user")
    if not claw_user:
        # No user set - can't check
        return {
            "claw": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "user": None,
            "error": "No claw user recorded",
            "missing_secrets": None,
            "onboarding_step": None,
        }

    # Validate username to prevent command injection
    if not VALID_USERNAME_PATTERN.match(claw_user):
        return {
            "claw": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "user": claw_user,
            "error": f"Invalid claw user format: {claw_user}",
            "missing_secrets": None,
            "onboarding_step": None,
        }

    # Get SSH key
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

    # Check for node process owned by claw user
    # OpenClaw runs as a Node.js process
    # Use shlex.quote for defense-in-depth (user already validated by regex)
    check_cmd = f"pgrep -u {shlex.quote(claw_user)} node >/dev/null 2>&1 && echo RUNNING || echo STOPPED"

    with tempfile.TemporaryDirectory() as tmpdir:
        os.chmod(tmpdir, 0o700)

        result = ansible_runner.run(
            private_data_dir=tmpdir,
            inventory=inventory,
            host_pattern=hostname,
            module="shell",
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
            }

        if result.status != "successful":
            return {
                "claw": claw_name,
                "host": hostname,
                "status": ClawStatus.UNKNOWN,
                "user": claw_user,
                "error": f"SSH failed: {result.status}",
                "missing_secrets": None,
                "onboarding_step": None,
            }

        # Parse output from events
        output = ""
        for event in result.events:
            event_type = event.get("event")
            if event_type == "runner_on_unreachable":
                # Host unreachable - network issue, not process status
                return {
                    "claw": claw_name,
                    "host": hostname,
                    "status": ClawStatus.UNKNOWN,
                    "user": claw_user,
                    "error": "Host unreachable",
                    "missing_secrets": None,
                    "onboarding_step": None,
                }
            if event_type == "runner_on_ok":
                output = event.get("event_data", {}).get("res", {}).get("stdout", "")
                break

        if "RUNNING" in output:
            # Check for missing required secrets
            missing = get_missing_secrets(claw_name, host, claw_record)
            if missing:
                # Claw is running but missing required secrets - degraded state
                return {
                    "claw": claw_name,
                    "host": hostname,
                    "status": ClawStatus.DEGRADED,
                    "user": claw_user,
                    "error": None,
                    "missing_secrets": missing,
                    "onboarding_step": None,
                }
            else:
                # Claw is running with all required secrets
                return {
                    "claw": claw_name,
                    "host": hostname,
                    "status": ClawStatus.RUNNING,
                    "user": claw_user,
                    "error": None,
                    "missing_secrets": None,
                    "onboarding_step": None,
                }
        elif "STOPPED" in output:
            # Process not running - check onboarding state
            status, step = get_onboarding_status(claw_record)
            return {
                "claw": claw_name,
                "host": hostname,
                "status": status,
                "user": claw_user,
                "error": None,
                "missing_secrets": None,
                "onboarding_step": step,
            }
        else:
            # Unexpected output - treat as unknown
            return {
                "claw": claw_name,
                "host": hostname,
                "status": ClawStatus.UNKNOWN,
                "user": claw_user,
                "error": f"Unexpected output: {output[:50]}" if output else "No output",
                "missing_secrets": None,
                "onboarding_step": None,
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

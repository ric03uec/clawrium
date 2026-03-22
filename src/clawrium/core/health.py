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

logger = logging.getLogger(__name__)

# Valid Linux username pattern: starts with lowercase letter, followed by
# lowercase letters, digits, underscores, or hyphens. Max 32 chars total.
VALID_USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class ClawStatus(str, Enum):
    """Status of a claw instance."""
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"
    NOT_INSTALLED = "not_installed"


class HealthResult(TypedDict):
    """Result of health check for a claw on a host."""
    claw: str
    host: str
    status: ClawStatus
    user: str | None
    error: str | None


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
        }

    # Validate username to prevent command injection
    if not VALID_USERNAME_PATTERN.match(claw_user):
        return {
            "claw": claw_name,
            "host": hostname,
            "status": ClawStatus.UNKNOWN,
            "user": claw_user,
            "error": f"Invalid claw user format: {claw_user}",
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
    check_cmd = f"pgrep -u {claw_user} node >/dev/null 2>&1 && echo RUNNING || echo STOPPED"

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
            }

        if result.status != "successful":
            return {
                "claw": claw_name,
                "host": hostname,
                "status": ClawStatus.UNKNOWN,
                "user": claw_user,
                "error": f"SSH failed: {result.status}",
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
                }
            if event_type == "runner_on_ok":
                output = event.get("event_data", {}).get("res", {}).get("stdout", "")
                break

        if "RUNNING" in output:
            return {
                "claw": claw_name,
                "host": hostname,
                "status": ClawStatus.RUNNING,
                "user": claw_user,
                "error": None,
            }
        elif "STOPPED" in output:
            return {
                "claw": claw_name,
                "host": hostname,
                "status": ClawStatus.STOPPED,
                "user": claw_user,
                "error": None,
            }
        else:
            # Unexpected output - treat as unknown
            return {
                "claw": claw_name,
                "host": hostname,
                "status": ClawStatus.UNKNOWN,
                "user": claw_user,
                "error": f"Unexpected output: {output[:50]}" if output else "No output",
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

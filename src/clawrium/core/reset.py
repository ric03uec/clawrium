"""Host reset operations.

This module handles removing all users, claw services, and configuration
from a managed host, leaving only the xclm management user intact.

Flow:
1. enumerate_targets() - Discovers what exists on host
2. execute_reset() - Runs ansible playbook to remove targets
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import ansible_runner

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host
from clawrium.core.keys import get_host_private_key

logger = logging.getLogger(__name__)

__all__ = [
    "ResetTargets",
    "ResetResult",
    "enumerate_targets",
    "execute_reset",
]

# Static paths to clean on reset
CLAWRIUM_PATHS = ["/etc/clawrium/", "/var/log/clawrium/"]


@dataclass
class ResetTargets:
    """Targets to remove during host reset.

    Attributes:
        users: List of usernames to remove (uid >= 1000, excluding xclm)
        services: List of systemd service names (*claw*.service pattern)
        paths: List of directory paths to clean
    """

    users: list[str]
    services: list[str]
    paths: list[str]


@dataclass
class ResetResult:
    """Result of host reset operation.

    Attributes:
        success: Whether reset completed without critical errors
        removed: Count of items removed by category {"users": N, "services": N, "paths": N}
        errors: List of error messages encountered during reset
    """

    success: bool
    removed: dict[str, int]
    errors: list[str]


def enumerate_targets(hostname: str) -> ResetTargets:
    """Find all users, services, and paths to remove on host.

    Connects to host via SSH/ansible and discovers:
    - Users with uid >= 1000 (excluding xclm)
    - Services matching *claw*.service pattern
    - Clawrium config paths

    Args:
        hostname: The hostname or alias of the target host

    Returns:
        ResetTargets with discovered items

    Raises:
        ValueError: If host not found in registry
        RuntimeError: If ansible commands fail
    """
    # Get host record
    host = get_host(hostname)
    if not host:
        raise ValueError(f"Host {hostname} not found in registry")

    # Get SSH key path
    key_id = host.get("key_id", host.get("hostname"))
    ssh_key = get_host_private_key(key_id)
    if ssh_key is None:
        raise ValueError(f"No SSH key found for host {hostname} (key_id: {key_id})")

    with tempfile.TemporaryDirectory() as tmpdir:
        os.chmod(tmpdir, 0o700)

        # Build inventory
        inventory = {
            "all": {
                "hosts": {
                    host["hostname"]: {
                        "ansible_user": host.get("user", "xclm"),
                        "ansible_port": host.get("port", 22),
                        "ansible_ssh_private_key_file": ssh_key,
                    }
                }
            }
        }

        # Get users with uid >= 1000
        users_result = ansible_runner.run(
            private_data_dir=tmpdir,
            inventory=inventory,
            host_pattern=host["hostname"],
            module="shell",
            module_args="getent passwd | awk -F: '$3 >= 1000 {print $1}'",
            quiet=True,
            timeout=30,
        )

        users = []
        if users_result.status == "successful":
            for event in users_result.events:
                if event.get("event") == "runner_on_ok":
                    stdout = (
                        event.get("event_data", {}).get("res", {}).get("stdout", "")
                    )
                    for user in stdout.strip().split("\n"):
                        user = user.strip()
                        if user and user != "xclm":
                            users.append(user)

        # Get claw services
        services_result = ansible_runner.run(
            private_data_dir=tmpdir,
            inventory=inventory,
            host_pattern=host["hostname"],
            module="shell",
            module_args="systemctl list-unit-files '*claw*.service' --no-legend 2>/dev/null | awk '{print $1}' || true",
            quiet=True,
            timeout=30,
        )

        services = []
        if services_result.status == "successful":
            for event in services_result.events:
                if event.get("event") == "runner_on_ok":
                    stdout = (
                        event.get("event_data", {}).get("res", {}).get("stdout", "")
                    )
                    for service in stdout.strip().split("\n"):
                        service = service.strip()
                        if service and "claw" in service:
                            services.append(service)

        return ResetTargets(
            users=users,
            services=services,
            paths=CLAWRIUM_PATHS.copy(),
        )


def _get_reset_playbook_path() -> Path:
    """Get path to reset playbook."""
    return Path(__file__).parent.parent / "platform" / "playbooks" / "reset.yaml"


def _get_logs_dir() -> Path:
    """Get logs directory, creating if needed."""
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def execute_reset(hostname: str, targets: ResetTargets) -> ResetResult:
    """Execute host reset by running ansible playbook.

    Removes all targets discovered by enumerate_targets:
    - Stops and removes claw services
    - Removes users and their home directories
    - Cleans configuration paths

    Args:
        hostname: The hostname or alias of the target host
        targets: ResetTargets from enumerate_targets()

    Returns:
        ResetResult with success status and counts
    """
    # Get host record
    host = get_host(hostname)
    if not host:
        return ResetResult(
            success=False,
            removed={"users": 0, "services": 0, "paths": 0},
            errors=[f"Host {hostname} not found in registry"],
        )

    # Get SSH key path
    key_id = host.get("key_id", host.get("hostname"))
    ssh_key = get_host_private_key(key_id)
    if ssh_key is None:
        return ResetResult(
            success=False,
            removed={"users": 0, "services": 0, "paths": 0},
            errors=[f"No SSH key found for host {hostname} (key_id: {key_id})"],
        )

    # Get playbook path
    playbook = _get_reset_playbook_path()
    if not playbook.exists():
        return ResetResult(
            success=False,
            removed={"users": 0, "services": 0, "paths": 0},
            errors=[f"Reset playbook not found: {playbook}"],
        )

    # Create timestamped log directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_dir = _get_logs_dir() / f"reset-{hostname}-{timestamp}"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Build inventory
    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": ssh_key,
                }
            },
            "vars": {
                "services_to_remove": targets.services,
                "users_to_remove": targets.users,
                "paths_to_clean": targets.paths,
            },
        }
    }

    logger.info(f"Executing reset on {hostname}, logs at {log_dir}")

    # Run reset playbook
    result = ansible_runner.run(
        private_data_dir=str(log_dir),
        inventory=inventory,
        playbook=str(playbook),
        quiet=True,
        timeout=300,  # 5 min timeout
    )

    errors = []
    if result.status == "timeout":
        errors.append("Reset playbook timed out after 300 seconds")
    elif result.status != "successful":
        errors.append(f"Reset playbook failed: {result.status}")

    # Count removed items (assume all targets were removed if successful)
    removed = {
        "users": len(targets.users) if result.status == "successful" else 0,
        "services": len(targets.services) if result.status == "successful" else 0,
        "paths": len(targets.paths) if result.status == "successful" else 0,
    }

    return ResetResult(
        success=result.status == "successful",
        removed=removed,
        errors=errors,
    )

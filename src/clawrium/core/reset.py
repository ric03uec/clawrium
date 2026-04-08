"""Host reset operations.

This module handles removing all users, claw services, and configuration
from a managed host, leaving only the xclm management user intact.

Flow:
1. enumerate_targets() - Discovers what exists on host
2. execute_reset() - Runs ansible playbook to remove targets
"""

import logging
import os
import re
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

# Validation patterns to prevent injection attacks (B1)
# Username: standard Linux username format
USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
# Service name: systemd unit name format
SERVICE_PATTERN = re.compile(r"^[a-zA-Z0-9@._-]+\.service$")
# Max items to prevent DoS
MAX_USERS = 50
MAX_SERVICES = 50


def _validate_username(username: str) -> bool:
    """Validate username matches safe pattern."""
    return bool(USERNAME_PATTERN.match(username))


def _validate_service_name(service: str) -> bool:
    """Validate service name matches safe pattern."""
    return bool(SERVICE_PATTERN.match(service))


def _sanitize_for_path(name: str) -> str:
    """Sanitize a string for use in filesystem paths (B2)."""
    # Only allow alphanumeric, dots, dashes, underscores
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


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
                            # B1: Validate username to prevent injection
                            if _validate_username(user):
                                users.append(user)
                            else:
                                logger.warning(f"Skipping invalid username: {user!r}")
            # B1: Cap number of users to prevent DoS
            if len(users) > MAX_USERS:
                logger.warning(
                    f"Truncating users list from {len(users)} to {MAX_USERS}"
                )
                users = users[:MAX_USERS]

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
                            # B1: Validate service name to prevent injection
                            if _validate_service_name(service):
                                services.append(service)
                            else:
                                logger.warning(f"Skipping invalid service: {service!r}")
            # B1: Cap number of services to prevent DoS
            if len(services) > MAX_SERVICES:
                logger.warning(
                    f"Truncating services list from {len(services)} to {MAX_SERVICES}"
                )
                services = services[:MAX_SERVICES]

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
    # B2: Sanitize hostname to prevent path traversal attacks
    safe_hostname = _sanitize_for_path(hostname)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    logs_base = _get_logs_dir()
    log_dir = logs_base / f"reset-{safe_hostname}-{timestamp}"

    # B2: Verify log_dir is inside logs_base (defense in depth)
    if not log_dir.resolve().is_relative_to(logs_base.resolve()):
        return ResetResult(
            success=False,
            removed={"users": 0, "services": 0, "paths": 0},
            errors=[f"Invalid log directory path for hostname: {hostname}"],
        )

    # W2: Create with restrictive permissions (contains inventory with key paths)
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_dir.chmod(0o700)  # Ensure permissions even if dir existed

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

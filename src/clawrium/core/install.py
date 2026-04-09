"""Installation orchestration for agent deployment.

This module handles the end-to-end installation flow:
1. Validate agent exists in registry
2. Check host compatibility
3. Run base playbook (system dependencies)
4. Run agent-specific playbook

Host record schema (extended):
{
    "hostname": str,
    "claws": {
        "openclaw": {
            "version": "0.1.0",
            "status": "installed" | "failed" | "installing",
            "installed_at": "ISO timestamp",
            "error": str | None,
            "user": "clever-einstein"  # friendly name, no prefix
        }
    },
    ...existing fields...
}
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

import ansible_runner

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host, update_host
from clawrium.core.keys import get_host_private_key
from clawrium.core.names import (
    generate_random_name,
    is_name_available_on_host,
    validate_claw_name,
)
from clawrium.core.registry import (
    check_compatibility,
    load_manifest,
    ManifestNotFoundError,
)
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
)
from clawrium.core.onboarding import initialize_onboarding

logger = logging.getLogger(__name__)


class InstallationError(Exception):
    """Raised when installation fails."""

    pass


class InstallResult(TypedDict):
    """Result of installation operation."""

    success: bool
    agent: str
    version: str
    host: str
    playbooks_run: list[str]
    error: str | None


def _get_base_playbook_path() -> Path:
    """Get path to base system playbook."""
    # Base playbook is at src/clawrium/platform/playbooks/base.yaml
    # From src/clawrium/core/install.py: parent.parent gets to src/clawrium
    return Path(__file__).parent.parent / "platform" / "playbooks" / "base.yaml"


def _get_claw_playbook_path(claw_name: str) -> Path:
    """Get path to agent-specific install playbook."""
    return (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / claw_name
        / "playbooks"
        / "install.yaml"
    )


def _get_logs_dir() -> Path:
    """Get logs directory, creating if needed."""
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def run_installation(
    claw_name: str,
    hostname: str,
    name: str | None = None,
    on_event: Callable[[str, str], None] | None = None,
) -> InstallResult:
    """Run full installation of an agent on a host.

    Args:
        claw_name: Name of agent to install (e.g., "openclaw")
        hostname: Hostname or alias of target host
        name: Optional friendly name for the agent instance. If not provided,
              a random Docker-style name will be generated (e.g., "clever-einstein")
        on_event: Optional callback for progress events (stage, message)

    Returns:
        InstallResult with success status and details

    Raises:
        InstallationError: If validation fails or playbook execution fails
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    # Step 1: Validate agent exists
    emit("validate", f"Checking {claw_name} manifest...")
    try:
        load_manifest(claw_name)  # Validates agent exists
    except ManifestNotFoundError as e:
        raise InstallationError(f"Agent '{claw_name}' not found in registry") from e

    # Step 2: Get host record
    emit("validate", f"Loading host {hostname}...")
    host = get_host(hostname)
    if not host:
        raise InstallationError(
            f"Host '{hostname}' not found. Run 'clm host add' first."
        )

    # Step 3: Check compatibility
    emit("validate", "Checking compatibility...")
    hardware = host.get("hardware", {})
    compat = check_compatibility(claw_name, hardware)

    if not compat["compatible"]:
        reasons = ", ".join(compat["reasons"])
        raise InstallationError(f"Host is incompatible: {reasons}")

    matched_version = compat["matched_entry"]["version"]
    emit("validate", f"Compatible with {claw_name} v{matched_version}")

    # Step 4: Validate custom name if provided (format only, uniqueness checked in updater)
    if name is not None:
        valid, error_msg = validate_claw_name(name)
        if not valid:
            raise InstallationError(f"Invalid name: {error_msg}")
        emit("validate", f"Validated custom name: {name}")

    # Step 5: Set installing state with uniqueness check under lock
    # Use a list to capture the chosen name from inside the updater
    chosen_name = [None]

    def set_installing(h: dict) -> dict:
        if name is None:
            # Auto-generate name with retry loop for uniqueness
            max_attempts = 10
            for attempt in range(max_attempts):
                candidate = generate_random_name()
                if is_name_available_on_host(candidate, h):
                    chosen_name[0] = candidate
                    break
            else:
                raise InstallationError(
                    f"Could not generate a unique name after {max_attempts} attempts. "
                    "Use --name to specify one."
                )
        else:
            # Use custom name, check uniqueness under lock
            if not is_name_available_on_host(name, h):
                raise InstallationError(
                    f"Name '{name}' already in use on this host. "
                    "Names must be unique across all agents on a host."
                )
            chosen_name[0] = name

        if "claws" not in h:
            h["claws"] = {}
        h["claws"][claw_name] = {
            "version": matched_version,
            "status": "installing",
            "installed_at": None,
            "error": None,
            "user": chosen_name[0],
        }
        return h

    update_host(host["hostname"], set_installing)

    # Extract the chosen name
    agent_name = chosen_name[0]

    # Emit message after lock is released and agent_name is set
    if name is None:
        emit("validate", f"Generated unique name: {agent_name}")
    else:
        emit("validate", f"Using provided name: {agent_name}")
    emit("validate", f"Installation state tracked (user: {agent_name})")

    # Step 5: Get SSH credentials
    key_id = host.get("key_id") or host["hostname"]
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        raise InstallationError(
            f"No SSH key found for host. Run 'clm host init {key_id}'."
        )

    # Step 6: Build inventory with extra vars for playbook
    matched_entry = compat["matched_entry"]
    claw_sha256 = matched_entry.get("sha256", "")

    # Load secrets for this agent instance
    instance_key = get_instance_key(host["hostname"], claw_name, agent_name)
    instance_secrets = get_instance_secrets(instance_key)

    # Map secret keys to ansible vars (uppercase SECRET_KEY -> lowercase secret_key)
    secret_vars = {}
    for key, entry in instance_secrets.items():
        ansible_var_name = key.lower()
        secret_vars[ansible_var_name] = entry.get("value", "")

    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": {
                "agent_name": agent_name,
                "agent_type": claw_name,
                "claw_version": f"v{matched_version}",
                "claw_sha256": claw_sha256,
                **secret_vars,  # Inject secrets as ansible vars
            },
        }
    }

    # Step 7: Setup persistent logs directory
    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = host.get("alias") or host.get("key_id") or host["hostname"]
    install_log_dir = logs_dir / f"install-{claw_name}-{host_display}-{timestamp}"
    install_log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(install_log_dir, 0o700)

    try:
        # Step 8: Run base playbook
        base_playbook = _get_base_playbook_path()
        if not base_playbook.exists():
            raise InstallationError(f"Base playbook not found: {base_playbook}")

        emit("base", "Installing system dependencies...")
        playbooks_run = []

        base_data_dir = install_log_dir / "base"
        base_data_dir.mkdir(exist_ok=True)

        result = ansible_runner.run(
            private_data_dir=str(base_data_dir),
            inventory=inventory,
            playbook=str(base_playbook),
            quiet=False,  # Show output
            timeout=300,  # 5 min timeout for base install
        )

        if result.status != "successful":
            raise InstallationError(
                f"Base playbook failed: {result.status}. "
                f"Check logs at {base_data_dir}/artifacts/"
            )
        playbooks_run.append(str(base_playbook))
        emit("base", "System dependencies installed")

        # Step 9: Run agent playbook
        claw_playbook = _get_claw_playbook_path(claw_name)
        if not claw_playbook.exists():
            raise InstallationError(f"Agent playbook not found: {claw_playbook}")

        emit("claw", f"Installing {claw_name}...")

        claw_data_dir = install_log_dir / "claw"
        claw_data_dir.mkdir(exist_ok=True)

        result = ansible_runner.run(
            private_data_dir=str(claw_data_dir),
            inventory=inventory,
            playbook=str(claw_playbook),
            quiet=False,  # Show output
            timeout=600,  # 10 min timeout for claw install
        )

        if result.status != "successful":
            raise InstallationError(
                f"Agent playbook failed: {result.status}. "
                f"Check logs at {claw_data_dir}/artifacts/"
            )
        playbooks_run.append(str(claw_playbook))
        emit("claw", f"{claw_name} installed successfully")

        # Step 10: Update host with success status
        def set_installed(h: dict) -> dict:
            if "claws" in h and claw_name in h["claws"]:
                h["claws"][claw_name]["status"] = "installed"
                h["claws"][claw_name]["installed_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
            return h

        update_host(host["hostname"], set_installed)

        # Step 11: Initialize onboarding record (non-fatal if it fails)
        try:
            if not initialize_onboarding(host["hostname"], claw_name):
                try:
                    emit(
                        "warn",
                        f"Onboarding setup incomplete — run `clm onboard init {host['hostname']} {claw_name}` to retry",
                    )
                except Exception:
                    logger.warning(
                        "Failed to emit onboarding warning event", exc_info=True
                    )
        except Exception as e:
            logger.warning("Onboarding init failed: %s", e, exc_info=True)
            try:
                emit(
                    "warn",
                    f"Onboarding setup failed — run `clm onboard init {host['hostname']} {claw_name}` to retry",
                )
            except Exception:
                logger.warning("Failed to emit onboarding warning event", exc_info=True)

        # Step 12: Emit completion event (non-fatal if callback fails)
        try:
            emit("complete", f"Installation complete. Logs at {install_log_dir}")
        except Exception:
            logger.warning("Failed to emit completion event", exc_info=True)

        return {
            "success": True,
            "agent": claw_name,
            "version": matched_version,
            "host": host["hostname"],
            "playbooks_run": playbooks_run,
            "error": None,
        }

    except Exception as e:
        # Step 13: Update host with failure status
        error_msg = str(e)

        def set_failed(h: dict) -> dict:
            if "claws" not in h:
                h["claws"] = {}
            if claw_name not in h["claws"]:
                h["claws"][claw_name] = {"version": matched_version, "user": agent_name}
            h["claws"][claw_name]["status"] = "failed"
            h["claws"][claw_name]["error"] = error_msg
            h["claws"][claw_name]["installed_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            return h

        update_host(host["hostname"], set_failed)
        emit("error", f"Installation failed. Logs at {install_log_dir}")

        # Re-raise the exception
        raise

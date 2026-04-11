"""Installation orchestration for agent deployment.

This module handles the end-to-end installation flow:
1. Validate agent exists in registry
2. Check host compatibility
3. Run base playbook (system dependencies)
4. Run agent-specific playbook

Host record schema (extended):
{
    "hostname": str,
    "agents": {
        "openclaw": {
            "version": "0.1.0",
            "status": "installed" | "failed" | "installing",
            "installed_at": "ISO timestamp",
            "error": str | None,
            "agent_name": "clever-einstein"  # friendly name, no prefix
        }
    },
    ...existing fields...
}
"""

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NotRequired, TypedDict

import ansible_runner

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host, update_host
from clawrium.core.keys import get_host_private_key
from clawrium.core.lifecycle import _resolve_agent_type
from clawrium.core.names import (
    generate_random_name,
    is_name_available_on_host,
    validate_agent_name,
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


class IncompleteInstallationError(InstallationError):
    """Raised when an incomplete installation already exists for an agent type."""

    def __init__(self, hostname: str, claw_name: str, details: dict):
        self.hostname = hostname
        self.claw_name = claw_name
        self.details = details
        status = details.get("status", "unknown")
        agent_name = details.get("agent_name") or claw_name
        super().__init__(
            "Incomplete installation detected for "
            f"'{agent_name}' on host '{hostname}' (status: {status})."
        )


class InstallResult(TypedDict):
    """Result of installation operation."""

    success: bool
    agent: str
    version: str
    host: str
    playbooks_run: list[str]
    error: str | None
    incomplete_installation: NotRequired[dict | None]
    skipped: NotRequired[bool]
    skip_reason: NotRequired[str | None]


def _get_incomplete_installation_details(host: dict, claw_name: str) -> dict | None:
    """Return existing incomplete installation details for an agent type, if any."""
    existing = host.get("agents", {}).get(claw_name)
    if not existing:
        return None

    status = existing.get("status")
    installed_at = existing.get("installed_at")
    # Detect explicit incomplete states from prior attempts.
    # Also treat a status-bearing record with no installed_at timestamp as incomplete.
    if status in {"installing", "failed"} or (
        status is not None and installed_at is None
    ):
        return {
            "status": status,
            "installed_at": installed_at,
            "error": existing.get("error"),
            "agent_name": existing.get("agent_name"),
            "version": existing.get("version"),
        }

    return None


def _get_base_playbook_path() -> Path:
    """Get path to base system playbook."""
    # Base playbook is at src/clawrium/platform/playbooks/base.yaml
    # From src/clawrium/core/install.py: parent.parent gets to src/clawrium
    return Path(__file__).parent.parent / "platform" / "playbooks" / "base.yaml"


def _get_agent_playbook_path(agent_type: str) -> Path:
    """Get path to agent-specific install playbook."""
    return (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / agent_type
        / "playbooks"
        / "install.yaml"
    )


def _get_logs_dir() -> Path:
    """Get logs directory, creating if needed."""
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _openclaw_install_was_skipped(playbook_result: object) -> bool:
    """Detect whether OpenClaw install task was skipped by Ansible conditions."""
    events = getattr(playbook_result, "events", None) or []

    for event in events:
        if event.get("event") != "runner_on_ok":
            continue

        event_data = event.get("event_data", {})
        task_name = event_data.get("task", "")
        result = event_data.get("res", {})

        if task_name == "Mark install as skipped when already installed":
            return True

        ansible_facts = result.get("ansible_facts", {})
        if ansible_facts.get("openclaw_already_installed_and_matching") is True:
            return True

        msg = result.get("msg", "")
        if (
            isinstance(msg, str)
            and "already installed with matching version" in msg.lower()
        ):
            return True

    return False


def run_installation(
    claw_name: str,
    hostname: str,
    name: str | None = None,
    on_event: Callable[[str, str], None] | None = None,
    cleanup_failed: bool = False,
    resume: bool = False,
) -> InstallResult:
    """Run full installation of an agent on a host.

    Args:
        claw_name: Name of agent to install (e.g., "openclaw")
        hostname: Hostname or alias of target host
        name: Optional friendly name for the agent instance. If not provided,
              a random Docker-style name will be generated (e.g., "clever-einstein")
        on_event: Optional callback for progress events (stage, message)
        cleanup_failed: Force cleanup of failed agent before installation
        resume: Resume existing installation using existing agent name

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
        valid, error_msg = validate_agent_name(name)
        if not valid:
            raise InstallationError(f"Invalid name: {error_msg}")
        emit("validate", f"Validated custom name: {name}")

    incomplete_details = _get_incomplete_installation_details(host, claw_name)

    # Handle cleanup if requested
    if cleanup_failed and incomplete_details:
        emit("cleanup", "Removing incomplete installation...")

        def cleanup_agent(h: dict) -> dict:
            # Remove agent entry (including onboarding state)
            if "agents" in h and claw_name in h["agents"]:
                del h["agents"][claw_name]
            return h

        update_host(host["hostname"], cleanup_agent)

        # Remove secrets for this instance
        if incomplete_details.get("agent_name"):
            from clawrium.core.secrets import load_secrets, save_secrets

            instance_key = get_instance_key(
                host["hostname"], claw_name, incomplete_details["agent_name"]
            )
            try:
                secrets = load_secrets()
                if instance_key in secrets:
                    del secrets[instance_key]
                    save_secrets(secrets)
                    emit("cleanup", "Removed secrets for incomplete installation")
            except Exception as e:
                logger.warning("Failed to remove secrets: %s", e)
                # Emit visible warning to user
                emit(
                    "warn",
                    f"Failed to remove secrets for {instance_key}. "
                    "Manual cleanup may be required.",
                )

        emit("cleanup", "Cleanup complete. Starting fresh installation...")
        incomplete_details = None

    # Handle resume if requested
    if resume and incomplete_details:
        # Only allow resume from 'installing' state - 'failed' requires cleanup
        if incomplete_details.get("status") == "failed":
            raise InstallationError(
                "Cannot resume from 'failed' state. "
                "Use cleanup option for failed installations."
            )
        # Use existing agent name from incomplete installation
        name = incomplete_details.get("agent_name")
        if not name:
            raise InstallationError(
                "Cannot resume: agent_name missing from incomplete installation state. "
                "Use cleanup option instead."
            )
        emit("validate", f"Resuming installation with existing name: {name}")
    elif incomplete_details:
        emit(
            "validate",
            "Found previous incomplete installation state; proceeding with retry.",
        )

    # Step 5: Set installing state with uniqueness check under lock
    # Use a list to capture the chosen name from inside the updater
    chosen_name = [None]
    reusing_existing_installed = [False]

    def set_installing(h: dict) -> dict:
        # Check for incomplete installation under lock (unless cleanup or resume)
        if not cleanup_failed and not resume:
            locked_incomplete = _get_incomplete_installation_details(h, claw_name)
            if locked_incomplete and locked_incomplete.get("status") == "installing":
                raise IncompleteInstallationError(
                    h["hostname"], claw_name, locked_incomplete
                )

        if name is None:
            existing_installed = h.get("agents", {}).get(claw_name, {})
            if (
                not resume
                and not cleanup_failed
                and existing_installed.get("status") == "installed"
                and existing_installed.get("agent_name")
            ):
                chosen_name[0] = existing_installed["agent_name"]
                reusing_existing_installed[0] = True
                return_name = chosen_name[0]
                if return_name:
                    logger.info(
                        "Reusing existing installed agent name under lock: %s",
                        return_name,
                    )
            else:
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
            # Use custom name, check uniqueness under lock (unless resuming)
            same_as_existing = (
                claw_name in h.get("agents", {})
                and h["agents"][claw_name].get("agent_name") == name
            )
            if (
                not resume
                and not (reusing_existing_installed[0] and same_as_existing)
                and not is_name_available_on_host(name, h)
            ):
                raise InstallationError(
                    f"Name '{name}' already in use on this host. "
                    "Names must be unique across all agents on a host."
                )
            chosen_name[0] = name

        if "agents" not in h:
            h["agents"] = {}

        # Update status to installing (preserving existing data if resuming/reusing)
        if resume or reusing_existing_installed[0]:
            if claw_name not in h["agents"]:
                raise InstallationError("Cannot resume: agent was removed")
            h["agents"][claw_name]["status"] = "installing"
            h["agents"][claw_name]["error"] = None
            h["agents"][claw_name]["version"] = matched_version  # Update version
        else:
            h["agents"][claw_name] = {
                "version": matched_version,
                "status": "installing",
                "installed_at": None,
                "error": None,
                "agent_name": chosen_name[0],
            }
        return h

    update_host(host["hostname"], set_installing)

    # Extract the chosen name
    agent_name = chosen_name[0]

    # Emit message after lock is released and agent_name is set
    if resume:
        emit("validate", f"Resuming with existing name: {agent_name}")
    elif reusing_existing_installed[0]:
        emit("validate", f"Using existing installed name: {agent_name}")
    elif name is None:
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

    # Get template path for agent type
    canonical_name = _resolve_agent_type(claw_name)
    template_path = (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / canonical_name
        / "templates"
    )

    # Calculate unique port for this agent (matches playbook's calculation)
    # This ensures config.gateway.port matches the openclaw_port ansible var
    port_hash = int(hashlib.md5(agent_name.encode()).hexdigest(), 16)
    openclaw_port = 40000 + (port_hash % 2000)

    # Build minimal config for templates
    config = {
        "gateway": {
            "mode": "local",
            "port": openclaw_port,
            "bind": "0.0.0.0",
        }
    }

    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_host": host["hostname"],
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
                "config": config,
                "template_path": str(template_path),
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
        claw_playbook = _get_agent_playbook_path(claw_name)
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
            timeout=1800,  # 30 min timeout for claw install
        )

        if result.status != "successful":
            raise InstallationError(
                f"Agent playbook failed: {result.status}. "
                f"Check logs at {claw_data_dir}/artifacts/"
            )
        playbooks_run.append(str(claw_playbook))
        install_skipped = False
        skip_reason = None
        if claw_name == "openclaw":
            install_skipped = _openclaw_install_was_skipped(result)
            if install_skipped:
                skip_reason = "already_installed_version_match"
                emit(
                    "claw",
                    "OpenClaw already installed with matching version; skipped install task",
                )
        if not install_skipped:
            emit("claw", f"{claw_name} installed successfully")

        # Step 9.5: Extract gateway token from Ansible facts (OpenClaw only)
        gateway_token = None
        gateway_url = None
        if claw_name == "openclaw" and result.status == "successful":
            # Get host facts from Ansible result
            try:
                # ansible-runner stores facts in artifacts/<run_id>/fact_cache/<hostname>
                import json

                artifacts_dir = Path(result.config.artifact_dir)
                fact_cache_dir = artifacts_dir / "fact_cache"

                if fact_cache_dir.exists():
                    # Find fact file for our host
                    for fact_file in fact_cache_dir.glob("*"):
                        try:
                            with open(fact_file) as f:
                                facts = json.load(f)
                                gateway_token = facts.get("openclaw_gateway_token")
                                gateway_url = facts.get("openclaw_gateway_url")
                                if gateway_token and gateway_url:
                                    emit(
                                        "claw", "Gateway authentication token captured"
                                    )
                                    break
                        except (json.JSONDecodeError, IOError) as file_err:
                            logger.debug(
                                "Skipping fact file %s: %s", fact_file, file_err
                            )
                            continue
            except Exception as e:
                logger.warning("Failed to extract gateway token: %s", e, exc_info=True)
                emit(
                    "warn",
                    "Gateway token capture failed - manual pairing may be needed",
                )

        # Step 10: Update host with success status and gateway auth (if available)
        def set_installed(h: dict) -> dict:
            if "agents" in h and claw_name in h["agents"]:
                h["agents"][claw_name]["status"] = "installed"
                h["agents"][claw_name]["installed_at"] = datetime.now(
                    timezone.utc
                ).isoformat()

                # Store gateway authentication (OpenClaw only)
                if gateway_token and gateway_url:
                    if "config" not in h["agents"][claw_name]:
                        h["agents"][claw_name]["config"] = {}
                    if "gateway" not in h["agents"][claw_name]["config"]:
                        h["agents"][claw_name]["config"]["gateway"] = {}

                    h["agents"][claw_name]["config"]["gateway"]["url"] = gateway_url
                    h["agents"][claw_name]["config"]["gateway"]["auth"] = gateway_token
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
            "incomplete_installation": incomplete_details,
            "skipped": install_skipped,
            "skip_reason": skip_reason,
        }

    except Exception as e:
        # Step 13: Update host with failure status
        error_msg = str(e)

        def set_failed(h: dict) -> dict:
            if "agents" not in h:
                h["agents"] = {}
            if claw_name not in h["agents"]:
                h["agents"][claw_name] = {
                    "version": matched_version,
                    "agent_name": agent_name,
                }
            h["agents"][claw_name]["status"] = "failed"
            h["agents"][claw_name]["error"] = error_msg
            h["agents"][claw_name]["installed_at"] = None
            return h

        update_host(host["hostname"], set_failed)
        emit("error", f"Installation failed. Logs at {install_log_dir}")

        # Re-raise the exception
        raise

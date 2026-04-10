"""Agent lifecycle management for agent instances.

This module handles start, stop, and restart operations for agent instances
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
from clawrium.core.hosts import get_host, update_host, remove_agent_from_host
from clawrium.core import keys as core_keys
from clawrium.core.onboarding import OnboardingState
from clawrium.core.secrets import get_instance_key, get_instance_secrets

logger = logging.getLogger(__name__)

__all__ = [
    "start_agent",
    "stop_agent",
    "restart_agent",
    "remove_agent",
    "configure_agent",
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
}


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


def _update_agent_runtime(hostname: str, claw_name: str, runtime_data: dict) -> bool:
    """Update agent runtime information in hosts.json.

    Args:
        hostname: The hostname of the host
        claw_name: Name of the agent
        runtime_data: Runtime data to store (pid, started_at, status, etc.)

    Returns:
        True if update succeeded
    """

    def updater(h: dict) -> dict:
        if "agents" not in h:
            h["agents"] = {}
        if claw_name not in h["agents"]:
            h["agents"][claw_name] = {}
        h["agents"][claw_name]["runtime"] = runtime_data
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
        claw_name: Type of agent
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

    claw_record = host.get("agents", {}).get(claw_name, {})
    agent_name = claw_record.get("agent_name") or claw_record.get("name")
    if not agent_name:
        return False, f"No agent name recorded for '{claw_name}' on '{hostname}'"

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
        instance_key = get_instance_key(hostname, claw_name, agent_name)
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
                "agent_name": agent_name,
                "agent_type": claw_name,
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


def start_agent(
    hostname: str,
    claw_name: str,
    force: bool = False,
    on_event: Callable[[str, str], None] | None = None,
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

    emit("validate", f"Checking {claw_name} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    claw_record = host.get("agents", {}).get(claw_name)
    if not claw_record:
        raise LifecycleError(f"Agent '{claw_name}' not installed on '{hostname}'")

    onboarding = claw_record.get("onboarding", {})
    state_value = onboarding.get("state", "pending")

    try:
        state = OnboardingState(state_value)
    except ValueError:
        state = OnboardingState.PENDING

    if state != OnboardingState.READY and not force:
        agent_display_name = (
            claw_record.get("agent_name") or claw_record.get("name") or claw_name
        )
        raise LifecycleError(
            f"Cannot start {claw_name}: onboarding incomplete (state={state_value}). "
            f"Run 'clm agent configure {agent_display_name}' first."
        )

    emit("start", f"Starting {claw_name} on {hostname}...")

    success, error = _run_lifecycle_playbook(claw_name, host["hostname"], "start", host)

    if not success:
        return {
            "success": False,
            "agent": claw_name,
            "host": hostname,
            "operation": "start",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    now = datetime.now(timezone.utc).isoformat()
    _update_agent_runtime(
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
        "agent": claw_name,
        "host": hostname,
        "operation": "start",
        "pid": None,
        "started_at": now,
        "error": None,
    }


def stop_agent(
    hostname: str,
    claw_name: str,
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

    emit("validate", f"Checking {claw_name} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    claw_record = host.get("agents", {}).get(claw_name)
    if not claw_record:
        raise LifecycleError(f"Agent '{claw_name}' not installed on '{hostname}'")

    emit("stop", f"Stopping {claw_name} on {hostname}...")

    success, error = _run_lifecycle_playbook(
        claw_name, host["hostname"], "stop", host, timeout=timeout + 30
    )

    if not success:
        return {
            "success": False,
            "agent": claw_name,
            "host": hostname,
            "operation": "stop",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    now = datetime.now(timezone.utc).isoformat()
    _update_agent_runtime(
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
        "agent": claw_name,
        "host": hostname,
        "operation": "stop",
        "pid": None,
        "started_at": None,
        "error": None,
    }


def restart_agent(
    hostname: str,
    claw_name: str,
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

    emit("restart", f"Restarting {claw_name} on {hostname}...")

    stop_result = stop_agent(hostname, claw_name, on_event=on_event)
    if not stop_result["success"]:
        return {
            "success": False,
            "agent": claw_name,
            "host": hostname,
            "operation": "restart",
            "pid": None,
            "started_at": None,
            "error": f"Stop failed: {stop_result['error']}",
        }

    start_result = start_agent(hostname, claw_name, on_event=on_event)
    start_result["operation"] = "restart"

    return start_result


def configure_agent(
    hostname: str,
    claw_name: str,
    config_data: dict,
    on_event: Callable[[str, str], None] | None = None,
) -> tuple[bool, str | None]:
    """Configure an agent instance on a remote host.

    Updates the agent configuration in hosts.json and applies the configuration
    to the remote host via Ansible playbook. This is the single source of truth
    for configuration management.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of agent to configure (e.g., "zeroclaw", "openclaw")
        config_data: Configuration dictionary containing gateway and provider settings
        on_event: Optional callback for progress events

    Returns:
        Tuple of (success, error_message)

    Raises:
        LifecycleError: If host not found or agent not installed
    """
    from clawrium.core.providers import get_provider_api_key

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    emit("configure", f"Configuring {claw_name} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    claw_record = host.get("agents", {}).get(claw_name)
    if not claw_record:
        raise LifecycleError(f"Agent '{claw_name}' not installed on '{hostname}'")

    # Validate config data before running Ansible
    # B7: Validate Ollama model names to prevent template injection
    if config_data.get("provider") and config_data["provider"].get("default_model"):
        model_name = config_data["provider"]["default_model"]
        if not re.match(r"^[a-zA-Z0-9_.:/+-]+$", model_name):
            return (
                False,
                f"Invalid model name: '{model_name}'. Model names must contain only alphanumeric characters, dots, colons, slashes, underscores, plus, and hyphens.",
            )

    # Validate required provider fields
    required_provider_fields = ["name", "type", "default_model"]
    if config_data.get("provider"):
        if not isinstance(config_data["provider"], dict):
            return False, "Invalid provider config - expected dict"
        missing = [
            f for f in required_provider_fields if not config_data["provider"].get(f)
        ]
        if missing:
            return False, f"Incomplete provider config - missing: {', '.join(missing)}"

        # Ollama providers require endpoint
        if config_data["provider"].get("type") == "ollama":
            if not config_data["provider"].get("endpoint"):
                return False, "Ollama provider requires 'endpoint' field"

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
    if config_data.get("provider") and config_data["provider"].get("name"):
        provider_name = config_data["provider"]["name"]
        provider_api_key = get_provider_api_key(provider_name) or ""
        if provider_api_key:
            emit("configure", "Loaded provider API key from secrets")

    # Get template path for this agent type
    canonical_name = _resolve_agent_type(claw_name)
    template_path = (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / canonical_name
        / "templates"
    )

    if not template_path.exists():
        return False, f"Template directory not found: {template_path}"

    # Get playbook path
    playbook_path = _get_lifecycle_playbook_path(claw_name, "configure")
    if not playbook_path.exists():
        return False, f"Configure playbook not found: {playbook_path}"

    # Get SSH key
    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return False, "SSH key not found"

    agent_name = claw_record.get("agent_name") or claw_record.get("name")
    if not agent_name:
        return False, f"No agent name recorded for '{claw_name}' on '{hostname}'"

    # Validate agent_name to prevent path traversal/injection in Ansible playbooks
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", agent_name):
        return (
            False,
            f"Invalid agent_name format: '{agent_name}'. Must start with lowercase letter and contain only lowercase letters, digits, hyphens, underscores (max 32 chars)",
        )

    # B4: Pass API key via environment variable instead of inventory to prevent plaintext logging
    # Build Ansible inventory without API key
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
                "config": config_data,
                "template_path": str(template_path),
            },
        }
    }

    # Set up logging
    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = host.get("alias") or host.get("key_id") or hostname
    operation_log_dir = logs_dir / f"configure-{claw_name}-{host_display}-{timestamp}"
    operation_log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(operation_log_dir, 0o700)

    emit("configure", "Running Ansible playbook...")

    # B4: Set API key in environment variable for Ansible to access
    env_vars = os.environ.copy()
    if provider_api_key:
        env_vars["CLAWRIUM_PROVIDER_API_KEY"] = provider_api_key

    try:
        result = ansible_runner.run(
            private_data_dir=str(operation_log_dir),
            inventory=inventory,
            playbook=str(playbook_path),
            quiet=True,
            timeout=60,
            envvars=env_vars,
        )

        if result.status == "timeout":
            return False, "Configure operation timed out"

        if result.status != "successful":
            error_msg = f"Configure playbook failed: {result.status}"
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

        # B2: Only update hosts.json after Ansible succeeds
        emit("configure", "Saving configuration to hosts.json...")

        def updater(h: dict) -> dict:
            if "agents" not in h:
                h["agents"] = {}
            if claw_name not in h["agents"]:
                h["agents"][claw_name] = {}
            h["agents"][claw_name]["config"] = config_data
            return h

        if not update_host(host["hostname"], updater):
            logger.warning(
                "Ansible succeeded but failed to update hosts.json for %s on %s",
                claw_name,
                hostname,
            )
            return (
                False,
                f"Configuration applied but failed to update local state for {claw_name} on {hostname}",
            )

        emit("configure", f"Successfully configured {claw_name}")
        return True, None

    except Exception as e:
        return False, str(e)


def remove_agent(
    hostname: str,
    claw_name: str,
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

    emit("validate", f"Checking {claw_name} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    claw_record = host.get("agents", {}).get(claw_name)
    if not claw_record:
        raise LifecycleError(f"Agent '{claw_name}' not installed on '{hostname}'")

    # Check if agent is running and stop it first
    runtime = claw_record.get("runtime", {})
    status = runtime.get("status", "stopped")

    if status == "running":
        emit("remove", f"Stopping {claw_name} before removal...")
        try:
            stop_result = stop_agent(hostname, claw_name, on_event=on_event)
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
            "agent": claw_name,
            "host": hostname,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    emit("remove", "Removing from local configuration...")

    # Remove agent from hosts.json
    # NOTE: remove_agent_from_host returns True if host was found (not if agent was found)
    # An exception here means the local config could not be updated after remote cleanup
    try:
        removed = remove_agent_from_host(host["hostname"], claw_name)
        if not removed:
            # Host not found - this shouldn't happen since we validated it earlier
            logger.error(
                "Host %s not found in configuration after remote cleanup", hostname
            )
            return {
                "success": False,
                "agent": claw_name,
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
            "agent": claw_name,
            "host": hostname,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": f"Remote removal succeeded but local config update failed: {e}. Run 'clm host ps {hostname}' to verify or manually edit hosts.json.",
        }

    emit("remove", f"Removed {claw_name} successfully")

    return {
        "success": True,
        "agent": claw_name,
        "host": hostname,
        "operation": "remove",
        "pid": None,
        "started_at": None,
        "error": None,
    }

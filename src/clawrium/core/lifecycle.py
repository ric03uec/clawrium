"""Agent lifecycle management for agent instances.

This module handles start, stop, and restart operations for agent instances
running on remote hosts via systemd service management.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

import ansible_runner

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host, update_host, remove_agent_from_host
from clawrium.core import keys as core_keys
from clawrium.core.onboarding import OnboardingState
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
    remove_instance_secrets,
)
from clawrium.core.skills_state import cleanup_agent_state

logger = logging.getLogger(__name__)

__all__ = [
    "start_agent",
    "stop_agent",
    "restart_agent",
    "remove_agent",
    "configure_agent",
    "sync_agent",
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


def _cleanup_ansible_artifacts(operation_log_dir: Path) -> None:
    """Clean up ansible-runner artifacts that may contain secrets.

    B3 fix: ansible-runner stores inventory and vars in artifacts/,
    which can contain API keys and tokens. Remove after all runs.
    """
    artifacts_dir = operation_log_dir / "artifacts"
    if artifacts_dir.exists():
        try:
            shutil.rmtree(artifacts_dir)
            logger.debug("Cleaned up ansible artifacts at %s", artifacts_dir)
        except Exception as e:
            logger.warning("Failed to clean up ansible artifacts: %s", e)

    # Also clean up env/ directory which may contain inventory with secrets
    env_dir = operation_log_dir / "env"
    if env_dir.exists():
        try:
            shutil.rmtree(env_dir)
            logger.debug("Cleaned up ansible env at %s", env_dir)
        except Exception as e:
            logger.warning("Failed to clean up ansible env: %s", e)

    # ansible-runner serializes the inventory dict (which contains provider
    # API keys, AWS credentials, Discord/Slack tokens, etc. as extravars) to
    # inventory/hosts.json on every run. Without cleanup these accumulate on
    # disk indefinitely. Strip alongside artifacts/ and env/.
    inventory_dir = operation_log_dir / "inventory"
    if inventory_dir.exists():
        try:
            shutil.rmtree(inventory_dir)
            logger.debug("Cleaned up ansible inventory at %s", inventory_dir)
        except Exception as e:
            logger.warning("Failed to clean up ansible inventory: %s", e)


def _resolve_agent_record(
    host: dict,
    identifier: str,
    expected_type: str | None = None,
) -> tuple[str, str, dict] | None:
    """Resolve an agent instance in host.agents.

    Agents must have an explicit 'type' field. Records without 'type' are skipped.
    Raises LifecycleError if multiple agents of the same type are found.
    """
    agents = host.get("agents", {})
    if not isinstance(agents, dict):
        return None

    # Direct key lookup
    direct = agents.get(identifier)
    if isinstance(direct, dict):
        direct_type = direct.get("type")
        if not isinstance(direct_type, str) or not direct_type:
            # Skip records without explicit type field
            return None
        if expected_type and direct_type != expected_type:
            return None
        return identifier, direct_type, direct

    # Search by type
    matches: list[tuple[str, str, dict]] = []
    for agent_key, record in agents.items():
        if not isinstance(record, dict):
            continue
        agent_type = record.get("type")
        # Skip records without explicit type field
        if not isinstance(agent_type, str) or not agent_type:
            continue
        if expected_type:
            if agent_type == expected_type:
                matches.append((agent_key, agent_type, record))
        elif agent_type == identifier:
            matches.append((agent_key, agent_type, record))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        instance_names = ", ".join(m[0] for m in matches)
        raise LifecycleError(
            f"Multiple {expected_type or identifier} agents found. "
            f"Specify instance name: {instance_names}"
        )
    return None


def _update_agent_runtime(hostname: str, agent_key: str, runtime_data: dict) -> bool:
    """Update agent runtime information in hosts.json.

    Args:
        hostname: The hostname of the host
        agent_key: Instance key for the agent
        runtime_data: Runtime data to store (pid, started_at, status, etc.)

    Returns:
        True if update succeeded
    """

    def updater(h: dict) -> dict:
        if "agents" not in h:
            h["agents"] = {}
        if agent_key not in h["agents"]:
            h["agents"][agent_key] = {}
        h["agents"][agent_key]["runtime"] = runtime_data
        return h

    return update_host(hostname, updater)


def _run_lifecycle_playbook(
    agent_type: str,
    agent_name: str,
    hostname: str,
    operation: str,
    host: dict,
    timeout: int = 60,
) -> tuple[bool, str | None]:
    """Run a lifecycle playbook on a host.

    Args:
        agent_type: Type of agent
        agent_name: Instance name
        hostname: Target hostname
        operation: Operation to perform ("start" or "stop")
        host: Host record dict
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, error_message)
    """
    playbook_path = _get_lifecycle_playbook_path(agent_type, operation)

    if not playbook_path.exists():
        return False, f"Playbook not found: {playbook_path}"

    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return False, "SSH key not found"

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
        instance_key = get_instance_key(hostname, agent_type, agent_name)
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
                "agent_type": agent_type,
                **secret_vars,
            },
        }
    }

    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = host.get("alias") or host.get("key_id") or hostname
    operation_log_dir = (
        logs_dir / f"{operation}-{agent_type}-{host_display}-{timestamp}"
    )
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
    finally:
        # W4 fix: Always clean up artifacts containing secrets (success, failure, or exception)
        _cleanup_ansible_artifacts(operation_log_dir)


def start_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
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

    target = agent_name or claw_name
    emit("validate", f"Checking {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, agent_type, claw_record = resolved

    onboarding = claw_record.get("onboarding", {})
    state_value = onboarding.get("state", "pending")

    try:
        state = OnboardingState(state_value)
    except ValueError:
        state = OnboardingState.PENDING

    if state != OnboardingState.READY and not force:
        agent_display_name = agent_key
        raise LifecycleError(
            f"Cannot start {agent_key}: onboarding incomplete (state={state_value}). "
            f"Run 'clm agent configure {agent_display_name}' first."
        )

    emit("start", f"Starting {agent_key} on {hostname}...")

    success, error = _run_lifecycle_playbook(
        agent_type, agent_key, host["hostname"], "start", host
    )

    if not success:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "start",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    now = datetime.now(timezone.utc).isoformat()
    _update_agent_runtime(
        host["hostname"],
        agent_key,
        {
            "status": "running",
            "started_at": now,
            "last_check": now,
        },
    )

    emit("start", f"Started {agent_key} successfully")

    return {
        "success": True,
        "agent": agent_key,
        "host": hostname,
        "operation": "start",
        "pid": None,
        "started_at": now,
        "error": None,
    }


def stop_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
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

    target = agent_name or claw_name
    emit("validate", f"Checking {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, agent_type, _ = resolved

    emit("stop", f"Stopping {agent_key} on {hostname}...")

    success, error = _run_lifecycle_playbook(
        agent_type, agent_key, host["hostname"], "stop", host, timeout=timeout + 30
    )

    if not success:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "stop",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    now = datetime.now(timezone.utc).isoformat()
    _update_agent_runtime(
        host["hostname"],
        agent_key,
        {
            "status": "stopped",
            "started_at": None,
            "stopped_at": now,
            "last_check": now,
        },
    )

    emit("stop", f"Stopped {agent_key} successfully")

    return {
        "success": True,
        "agent": agent_key,
        "host": hostname,
        "operation": "stop",
        "pid": None,
        "started_at": None,
        "error": None,
    }


def restart_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
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

    target = agent_name or claw_name
    emit("restart", f"Restarting {target} on {hostname}...")

    stop_result = stop_agent(
        hostname, claw_name, agent_name=agent_name, on_event=on_event
    )
    if not stop_result["success"]:
        return {
            "success": False,
            "agent": target,
            "host": hostname,
            "operation": "restart",
            "pid": None,
            "started_at": None,
            "error": f"Stop failed: {stop_result['error']}",
        }

    start_result = start_agent(
        hostname, claw_name, agent_name=agent_name, on_event=on_event
    )
    start_result["operation"] = "restart"

    return start_result


def sync_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    workspace_only: bool = False,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Sync configuration and optionally restart an agent instance.

    Orchestrates: configure_agent -> restart_agent (unless workspace_only).
    This is a single command to ensure an agent is running the latest configuration.

    Args:
        hostname: Hostname or alias of target host
        claw_name: Type of agent to sync (e.g., "openclaw")
        agent_name: Optional specific instance name
        workspace_only: If True, only sync workspace files without restarting
        on_event: Optional callback for progress events

    Returns:
        LifecycleResult with success status and details
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("sync", f"Syncing {target} on {hostname}...")

    # Validate host and agent exist
    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, agent_type, claw_record = resolved

    # Check onboarding state - agent must be past PENDING to sync
    # This allows syncing during onboarding (e.g., after identity stage)
    onboarding = claw_record.get("onboarding", {})
    state_value = onboarding.get("state", "pending")

    try:
        state = OnboardingState(state_value)
    except ValueError:
        state = OnboardingState.PENDING

    if state == OnboardingState.PENDING:
        raise LifecycleError(
            f"Cannot sync {agent_key}: onboarding not started (state={state_value}). "
            f"Run 'clm agent configure {agent_key}' first."
        )

    # Auto-coerce workspace_only=True for non-READY states
    # start_agent() enforces state==READY, so restart would fail
    if state != OnboardingState.READY and not workspace_only:
        workspace_only = True
        emit(
            "sync",
            f"Note: Agent not fully onboarded (state={state_value}), syncing workspace only",
        )

    # Get existing config to re-apply
    existing_config = claw_record.get("config", {})
    if not existing_config:
        raise LifecycleError(
            f"No configuration found for {agent_key}. "
            f"Run 'clm agent configure {agent_key}' first."
        )

    # Step 1: Configure agent (sync config files)
    emit("sync", f"Configuring {agent_key}...")
    config_success, config_error = configure_agent(
        hostname,
        agent_type,
        existing_config,
        agent_name=agent_key,
        on_event=on_event,
    )

    if not config_success:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": f"Configure failed: {config_error}",
        }

    # Step 2: Restart agent (unless workspace_only)
    if workspace_only:
        emit("sync", f"Workspace sync complete for {agent_key} (no restart)")
        return {
            "success": True,
            "agent": agent_key,
            "host": hostname,
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": None,
        }

    # Wrap in try/except to maintain LifecycleResult return contract
    emit("sync", f"Restarting {agent_key}...")
    try:
        restart_result = restart_agent(
            hostname,
            agent_type,
            agent_name=agent_key,
            on_event=on_event,
        )
    except LifecycleError as e:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": f"Restart failed: {e}",
        }

    if not restart_result["success"]:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": f"Restart failed: {restart_result['error']}",
        }

    emit("sync", f"Sync complete for {agent_key}")

    return {
        "success": True,
        "agent": agent_key,
        "host": hostname,
        "operation": "sync",
        "pid": restart_result.get("pid"),
        "started_at": restart_result.get("started_at"),
        "error": None,
    }


def configure_agent(
    hostname: str,
    claw_name: str,
    config_data: dict,
    agent_name: str | None = None,
    extra_vars: dict | None = None,
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
        agent_name: Optional specific instance name
        extra_vars: Optional extra Ansible vars (not persisted to hosts.json)
        on_event: Optional callback for progress events

    Returns:
        Tuple of (success, error_message)

    Raises:
        LifecycleError: If host not found or agent not installed
    """
    from clawrium.core.providers import get_provider_api_key, get_provider_aws_credentials
    from clawrium.core.integrations import (
        INTEGRATION_TYPES,
        get_agent_integrations,
        get_integration,
        get_integration_credentials,
    )

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("configure", f"Configuring {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, resolved_type, agent_record = resolved
    # Use inner agent_name (Unix username) if available, otherwise fall back to dict key
    unix_agent_name = agent_record.get("agent_name") or agent_key

    # Hermes: hydrate the persisted api_server block (non-sensitive shape from
    # hosts.json) PLUS the bearer token from secrets.json into config_data so
    # the configure playbook can render API_SERVER_KEY into ~/.hermes/.env.
    # Reconfigure flows reuse the persisted token verbatim (idempotency
    # contract — clients reading the gateway don't see rotation).
    if resolved_type == "hermes":
        from clawrium.core.install import _is_valid_hermes_api_server_key

        persisted_api_server = agent_record.get("config", {}).get("api_server")
        # Use canonical hostname (host['hostname']) instead of the raw hostname
        # parameter so the lookup matches install.py's instance_key even when
        # callers pass an alias. CLI paths today always resolve canonical, but
        # programmatic callers may not.
        instance_key = get_instance_key(
            host["hostname"], resolved_type, unix_agent_name
        )
        secret_entry = get_instance_secrets(instance_key).get("HERMES_API_SERVER_KEY")
        # `.get("value")` not `["value"]`: a truthy-but-malformed entry (no
        # "value" field) would otherwise raise KeyError out of configure
        # instead of routing through the validity check below.
        api_server_key = secret_entry.get("value") if secret_entry else None

        if not _is_valid_hermes_api_server_key(api_server_key):
            return (
                False,
                "Hermes agent missing or invalid HERMES_API_SERVER_KEY in "
                "secrets.json (expected 64-char lowercase hex). "
                "Re-run 'clm agent install --type hermes ...' to generate one.",
            )

        if isinstance(persisted_api_server, dict):
            # Opportunistic migration: legacy hermes installs persisted
            # host="127.0.0.1". The OpenAI-compatible gateway must bind a
            # reachable interface so `clm chat <hermes>` works from any clm
            # machine. Hermes' own startup check (api_server.py:3150) refuses
            # to bind non-loopback unless a strong API_SERVER_KEY is set; we
            # always generate a 64-char hex key, so the safety check passes.
            # Rewrite in-memory and persist before merging.
            if persisted_api_server.get("host") == "127.0.0.1":
                persisted_api_server = {**persisted_api_server, "host": "0.0.0.0"}

                def _migrate_bind(h: dict) -> dict:
                    agents = h.get("agents") or {}
                    record = agents.get(agent_key)
                    if not isinstance(record, dict):
                        return h
                    config = record.get("config")
                    if not isinstance(config, dict):
                        return h
                    api_server = config.get("api_server")
                    if (
                        isinstance(api_server, dict)
                        and api_server.get("host") == "127.0.0.1"
                    ):
                        api_server["host"] = "0.0.0.0"
                    return h

                update_host(host["hostname"], _migrate_bind)

            existing_api_server = config_data.get("api_server") or {}
            if not isinstance(existing_api_server, dict):
                existing_api_server = {}
            merged_api_server = {**existing_api_server, **persisted_api_server}
            merged_api_server["key"] = api_server_key
            config_data["api_server"] = merged_api_server
        else:
            # hosts.json shape missing (legacy/corrupted); reconstruct defaults
            # alongside the token from secrets.json so the playbook can run.
            config_data["api_server"] = {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 8642,
                "key": api_server_key,
            }

        # Hermes Slack: merge persisted channels.slack shape from hosts.json
        # with anything passed in config_data, then hydrate the bot/app tokens
        # from secrets.json. Mirrors the Discord hydration pattern.
        #
        # Discord hydration moved out of this hermes-only branch to a sibling
        # block below (#422) so zeroclaw can share it; Slack stays hermes-only
        # because zeroclaw v0.7.5 has no native Slack channel. The
        # persisted_channels/incoming_channels locals below feed only Slack.
        persisted_channels = agent_record.get("config", {}).get("channels") or {}
        if not isinstance(persisted_channels, dict):
            persisted_channels = {}
        incoming_channels = config_data.get("channels") or {}
        if not isinstance(incoming_channels, dict):
            incoming_channels = {}

        persisted_slack = persisted_channels.get("slack") or {}
        if not isinstance(persisted_slack, dict):
            persisted_slack = {}

        incoming_slack = incoming_channels.get("slack") or {}
        if not isinstance(incoming_slack, dict):
            incoming_slack = {}

        merged_slack = {**persisted_slack, **incoming_slack}

        if merged_slack.get("enabled"):
            slack_secrets = get_instance_secrets(instance_key)
            slack_bot_secret = slack_secrets.get("SLACK_BOT_TOKEN")
            slack_bot_val = (
                slack_bot_secret.get("value")
                if isinstance(slack_bot_secret, dict)
                else None
            )
            slack_app_secret = slack_secrets.get("SLACK_APP_TOKEN")
            slack_app_val = (
                slack_app_secret.get("value")
                if isinstance(slack_app_secret, dict)
                else None
            )
            if (
                not isinstance(slack_bot_val, str)
                or not slack_bot_val.startswith("xoxb-")
            ):
                return (
                    False,
                    "Slack enabled for this agent but SLACK_BOT_TOKEN is "
                    "missing or invalid in secrets.json. Re-run "
                    "'clm agent configure <name> --stage channels' to set it.",
                )
            if (
                not isinstance(slack_app_val, str)
                or not slack_app_val.startswith("xapp-")
            ):
                return (
                    False,
                    "Slack enabled for this agent but SLACK_APP_TOKEN is "
                    "missing or invalid in secrets.json. Re-run "
                    "'clm agent configure <name> --stage channels' to set it.",
                )
            merged_slack["bot_token"] = slack_bot_val
            merged_slack["app_token"] = slack_app_val

        if persisted_slack or incoming_slack:
            current_channels = config_data.get("channels") or {}
            if not isinstance(current_channels, dict):
                current_channels = {}
            current_channels["slack"] = merged_slack
            config_data["channels"] = current_channels

    # Discord channel hydration (#422). Shared between hermes and zeroclaw —
    # both consume the same DISCORD_BOT_TOKEN secrets.json entry, the only
    # difference is downstream: hermes renders DISCORD_BOT_TOKEN into .env
    # via .env.j2 while zeroclaw renders bot_token = "<token>" into config.toml
    # via config.toml.j2's [channels.discord] block. The hydration is identical.
    #
    # Gated on Discord being present in either persisted or incoming config
    # before any get_instance_key call so a configure for a non-Discord agent
    # with an unusable agent_name (e.g. the invalid-claw-user test path) still
    # falls through to the validation block below.
    if resolved_type in ("hermes", "zeroclaw"):
        discord_persisted_channels = (
            agent_record.get("config", {}).get("channels") or {}
        )
        if not isinstance(discord_persisted_channels, dict):
            discord_persisted_channels = {}
        discord_persisted = discord_persisted_channels.get("discord") or {}
        if not isinstance(discord_persisted, dict):
            discord_persisted = {}

        discord_incoming_channels = config_data.get("channels") or {}
        if not isinstance(discord_incoming_channels, dict):
            discord_incoming_channels = {}
        discord_incoming = discord_incoming_channels.get("discord") or {}
        if not isinstance(discord_incoming, dict):
            discord_incoming = {}

        if discord_persisted or discord_incoming:
            # Persisted onto incoming so an explicit caller-provided field
            # wins, but fields the caller didn't set (e.g.
            # _sync_provider_config only carrying provider) inherit from
            # hosts.json.
            discord_merged = {**discord_persisted, **discord_incoming}

            if discord_merged.get("enabled"):
                discord_instance_key = get_instance_key(
                    host["hostname"], resolved_type, unix_agent_name
                )
                discord_secret = get_instance_secrets(discord_instance_key).get(
                    "DISCORD_BOT_TOKEN"
                )
                discord_token = (
                    discord_secret.get("value")
                    if isinstance(discord_secret, dict)
                    else None
                )
                if (
                    not isinstance(discord_token, str)
                    or len(discord_token) < 50
                ):
                    return (
                        False,
                        "Discord enabled for this agent but DISCORD_BOT_TOKEN "
                        "is missing or invalid in secrets.json. Re-run "
                        "'clm agent configure <name> --stage channels' to set "
                        "it.",
                    )
                discord_merged["bot_token"] = discord_token

            current_channels = config_data.get("channels") or {}
            if not isinstance(current_channels, dict):
                current_channels = {}
            current_channels["discord"] = discord_merged
            config_data["channels"] = current_channels

    # Validate config data before running Ansible
    # Validate required provider fields (must check dict type first)
    required_provider_fields = ["name", "type", "default_model"]
    if config_data.get("provider"):
        if not isinstance(config_data["provider"], dict):
            return False, "Invalid provider config - expected dict"
        missing = [
            f for f in required_provider_fields if not config_data["provider"].get(f)
        ]
        if missing:
            return False, f"Incomplete provider config - missing: {', '.join(missing)}"

        # Validate model names to prevent template injection
        if config_data["provider"].get("default_model"):
            model_name = config_data["provider"]["default_model"]
            if not re.match(r"^[a-zA-Z0-9_.:/+-]+$", model_name):
                return (
                    False,
                    f"Invalid model name: '{model_name}'. Model names must contain only alphanumeric characters, dots, colons, slashes, underscores, plus, and hyphens.",
                )

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
    aws_access_key = ""
    aws_secret_key = ""
    if config_data.get("provider") and config_data["provider"].get("name"):
        provider_name = config_data["provider"]["name"]
        provider_type = config_data["provider"].get("type", "")
        if provider_type == "bedrock":
            # Bedrock uses AWS credentials instead of API key
            access_key, secret_key = get_provider_aws_credentials(provider_name)
            if access_key and secret_key:
                aws_access_key = access_key
                aws_secret_key = secret_key
                emit("configure", "Loaded AWS credentials from secrets")
        else:
            provider_api_key = get_provider_api_key(provider_name) or ""
            if provider_api_key:
                emit("configure", "Loaded provider API key from secrets")

    # Load channel secrets (Discord bot token)
    discord_bot_token = ""
    try:
        instance_key = get_instance_key(
            host["hostname"], resolved_type, unix_agent_name
        )
        instance_secrets = get_instance_secrets(instance_key)
        # ATX Round 2 W4: match the safe `.get("value")` pattern used
        # by the Hermes API-server-key path (line ~762). A malformed
        # secrets.json entry (truthy dict without a "value" field)
        # otherwise raises KeyError, which the outer `except Exception`
        # silently swallows into an empty token and the user can't tell
        # why Discord/Slack stopped working.
        discord_entry = instance_secrets.get("DISCORD_BOT_TOKEN")
        if isinstance(discord_entry, dict):
            discord_value = discord_entry.get("value")
            if isinstance(discord_value, str):
                discord_bot_token = discord_value
                emit("configure", "Loaded Discord bot token from secrets")
    except Exception as e:
        logger.warning("Failed to load Discord bot token for %s: %s", agent_key, e)

    # Load channel secrets (Slack bot token)
    slack_bot_token = ""
    slack_app_token = ""
    try:
        instance_key = get_instance_key(
            host["hostname"], resolved_type, unix_agent_name
        )
        instance_secrets = get_instance_secrets(instance_key)
        # ATX Round 2 W4: same safe-indexing pattern as Discord above.
        slack_bot_entry = instance_secrets.get("SLACK_BOT_TOKEN")
        if isinstance(slack_bot_entry, dict):
            slack_bot_value = slack_bot_entry.get("value")
            if isinstance(slack_bot_value, str):
                slack_bot_token = slack_bot_value
                emit("configure", "Loaded Slack bot token from secrets")
        slack_app_entry = instance_secrets.get("SLACK_APP_TOKEN")
        if isinstance(slack_app_entry, dict):
            slack_app_value = slack_app_entry.get("value")
            if isinstance(slack_app_value, str):
                slack_app_token = slack_app_value
                emit("configure", "Loaded Slack app token from secrets")
    except Exception as e:
        logger.warning("Failed to load Slack tokens for %s: %s", agent_key, e)

    # Load integrations assigned to this agent
    # Key by integration_name to avoid collisions when multiple integrations
    # of the same type are assigned (e.g., work-github and personal-github)
    integrations_data: dict[str, dict] = {}
    assigned_integrations = get_agent_integrations(hostname, agent_key)
    for integration_name in assigned_integrations:
        integration = get_integration(integration_name)
        if not integration:
            logger.warning(
                "Integration '%s' assigned to %s not found, skipping",
                integration_name,
                agent_key,
            )
            continue
        integration_type = integration.get("type", "")
        # Surface unknown types (e.g., a stale `jira`/`confluence` record from
        # before this PR, or a missing/empty `type` from a hand-edited file)
        # so the user knows MCP wiring will be a no-op rather than silently
        # shipping a green configure with no Atlassian access. Empty string is
        # not a key in INTEGRATION_TYPES, so the same branch catches both.
        if integration_type not in INTEGRATION_TYPES:
            valid = ", ".join(sorted(INTEGRATION_TYPES.keys()))
            warning_msg = (
                f"WARNING: integration '{integration_name}' has unknown type "
                f"'{integration_type}' — skipping. Valid types: {valid}. "
                f"Run `clm integration remove {integration_name}` and "
                f"`clm integration add {integration_name} --type <valid-type>` "
                "to recover."
            )
            emit("configure", warning_msg)
            logger.warning(warning_msg)
            continue
        credentials = get_integration_credentials(integration_name)
        if credentials:
            # Store by integration_name with type and credentials
            # Templates access via: integrations.<name>.type and integrations.<name>.<key>
            integrations_data[integration_name] = {
                "type": integration_type,
                **credentials,
            }
            emit(
                "configure",
                f"Loaded {integration_name} ({integration_type}) credentials",
            )
        else:
            logger.warning(
                "No credentials found for integration '%s', skipping",
                integration_name,
            )

    # Get template path for this agent type
    canonical_name = _resolve_agent_type(resolved_type)
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
    playbook_path = _get_lifecycle_playbook_path(resolved_type, "configure")
    if not playbook_path.exists():
        return False, f"Configure playbook not found: {playbook_path}"

    # Get SSH key
    key_id = host.get("key_id") or hostname
    ssh_key = get_host_private_key(key_id)
    if not ssh_key:
        return False, "SSH key not found"

    if not unix_agent_name:
        return False, f"No agent name recorded for '{claw_name}' on '{hostname}'"

    # Validate agent_name to prevent path traversal/injection in Ansible playbooks
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", unix_agent_name):
        return (
            False,
            f"Invalid agent_name format: '{unix_agent_name}'. Must start with lowercase letter and contain only lowercase letters, digits, hyphens, underscores (max 32 chars)",
        )

    # Build Ansible inventory with API key passed directly
    ansible_vars = {
        "agent_name": unix_agent_name,
        "agent_type": resolved_type,
        "config": config_data,
        "template_path": str(template_path),
        "provider_api_key": provider_api_key,
        "aws_access_key": aws_access_key,
        "aws_secret_key": aws_secret_key,
        "discord_bot_token": discord_bot_token,
        "slack_bot_token": slack_bot_token,
        "slack_app_token": slack_app_token,
        "integrations": integrations_data,
    }

    # ZeroClaw idempotent re-configure (ATX Round 1 B3): pass any
    # existing bearer token in via Ansible vars so the configure playbook
    # can skip the pairing handshake when already paired. Without this
    # every configure call would mint a fresh token and silently
    # invalidate any in-flight `clm chat` WebSocket.
    if resolved_type == "zeroclaw":
        existing_gateway = agent_record.get("config", {}).get("gateway") or {}
        existing_token = existing_gateway.get("auth")
        # ATX Round 2 W5: keep the Python-side threshold consistent with
        # the playbook's `length >= 16` check. A 1-15 char hand-edited
        # token would otherwise be passed in but silently rejected by the
        # playbook, causing an opaque re-pair.
        if (
            isinstance(existing_token, str)
            and len(existing_token.strip()) >= 16
        ):
            ansible_vars["existing_gateway_token"] = existing_token.strip()
        else:
            # ATX Round 3 W5 / Round 4 B1: when a too-short token
            # forces a re-pair, surface that explicitly so the operator
            # can tell whether any live `clm chat` sessions are about
            # to break. Suppressed when there is no token at all
            # (first configure) — that's the normal mint path, not an
            # unexpected re-pair.
            #
            # Must use the `WARNING:` prefix + stage="configure" pattern
            # (mirrors the integration-type warning at lifecycle.py:1046)
            # so cli/agent.py's `_print_configure_warnings` callback
            # routes the message to the user. The callback dispatches
            # on the `WARNING:` prefix; a `stage="warn"` event with a
            # different prefix is silently dropped at the terminal.
            if isinstance(existing_token, str) and existing_token.strip():
                warning_msg = (
                    f"WARNING: Existing gateway token for {agent_key} "
                    f"is shorter than 16 characters — treating as "
                    f"absent. A new pairing handshake will be performed "
                    f"and any live `clm chat {agent_key}` session will "
                    f"need to reconnect."
                )
                emit("configure", warning_msg)
                logger.warning(warning_msg)
            ansible_vars["existing_gateway_token"] = ""
        # `force_repair` flows in via extra_vars when the CLI surfaces
        # an explicit rotation flag; default false so normal reconfigures
        # are idempotent. ATX Round 2 S1: direct assignment — `setdefault`
        # on a freshly constructed dict reads as a guard that doesn't
        # exist in practice.
        ansible_vars["force_repair"] = False

    # Merge extra_vars (not persisted to hosts.json)
    if extra_vars:
        ansible_vars.update(extra_vars)

    inventory = {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": ansible_vars,
        }
    }

    # Set up logging
    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    host_display = host.get("alias") or host.get("key_id") or hostname
    operation_log_dir = (
        logs_dir / f"configure-{resolved_type}-{host_display}-{timestamp}"
    )
    operation_log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(operation_log_dir, 0o700)

    emit("configure", "Running Ansible playbook...")

    # Hermes' configure flow restarts the service and probes /health with up
    # to 20×3s retries (60s) — leave generous headroom for slow first-startup
    # path that loads the agent venv. Zeroclaw's configure does a pairing
    # handshake + /health/providers probe (30×2s = 60s upper bound) plus 7
    # workspace template renders after #358 — 60s leaves no margin, so the
    # claw gets a 180s budget. Other claws keep the legacy 60s budget.
    if resolved_type == "hermes":
        configure_timeout = 240
    elif resolved_type == "zeroclaw":
        configure_timeout = 180
    else:
        configure_timeout = 60

    try:
        result = ansible_runner.run(
            private_data_dir=str(operation_log_dir),
            inventory=inventory,
            playbook=str(playbook_path),
            quiet=True,
            timeout=configure_timeout,
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

        # ZeroClaw: extract the bearer token + gateway URL the configure
        # playbook minted via the pairing handshake. configure.yaml emits
        # them as cacheable host facts (`zeroclaw_gateway_token` and
        # `zeroclaw_gateway_url`); we read them out of the fact cache and
        # surface them via `config_data["gateway"]` so the updater below
        # persists them to hosts.json under
        # `agents.<n>.config.gateway.{auth,url}`. Mirrors the OpenClaw fact
        # extraction in install.py:688-794. Done outside the updater closure
        # so any read failure surfaces as a configure-time error rather than
        # corrupting hosts.json silently.
        zc_gateway_token: str | None = None
        zc_gateway_url: str | None = None
        if resolved_type == "zeroclaw":
            try:
                artifacts_dir = Path(result.config.artifact_dir)
                fact_cache_dir = artifacts_dir / "fact_cache"
                if fact_cache_dir.exists():
                    for fact_file in fact_cache_dir.glob("*"):
                        try:
                            with open(fact_file) as fh:
                                facts = json.load(fh)
                        except (json.JSONDecodeError, IOError) as file_err:
                            logger.debug(
                                "Skipping fact file %s: %s", fact_file, file_err
                            )
                            continue
                        payload = facts.get("__payload__")
                        if not isinstance(payload, str) or not payload:
                            continue
                        try:
                            parsed = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(parsed, dict):
                            continue

                        token_raw = parsed.get("zeroclaw_gateway_token")
                        url_raw = parsed.get("zeroclaw_gateway_url")
                        health_warn_raw = parsed.get(
                            "zeroclaw_provider_health_warning"
                        )

                        # Tolerate Ansible's occasional `{"value": "..."}`
                        # wrapping for cacheable string facts.
                        if isinstance(token_raw, dict):
                            token_raw = token_raw.get("value")
                        if isinstance(url_raw, dict):
                            url_raw = url_raw.get("value")
                        if isinstance(health_warn_raw, dict):
                            health_warn_raw = health_warn_raw.get("value")
                        if isinstance(token_raw, str):
                            token_raw = token_raw.strip()
                        if isinstance(url_raw, str):
                            url_raw = url_raw.strip()

                        # ATX Round 2 W1: when the playbook recorded a
                        # 401 from /health/providers, surface a one-shot
                        # warning to the CLI event stream. Without this
                        # the operator finishes configure with exit 0
                        # and a silently-misconfigured provider — they
                        # only learn at the next `clm chat` invocation.
                        if health_warn_raw is True or health_warn_raw == "true":
                            # ATX Round 4 B1: same "WARNING:" /
                            # stage="configure" pattern as the
                            # short-token re-pair warning above —
                            # ensures `_print_configure_warnings`
                            # actually surfaces this to the user
                            # instead of silently emitting at INFO.
                            health_warning_msg = (
                                f"WARNING: /health/providers returned "
                                f"401 — gateway is reachable but "
                                f"provider "
                                f"'{config_data.get('provider', {}).get('type', '?')}' "
                                f"credentials may be invalid. Verify "
                                f"the API key and re-run "
                                f"`clm agent configure {agent_key}` "
                                f"if needed."
                            )
                            emit("configure", health_warning_msg)
                            logger.warning(health_warning_msg)

                        if (
                            isinstance(token_raw, str) and token_raw
                            and isinstance(url_raw, str) and url_raw
                        ):
                            zc_gateway_token = token_raw
                            zc_gateway_url = url_raw
                            emit("configure", "Pairing token captured")
                            break
            except Exception as exc:
                logger.warning(
                    "Failed to extract zeroclaw gateway facts: %s",
                    exc,
                    exc_info=True,
                )

            if not zc_gateway_token or not zc_gateway_url:
                # The playbook succeeded but the token did not surface in
                # the fact cache. Fail fast — without a bearer token, the
                # later `clm chat` call has nothing to authenticate with
                # and would dead-end at the gateway.
                return (
                    False,
                    "Configure playbook succeeded but the pairing token "
                    "was not captured. Re-run `clm agent configure "
                    f"{agent_key}` and check daemon logs at "
                    f"`journalctl --unit zeroclaw-{agent_key}` for the "
                    "pairing handshake.",
                )

            # Surface to the updater via config_data so the gateway block
            # round-trips into hosts.json on the same write that persists
            # everything else from this configure call.
            existing_gateway = config_data.get("gateway")
            if not isinstance(existing_gateway, dict):
                existing_gateway = {}
            existing_gateway = dict(existing_gateway)
            existing_gateway["auth"] = zc_gateway_token
            existing_gateway["url"] = zc_gateway_url
            config_data["gateway"] = existing_gateway

        # B2: Only update hosts.json after Ansible succeeds
        emit("configure", "Saving configuration to hosts.json...")

        def updater(h: dict) -> dict:
            if "agents" not in h:
                h["agents"] = {}
            if agent_key not in h["agents"]:
                h["agents"][agent_key] = {}
            h["agents"][agent_key]["type"] = resolved_type

            # Preserve device credentials when updating config
            existing_config = h["agents"][agent_key].get("config", {})
            existing_gateway = existing_config.get("gateway", {})
            device_creds = existing_gateway.get("device")

            # Strip the hermes bearer token before persisting to hosts.json.
            # The token was hydrated into config_data['api_server']['key']
            # earlier in this call (line ~752) so the ansible playbook could
            # render it, but the canonical store is secrets.json. Keeping it
            # in hosts.json after configure would defeat the B3 migration.
            persisted_config = dict(config_data)
            if resolved_type == "hermes":
                if "api_server" in persisted_config:
                    api_server_persisted = dict(persisted_config["api_server"])
                    api_server_persisted.pop("key", None)
                    persisted_config["api_server"] = api_server_persisted

            # B3 invariant for Discord: bot_token lives in secrets.json only,
            # never in hosts.json. Applies to both hermes (DISCORD_BOT_TOKEN
            # hydrated into .env via .env.j2) and zeroclaw (#422 — token
            # hydrated into config.toml's [channels.discord]). Without this
            # strip, the bot_token roundtrips: hydrated → persisted → read
            # back into existing_config on next configure → re-hydrated, etc.
            # ATX B1 finding. Slack inclusion is hermes-only in practice but
            # the pop is idempotent on absent keys so leaving it covers both
            # agent types in one branch.
            if resolved_type in ("hermes", "zeroclaw"):
                if "channels" in persisted_config:
                    channels_persisted = persisted_config.get("channels")
                    if isinstance(channels_persisted, dict):
                        channels_persisted = dict(channels_persisted)
                        discord_persisted = channels_persisted.get("discord")
                        if isinstance(discord_persisted, dict):
                            discord_persisted = dict(discord_persisted)
                            discord_persisted.pop("bot_token", None)
                            channels_persisted["discord"] = discord_persisted
                        slack_persisted = channels_persisted.get("slack")
                        if isinstance(slack_persisted, dict):
                            slack_persisted = dict(slack_persisted)
                            slack_persisted.pop("bot_token", None)
                            slack_persisted.pop("app_token", None)
                            channels_persisted["slack"] = slack_persisted
                        persisted_config["channels"] = channels_persisted
                    else:
                        # Unexpected shape (string/list/etc.) — drop rather
                        # than risk persisting a token via an unknown path.
                        logger.warning(
                            "Dropping unexpected channels block (type=%s) for "
                            "agent %s during persist to avoid B3 violation.",
                            type(channels_persisted).__name__,
                            agent_key,
                        )
                        persisted_config.pop("channels", None)

            h["agents"][agent_key]["config"] = persisted_config

            # Restore device credentials if they existed
            if device_creds:
                if "gateway" not in h["agents"][agent_key]["config"]:
                    h["agents"][agent_key]["config"]["gateway"] = {}
                h["agents"][agent_key]["config"]["gateway"]["device"] = device_creds

            return h

        if not update_host(host["hostname"], updater):
            logger.warning(
                "Ansible succeeded but failed to update hosts.json for %s on %s",
                claw_name,
                hostname,
            )
            return (
                False,
                f"Configuration applied but failed to update local state for {agent_key} on {hostname}",
            )

        emit("configure", f"Successfully configured {agent_key}")
        return True, None

    except Exception as e:
        return False, str(e)
    finally:
        # W4 fix: Always clean up artifacts containing secrets (success, failure, or exception)
        _cleanup_ansible_artifacts(operation_log_dir)


def remove_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
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

    target = agent_name or claw_name
    emit("validate", f"Checking {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, agent_type, claw_record = resolved

    # Check if agent is running and stop it first
    runtime = claw_record.get("runtime", {})
    status = runtime.get("status", "stopped")

    if status == "running":
        emit("remove", f"Stopping {agent_key} before removal...")
        try:
            stop_result = stop_agent(
                hostname, claw_name, agent_name=agent_key, on_event=on_event
            )
            if not stop_result["success"]:
                logger.warning(
                    "Failed to stop %s cleanly: %s", agent_key, stop_result["error"]
                )
                emit(
                    "remove",
                    "Warning: Failed to stop cleanly, continuing with removal...",
                )
        except Exception as e:
            logger.warning("Error stopping %s: %s", agent_key, e)
            emit("remove", "Warning: Error stopping, continuing with removal...")

    emit("remove", f"Removing {agent_key} from {hostname}...")

    success, error = _run_lifecycle_playbook(
        agent_type, agent_key, host["hostname"], "remove", host, timeout=120
    )

    if not success:
        return {
            "success": False,
            "agent": agent_key,
            "host": hostname,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": error,
        }

    emit("remove", "Removing from local configuration...")

    # Clean up per-instance secrets (Discord bot token, etc.)
    try:
        unix_agent_name = claw_record.get("agent_name") or agent_key
        instance_key = get_instance_key(host["hostname"], agent_type, unix_agent_name)
        remove_instance_secrets(instance_key)
        emit("remove", "Cleaned up instance secrets")
    except Exception as e:
        logger.warning("Failed to clean up instance secrets for %s: %s", agent_key, e)

    # Clean up agent state directory (skills.json, etc.)
    try:
        unix_agent_name = claw_record.get("agent_name") or agent_key
        cleanup_agent_state(unix_agent_name)
        emit("remove", "Cleaned up agent state directory")
    except Exception as e:
        logger.warning("Failed to clean up agent state for %s: %s", agent_key, e)

    # Remove agent from hosts.json
    # NOTE: remove_agent_from_host returns True if host was found (not if agent was found)
    # An exception here means the local config could not be updated after remote cleanup
    try:
        removed = remove_agent_from_host(host["hostname"], agent_key)
        if not removed:
            # Host not found - this shouldn't happen since we validated it earlier
            logger.error(
                "Host %s not found in configuration after remote cleanup", hostname
            )
            return {
                "success": False,
                "agent": agent_key,
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
            "agent": agent_key,
            "host": hostname,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": f"Remote removal succeeded but local config update failed: {e}. Run 'clm host ps {hostname}' to verify or manually edit hosts.json.",
        }

    emit("remove", f"Removed {agent_key} successfully")

    return {
        "success": True,
        "agent": agent_key,
        "host": hostname,
        "operation": "remove",
        "pid": None,
        "started_at": None,
        "error": None,
    }

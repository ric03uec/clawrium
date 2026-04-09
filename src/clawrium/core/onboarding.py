"""Onboarding state machine for agent instances.

This module manages the onboarding workflow for newly installed agents,
tracking progress through a fixed set of universal stages.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from clawrium.core.hosts import get_host, update_host
from clawrium.core.registry import load_manifest

__all__ = [
    "OnboardingState",
    "StageStatus",
    "TRANSITIONS",
    "get_onboarding_state",
    "transition_state",
    "complete_stage",
    "initialize_onboarding",
    "can_skip_stage",
    "get_stage_tasks",
    "run_stage",
    "InvalidTransitionError",
    "OnboardingNotFoundError",
    "AgentNotFoundError",
]


class OnboardingState(str, Enum):
    """States in the onboarding workflow."""

    PENDING = "pending"  # After install, before onboarding
    PROVIDERS = "providers"  # Configuring inference provider
    IDENTITY = "identity"  # Configuring agent persona
    CHANNELS = "channels"  # Configuring communication
    VALIDATE = "validate"  # Running verification
    READY = "ready"  # Onboarding complete


class StageStatus(str, Enum):
    """Status of an individual onboarding stage."""

    PENDING = "pending"
    COMPLETE = "complete"
    SKIPPED = "skipped"


# Valid state transitions
TRANSITIONS: dict[str, list[str]] = {
    "pending": ["providers"],
    "providers": ["identity"],
    "identity": ["channels"],
    "channels": ["validate"],
    "validate": ["ready", "channels"],  # Fail → back to fix
    "ready": [],
}


class InvalidTransitionError(Exception):
    """Raised when attempting an invalid state transition."""

    pass


class OnboardingNotFoundError(Exception):
    """Raised when onboarding record does not exist for an agent."""

    pass


class AgentNotFoundError(Exception):
    """Raised when agent is not found on the host."""

    pass


def _get_claw_record(host: str, claw_name: str) -> dict | None:
    """Get agent record from host.

    Args:
        host: Hostname or alias
        claw_name: Name of the agent (e.g., "openclaw")

    Returns:
        Agent record dict or None if not found
    """
    host_data = get_host(host)
    if not host_data:
        return None
    claws = host_data.get("claws", {})
    return claws.get(claw_name)


def get_onboarding_state(host: str, claw_name: str) -> OnboardingState:
    """Get current onboarding state for an agent.

    Args:
        host: Hostname or alias
        claw_name: Name of the agent

    Returns:
        Current OnboardingState

    Raises:
        AgentNotFoundError: If agent is not installed on host
        OnboardingNotFoundError: If onboarding has not been initialized
    """
    claw = _get_claw_record(host, claw_name)
    if claw is None:
        raise AgentNotFoundError(f"Agent '{claw_name}' not found on host '{host}'")

    onboarding = claw.get("onboarding")
    if onboarding is None:
        raise OnboardingNotFoundError(
            f"Onboarding not initialized for '{claw_name}' on '{host}'"
        )

    state_value = onboarding.get("state", "pending")
    try:
        return OnboardingState(state_value)
    except ValueError:
        raise OnboardingNotFoundError(
            f"Unknown onboarding state '{state_value}' for '{claw_name}' on '{host}'"
        )


def transition_state(host: str, claw_name: str, to_state: OnboardingState) -> bool:
    """Transition agent to a new onboarding state.

    Validates that the transition is allowed according to TRANSITIONS.

    Args:
        host: Hostname or alias
        claw_name: Name of the agent
        to_state: Target state to transition to

    Returns:
        True if transition succeeded

    Raises:
        AgentNotFoundError: If agent is not installed on host
        OnboardingNotFoundError: If onboarding has not been initialized
        InvalidTransitionError: If transition is not allowed
    """
    current_state = get_onboarding_state(host, claw_name)
    allowed = TRANSITIONS.get(current_state.value, [])

    if to_state.value not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from '{current_state.value}' to '{to_state.value}'. "
            f"Allowed transitions: {allowed}"
        )

    host_data = get_host(host)
    if not host_data:
        raise AgentNotFoundError(f"Host '{host}' not found")

    hostname = host_data["hostname"]

    def updater(h: dict) -> dict:
        h["claws"][claw_name]["onboarding"]["state"] = to_state.value
        return h

    return update_host(hostname, updater)


def complete_stage(
    host: str,
    claw_name: str,
    stage: str,
    status: StageStatus,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Mark an onboarding stage as complete or skipped.

    Args:
        host: Hostname or alias
        claw_name: Name of the agent
        stage: Stage name (providers, identity, channels, validate)
        status: Status to set (complete or skipped)
        metadata: Optional metadata to store with the stage

    Returns:
        True if update succeeded

    Raises:
        AgentNotFoundError: If agent is not installed on host
        OnboardingNotFoundError: If onboarding has not been initialized
        ValueError: If stage is not a valid stage name
        InvalidTransitionError: If completing this stage is not permitted in current state
    """
    valid_stages = {"providers", "identity", "channels", "validate"}
    if stage not in valid_stages:
        raise ValueError(f"Invalid stage '{stage}'. Valid stages: {valid_stages}")

    claw = _get_claw_record(host, claw_name)
    if claw is None:
        raise AgentNotFoundError(f"Agent '{claw_name}' not found on host '{host}'")

    onboarding = claw.get("onboarding")
    if onboarding is None:
        raise OnboardingNotFoundError(
            f"Onboarding not initialized for '{claw_name}' on '{host}'"
        )

    # Verify current state permits completing this stage
    # Skip validation for SKIPPED status (stages can be skipped at any time)
    if status != StageStatus.SKIPPED:
        # State-to-stage mapping: current state -> stages that can be completed
        # States represent "currently working on" so a state can complete its own stage
        state_to_allowed_stages = {
            "pending": ["providers"],  # Can start providers from pending
            "providers": [
                "providers"
            ],  # Can complete providers while in providers state
            "identity": ["identity"],  # Can complete identity while in identity state
            "channels": ["channels"],  # Can complete channels while in channels state
            "validate": ["validate"],  # Can complete validate while in validate state
            "ready": ["providers", "identity", "channels", "validate"],  # Allow reconfiguration when ready
        }

        current_state = get_onboarding_state(host, claw_name)
        allowed_stages = state_to_allowed_stages.get(current_state.value, [])

        if stage not in allowed_stages:
            raise InvalidTransitionError(
                f"Cannot complete stage '{stage}' while in state '{current_state.value}'. "
                f"Allowed stages in this state: {allowed_stages}"
            )

    host_data = get_host(host)
    if not host_data:
        raise AgentNotFoundError(f"Host '{host}' not found")

    hostname = host_data["hostname"]
    now = datetime.now(timezone.utc).isoformat()

    def updater(h: dict) -> dict:
        stage_data = h["claws"][claw_name]["onboarding"]["stages"][stage]
        stage_data["status"] = status.value
        stage_data["completed_at"] = now
        if metadata:
            for key, value in metadata.items():
                stage_data[key] = value
        return h

    return update_host(hostname, updater)


def initialize_onboarding(host: str, claw_name: str) -> bool:
    """Initialize onboarding record for an agent.

    Creates the onboarding data structure with state=PENDING and all
    stages initialized to pending status.

    Args:
        host: Hostname or alias
        claw_name: Name of the agent

    Returns:
        True if initialization succeeded

    Raises:
        AgentNotFoundError: If agent is not installed on host
    """
    claw = _get_claw_record(host, claw_name)
    if claw is None:
        raise AgentNotFoundError(f"Agent '{claw_name}' not found on host '{host}'")

    host_data = get_host(host)
    if not host_data:
        raise AgentNotFoundError(f"Host '{host}' not found")

    hostname = host_data["hostname"]
    now = datetime.now(timezone.utc).isoformat()

    def updater(h: dict) -> dict:
        h["claws"][claw_name]["onboarding"] = {
            "state": OnboardingState.PENDING.value,
            "started_at": now,
            "stages": {
                "providers": {
                    "status": StageStatus.PENDING.value,
                    "completed_at": None,
                    "provider_id": None,
                },
                "identity": {"status": StageStatus.PENDING.value, "completed_at": None},
                "channels": {"status": StageStatus.PENDING.value, "completed_at": None},
                "validate": {"status": StageStatus.PENDING.value, "completed_at": None},
            },
        }
        return h

    return update_host(hostname, updater)


def can_skip_stage(agent_type: str, stage: str) -> bool:
    """Check if a stage can be auto-skipped for an agent type.

    Some agent types may not need certain stages (e.g., an agent without
    communication features doesn't need the channels stage).

    Args:
        agent_type: Type of agent (e.g., "openclaw", "zeroclaw")
        stage: Stage name to check

    Returns:
        True if the stage can be skipped for this agent type
    """
    try:
        manifest = load_manifest(agent_type)
    except Exception:
        return False

    # Check if manifest has skip_stages configuration
    skip_stages = manifest.get("skip_stages", [])
    return stage in skip_stages


def get_stage_tasks(agent_type: str, stage: str) -> list[dict]:
    """Get tasks for a stage from the agent manifest.

    Args:
        agent_type: Type of agent (e.g., "openclaw", "zeroclaw")
        stage: Stage name

    Returns:
        List of task dictionaries for the stage. Empty list if no tasks defined.
    """
    try:
        manifest = load_manifest(agent_type)
    except Exception:
        return []

    # Check if manifest has onboarding.stages configuration
    onboarding_config = manifest.get("onboarding", {})
    stages_config = onboarding_config.get("stages", {})
    stage_config = stages_config.get(stage, {})

    return stage_config.get("tasks", [])


def run_stage(agent_type: str, host: str, claw_name: str, stage: str) -> bool:
    """Execute tasks for an onboarding stage.

    This is a placeholder for stage execution logic. In practice, this would:
    1. Get tasks from manifest
    2. Execute each task (possibly via Ansible)
    3. Update stage status

    Args:
        agent_type: Type of agent (e.g., "openclaw", "zeroclaw")
        host: Hostname or alias
        claw_name: Name of the agent instance
        stage: Stage name to execute

    Returns:
        True if stage completed successfully
    """
    # Check if stage can be skipped
    if can_skip_stage(agent_type, stage):
        complete_stage(host, claw_name, stage, StageStatus.SKIPPED)
        return True

    # Get tasks for this stage
    tasks = get_stage_tasks(agent_type, stage)

    if not tasks:
        # No tasks defined - mark as complete
        complete_stage(host, claw_name, stage, StageStatus.COMPLETE)
        return True

    # Execute tasks (placeholder - actual implementation would run Ansible or similar)
    # For now, we just mark the stage as complete
    # Future implementation will iterate through tasks and execute them
    complete_stage(host, claw_name, stage, StageStatus.COMPLETE)
    return True

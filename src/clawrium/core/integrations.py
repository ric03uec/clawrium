"""Integration storage operations for Clawrium.

Integrations are external services that agents can connect to for
enhanced functionality (e.g., GitHub for code review, Atlassian (Jira +
Confluence) for project tracking and docs).
"""

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from typing import Callable

from clawrium.core.config import get_config_dir, init_config_dir

__all__ = [
    "INTEGRATIONS_FILE",
    "INTEGRATION_TYPES",
    "load_integrations",
    "save_integrations",
    "add_integration",
    "get_integration",
    "update_integration",
    "remove_integration",
    "validate_integration_name",
    "validate_integration_type",
    "get_credentials_for_type",
    "get_integration_instance_key",
    "set_integration_credential",
    "get_integration_credentials",
    "remove_integration_credentials",
    "get_agent_integrations",
    "set_agent_integrations",
    "add_agent_integration",
    "remove_agent_integration",
    "find_agents_using_integration",
    "IntegrationsFileCorruptedError",
    "DuplicateIntegrationError",
    "InvalidIntegrationTypeError",
    "InvalidIntegrationNameError",
    "IntegrationInUseError",
]

INTEGRATIONS_FILE = "integrations.json"

# Integration name pattern: starts with letter, alphanumeric/underscore/hyphen, 1-64 chars
INTEGRATION_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

# Supported integration types with their credential requirements
INTEGRATION_TYPES: dict[str, dict] = {
    "github": {
        "description": "GitHub for code hosting, PRs, and issues",
        "credentials": [
            {
                "key": "GITHUB_TOKEN",
                "description": "Personal access token or fine-grained token",
                "required": True,
            },
        ],
    },
    "gitlab": {
        "description": "GitLab for code hosting, MRs, and issues",
        "credentials": [
            {
                "key": "GITLAB_TOKEN",
                "description": "Personal access token",
                "required": True,
            },
            {
                "key": "GITLAB_URL",
                "description": "GitLab instance URL (defaults to gitlab.com)",
                "required": False,
            },
        ],
    },
    "atlassian": {
        "description": "Atlassian Cloud (Jira + Confluence) via API token",
        "credentials": [
            {
                "key": "ATLASSIAN_URL",
                "description": "Atlassian instance URL (e.g., https://company.atlassian.net)",
                "required": True,
            },
            {
                "key": "ATLASSIAN_EMAIL",
                "description": "Account email for authentication",
                "required": True,
            },
            {
                "key": "ATLASSIAN_API_TOKEN",
                "description": "API token (create at https://id.atlassian.com/manage-profile/security/api-tokens)",
                "required": True,
            },
            {
                "key": "CONFLUENCE_SPACES_FILTER",
                "description": "Comma-separated Confluence space keys to filter (optional)",
                "required": False,
            },
            {
                "key": "JIRA_PROJECTS_FILTER",
                "description": "Comma-separated Jira project keys to filter (optional)",
                "required": False,
            },
        ],
    },
    "linear": {
        "description": "Linear for issue tracking and project management",
        "credentials": [
            {
                "key": "LINEAR_API_KEY",
                "description": "Linear API key",
                "required": True,
            },
        ],
    },
    "notion": {
        "description": "Notion for documentation and workspace management",
        "credentials": [
            {
                "key": "NOTION_API_KEY",
                "description": "Notion integration token",
                "required": True,
            },
        ],
    },
}


class IntegrationsFileCorruptedError(Exception):
    """Raised when integrations.json cannot be parsed."""

    pass


class DuplicateIntegrationError(Exception):
    """Raised when trying to add an integration that already exists."""

    pass


class InvalidIntegrationTypeError(Exception):
    """Raised when an invalid integration type is specified."""

    pass


class InvalidIntegrationNameError(Exception):
    """Raised when an invalid integration name is specified."""

    pass


class IntegrationInUseError(Exception):
    """Raised when trying to remove an integration that is assigned to agents."""

    pass


def validate_integration_name(name: str | None) -> None:
    """Validate integration name format.

    Args:
        name: Integration name to validate.

    Raises:
        InvalidIntegrationNameError: If name is None or doesn't match pattern.
    """
    if not isinstance(name, str):
        raise InvalidIntegrationNameError("Integration name must be a string")

    if not INTEGRATION_NAME_PATTERN.match(name):
        raise InvalidIntegrationNameError(
            f"Invalid integration name '{name}'. "
            "Must start with a letter, contain only alphanumeric characters, "
            "underscores, or hyphens, and be 1-64 characters long."
        )


def validate_integration_type(integration_type: str) -> None:
    """Validate integration type.

    Args:
        integration_type: Integration type to validate.

    Raises:
        InvalidIntegrationTypeError: If type is not in INTEGRATION_TYPES.
    """
    if integration_type not in INTEGRATION_TYPES:
        valid_types = ", ".join(sorted(INTEGRATION_TYPES.keys()))
        raise InvalidIntegrationTypeError(
            f"Invalid integration type '{integration_type}'. Valid types: {valid_types}"
        )


def get_credentials_for_type(integration_type: str) -> list[dict]:
    """Get required credentials for an integration type.

    Args:
        integration_type: Integration type to get credentials for.

    Returns:
        List of credential definitions.

    Raises:
        InvalidIntegrationTypeError: If type is not valid.
    """
    validate_integration_type(integration_type)
    return INTEGRATION_TYPES[integration_type]["credentials"]


# Integration credential storage using secrets module


def get_integration_instance_key(integration_name: str) -> str:
    """Generate secrets instance key for an integration.

    Args:
        integration_name: Name of the integration.

    Returns:
        Instance key in format "integration:{name}".
    """
    return f"integration:{integration_name}"


def set_integration_credential(
    integration_name: str, key: str, value: str, description: str = ""
) -> bool:
    """Store a credential for an integration securely.

    Uses the secrets module to store the credential.

    Args:
        integration_name: Name of the integration.
        key: Credential key (e.g., GITHUB_TOKEN).
        value: Credential value to store.
        description: Optional description for the credential.

    Returns:
        True if new secret created, False if existing secret updated.
    """
    from clawrium.core.secrets import set_instance_secret

    instance_key = get_integration_instance_key(integration_name)
    return set_instance_secret(
        instance_key,
        key,
        value,
        description=description or f"{key} for integration {integration_name}",
    )


def get_integration_credentials(integration_name: str) -> dict[str, str]:
    """Retrieve all credentials for an integration.

    Args:
        integration_name: Name of the integration.

    Returns:
        Dict mapping credential keys to their values.
    """
    from clawrium.core.secrets import get_instance_secrets

    instance_key = get_integration_instance_key(integration_name)
    secrets = get_instance_secrets(instance_key)
    return {key: entry["value"] for key, entry in secrets.items()}


def remove_integration_credentials(integration_name: str) -> bool:
    """Remove all credentials for an integration.

    Args:
        integration_name: Name of the integration.

    Returns:
        True if any credentials were removed, False otherwise.
    """
    from clawrium.core.secrets import remove_instance_secrets

    instance_key = get_integration_instance_key(integration_name)
    return remove_instance_secrets(instance_key)


def load_integrations() -> list[dict]:
    """Load integrations from JSON file.

    Returns:
        List of integration dictionaries. Empty list if file doesn't exist.

    Raises:
        IntegrationsFileCorruptedError: If integrations.json exists but cannot be parsed.
    """
    integrations_path = get_config_dir() / INTEGRATIONS_FILE
    if not integrations_path.exists():
        return []

    try:
        with open(integrations_path) as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise IntegrationsFileCorruptedError(
                    f"integrations.json is not a list: {integrations_path}"
                )
            if not all(isinstance(i, dict) for i in data):
                raise IntegrationsFileCorruptedError(
                    f"integrations.json contains invalid entries (expected list of objects): {integrations_path}"
                )
            return data
    except json.JSONDecodeError as e:
        raise IntegrationsFileCorruptedError(
            f"integrations.json is corrupted: {e}. "
            f"Backup the file and delete it to recover: {integrations_path}"
        ) from e


@contextmanager
def _integrations_lock():
    """Context manager for exclusive access to integrations.json.

    Uses fcntl.flock for advisory locking to prevent TOCTOU races
    when multiple processes try to modify integrations.json concurrently.
    """
    config_dir = init_config_dir()
    lock_path = config_dir / ".integrations.lock"

    # Create lock file if it doesn't exist
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _save_integrations_atomic(integrations: list[dict], config_dir) -> None:
    """Internal: Write integrations atomically without acquiring lock.

    This function performs the atomic write (temp file + rename).
    Caller MUST hold the _integrations_lock().

    Args:
        integrations: List of integration dictionaries.
        config_dir: Path to config directory.
    """
    integrations_path = config_dir / INTEGRATIONS_FILE
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
    try:
        # Set restrictive permissions on temp file before writing (survives rename)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(integrations, f, indent=2)
        os.replace(tmp_path, integrations_path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_integrations(integrations: list[dict]) -> None:
    """Save integrations to JSON file atomically with file locking.

    Creates config directory if it doesn't exist.
    Uses atomic write (temp file + rename) to prevent data loss on crash.
    Uses fcntl.flock to prevent concurrent write races.

    Args:
        integrations: List of integration dictionaries to save.
    """
    # Ensure config directory exists
    config_dir = init_config_dir()

    with _integrations_lock():
        _save_integrations_atomic(integrations, config_dir)


def add_integration(integration: dict) -> None:
    """Add an integration to the registry atomically.

    Acquires exclusive lock for the entire load-modify-save operation
    to prevent TOCTOU races from concurrent add_integration calls.

    Args:
        integration: Integration dictionary to add. Must have 'name' and 'type' keys.

    Raises:
        DuplicateIntegrationError: If integration name already exists.
        InvalidIntegrationNameError: If integration name is invalid.
        InvalidIntegrationTypeError: If integration type is invalid.
    """
    name = integration.get("name")
    validate_integration_name(name)

    integration_type = integration.get("type")
    if integration_type:
        validate_integration_type(integration_type)

    with _integrations_lock():
        integrations = load_integrations()

        # Check for duplicate
        for existing in integrations:
            if existing.get("name") == name:
                raise DuplicateIntegrationError(f"Integration '{name}' already exists")

        integrations.append(integration)

        # Save without re-acquiring lock
        config_dir = init_config_dir()
        _save_integrations_atomic(integrations, config_dir)


def get_integration(name: str) -> dict | None:
    """Get an integration by name.

    Args:
        name: Integration name to search for.

    Returns:
        Integration dictionary if found, None otherwise.
    """
    integrations = load_integrations()
    for integration in integrations:
        if integration.get("name") == name:
            return integration
    return None


def update_integration(name: str, updater: Callable[[dict], dict]) -> bool:
    """Atomically update an integration record.

    Acquires exclusive lock, loads integrations, applies updater function,
    and saves in a single atomic operation. Prevents TOCTOU races.

    Args:
        name: The name of the integration to update.
        updater: Function that takes integration dict and returns updated dict.

    Returns:
        True if integration was found and updated, False if not found.
    """
    with _integrations_lock():
        integrations = load_integrations()
        found = False
        for i, integration in enumerate(integrations):
            if integration.get("name") == name:
                integrations[i] = updater(integration)
                found = True
                break

        if found:
            # Save without re-acquiring lock (we already hold it)
            config_dir = init_config_dir()
            _save_integrations_atomic(integrations, config_dir)

        return found


def find_agents_using_integration(integration_name: str) -> list[tuple[str, str]]:
    """Find all agents that have a specific integration assigned.

    Args:
        integration_name: Name of the integration to search for.

    Returns:
        List of (hostname, agent_key) tuples for agents using this integration.
    """
    from clawrium.core.hosts import load_hosts

    hosts = load_hosts()
    results = []

    for host in hosts:
        hostname = host.get("hostname", "")
        agents = host.get("agents", {})

        for agent_key, agent_data in agents.items():
            if not isinstance(agent_data, dict):
                continue

            # Check dedicated 'integrations' field
            integrations = agent_data.get("integrations", [])
            if isinstance(integrations, list) and integration_name in integrations:
                results.append((hostname, agent_key))

    return results


def remove_integration(name: str, force: bool = False) -> bool:
    """Remove an integration by name atomically.

    Acquires exclusive lock for the entire load-modify-save operation
    to prevent TOCTOU races from concurrent remove_integration calls.
    Also removes all stored credentials for the integration.

    By default, refuses to remove integrations that are assigned to agents.
    Use force=True to remove the integration anyway (leaves dangling refs).

    Args:
        name: The integration name to remove.
        force: If True, remove even if assigned to agents.

    Returns:
        True if integration was found and removed, False otherwise.

    Raises:
        IntegrationInUseError: If integration is assigned to agents and force=False.
    """
    with _integrations_lock():
        # Check if integration is in use INSIDE lock to prevent TOCTOU race
        # where concurrent add_agent_integration could assign between check and delete
        if not force:
            agents_using = find_agents_using_integration(name)
            if agents_using:
                agent_list = ", ".join(f"{h}:{a}" for h, a in agents_using[:3])
                if len(agents_using) > 3:
                    agent_list += f" and {len(agents_using) - 3} more"
                raise IntegrationInUseError(
                    f"Integration '{name}' is assigned to agents: {agent_list}. "
                    "Remove from agents first or use force=True."
                )

        integrations = load_integrations()
        filtered = [i for i in integrations if i.get("name") != name]

        if len(filtered) == len(integrations):
            # No integration was removed
            return False

        # Save without re-acquiring lock
        config_dir = init_config_dir()
        _save_integrations_atomic(filtered, config_dir)

    # Remove credentials (outside lock since secrets has its own locking)
    remove_integration_credentials(name)

    return True


# Agent integration assignment functions


def get_agent_integrations(host: str, agent_key: str) -> list[str]:
    """Get list of integrations assigned to an agent.

    Integrations are stored in a dedicated field (agent.integrations) to avoid
    conflicts with agent.config which is managed by configure_agent.

    Args:
        host: Hostname or alias.
        agent_key: Agent instance key (e.g., 'clever-einstein'), not agent type.

    Returns:
        List of integration names assigned to the agent.
    """
    from clawrium.core.hosts import get_host

    host_data = get_host(host)
    if not host_data:
        return []

    agents = host_data.get("agents", {})
    if agent_key not in agents:
        return []

    agent_data = agents[agent_key]
    if not isinstance(agent_data, dict):
        return []

    # Use dedicated 'integrations' field (not inside 'config')
    integrations = agent_data.get("integrations", [])

    if not isinstance(integrations, list):
        return []

    return integrations


def set_agent_integrations(host: str, agent_key: str, integrations: list[str]) -> bool:
    """Set the list of integrations assigned to an agent.

    Integrations are stored in a dedicated field (agent.integrations) to avoid
    conflicts with agent.config which is managed by configure_agent.

    Args:
        host: Hostname or alias.
        agent_key: Agent instance key (e.g., 'clever-einstein'), not agent type.
        integrations: List of integration names to assign.

    Returns:
        True if update succeeded, False otherwise.
    """
    from clawrium.core.hosts import get_host, update_host

    host_data = get_host(host)
    if not host_data:
        return False

    hostname = host_data["hostname"]

    def updater(h: dict) -> dict:
        agents = h.get("agents", {})
        if agent_key not in agents:
            return h

        agent_data = agents[agent_key]
        if not isinstance(agent_data, dict):
            return h

        # Use dedicated 'integrations' field (not inside 'config')
        agent_data["integrations"] = integrations
        return h

    return update_host(hostname, updater)


def add_agent_integration(host: str, claw_name: str, integration_name: str) -> bool:
    """Add an integration to an agent atomically.

    Performs read-modify-write within a single update_host call to prevent
    TOCTOU races from concurrent operations.

    Integrations are stored in a dedicated field (agent.integrations) to avoid
    conflicts with agent.config which is managed by configure_agent.

    Args:
        host: Hostname or alias.
        claw_name: Agent instance name.
        integration_name: Name of integration to add.

    Returns:
        True if integration was added, False if already exists or update failed.
    """
    from clawrium.core.hosts import get_host, update_host

    host_data = get_host(host)
    if not host_data:
        return False

    hostname = host_data["hostname"]
    added = False

    def updater(h: dict) -> dict:
        nonlocal added
        agents = h.get("agents", {})
        if claw_name not in agents:
            return h

        agent_data = agents[claw_name]
        if not isinstance(agent_data, dict):
            return h

        # Use dedicated 'integrations' field (not inside 'config')
        current = agent_data.get("integrations", [])
        if not isinstance(current, list):
            current = []

        if integration_name in current:
            return h  # Already exists

        current.append(integration_name)
        agent_data["integrations"] = current
        added = True
        return h

    update_host(hostname, updater)
    return added


def remove_agent_integration(host: str, claw_name: str, integration_name: str) -> bool:
    """Remove an integration from an agent atomically.

    Performs read-modify-write within a single update_host call to prevent
    TOCTOU races from concurrent operations.

    Integrations are stored in a dedicated field (agent.integrations) to avoid
    conflicts with agent.config which is managed by configure_agent.

    Args:
        host: Hostname or alias.
        claw_name: Agent instance name.
        integration_name: Name of integration to remove.

    Returns:
        True if integration was removed, False if not found or update failed.
    """
    from clawrium.core.hosts import get_host, update_host

    host_data = get_host(host)
    if not host_data:
        return False

    hostname = host_data["hostname"]
    removed = False

    def updater(h: dict) -> dict:
        nonlocal removed
        agents = h.get("agents", {})
        if claw_name not in agents:
            return h

        agent_data = agents[claw_name]
        if not isinstance(agent_data, dict):
            return h

        # Use dedicated 'integrations' field (not inside 'config')
        current = agent_data.get("integrations", [])
        if not isinstance(current, list):
            return h

        if integration_name not in current:
            return h  # Not found

        current.remove(integration_name)
        agent_data["integrations"] = current
        removed = True
        return h

    update_host(hostname, updater)
    return removed

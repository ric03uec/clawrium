"""Host storage operations for Clawrium."""

import json
from pathlib import Path
from clawrium.core.config import get_config_dir, init_config_dir

__all__ = ["load_hosts", "save_hosts", "add_host", "remove_host", "get_host", "HOSTS_FILE"]

HOSTS_FILE = "hosts.json"


def load_hosts() -> list[dict]:
    """Load hosts from JSON file.

    Returns:
        List of host dictionaries. Empty list if file doesn't exist.
    """
    hosts_path = get_config_dir() / HOSTS_FILE
    if not hosts_path.exists():
        return []

    with open(hosts_path) as f:
        return json.load(f)


def save_hosts(hosts: list[dict]) -> None:
    """Save hosts to JSON file.

    Creates config directory if it doesn't exist.

    Args:
        hosts: List of host dictionaries to save.
    """
    # Ensure config directory exists
    config_dir = init_config_dir()
    hosts_path = config_dir / HOSTS_FILE

    with open(hosts_path, 'w') as f:
        json.dump(hosts, f, indent=2)


def add_host(host: dict) -> None:
    """Add a host to the registry.

    Args:
        host: Host dictionary to add.
    """
    hosts = load_hosts()
    hosts.append(host)
    save_hosts(hosts)


def remove_host(hostname: str) -> bool:
    """Remove a host by hostname.

    Args:
        hostname: The hostname to remove.

    Returns:
        True if host was found and removed, False otherwise.
    """
    hosts = load_hosts()
    filtered = [h for h in hosts if h["hostname"] != hostname]

    if len(filtered) == len(hosts):
        # No host was removed
        return False

    save_hosts(filtered)
    return True


def get_host(identifier: str) -> dict | None:
    """Get a host by hostname or alias.

    Args:
        identifier: Hostname or alias to search for.

    Returns:
        Host dictionary if found, None otherwise.
    """
    hosts = load_hosts()
    for host in hosts:
        if host["hostname"] == identifier:
            return host
        if host.get("alias") == identifier:
            return host
    return None

"""Host storage operations for Clawrium."""

import json
import os
import tempfile
from pathlib import Path
from clawrium.core.config import get_config_dir, init_config_dir

__all__ = ["load_hosts", "save_hosts", "add_host", "remove_host", "get_host", "HOSTS_FILE"]

HOSTS_FILE = "hosts.json"


class HostsFileCorruptedError(Exception):
    """Raised when hosts.json cannot be parsed."""
    pass


def load_hosts() -> list[dict]:
    """Load hosts from JSON file.

    Returns:
        List of host dictionaries. Empty list if file doesn't exist.

    Raises:
        HostsFileCorruptedError: If hosts.json exists but cannot be parsed.
    """
    hosts_path = get_config_dir() / HOSTS_FILE
    if not hosts_path.exists():
        return []

    try:
        with open(hosts_path) as f:
            data = json.load(f)
            # Validate it's a list
            if not isinstance(data, list):
                raise HostsFileCorruptedError(
                    f"hosts.json is not a list: {hosts_path}"
                )
            return data
    except json.JSONDecodeError as e:
        raise HostsFileCorruptedError(
            f"hosts.json is corrupted: {e}. "
            f"Backup the file and delete it to recover: {hosts_path}"
        ) from e


def save_hosts(hosts: list[dict]) -> None:
    """Save hosts to JSON file atomically.

    Creates config directory if it doesn't exist.
    Uses atomic write (temp file + rename) to prevent data loss on crash.

    Args:
        hosts: List of host dictionaries to save.
    """
    # Ensure config directory exists
    config_dir = init_config_dir()
    hosts_path = config_dir / HOSTS_FILE

    # Atomic write: write to temp file, then rename (atomic on POSIX)
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(hosts, f, indent=2)
        os.replace(tmp_path, hosts_path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
    filtered = [h for h in hosts if h.get("hostname") != hostname]

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
        if host.get("hostname") == identifier:
            return host
        if host.get("alias") == identifier:
            return host
    return None

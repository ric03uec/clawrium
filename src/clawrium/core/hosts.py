"""Host storage operations for Clawrium."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from typing import Callable

from clawrium.core.config import get_config_dir, init_config_dir

__all__ = [
    "load_hosts",
    "save_hosts",
    "add_host",
    "remove_host",
    "get_host",
    "get_host_by_key_id",
    "update_host",
    "remove_claw_from_host",
    "HOSTS_FILE",
    "HostsFileCorruptedError",
    "DuplicateHostError",
]

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
            # Validate it's a list of dicts
            if not isinstance(data, list):
                raise HostsFileCorruptedError(f"hosts.json is not a list: {hosts_path}")
            if not all(isinstance(h, dict) for h in data):
                raise HostsFileCorruptedError(
                    f"hosts.json contains invalid entries (expected list of objects): {hosts_path}"
                )
            return data
    except json.JSONDecodeError as e:
        raise HostsFileCorruptedError(
            f"hosts.json is corrupted: {e}. "
            f"Backup the file and delete it to recover: {hosts_path}"
        ) from e


@contextmanager
def _hosts_lock():
    """Context manager for exclusive access to hosts.json.

    Uses fcntl.flock for advisory locking to prevent TOCTOU races
    when multiple processes try to modify hosts.json concurrently.
    """
    config_dir = init_config_dir()
    lock_path = config_dir / ".hosts.lock"

    # Create lock file if it doesn't exist
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def save_hosts(hosts: list[dict]) -> None:
    """Save hosts to JSON file atomically with file locking.

    Creates config directory if it doesn't exist.
    Uses atomic write (temp file + rename) to prevent data loss on crash.
    Uses fcntl.flock to prevent concurrent write races.

    Args:
        hosts: List of host dictionaries to save.
    """
    # Ensure config directory exists
    config_dir = init_config_dir()
    hosts_path = config_dir / HOSTS_FILE

    with _hosts_lock():
        # Atomic write: write to temp file, then rename (atomic on POSIX)
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            # Set restrictive permissions on temp file before writing (survives rename)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(hosts, f, indent=2)
            os.replace(tmp_path, hosts_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def update_host(hostname: str, updater: Callable[[dict], dict]) -> bool:
    """Atomically update a host record.

    Acquires exclusive lock, loads hosts, applies updater function,
    and saves in a single atomic operation. Prevents TOCTOU races.

    Args:
        hostname: The hostname of the host to update.
        updater: Function that takes host dict and returns updated host dict.

    Returns:
        True if host was found and updated, False if not found.
    """
    with _hosts_lock():
        hosts = load_hosts()
        found = False
        for i, host in enumerate(hosts):
            if host.get("hostname") == hostname:
                hosts[i] = updater(host)
                found = True
                break

        if found:
            # Save without re-acquiring lock (we already hold it)
            config_dir = init_config_dir()
            hosts_path = config_dir / HOSTS_FILE
            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(hosts, f, indent=2)
                os.replace(tmp_path, hosts_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        return found


class DuplicateHostError(Exception):
    """Raised when trying to add a host that already exists."""

    pass


def add_host(host: dict) -> None:
    """Add a host to the registry atomically.

    Acquires exclusive lock for the entire load-modify-save operation
    to prevent TOCTOU races from concurrent add_host calls.

    Args:
        host: Host dictionary to add.

    Raises:
        DuplicateHostError: If hostname already exists in registry.
    """
    hostname = host.get("hostname")
    with _hosts_lock():
        hosts = load_hosts()

        # Check for duplicate
        for existing in hosts:
            if existing.get("hostname") == hostname:
                raise DuplicateHostError(f"Host '{hostname}' already exists")

        hosts.append(host)

        # Save without re-acquiring lock
        config_dir = init_config_dir()
        hosts_path = config_dir / HOSTS_FILE
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(hosts, f, indent=2)
            os.replace(tmp_path, hosts_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def remove_host(hostname: str) -> bool:
    """Remove a host by hostname atomically.

    Acquires exclusive lock for the entire load-modify-save operation
    to prevent TOCTOU races from concurrent remove_host calls.

    Args:
        hostname: The hostname to remove.

    Returns:
        True if host was found and removed, False otherwise.
    """
    with _hosts_lock():
        hosts = load_hosts()
        filtered = [h for h in hosts if h.get("hostname") != hostname]

        if len(filtered) == len(hosts):
            # No host was removed
            return False

        # Save without re-acquiring lock
        config_dir = init_config_dir()
        hosts_path = config_dir / HOSTS_FILE
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(filtered, f, indent=2)
            os.replace(tmp_path, hosts_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

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


def get_host_by_key_id(key_id: str) -> dict | None:
    """Get a host by its key_id.

    Args:
        key_id: Key identifier to search for.

    Returns:
        Host dictionary if found, None otherwise.
    """
    hosts = load_hosts()
    for host in hosts:
        if host.get("key_id") == key_id:
            return host
    return None


def remove_claw_from_host(hostname: str, claw_name: str) -> bool:
    """Remove a claw from a host's record atomically.

    Acquires exclusive lock for the entire load-modify-save operation
    to prevent TOCTOU races from concurrent operations.

    Args:
        hostname: The hostname of the host.
        claw_name: Name of the claw to remove.

    Returns:
        True if claw was found and removed, False if not found.
    """

    def updater(h: dict) -> dict:
        if "claws" in h and claw_name in h["claws"]:
            del h["claws"][claw_name]
        return h

    return update_host(hostname, updater)

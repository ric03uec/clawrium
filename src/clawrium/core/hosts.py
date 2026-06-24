"""Host storage operations for Clawrium."""

import fcntl
import ipaddress
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
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
    "remove_agent_from_host",
    "get_agent_by_name",
    "alias_exists",
    "add_address_to_host",
    "remove_address_from_host",
    "set_primary_address",
    "get_host_addresses",
    "HOSTS_FILE",
    "HostsFileCorruptedError",
    "DuplicateHostError",
    "AddressError",
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
        HostsFileCorruptedError: If hosts.json exists but cannot be parsed or uses old schema.
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

            # Detect old schema format and provide migration guidance
            for host in data:
                if "claws" in host:
                    raise HostsFileCorruptedError(
                        f"hosts.json uses old schema format (found 'claws' key). "
                        f"This version requires the new schema format. "
                        f"Migration required: Remove all existing agents and reinstall them. "
                        f"See CHANGELOG for breaking changes: {hosts_path}"
                    )

            # Migrate hosts to addresses format if needed
            return [
                _prune_agent_config_mirror(
                    _apply_legacy_defaults(_ensure_addresses(host))
                )
                for host in data
            ]
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


class AddressError(Exception):
    """Raised for address operation failures."""

    pass


def _validate_address(address: str) -> None:
    """Validate address format for security and correctness.

    Args:
        address: The address string to validate.

    Raises:
        AddressError: If address format is invalid or contains dangerous characters.
    """
    if not address or not address.strip():
        raise AddressError("Address cannot be empty")

    address = address.strip()

    # Reject shell metacharacters and control characters
    dangerous_chars = r"[|&;$`\'\"\\<>(){}!\n\r\t\x00-\x1f]"
    if re.search(dangerous_chars, address):
        raise AddressError(
            "Address contains invalid characters. "
            "Use only alphanumeric characters, dots, hyphens, and colons."
        )

    # Reject user prefix (@)
    if "@" in address:
        raise AddressError(
            "Address cannot contain '@'. Specify user with --user flag instead."
        )

    # Try to parse as IP address first
    try:
        ipaddress.ip_address(address)
        return  # Valid IP address
    except ValueError:
        pass

    # Try to parse as IP network (for CIDR notation rejection)
    if "/" in address:
        raise AddressError(
            "Address cannot contain '/'. Use IP address or hostname without CIDR notation."
        )

    # Validate as hostname (RFC 1123 compliant)
    # Allow: alphanumeric, hyphens, dots; max 253 chars total, 63 per label
    if len(address) > 253:
        raise AddressError("Address is too long (max 253 characters)")

    hostname_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
    if not re.match(hostname_pattern, address):
        raise AddressError(
            "Invalid address format. Must be a valid IP address or hostname. "
            "Hostnames can only contain alphanumeric characters, dots, and hyphens."
        )


def _ensure_addresses(host: dict) -> dict:
    """Migrate host to addresses format if needed.

    If the host doesn't have an 'addresses' field, creates it from
    the 'hostname' field with is_primary=True.

    Args:
        host: Host dictionary to migrate.

    Returns:
        Modified host dictionary with addresses field.
    """
    if "addresses" not in host:
        hostname = host.get("hostname", "")
        if hostname:
            host["addresses"] = [
                {
                    "address": hostname,
                    "is_primary": True,
                    "label": None,
                    "added_at": host.get("metadata", {}).get(
                        "added_at", datetime.now(timezone.utc).isoformat()
                    ),
                }
            ]
        else:
            host["addresses"] = []
    return host


_PRUNED_AGENT_CONFIG_KEYS = frozenset({"provider", "providers", "channels"})
_PRESERVED_AGENT_CONFIG_KEYS = frozenset({"gateway", "dashboard", "api_server"})

# Group B keys hold canonical on-disk state (bearer tokens, ports); a
# future maintainer widening _PRUNED_AGENT_CONFIG_KEYS into Group B
# would silently wipe them on every load. Trip at import time instead.
# Use `raise` rather than `assert` — `assert` is stripped under `python
# -O` / `PYTHONOPTIMIZE=1`, which would defeat the guard.
if _PRUNED_AGENT_CONFIG_KEYS & _PRESERVED_AGENT_CONFIG_KEYS:
    raise RuntimeError("Group B keys must never appear in _PRUNED_AGENT_CONFIG_KEYS")


def _prune_agent_config_mirror(host: dict) -> dict:
    """Strip the legacy `config.provider/providers/channels` mirror.

    These keys were a stale denormalized copy of canonical state held in
    `providers.json` (provider attachments) and `channels.json` (channel
    attachments). #794 stopped writing them; this strips any residue
    from `hosts.json` files written before that change so the file
    shrinks naturally on the next save round-trip. `config.gateway`,
    `config.dashboard`, and `config.api_server` (Group B) are
    canonically stored on disk and MUST be preserved.
    """
    agents = host.get("agents")
    if not isinstance(agents, dict):
        return host
    for record in agents.values():
        if not isinstance(record, dict):
            continue
        config = record.get("config")
        if not isinstance(config, dict):
            continue
        for key in _PRUNED_AGENT_CONFIG_KEYS:
            config.pop(key, None)
    return host


def _apply_legacy_defaults(host: dict) -> dict:
    """Backfill fields that may be missing on hosts registered before they existed.

    Currently this is just `os_family`: every host registered before macOS
    support landed is assumed to be Linux. New hosts get the value detected
    inside `clawctl host create` via `uname -s`; this backfill only kicks
    in for legacy records.
    """
    host.setdefault("os_family", "linux")
    return host


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

        # Initialize addresses if not present
        _ensure_addresses(host)
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
    """Get a host by hostname, alias, or key_id.

    `key_id` is the immutable host identifier (issue #448); matching it
    here lets callers that hold a stable key (e.g. the value returned by
    `get_installed_claw`) resolve back to the host record even after the
    operator has mutated `hostname` (IP → DNS, renumbering, etc.).

    Args:
        identifier: Hostname, alias, or key_id to search for.

    Returns:
        Host dictionary if found, None otherwise.
    """
    hosts = load_hosts()
    for host in hosts:
        if host.get("hostname") == identifier:
            return host
        if host.get("alias") == identifier:
            return host
        if host.get("key_id") == identifier:
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


def alias_exists(
    alias: str, exclude_hostname: str | None = None
) -> tuple[bool, str | None]:
    """Check if alias is already in use by another host.

    Checks against both hostname and alias fields of all hosts.

    Args:
        alias: The alias to check for conflicts.
        exclude_hostname: Optionally exclude this hostname from the check (for self-reference).

    Returns:
        Tuple of (exists, conflicting_hostname).
        - (True, hostname) if alias conflicts with another host's hostname or alias.
        - (False, None) if alias is available.
    """
    hosts = load_hosts()
    for host in hosts:
        host_hostname = host.get("hostname")
        # Skip the excluded host
        if exclude_hostname and host_hostname == exclude_hostname:
            continue

        # Check if alias matches this host's hostname
        if host_hostname == alias:
            return (True, host_hostname)

        # Check if alias matches this host's alias
        if host.get("alias") == alias:
            return (True, host_hostname)

    return (False, None)


def remove_agent_from_host(hostname: str, agent_identifier: str) -> bool:
    """Remove an agent instance from a host's record atomically.

    Acquires exclusive lock for the entire load-modify-save operation
    to prevent TOCTOU races from concurrent operations.

    Args:
        hostname: The hostname of the host.
        agent_identifier: Agent instance name (preferred).
            For backward compatibility, if no instance key matches this value,
            a unique matching record by ``record["type"]`` is removed.

    Returns:
        True if the host was found (operation attempted), False if host not found.
        Note: Returns True even if the agent was not present in the host's agents dict,
        making the operation idempotent. Does NOT indicate whether agent was actually removed.
    """

    def updater(h: dict) -> dict:
        agents = h.get("agents")
        if not isinstance(agents, dict):
            return h

        if agent_identifier in agents:
            del agents[agent_identifier]
            return h

        # Backward compatibility: remove by unique type match.
        matches = [
            key
            for key, record in agents.items()
            if isinstance(record, dict) and record.get("type") == agent_identifier
        ]
        if len(matches) == 1:
            del agents[matches[0]]
        return h

    return update_host(hostname, updater)


def get_agent_by_name(agent_name: str) -> tuple[dict, str, dict] | None:
    """Resolve an installed agent by user-facing name.

    Matches against each host's installed agent records in this priority:
    1) instance key in `host["agents"]`
    2) explicit `agent_name`
    3) legacy `name`

    Args:
        agent_name: Name provided by the user.

    Returns:
        Tuple of (host_record, agent_type, agent_record) if uniquely found,
        None if not found.

    Raises:
        ValueError: If multiple installed agents match the given name.
    """
    query = agent_name.strip()
    if not query:
        return None

    matches: list[tuple[dict, str, dict]] = []
    for host in load_hosts():
        agents = host.get("agents")
        if not isinstance(agents, dict):
            continue
        for agent_key, agent_record in agents.items():
            if not isinstance(agent_record, dict):
                continue

            agent_type = agent_record.get("type")
            if not isinstance(agent_type, str) or not agent_type:
                # Backward compatibility for old type-keyed records
                agent_type = agent_key

            candidates = [
                agent_key,
                agent_record.get("agent_name"),
                agent_record.get("name"),
            ]
            if any(isinstance(v, str) and v == query for v in candidates):
                matches.append((host, agent_type, agent_record))

    if not matches:
        return None
    if len(matches) > 1:
        labels = []
        for host, agent_type, agent_record in matches:
            host_label = host.get("alias") or host.get("hostname") or "unknown-host"
            agent_label = (
                agent_record.get("agent_name") or agent_record.get("name") or agent_type
            )
            labels.append(f"{agent_label}@{host_label}")
        raise ValueError(
            f"Agent name '{query}' is ambiguous across hosts: {', '.join(labels)}"
        )

    return matches[0]


def add_address_to_host(hostname: str, address: str, label: str | None = None) -> None:
    """Add an address to a host.

    Args:
        hostname: The hostname or alias of the host.
        address: The address (IP or hostname) to add.
        label: Optional label for the address (e.g., "lan", "vpn").

    Raises:
        AddressError: If host not found, address already exists, or address is invalid.
    """
    # Validate address format before any operations
    _validate_address(address)

    host = get_host(hostname)
    if not host:
        raise AddressError(f"Host '{hostname}' not found")

    actual_hostname = host["hostname"]

    def updater(h: dict) -> dict:
        _ensure_addresses(h)
        addresses = h.get("addresses", [])

        # Check for duplicate
        for addr in addresses:
            if addr.get("address") == address:
                raise AddressError(
                    f"Address '{address}' already exists on host '{hostname}'"
                )

        # Add new address
        addresses.append(
            {
                "address": address,
                "is_primary": False,
                "label": label,
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        h["addresses"] = addresses
        return h

    if not update_host(actual_hostname, updater):
        raise AddressError(f"Host '{hostname}' not found")


def remove_address_from_host(hostname: str, address: str) -> None:
    """Remove an address from a host.

    Args:
        hostname: The hostname or alias of the host.
        address: The address to remove.

    Raises:
        AddressError: If host not found, address not found, or address is primary.
    """
    host = get_host(hostname)
    if not host:
        raise AddressError(f"Host '{hostname}' not found")

    actual_hostname = host["hostname"]

    def updater(h: dict) -> dict:
        _ensure_addresses(h)
        addresses = h.get("addresses", [])

        # Find the address
        found_idx = None
        for i, addr in enumerate(addresses):
            if addr.get("address") == address:
                found_idx = i
                break

        if found_idx is None:
            raise AddressError(f"Address '{address}' not found on host '{hostname}'")

        # Check if primary
        if addresses[found_idx].get("is_primary"):
            raise AddressError("Cannot remove primary address. Use 'set-primary' first")

        # Remove the address
        addresses.pop(found_idx)
        h["addresses"] = addresses
        return h

    if not update_host(actual_hostname, updater):
        raise AddressError(f"Host '{hostname}' not found")


def set_primary_address(hostname: str, address: str) -> None:
    """Set a different address as primary for a host.

    Updates the hostname field to match the new primary address.

    Args:
        hostname: The hostname or alias of the host.
        address: The address to make primary.

    Raises:
        AddressError: If host not found, address not found, or address is invalid.
    """
    # Validate address format before any operations
    _validate_address(address)

    host = get_host(hostname)
    if not host:
        raise AddressError(f"Host '{hostname}' not found")

    actual_hostname = host["hostname"]

    def updater(h: dict) -> dict:
        _ensure_addresses(h)
        addresses = h.get("addresses", [])

        # Find the address
        found = False
        for addr in addresses:
            if addr.get("address") == address:
                found = True
                break

        if not found:
            raise AddressError(
                f"Address '{address}' not found. Add it first with 'host address add'"
            )

        # Update primary flags and hostname
        for addr in addresses:
            addr["is_primary"] = addr.get("address") == address

        h["addresses"] = addresses
        h["hostname"] = address
        return h

    if not update_host(actual_hostname, updater):
        raise AddressError(f"Host '{hostname}' not found")


def get_host_addresses(hostname: str) -> list[dict]:
    """Get all addresses for a host.

    Args:
        hostname: The hostname or alias of the host.

    Returns:
        List of address dictionaries.

    Raises:
        AddressError: If host not found.
    """
    host = get_host(hostname)
    if not host:
        raise AddressError(f"Host '{hostname}' not found")

    _ensure_addresses(host)
    return host.get("addresses", [])

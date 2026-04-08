"""Secret storage operations for Clawrium."""

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TypedDict

from clawrium.core.config import get_config_dir, init_config_dir

__all__ = [
    "load_secrets",
    "save_secrets",
    "validate_secret_key",
    "SECRETS_FILE",
    "SecretEntry",
    "SecretsFileCorruptedError",
    "InvalidSecretKeyError",
    "InvalidInstanceKeyComponentError",
    "get_instance_key",
    "get_installed_claw",
    "get_instance_secrets",
    "set_instance_secret",
    "remove_instance_secret",
    "list_instances_with_secrets",
    "ClawNotFoundError",
]

SECRETS_FILE = "secrets.json"

# Valid secret key: starts with uppercase letter, followed by uppercase letters, digits, or underscores
# Max 128 characters total (env-var-safe pattern)
SECRET_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")

# Valid instance key component: no colons allowed (used as separator in instance keys)
# Allows alphanumeric, hyphens, underscores, dots (for hostnames, claw types, claw names)
INSTANCE_KEY_COMPONENT_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


class InvalidInstanceKeyComponentError(ValueError):
    """Raised when instance key component contains invalid characters (e.g., colons)."""

    pass


class SecretEntry(TypedDict):
    """Secret entry stored in secrets.json."""

    key: str
    value: str
    created_at: str  # ISO 8601 timestamp
    updated_at: str  # ISO 8601 timestamp
    description: str  # Optional description, empty string if not provided


class SecretsFileCorruptedError(Exception):
    """Raised when secrets.json cannot be parsed."""

    pass


class InvalidSecretKeyError(ValueError):
    """Raised when secret key contains invalid characters."""

    pass


class ClawNotFoundError(Exception):
    """Raised when claw is not found in hosts registry."""

    pass


def validate_secret_key(key: str) -> str:
    """Validate secret key to ensure env-var-safe naming.

    Valid keys: start with uppercase letter, contain only uppercase letters,
    digits, and underscores. Max 128 characters.

    Args:
        key: The secret key to validate.

    Returns:
        The validated key.

    Raises:
        InvalidSecretKeyError: If key is invalid.
    """
    if not key:
        raise InvalidSecretKeyError("Secret key cannot be empty")

    if not SECRET_KEY_PATTERN.match(key):
        raise InvalidSecretKeyError(
            f"Invalid secret key '{key}': must start with uppercase letter, "
            "contain only uppercase letters, digits, and underscores, "
            "and be at most 128 characters"
        )

    return key


def load_secrets() -> dict[str, dict[str, SecretEntry]]:
    """Load secrets from JSON file with nested per-instance structure.

    Returns:
        Dict mapping instance keys to dicts of SecretEntry objects.
        Structure: {instance_key: {secret_key: SecretEntry}}
        Empty dict if file doesn't exist.

    Raises:
        SecretsFileCorruptedError: If secrets.json exists but cannot be parsed.
    """
    secrets_path = get_config_dir() / SECRETS_FILE
    if not secrets_path.exists():
        return {}

    try:
        with open(secrets_path) as f:
            data = json.load(f)
            # Validate it's a dict
            if not isinstance(data, dict):
                raise SecretsFileCorruptedError(
                    f"secrets.json is not a dict: {secrets_path}"
                )
            return data
    except json.JSONDecodeError as e:
        raise SecretsFileCorruptedError(
            f"secrets.json is corrupted: {e}. "
            f"Backup the file and delete it to recover: {secrets_path}"
        ) from e


@contextmanager
def _secrets_lock():
    """Context manager for exclusive access to secrets.json.

    Uses fcntl.flock for advisory locking to prevent TOCTOU races
    when multiple processes try to modify secrets.json concurrently.
    """
    config_dir = init_config_dir()
    lock_path = config_dir / ".secrets.lock"

    # Create lock file if it doesn't exist
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _save_secrets_atomic(
    secrets: dict[str, dict[str, SecretEntry]], config_dir
) -> None:
    """Internal: Write secrets atomically without acquiring lock.

    This function performs the atomic write (temp file + rename).
    Caller MUST hold the _secrets_lock().

    Args:
        secrets: Dict mapping instance keys to dicts of SecretEntry objects.
        config_dir: Path to config directory.
    """
    secrets_path = config_dir / SECRETS_FILE
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
    try:
        # Set restrictive permissions on temp file before writing (survives rename)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(secrets, f, indent=2)
        os.replace(tmp_path, secrets_path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_secrets(secrets: dict[str, dict[str, SecretEntry]]) -> None:
    """Save secrets to JSON file atomically with file locking.

    Creates config directory if it doesn't exist.
    Uses atomic write (temp file + rename) to prevent data loss on crash.
    Uses fcntl.flock to prevent concurrent write races.

    Args:
        secrets: Dict mapping instance keys to dicts of SecretEntry objects.
    """
    # Ensure config directory exists
    config_dir = init_config_dir()

    with _secrets_lock():
        _save_secrets_atomic(secrets, config_dir)


# Per-instance secret operations (Phase 06)


def _validate_instance_key_component(component: str, component_name: str) -> None:
    """Validate an instance key component does not contain colons.

    Args:
        component: The component value to validate.
        component_name: Name of the component for error messages.

    Raises:
        InvalidInstanceKeyComponentError: If component contains colons or invalid chars.
    """
    if not component:
        raise InvalidInstanceKeyComponentError(f"{component_name} cannot be empty")
    if not INSTANCE_KEY_COMPONENT_PATTERN.match(component):
        raise InvalidInstanceKeyComponentError(
            f"Invalid {component_name} '{component}': must contain only "
            "alphanumeric characters, hyphens, underscores, and dots"
        )


def get_instance_key(host: str, claw_type: str, claw_name: str) -> str:
    """Generate instance key from host, claw type, and claw name.

    Args:
        host: Hostname where claw is installed.
        claw_type: Type of claw (openclaw, zeroclaw, etc.).
        claw_name: Name of the claw instance.

    Returns:
        Instance key in format "host:claw_type:claw_name".

    Raises:
        InvalidInstanceKeyComponentError: If any component contains colons or invalid chars.
    """
    _validate_instance_key_component(host, "hostname")
    _validate_instance_key_component(claw_type, "claw_type")
    _validate_instance_key_component(claw_name, "claw_name")
    return f"{host}:{claw_type}:{claw_name}"


def get_installed_claw(claw_name: str) -> tuple[str, str, str]:
    """Get installed claw details from hosts registry.

    Searches all hosts for a claw with matching name. Searches by:
    1. The "name" field
    2. The "user" field (claw system user)
    3. The claw_type key itself (e.g., "zeroclaw")

    Args:
        claw_name: Name of the claw instance (e.g., "opc-work", "zc-kevin", "zeroclaw").

    Returns:
        Tuple of (hostname, claw_type, claw_name).

    Raises:
        ClawNotFoundError: If claw with this name is not found in any host.
    """
    from clawrium.core.hosts import load_hosts

    hosts = load_hosts()
    for host in hosts:
        hostname = host.get("hostname", "")
        claws = host.get("claws", {})
        for claw_type, claw_data in claws.items():
            # Check name field, user field, or claw_type
            name = claw_data.get("name")
            user = claw_data.get("user")
            if claw_name in (name, user, claw_type):
                # Return the canonical name (name > user > claw_type)
                canonical_name = name or user or claw_type
                return (hostname, claw_type, canonical_name)

    raise ClawNotFoundError(
        f"Claw '{claw_name}' not found. Only installed claws can have secrets."
    )


def get_instance_secrets(instance_key: str) -> dict[str, SecretEntry]:
    """Get all secrets for a specific claw instance.

    Args:
        instance_key: Instance key in format "host:claw_type:claw_name".

    Returns:
        Dict mapping secret keys to SecretEntry objects for this instance.
        Empty dict if no secrets exist for this instance.
    """
    secrets = load_secrets()
    return secrets.get(instance_key, {})


def set_instance_secret(
    instance_key: str, key: str, value: str, description: str = ""
) -> bool:
    """Set or update a secret for a specific claw instance.

    If the secret exists for this instance, updates value and updated_at timestamp
    while preserving created_at. If description is not provided, preserves existing
    description for updates.

    Args:
        instance_key: Instance key in format "host:claw_type:claw_name".
        key: Secret key (must be env-var-safe: uppercase letters, digits, underscores).
        value: Secret value.
        description: Optional description (default: "").

    Returns:
        True if new secret created, False if existing secret updated.

    Raises:
        InvalidSecretKeyError: If key is not valid (see validate_secret_key).
    """
    validate_secret_key(key)

    with _secrets_lock():
        secrets = load_secrets()
        now = datetime.now(timezone.utc).isoformat()

        # Ensure instance dict exists
        if instance_key not in secrets:
            secrets[instance_key] = {}

        if key in secrets[instance_key]:
            # Update existing - preserve created_at and description if not provided
            existing = secrets[instance_key][key]
            secrets[instance_key][key] = SecretEntry(
                key=key,
                value=value,
                created_at=existing["created_at"],
                updated_at=now,
                description=description
                if description
                else existing.get("description", ""),
            )
            created = False
        else:
            # Create new
            secrets[instance_key][key] = SecretEntry(
                key=key,
                value=value,
                created_at=now,
                updated_at=now,
                description=description,
            )
            created = True

        # Save without re-acquiring lock (we already hold it)
        config_dir = init_config_dir()
        _save_secrets_atomic(secrets, config_dir)

        return created


def remove_instance_secret(instance_key: str, key: str) -> bool:
    """Remove a secret from a specific claw instance.

    Args:
        instance_key: Instance key in format "host:claw_type:claw_name".
        key: Secret key to remove.

    Returns:
        True if secret was found and removed, False otherwise.

    Raises:
        InvalidSecretKeyError: If key is not valid.
    """
    validate_secret_key(key)

    with _secrets_lock():
        secrets = load_secrets()

        if instance_key not in secrets or key not in secrets[instance_key]:
            return False

        del secrets[instance_key][key]

        # Clean up empty instance dict
        if not secrets[instance_key]:
            del secrets[instance_key]

        # Save without re-acquiring lock (we already hold it)
        config_dir = init_config_dir()
        _save_secrets_atomic(secrets, config_dir)

        return True


def list_instances_with_secrets() -> list[str]:
    """Get list of all instance keys that have at least one secret.

    Returns:
        Sorted list of instance keys in format "host:claw_type:claw_name".
    """
    secrets = load_secrets()
    return sorted(secrets.keys())


# Deprecated global functions (Phase 05) - kept for reference, will be removed in Phase 06 Plan 02


def get_secret(key: str) -> SecretEntry | None:
    """DEPRECATED: Use get_instance_secrets instead.

    Get a secret entry by key from global namespace (legacy support).
    This function is kept for backward compatibility with existing CLI.
    Will be removed in Phase 06 Plan 02.

    Args:
        key: Secret key to retrieve.

    Returns:
        SecretEntry if found, None otherwise.
    """
    secrets = load_secrets()
    global_key = "__global__"
    if global_key not in secrets:
        return None
    return secrets[global_key].get(key)


def set_secret(
    key: str, value: str, description: str = "", *, strict: bool = False
) -> bool:
    """DEPRECATED: Use set_instance_secret instead.

    Set or update a global secret (legacy support for CLI).
    This function is kept for backward compatibility with existing CLI.
    Will be removed in Phase 06 Plan 02.

    Args:
        key: Secret key.
        value: Secret value.
        description: Optional description.
        strict: Ignored (deprecated parameter).

    Returns:
        True if new secret created, False if existing secret updated.

    Raises:
        InvalidSecretKeyError: If key is not valid.
    """
    validate_secret_key(key)

    with _secrets_lock():
        secrets = load_secrets()
        now = datetime.now(timezone.utc).isoformat()

        # Legacy support: use special "__global__" instance key for backward compatibility
        global_key = "__global__"
        if global_key not in secrets:
            secrets[global_key] = {}

        if key in secrets[global_key]:
            # Update existing - preserve created_at and description if not provided
            existing = secrets[global_key][key]
            secrets[global_key][key] = SecretEntry(
                key=key,
                value=value,
                created_at=existing["created_at"],
                updated_at=now,
                description=description
                if description
                else existing.get("description", ""),
            )
            created = False
        else:
            # Create new
            secrets[global_key][key] = SecretEntry(
                key=key,
                value=value,
                created_at=now,
                updated_at=now,
                description=description,
            )
            created = True

        # Save without re-acquiring lock (we already hold it)
        config_dir = init_config_dir()
        _save_secrets_atomic(secrets, config_dir)

        return created


def remove_secret(key: str) -> bool:
    """DEPRECATED: Use remove_instance_secret instead.

    Remove a global secret (legacy support for CLI).
    This function is kept for backward compatibility with existing CLI.
    Will be removed in Phase 06 Plan 02.

    Args:
        key: Secret key to remove.

    Returns:
        True if secret was found and removed, False otherwise.

    Raises:
        InvalidSecretKeyError: If key is not valid.
    """
    validate_secret_key(key)

    with _secrets_lock():
        secrets = load_secrets()

        # Legacy support: use special "__global__" instance key
        global_key = "__global__"
        if global_key not in secrets or key not in secrets[global_key]:
            return False

        del secrets[global_key][key]

        # Clean up empty global dict
        if not secrets[global_key]:
            del secrets[global_key]

        # Save without re-acquiring lock (we already hold it)
        config_dir = init_config_dir()
        _save_secrets_atomic(secrets, config_dir)

        return True


def list_secrets() -> list[str]:
    """DEPRECATED: Use list_instances_with_secrets instead.

    Get list of global secret keys (legacy support for CLI).
    This function is kept for backward compatibility with existing CLI.
    Will be removed in Phase 06 Plan 02.

    Returns:
        Sorted list of global secret keys.
    """
    secrets = load_secrets()
    global_key = "__global__"
    if global_key not in secrets:
        return []
    return sorted(secrets[global_key].keys())

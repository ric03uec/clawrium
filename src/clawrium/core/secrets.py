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
    "get_secret",
    "set_secret",
    "remove_secret",
    "list_secrets",
    "validate_secret_key",
    "SECRETS_FILE",
    "SecretEntry",
    "SecretsFileCorruptedError",
    "DuplicateSecretError",
    "InvalidSecretKeyError",
]

SECRETS_FILE = "secrets.json"

# Valid secret key: starts with uppercase letter, followed by uppercase letters, digits, or underscores
# Max 128 characters total (env-var-safe pattern)
SECRET_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


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


class DuplicateSecretError(Exception):
    """Raised when trying to add a secret that already exists (for strict mode)."""

    pass


class InvalidSecretKeyError(ValueError):
    """Raised when secret key contains invalid characters."""

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


def load_secrets() -> dict[str, SecretEntry]:
    """Load secrets from JSON file.

    Returns:
        Dict mapping secret keys to SecretEntry objects. Empty dict if file doesn't exist.

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


def save_secrets(secrets: dict[str, SecretEntry]) -> None:
    """Save secrets to JSON file atomically with file locking.

    Creates config directory if it doesn't exist.
    Uses atomic write (temp file + rename) to prevent data loss on crash.
    Uses fcntl.flock to prevent concurrent write races.

    Args:
        secrets: Dict mapping secret keys to SecretEntry objects.
    """
    # Ensure config directory exists
    config_dir = init_config_dir()
    secrets_path = config_dir / SECRETS_FILE

    with _secrets_lock():
        # Atomic write: write to temp file, then rename (atomic on POSIX)
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


def get_secret(key: str) -> SecretEntry | None:
    """Get a secret entry by key.

    Args:
        key: Secret key to retrieve.

    Returns:
        SecretEntry if found, None otherwise.
    """
    secrets = load_secrets()
    return secrets.get(key)


def set_secret(key: str, value: str, description: str = "", *, strict: bool = False) -> bool:
    """Set or update a secret.

    If the secret exists, updates value and updated_at timestamp while preserving created_at.
    If description is not provided, preserves existing description for updates.

    Args:
        key: Secret key (must be env-var-safe: uppercase letters, digits, underscores).
        value: Secret value.
        description: Optional description (default: "").
        strict: If True, raise DuplicateSecretError if key already exists (default: False).

    Returns:
        True if new secret created, False if existing secret updated.

    Raises:
        InvalidSecretKeyError: If key is not valid (see validate_secret_key).
        DuplicateSecretError: If strict=True and key already exists.
    """
    validate_secret_key(key)

    with _secrets_lock():
        secrets = load_secrets()
        now = datetime.now(timezone.utc).isoformat()

        if key in secrets:
            if strict:
                raise DuplicateSecretError(f"Secret '{key}' already exists")
            # Update existing - preserve created_at and description if not provided
            existing = secrets[key]
            secrets[key] = SecretEntry(
                key=key,
                value=value,
                created_at=existing["created_at"],
                updated_at=now,
                description=description if description else existing.get("description", ""),
            )
            created = False
        else:
            # Create new
            secrets[key] = SecretEntry(
                key=key,
                value=value,
                created_at=now,
                updated_at=now,
                description=description,
            )
            created = True

        # Save without re-acquiring lock (we already hold it)
        config_dir = init_config_dir()
        secrets_path = config_dir / SECRETS_FILE
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(secrets, f, indent=2)
            os.replace(tmp_path, secrets_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return created


def remove_secret(key: str) -> bool:
    """Remove a secret by key.

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

        if key not in secrets:
            return False

        del secrets[key]

        # Save without re-acquiring lock (we already hold it)
        config_dir = init_config_dir()
        secrets_path = config_dir / SECRETS_FILE
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(secrets, f, indent=2)
            os.replace(tmp_path, secrets_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return True


def list_secrets() -> list[str]:
    """Get list of all secret keys.

    Returns secret keys only, not values, for security.

    Returns:
        Sorted list of secret keys.
    """
    secrets = load_secrets()
    return sorted(secrets.keys())

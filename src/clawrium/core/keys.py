"""Per-host SSH key management for Clawrium."""

import os
import re
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from clawrium.core.config import get_config_dir, init_config_dir

__all__ = [
    "get_host_key_dir",
    "get_host_private_key",
    "get_host_public_key",
    "generate_host_keypair",
    "delete_host_keys",
    "read_public_key",
    "validate_key_id",
]

KEY_FILENAME = "xclm_ed25519"

# Valid key_id: alphanumeric, dots, underscores, hyphens only
KEY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


class InvalidKeyIdError(ValueError):
    """Raised when key_id contains invalid characters."""

    pass


def validate_key_id(key_id: str) -> str:
    """Validate key_id to prevent path traversal attacks.

    Args:
        key_id: The key identifier to validate.

    Returns:
        The validated key_id.

    Raises:
        InvalidKeyIdError: If key_id contains invalid characters.
    """
    if not key_id:
        raise InvalidKeyIdError("key_id cannot be empty")

    if not KEY_ID_PATTERN.match(key_id):
        raise InvalidKeyIdError(
            f"Invalid key_id '{key_id}': only alphanumeric, dots, underscores, and hyphens allowed"
        )

    # Extra safety: reject any path traversal attempts
    if ".." in key_id or key_id.startswith("/"):
        raise InvalidKeyIdError(
            f"Invalid key_id '{key_id}': path traversal not allowed"
        )

    return key_id


def get_host_key_dir(key_id: str) -> Path:
    """Get the directory for a host's SSH keys.

    Args:
        key_id: The key identifier (validated for safety).

    Returns:
        Path to keys/<key_id>/ directory.

    Raises:
        InvalidKeyIdError: If key_id contains invalid characters.
    """
    validate_key_id(key_id)

    keys_base = get_config_dir() / "keys"
    key_dir = keys_base / key_id

    # Defense in depth: verify resolved path is within keys directory
    try:
        resolved = key_dir.resolve()
        keys_base_resolved = keys_base.resolve()
        if not str(resolved).startswith(str(keys_base_resolved) + os.sep):
            raise InvalidKeyIdError(
                f"Invalid key_id '{key_id}': path escapes keys directory"
            )
    except (OSError, ValueError) as e:
        raise InvalidKeyIdError(f"Invalid key_id '{key_id}': {e}")

    return key_dir


def get_host_private_key(hostname: str) -> Path | None:
    """Get the path to a host's private key.

    Args:
        hostname: The hostname or IP address.

    Returns:
        Path to xclm_ed25519 if exists, None otherwise.
    """
    key_path = get_host_key_dir(hostname) / KEY_FILENAME
    return key_path if key_path.exists() else None


def get_host_public_key(hostname: str) -> Path | None:
    """Get the path to a host's public key.

    Args:
        hostname: The hostname or IP address.

    Returns:
        Path to xclm_ed25519.pub if exists, None otherwise.
    """
    key_path = get_host_key_dir(hostname) / f"{KEY_FILENAME}.pub"
    return key_path if key_path.exists() else None


def generate_host_keypair(hostname: str, overwrite: bool = False) -> tuple[Path, Path]:
    """Generate an ed25519 keypair for a host.

    Creates the key directory with 0700 permissions and the private key
    with 0600 permissions.

    Args:
        hostname: The hostname or IP address.
        overwrite: If True, overwrite existing keys. If False (default),
            raise ValueError if keys already exist.

    Returns:
        Tuple of (private_key_path, public_key_path).

    Raises:
        ValueError: If keys already exist and overwrite is False.
    """
    # Ensure config directory exists
    init_config_dir()

    # Check for existing keys
    key_dir = get_host_key_dir(hostname)
    private_key_path = key_dir / KEY_FILENAME
    if private_key_path.exists() and not overwrite:
        raise ValueError(
            f"Keypair already exists for '{hostname}'. Use overwrite=True to replace."
        )
    old_umask = os.umask(0o077)
    try:
        key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    finally:
        os.umask(old_umask)
    # Ensure permissions are correct even if directory already existed
    key_dir.chmod(0o700)

    # Generate ed25519 keypair
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Serialize private key in OpenSSH format
    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # Serialize public key in OpenSSH format
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )

    # Write private key with 0600 permissions
    private_key_path = key_dir / KEY_FILENAME
    old_umask = os.umask(0o177)  # Results in 0600
    try:
        with open(private_key_path, "wb") as f:
            f.write(private_key_bytes)
    finally:
        os.umask(old_umask)
    private_key_path.chmod(0o600)

    # Write public key with comment and explicit permissions
    public_key_path = key_dir / f"{KEY_FILENAME}.pub"
    public_key_str = public_key_bytes.decode("utf-8") + " clawrium\n"
    with open(public_key_path, "w") as f:
        f.write(public_key_str)
    public_key_path.chmod(0o644)

    return private_key_path, public_key_path


def delete_host_keys(key_id: str) -> bool:
    """Delete all SSH keys for a host.

    Removes the entire keys/<key_id>/ directory.

    Args:
        key_id: The key identifier.

    Returns:
        True if keys were deleted, False if directory didn't exist.

    Raises:
        InvalidKeyIdError: If key_id contains invalid characters.
    """
    # validate_key_id is called by get_host_key_dir
    key_dir = get_host_key_dir(key_id)
    if not key_dir.exists():
        return False

    shutil.rmtree(key_dir)
    return True


def read_public_key(hostname: str) -> str | None:
    """Read the public key content for a host.

    Args:
        hostname: The hostname or IP address.

    Returns:
        Public key content as string, or None if not found.
    """
    public_key_path = get_host_public_key(hostname)
    if public_key_path is None:
        return None

    return public_key_path.read_text().strip()

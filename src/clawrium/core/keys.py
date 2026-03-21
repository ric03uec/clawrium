"""Per-host SSH key management for Clawrium."""

import os
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
]

KEY_FILENAME = "xclm_ed25519"


def get_host_key_dir(hostname: str) -> Path:
    """Get the directory for a host's SSH keys.

    Args:
        hostname: The hostname or IP address.

    Returns:
        Path to keys/<hostname>/ directory.
    """
    return get_config_dir() / "keys" / hostname


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
        raise ValueError(f"Keypair already exists for '{hostname}'. Use overwrite=True to replace.")
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
        encryption_algorithm=serialization.NoEncryption()
    )

    # Serialize public key in OpenSSH format
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH
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


def delete_host_keys(hostname: str) -> bool:
    """Delete all SSH keys for a host.

    Removes the entire keys/<hostname>/ directory.

    Args:
        hostname: The hostname or IP address.

    Returns:
        True if keys were deleted, False if directory didn't exist.
    """
    key_dir = get_host_key_dir(hostname)
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

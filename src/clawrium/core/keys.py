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
    "get_agent_key_dir",
    "get_agent_private_key",
    "get_agent_public_key",
    "ensure_agent_keypair",
    "read_agent_public_key",
]

KEY_FILENAME = "xclm_ed25519"
AGENT_KEY_FILENAME = "id_ed25519"

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
        if not resolved.is_relative_to(keys_base_resolved):
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


def get_agent_key_dir(key_id: str, agent_name: str) -> Path:
    """Return the controller-side directory for one agent SSH identity.

    Agent identities deliberately live under ``agent-keys/`` rather than
    ``keys/``: host reset deletes the latter management-key tree.
    """
    validate_key_id(key_id)
    validate_key_id(agent_name)
    base = get_config_dir() / "agent-keys"
    path = base / key_id / agent_name
    try:
        # `resolve()` alone accepts a symlinked child that happens to point
        # back inside the root. Reject every controlled component instead.
        for component in (base, base / key_id, path):
            if component.is_symlink():
                raise InvalidKeyIdError("agent key path contains a symlink")
        if not path.resolve().is_relative_to(base.resolve()):
            raise InvalidKeyIdError("agent key path escapes agent-keys directory")
    except OSError as exc:
        raise InvalidKeyIdError(f"unsafe agent key path: {exc}") from exc
    return path


def _agent_key_paths(key_id: str, agent_name: str) -> tuple[Path, Path]:
    directory = get_agent_key_dir(key_id, agent_name)
    return directory / AGENT_KEY_FILENAME, directory / f"{AGENT_KEY_FILENAME}.pub"


def _validate_agent_keypair(private_path: Path, public_path: Path) -> None:
    """Fail closed unless both non-symlinked files form one Ed25519 pair."""
    if private_path.is_symlink() or public_path.is_symlink():
        raise ValueError("agent SSH identity contains a symlink; remove it manually")
    if not private_path.exists() or not public_path.exists():
        raise ValueError("agent SSH identity is incomplete; remove or recover it manually")
    try:
        private = serialization.load_ssh_private_key(private_path.read_bytes(), password=None)
        expected = private.public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        actual = public_path.read_bytes().strip().split(maxsplit=2)[:2]
    except (ValueError, OSError) as exc:
        raise ValueError("agent SSH identity is corrupt; remove or recover it manually") from exc
    if not isinstance(private, ed25519.Ed25519PrivateKey) or b" ".join(actual) != expected:
        raise ValueError("agent SSH public key does not match private key; recover manually")


def get_agent_private_key(key_id: str, agent_name: str) -> Path | None:
    """Return a valid controller-side agent private key, if present."""
    private_path, public_path = _agent_key_paths(key_id, agent_name)
    if not private_path.exists() and not public_path.exists():
        return None
    _validate_agent_keypair(private_path, public_path)
    return private_path


def get_agent_public_key(key_id: str, agent_name: str) -> Path | None:
    """Return a valid controller-side agent public key, if present."""
    private_path = get_agent_private_key(key_id, agent_name)
    return private_path.with_suffix(private_path.suffix + ".pub") if private_path else None


def ensure_agent_keypair(key_id: str, agent_name: str) -> tuple[Path, Path]:
    """Create one durable Ed25519 agent identity, without rotating one.

    Existing partial, corrupt, or symlinked state is rejected. Temporary files
    are linked into place only after both files have been written, so a second
    caller never replaces an established identity.
    """
    init_config_dir()
    private_path, public_path = _agent_key_paths(key_id, agent_name)
    directory = private_path.parent
    if directory.is_symlink():
        raise ValueError("agent SSH identity directory is a symlink; recover manually")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    if private_path.exists() or public_path.exists():
        _validate_agent_keypair(private_path, public_path)
        return private_path, public_path

    private = ed25519.Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ) + b" clawrium\n"
    # O_EXCL protects against a concurrent creator.  A loser validates and
    # retains the winner's pair rather than regenerating it.
    try:
        fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _validate_agent_keypair(private_path, public_path)
        return private_path, public_path
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(private_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            pub_fd = os.open(public_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError as exc:
            raise ValueError("agent SSH identity was concurrently interrupted; recover manually") from exc
        with os.fdopen(pub_fd, "wb") as handle:
            handle.write(public_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # Never leave a partial pair created by this invocation.
        private_path.unlink(missing_ok=True)
        public_path.unlink(missing_ok=True)
        raise
    private_path.chmod(0o600)
    public_path.chmod(0o644)
    _validate_agent_keypair(private_path, public_path)
    return private_path, public_path


def read_agent_public_key(key_id: str, agent_name: str) -> str | None:
    """Read the complete public half of a valid agent identity."""
    path = get_agent_public_key(key_id, agent_name)
    return path.read_text().strip() if path else None


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

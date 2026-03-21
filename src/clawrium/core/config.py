"""Configuration directory management for Clawrium."""

import os
from pathlib import Path

__all__ = ["get_config_dir", "init_config_dir"]


def get_config_dir() -> Path:
    """Get the Clawrium configuration directory path.

    Respects XDG_CONFIG_HOME if set to an absolute path,
    otherwise falls back to ~/.config/clawrium.

    Returns:
        Path to the clawrium configuration directory.
    """
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config and Path(xdg_config).is_absolute():
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"
    return base / "clawrium"


def init_config_dir() -> Path:
    """Create and return the configuration directory.

    Creates the directory and any parent directories if they don't exist.
    Sets restrictive permissions (0700) for security.
    Safe to call multiple times (idempotent).

    Returns:
        Path to the created configuration directory.
    """
    import os

    config_dir = get_config_dir()
    # Set restrictive umask before mkdir to protect any created parent dirs
    old_umask = os.umask(0o077)
    try:
        config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    finally:
        os.umask(old_umask)
    # Ensure permissions are correct even if directory already existed
    config_dir.chmod(0o700)
    return config_dir

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
    Safe to call multiple times (idempotent).

    Returns:
        Path to the created configuration directory.
    """
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

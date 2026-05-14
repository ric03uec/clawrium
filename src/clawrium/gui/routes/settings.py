"""Settings API routes.

Provides application settings and version information.
"""

import importlib.metadata
import logging
import platform

from fastapi import APIRouter

from clawrium.core.config import get_config_dir
from clawrium.gui.services.usage_tracker import get_usage_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    """Get current application settings."""
    config_dir = get_config_dir()
    tracker = get_usage_tracker()
    return {
        "config_dir": str(config_dir),
        "hosts_file": str(config_dir / "hosts.json"),
        "providers_file": str(config_dir / "providers.json"),
        "secrets_file": str(config_dir / "secrets.json"),
        "usage_db": tracker.get_db_path(),
    }


@router.get("/version")
async def get_version():
    """Get version and system information."""
    try:
        version = importlib.metadata.version("clawrium")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    return {
        "version": version,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "arch": platform.machine(),
    }

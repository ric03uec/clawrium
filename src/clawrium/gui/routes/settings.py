"""Settings API routes.

Provides application settings and version information.
"""

import importlib.metadata
import logging
import platform

from fastapi import APIRouter

from clawrium.core.config import get_config_dir
from clawrium.core.secrets import SECRETS_FILE
from clawrium.gui.services.usage_tracker import get_usage_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    """Get current application settings."""
    config_dir = get_config_dir()
    tracker = get_usage_tracker()
    secrets_file = config_dir / SECRETS_FILE
    return {
        "config_dir": str(config_dir),
        "secrets_configured": secrets_file.exists(),
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


@router.post("/reset")
async def reset_configuration():
    """Reset all configuration files to empty state.

    This removes providers, integrations, and agent definitions.
    Agents already installed on hosts are NOT uninstalled.
    """
    import json

    config_dir = get_config_dir()

    files_reset = []

    # Reset providers
    providers_file = config_dir / "providers.json"
    if providers_file.exists():
        providers_file.write_text(json.dumps({"providers": []}, indent=2))
        files_reset.append("providers.json")

    # Reset secrets
    secrets_file = config_dir / "secrets.json"
    if secrets_file.exists():
        secrets_file.write_text(json.dumps({}, indent=2))
        files_reset.append("secrets.json")

    # Reset integrations
    integrations_file = config_dir / "integrations.json"
    if integrations_file.exists():
        integrations_file.write_text(json.dumps({"integrations": []}, indent=2))
        files_reset.append("integrations.json")

    # Clear usage data
    tracker = get_usage_tracker()
    tracker.clear()
    files_reset.append("usage.db")

    logger.warning("Configuration reset via GUI: %s", ", ".join(files_reset))

    return {
        "success": True,
        "files_reset": files_reset,
        "message": "Configuration reset. Agents on hosts are unchanged.",
    }

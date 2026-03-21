"""Registry loading and claw manifest management.

This module provides functions to discover available claw types from bundled
manifests and extract their requirements and platform compatibility.
"""

import logging
from pathlib import Path
from typing import TypedDict

import yaml
from packaging.version import Version

logger = logging.getLogger(__name__)


class Requirements(TypedDict):
    """Claw requirements specification."""

    min_memory_mb: int
    gpu_required: bool
    dependencies: dict[str, str]


class ManifestEntry(TypedDict):
    """Single platform entry in a claw manifest."""

    version: str
    os: str
    os_version: str
    arch: str
    requirements: Requirements


class ClawManifest(TypedDict):
    """Complete claw manifest with all platform entries."""

    name: str
    description: str
    entries: list[ManifestEntry]


class ManifestNotFoundError(Exception):
    """Raised when a claw manifest is not found."""

    pass


class ManifestParseError(Exception):
    """Raised when a manifest YAML is malformed."""

    pass


def load_manifest(claw_name: str) -> ClawManifest:
    """Load claw manifest from bundled registry.

    Args:
        claw_name: Name of the claw (e.g., "openclaw")

    Returns:
        Parsed ClawManifest dictionary

    Raises:
        ManifestNotFoundError: If claw directory doesn't exist
        ManifestParseError: If YAML is invalid
    """
    try:
        # Use importlib.resources to read manifest from package
        from importlib.resources import files

        registry_package = files("clawrium.platform.registry")
        claw_dir = registry_package / claw_name

        # Check if claw directory exists
        if not claw_dir.is_dir():
            raise ManifestNotFoundError(f"Claw '{claw_name}' not found in registry")

        manifest_file = claw_dir / "manifest.yaml"

        # Read and parse manifest
        manifest_text = manifest_file.read_text()
        manifest_data = yaml.safe_load(manifest_text)

        if not isinstance(manifest_data, dict):
            raise ManifestParseError(
                f"Manifest for '{claw_name}' is not a valid YAML dict"
            )

        # Validate basic structure
        if "name" not in manifest_data or "entries" not in manifest_data:
            raise ManifestParseError(
                f"Manifest for '{claw_name}' missing required fields (name, entries)"
            )

        return manifest_data

    except FileNotFoundError as e:
        raise ManifestNotFoundError(f"Claw '{claw_name}' not found in registry") from e
    except yaml.YAMLError as e:
        raise ManifestParseError(
            f"Failed to parse manifest for '{claw_name}': {e}"
        ) from e


def list_claws() -> list[str]:
    """List all available claw types in the registry.

    Returns:
        Sorted list of claw names
    """
    try:
        from importlib.resources import files

        registry_package = files("clawrium.platform.registry")

        # List subdirectories that contain manifest.yaml
        claws = []
        for item in registry_package.iterdir():
            if item.is_dir():
                manifest_file = item / "manifest.yaml"
                try:
                    # Check if manifest exists by trying to read it
                    _ = manifest_file.read_text()
                    claws.append(item.name)
                except (FileNotFoundError, AttributeError):
                    # Skip directories without manifest.yaml
                    continue

        return sorted(claws)

    except Exception as e:
        logger.error("Failed to list claws: %s", e)
        return []


def get_claw_info(claw_name: str) -> dict:
    """Get summary information about a claw.

    Args:
        claw_name: Name of the claw

    Returns:
        Dictionary with: name, description, latest_version, supported_platforms

    Raises:
        ManifestNotFoundError: If claw doesn't exist
    """
    manifest = load_manifest(claw_name)

    # Find latest version (highest semver)
    versions = [Version(entry["version"]) for entry in manifest["entries"]]
    latest_version = str(max(versions))

    # Build supported platforms list
    platforms = []
    for entry in manifest["entries"]:
        platform = f"{entry['os']} {entry['os_version']} {entry['arch']}"
        if platform not in platforms:
            platforms.append(platform)

    return {
        "name": manifest["name"],
        "description": manifest.get("description", ""),
        "latest_version": latest_version,
        "supported_platforms": sorted(platforms),
    }

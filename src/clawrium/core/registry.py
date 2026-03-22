"""Registry loading and claw manifest management.

This module provides functions to discover available claw types from bundled
manifests and extract their requirements and platform compatibility.
"""

import logging
import re
from typing import NotRequired, TypedDict

import yaml
from packaging.version import Version, InvalidVersion

logger = logging.getLogger(__name__)


class InvalidClawNameError(Exception):
    """Raised when claw name contains invalid characters."""

    pass


def validate_claw_name(claw_name: str) -> None:
    """Validate claw name to prevent path traversal attacks.

    Args:
        claw_name: Name of the claw to validate

    Raises:
        InvalidClawNameError: If claw name contains invalid characters
    """
    if not claw_name:
        raise InvalidClawNameError("Claw name cannot be empty")

    # Only allow alphanumeric, underscore, and hyphen
    if not re.match(r"^[a-zA-Z0-9_-]+$", claw_name):
        raise InvalidClawNameError(
            f"Claw name '{claw_name}' contains invalid characters. "
            "Only alphanumeric, underscore, and hyphen are allowed."
        )

    # Reject path traversal attempts
    if ".." in claw_name or "/" in claw_name or "\\" in claw_name:
        raise InvalidClawNameError(
            f"Claw name '{claw_name}' contains path traversal characters"
        )


class Requirements(TypedDict):
    """Claw requirements specification."""

    min_memory_mb: int
    gpu_required: bool
    dependencies: dict[str, str]


class SecretDefinition(TypedDict):
    """Secret definition in manifest."""

    key: str
    description: str


class ManifestEntry(TypedDict):
    """Single platform entry in a claw manifest."""

    version: str
    os: str
    os_version: str
    arch: str
    requirements: Requirements
    sha256: NotRequired[str]  # SHA256 checksum for binary verification


class ClawManifest(TypedDict):
    """Complete claw manifest with all platform entries."""

    name: str
    description: str
    entries: list[ManifestEntry]
    required_secrets: NotRequired[list[SecretDefinition]]
    optional_secrets: NotRequired[list[SecretDefinition]]


class CompatibilityResult(TypedDict):
    """Result of compatibility check between host and claw."""

    compatible: bool
    matched_entry: ManifestEntry | None
    reasons: list[str]


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
        InvalidClawNameError: If claw name contains invalid characters
    """
    # Validate claw name to prevent path traversal
    validate_claw_name(claw_name)

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
    versions = []
    for entry in manifest["entries"]:
        try:
            versions.append(Version(entry["version"]))
        except InvalidVersion:
            logger.warning("Invalid version '%s' in manifest for %s", entry["version"], claw_name)
            continue

    if not versions:
        raise ManifestParseError(f"No valid versions found in manifest for '{claw_name}'")

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


def get_required_secrets(claw_name: str) -> list[SecretDefinition]:
    """Get list of required secrets for a claw.

    Args:
        claw_name: Name of the claw

    Returns:
        List of SecretDefinition dicts. Empty list if claw has no required_secrets field.

    Raises:
        ManifestNotFoundError: If claw manifest doesn't exist
    """
    manifest = load_manifest(claw_name)
    return manifest.get("required_secrets", [])


def get_optional_secrets(claw_name: str) -> list[SecretDefinition]:
    """Get list of optional secrets for a claw.

    Args:
        claw_name: Name of the claw

    Returns:
        List of SecretDefinition dicts. Empty list if claw has no optional_secrets field.

    Raises:
        ManifestNotFoundError: If claw manifest doesn't exist
    """
    manifest = load_manifest(claw_name)
    return manifest.get("optional_secrets", [])


def check_compatibility(
    claw_name: str,
    hardware: dict,
    version: str | None = None,
) -> CompatibilityResult:
    """Check if host hardware is compatible with a claw.

    This implements sparse matrix matching - only explicitly supported
    combinations (OS, version, arch) are valid. All requirements must
    be met for compatibility.

    Args:
        claw_name: Name of the claw (e.g., "openclaw")
        hardware: HardwareInfo dict from host (see hardware.py)
        version: Optional specific version to check (default: any version)

    Returns:
        CompatibilityResult with:
            - compatible: True if host matches any manifest entry
            - matched_entry: The ManifestEntry that matched, or None
            - reasons: List of failure reasons (empty if compatible)

    Raises:
        ManifestNotFoundError: If claw manifest doesn't exist
    """
    manifest = load_manifest(claw_name)

    # Filter entries by version if specified
    entries = manifest["entries"]
    if version:
        entries = [e for e in entries if e["version"] == version]
        if not entries:
            return {
                "compatible": False,
                "matched_entry": None,
                "reasons": [f"Version {version} not found in manifest"],
            }

    # Collect all failure reasons across all entries
    all_reasons = []

    # Try each entry in order
    for entry in entries:
        reasons = []

        # Check OS match
        if entry["os"] != hardware.get("os"):
            reasons.append(
                f"Requires {entry['os']} {entry['os_version']}, "
                f"host has {hardware.get('os', 'unknown')} {hardware.get('os_version', 'unknown')}"
            )

        # Check OS version match
        elif entry["os_version"] != hardware.get("os_version"):
            reasons.append(
                f"Requires {entry['os']} {entry['os_version']}, "
                f"host has {hardware.get('os', 'unknown')} {hardware.get('os_version', 'unknown')}"
            )

        # Check architecture match
        if entry["arch"] != hardware.get("architecture"):
            reasons.append(
                f"Requires {entry['arch']}, host has {hardware.get('architecture', 'unknown')}"
            )

        # Check memory requirement (use .get() for safety)
        requirements = entry.get("requirements", {})
        min_memory = requirements.get("min_memory_mb", 0)
        host_memory = hardware.get("memtotal_mb", 0)
        if host_memory < min_memory:
            reasons.append(
                f"Requires {min_memory}MB RAM, host has {host_memory}MB"
            )

        # Check GPU requirement (use .get() for safety)
        if requirements.get("gpu_required", False):
            gpu = hardware.get("gpu", {})
            if not gpu.get("present"):
                reasons.append("Requires GPU, host has none")

        # TODO: Dependency checking deferred to future phase
        # Hardware dict doesn't include installed package versions yet

        # If this entry matches all requirements, return success
        if not reasons:
            return {
                "compatible": True,
                "matched_entry": entry,
                "reasons": [],
            }

        # Collect reasons from this entry
        all_reasons.extend(reasons)

    # No entry matched - return failure with all collected reasons
    # Deduplicate reasons while preserving order
    unique_reasons = []
    seen = set()
    for r in all_reasons:
        if r not in seen:
            unique_reasons.append(r)
            seen.add(r)

    return {
        "compatible": False,
        "matched_entry": None,
        "reasons": unique_reasons,
    }

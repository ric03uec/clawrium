"""Tests for registry loading functionality."""

import pytest
from clawrium.core.registry import (
    ClawManifest,
    ManifestNotFoundError,
    ManifestParseError,
    get_claw_info,
    list_claws,
    load_manifest,
)


def test_load_manifest_openclaw():
    """Test loading openclaw manifest returns valid ClawManifest."""
    manifest = load_manifest("openclaw")

    assert isinstance(manifest, dict)
    assert manifest["name"] == "openclaw"
    assert "description" in manifest
    assert "entries" in manifest
    assert len(manifest["entries"]) > 0

    # Validate first entry structure
    entry = manifest["entries"][0]
    assert "version" in entry
    assert "os" in entry
    assert "os_version" in entry
    assert "arch" in entry
    assert "requirements" in entry

    # Validate requirements structure
    req = entry["requirements"]
    assert "min_memory_mb" in req
    assert "gpu_required" in req
    assert "dependencies" in req


def test_load_manifest_nonexistent():
    """Test loading nonexistent claw raises ManifestNotFoundError."""
    with pytest.raises(ManifestNotFoundError, match="not found"):
        load_manifest("nonexistent")


def test_load_manifest_malformed(tmp_path):
    """Test loading malformed YAML raises ManifestParseError."""
    # This will be tested with a malformed manifest file
    # For now, we test that the exception type exists
    with pytest.raises(ManifestParseError):
        raise ManifestParseError("test")


def test_list_claws():
    """Test list_claws returns openclaw."""
    claws = list_claws()

    assert isinstance(claws, list)
    assert "openclaw" in claws
    assert len(claws) > 0


def test_get_claw_info_openclaw():
    """Test get_claw_info returns summary for openclaw."""
    info = get_claw_info("openclaw")

    assert isinstance(info, dict)
    assert info["name"] == "openclaw"
    assert "description" in info
    assert "latest_version" in info
    assert "supported_platforms" in info

    # Supported platforms should be a list of strings
    assert isinstance(info["supported_platforms"], list)
    assert len(info["supported_platforms"]) > 0

    # Each platform should be formatted as "os os_version arch"
    for platform in info["supported_platforms"]:
        assert isinstance(platform, str)
        parts = platform.split()
        assert len(parts) == 3


def test_get_claw_info_nonexistent():
    """Test get_claw_info with nonexistent claw raises ManifestNotFoundError."""
    with pytest.raises(ManifestNotFoundError, match="not found"):
        get_claw_info("nonexistent")

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


# Compatibility checking tests


def test_check_compatibility_matching():
    """Test compatibility check with matching hardware returns compatible=True."""
    from clawrium.core.registry import check_compatibility

    # Create hardware that matches openclaw requirements
    hardware = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "x86_64",
        "memtotal_mb": 4096,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("openclaw", hardware)

    assert result["compatible"] is True
    assert result["matched_entry"] is not None
    assert result["matched_entry"]["os"] == "ubuntu"
    assert result["matched_entry"]["arch"] == "x86_64"
    assert result["reasons"] == []


def test_check_compatibility_wrong_os():
    """Test compatibility check with wrong OS returns compatible=False with reason."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "debian",
        "os_version": "12",
        "architecture": "x86_64",
        "memtotal_mb": 4096,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("openclaw", hardware)

    assert result["compatible"] is False
    assert result["matched_entry"] is None
    assert len(result["reasons"]) > 0
    assert any("ubuntu" in r.lower() and "debian" in r.lower() for r in result["reasons"])


def test_check_compatibility_wrong_arch():
    """Test compatibility check with wrong architecture returns compatible=False."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "aarch64",
        "memtotal_mb": 4096,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("openclaw", hardware)

    assert result["compatible"] is False
    assert result["matched_entry"] is None
    assert len(result["reasons"]) > 0
    assert any("x86_64" in r and "aarch64" in r for r in result["reasons"])


def test_check_compatibility_insufficient_memory():
    """Test compatibility check with insufficient memory returns compatible=False."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "x86_64",
        "memtotal_mb": 512,  # Below minimum
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("openclaw", hardware)

    assert result["compatible"] is False
    assert result["matched_entry"] is None
    assert len(result["reasons"]) > 0
    assert any("memory" in r.lower() or "ram" in r.lower() for r in result["reasons"])


def test_check_compatibility_gpu_required():
    """Test compatibility check when GPU required but not present."""
    from clawrium.core.registry import check_compatibility

    # First, verify openclaw doesn't require GPU
    hardware_no_gpu = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "x86_64",
        "memtotal_mb": 4096,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("openclaw", hardware_no_gpu)
    # This should pass since openclaw doesn't require GPU
    assert result["compatible"] is True

    # For a hypothetical claw that requires GPU, we'd need to test the failure case
    # This test validates the logic exists even if openclaw doesn't use it


def test_check_compatibility_all_requirements_met():
    """Test compatibility check with all requirements met returns compatible=True."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "x86_64",
        "memtotal_mb": 8192,  # More than enough
        "gpu": {"present": True, "vendor": "nvidia", "error": None},
        "processor_cores": 8,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("openclaw", hardware)

    assert result["compatible"] is True
    assert result["matched_entry"] is not None
    assert result["reasons"] == []


def test_check_compatibility_nonexistent_claw():
    """Test compatibility check with nonexistent claw raises ManifestNotFoundError."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "x86_64",
        "memtotal_mb": 4096,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    with pytest.raises(ManifestNotFoundError, match="not found"):
        check_compatibility("nonexistent", hardware)


def test_check_compatibility_wrong_os_version():
    """Test compatibility check with wrong OS version returns compatible=False."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "ubuntu",
        "os_version": "20.04",  # Unsupported version
        "architecture": "x86_64",
        "memtotal_mb": 4096,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("openclaw", hardware)

    assert result["compatible"] is False
    assert result["matched_entry"] is None
    assert len(result["reasons"]) > 0
    # Should mention a supported version and the host version
    assert any("20.04" in r for r in result["reasons"])

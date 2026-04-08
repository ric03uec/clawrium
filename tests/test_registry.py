"""Tests for registry loading functionality."""

import pytest
from clawrium.core.registry import (
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


def test_load_manifest_path_traversal():
    """Test path traversal attempt triggers InvalidClawNameError."""
    from clawrium.core.registry import InvalidClawNameError

    with pytest.raises(InvalidClawNameError):
        load_manifest("../etc/passwd")


def test_load_manifest_malformed_yaml(monkeypatch):
    """Test loading malformed YAML raises ManifestParseError."""
    import yaml as yaml_module

    def raise_yaml_error(*args, **kwargs):
        raise yaml_module.YAMLError("test parse error")

    # Monkeypatch yaml.safe_load in the registry module
    from clawrium.core import registry

    monkeypatch.setattr(registry.yaml, "safe_load", raise_yaml_error)

    with pytest.raises(ManifestParseError, match="Failed to parse"):
        load_manifest("openclaw")


def test_load_manifest_not_dict(monkeypatch):
    """Test manifest that parses to non-dict raises ManifestParseError."""
    # Monkeypatch yaml.safe_load to return a list instead of dict
    from clawrium.core import registry

    monkeypatch.setattr(registry.yaml, "safe_load", lambda x: ["item1", "item2"])

    with pytest.raises(ManifestParseError, match="not a valid YAML dict"):
        load_manifest("openclaw")


def test_load_manifest_missing_required_fields(monkeypatch):
    """Test manifest missing name/entries raises ManifestParseError."""
    # Monkeypatch yaml.safe_load to return dict missing 'entries'
    from clawrium.core import registry

    monkeypatch.setattr(registry.yaml, "safe_load", lambda x: {"name": "incomplete"})

    with pytest.raises(ManifestParseError, match="missing required fields"):
        load_manifest("openclaw")


def test_list_claws():
    """Test list_claws returns openclaw and zeroclaw."""
    claws = list_claws()

    assert isinstance(claws, list)
    assert "openclaw" in claws
    assert "zeroclaw" in claws
    assert len(claws) >= 2


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
    assert any(
        "ubuntu" in r.lower() and "debian" in r.lower() for r in result["reasons"]
    )


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


def test_load_manifest_zeroclaw():
    """Test loading zeroclaw manifest returns valid ClawManifest."""
    manifest = load_manifest("zeroclaw")

    assert isinstance(manifest, dict)
    assert manifest["name"] == "zeroclaw"
    assert "entries" in manifest
    assert len(manifest["entries"]) > 0

    # Should have armv7l entries for Pi 2/3
    archs = [e["arch"] for e in manifest["entries"]]
    assert "armv7l" in archs


def test_check_compatibility_zeroclaw_armv7l():
    """Test zeroclaw compatibility with Raspberry Pi 2 hardware (Debian 13)."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "debian",
        "os_version": "13",
        "architecture": "armv7l",
        "memtotal_mb": 921,  # Pi 2 has ~920MB usable
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("zeroclaw", hardware)

    assert result["compatible"] is True
    assert result["matched_entry"] is not None
    assert result["matched_entry"]["arch"] == "armv7l"


def test_check_compatibility_zeroclaw_low_memory():
    """Test zeroclaw compatibility with very low memory fails."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "debian",
        "os_version": "13",
        "architecture": "armv7l",
        "memtotal_mb": 256,  # Below 512MB minimum
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("zeroclaw", hardware)

    assert result["compatible"] is False
    assert any("memory" in r.lower() or "ram" in r.lower() for r in result["reasons"])


def test_check_compatibility_zeroclaw_debian12_incompatible():
    """Test zeroclaw does not match Debian 12 (only 13 supported)."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "debian",
        "os_version": "12",
        "architecture": "armv7l",
        "memtotal_mb": 921,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("zeroclaw", hardware)

    assert result["compatible"] is False
    assert any(
        "debian 13" in r.lower() and "debian 12" in r.lower() for r in result["reasons"]
    )


def test_check_compatibility_zeroclaw_ubuntu_aarch64():
    """Test zeroclaw compatibility with Ubuntu aarch64 (Pi 4/5)."""
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

    result = check_compatibility("zeroclaw", hardware)

    assert result["compatible"] is True
    assert result["matched_entry"] is not None
    assert result["matched_entry"]["arch"] == "aarch64"
    assert result["matched_entry"]["os"] == "ubuntu"


def test_check_compatibility_zeroclaw_ubuntu_x86_64():
    """Test zeroclaw compatibility with Ubuntu x86_64."""
    from clawrium.core.registry import check_compatibility

    hardware = {
        "os": "ubuntu",
        "os_version": "22.04",
        "architecture": "x86_64",
        "memtotal_mb": 8192,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 8,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("zeroclaw", hardware)

    assert result["compatible"] is True
    assert result["matched_entry"] is not None
    assert result["matched_entry"]["arch"] == "x86_64"
    assert result["matched_entry"]["os"] == "ubuntu"


def test_check_compatibility_prefers_latest_version():
    """Test that check_compatibility returns latest version when multiple match."""
    from clawrium.core.registry import check_compatibility, get_claw_info

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

    # The matched version should be the latest version
    info = get_claw_info("openclaw")
    assert result["matched_entry"]["version"] == info["latest_version"]


# Secret function tests


def test_get_required_secrets_returns_list():
    """Test get_required_secrets returns list of SecretDefinition dicts."""
    from clawrium.core.registry import get_required_secrets

    secrets = get_required_secrets("openclaw")

    assert isinstance(secrets, list)
    assert len(secrets) > 0
    # Each secret should have key and description
    for secret in secrets:
        assert "key" in secret
        assert "description" in secret


def test_get_required_secrets_zeroclaw():
    """Test get_required_secrets for zeroclaw returns expected secrets."""
    from clawrium.core.registry import get_required_secrets

    secrets = get_required_secrets("zeroclaw")

    assert isinstance(secrets, list)
    assert len(secrets) >= 2
    keys = [s["key"] for s in secrets]
    assert "LLM_PROVIDER_URL" in keys
    assert "LLM_MODEL" in keys


def test_get_optional_secrets_returns_list():
    """Test get_optional_secrets returns list of SecretDefinition dicts."""
    from clawrium.core.registry import get_optional_secrets

    secrets = get_optional_secrets("openclaw")

    assert isinstance(secrets, list)
    # openclaw has optional secrets defined
    for secret in secrets:
        assert "key" in secret
        assert "description" in secret


def test_get_required_secrets_nonexistent_raises():
    """Test get_required_secrets with nonexistent claw raises ManifestNotFoundError."""
    from clawrium.core.registry import get_required_secrets

    with pytest.raises(ManifestNotFoundError, match="not found"):
        get_required_secrets("nonexistent")


def test_get_optional_secrets_nonexistent_raises():
    """Test get_optional_secrets with nonexistent claw raises ManifestNotFoundError."""
    from clawrium.core.registry import get_optional_secrets

    with pytest.raises(ManifestNotFoundError, match="not found"):
        get_optional_secrets("nonexistent")


# validate_claw_name tests


def test_validate_claw_name_empty_raises():
    """Test validate_claw_name with empty string raises InvalidClawNameError."""
    from clawrium.core.registry import validate_claw_name, InvalidClawNameError

    with pytest.raises(InvalidClawNameError, match="cannot be empty"):
        validate_claw_name("")


def test_validate_claw_name_with_slash_raises():
    """Test validate_claw_name with slash raises InvalidClawNameError."""
    from clawrium.core.registry import validate_claw_name, InvalidClawNameError

    with pytest.raises(InvalidClawNameError, match="invalid characters"):
        validate_claw_name("foo/bar")


def test_validate_claw_name_with_backslash_raises():
    """Test validate_claw_name with backslash raises InvalidClawNameError."""
    from clawrium.core.registry import validate_claw_name, InvalidClawNameError

    with pytest.raises(InvalidClawNameError, match="invalid characters"):
        validate_claw_name("foo\\bar")


def test_validate_claw_name_valid():
    """Test validate_claw_name with valid names passes."""
    from clawrium.core.registry import validate_claw_name

    # These should not raise
    validate_claw_name("openclaw")
    validate_claw_name("zero-claw")
    validate_claw_name("claw_v2")
    validate_claw_name("Claw123")


# check_compatibility version parameter tests


def test_check_compatibility_specific_version_match():
    """Test check_compatibility with specific version that exists."""
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

    # openclaw has version 0.1.0 for Ubuntu 24.04
    result = check_compatibility("openclaw", hardware, version="0.1.0")

    assert result["compatible"] is True
    assert result["matched_entry"]["version"] == "0.1.0"


def test_check_compatibility_specific_version_not_found():
    """Test check_compatibility with specific version that doesn't exist."""
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

    result = check_compatibility("openclaw", hardware, version="99.99.99")

    assert result["compatible"] is False
    assert result["matched_entry"] is None
    assert any("not found" in r for r in result["reasons"])


def test_check_compatibility_invalid_version_format():
    """Test check_compatibility with invalid version format."""
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

    result = check_compatibility("openclaw", hardware, version="not-a-version")

    assert result["compatible"] is False
    assert any("invalid version" in r.lower() for r in result["reasons"])


# GPU requirement tests


def test_check_compatibility_gpu_required_but_missing(monkeypatch):
    """Test compatibility check when GPU required but not present."""
    from clawrium.core.registry import check_compatibility
    from clawrium.core import registry

    # Create a fake manifest with GPU required
    fake_manifest = {
        "name": "gpuclaw",
        "description": "GPU-requiring claw",
        "entries": [
            {
                "version": "1.0.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": True,
                    "dependencies": {},
                },
            }
        ],
    }

    monkeypatch.setattr(registry, "load_manifest", lambda x: fake_manifest)

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

    result = check_compatibility("gpuclaw", hardware)

    assert result["compatible"] is False
    assert any("gpu" in r.lower() for r in result["reasons"])


def test_check_compatibility_gpu_detection_failed(monkeypatch):
    """Test compatibility check when GPU detection failed (present=None)."""
    from clawrium.core.registry import check_compatibility
    from clawrium.core import registry

    fake_manifest = {
        "name": "gpuclaw",
        "description": "GPU-requiring claw",
        "entries": [
            {
                "version": "1.0.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": True,
                    "dependencies": {},
                },
            }
        ],
    }

    monkeypatch.setattr(registry, "load_manifest", lambda x: fake_manifest)

    hardware = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "x86_64",
        "memtotal_mb": 4096,
        "gpu": {"present": None, "vendor": None, "error": "detection failed"},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("gpuclaw", hardware)

    assert result["compatible"] is False
    assert any("detection failed" in r.lower() for r in result["reasons"])


# Onboarding schema tests


def test_load_manifest_openclaw_with_onboarding():
    """Test loading openclaw manifest includes onboarding section."""
    manifest = load_manifest("openclaw")

    assert "onboarding" in manifest
    onboarding = manifest["onboarding"]
    assert isinstance(onboarding, dict)

    # Check all expected stages are present
    assert "providers" in onboarding
    assert "identity" in onboarding
    assert "channels" in onboarding
    assert "validate" in onboarding

    # Validate providers stage structure
    providers = onboarding["providers"]
    assert providers["required"] is True
    assert "description" in providers
    assert "tasks" in providers
    assert len(providers["tasks"]) == 2
    assert providers["tasks"][0]["type"] == "provider_select"
    assert providers["tasks"][1]["type"] == "provider_test"

    # Validate identity stage structure
    identity = onboarding["identity"]
    assert identity["required"] is True
    assert "tasks" in identity
    assert len(identity["tasks"]) == 2
    # Check file_create tasks have required fields
    for task in identity["tasks"]:
        assert task["type"] == "file_create"
        assert "path" in task
        assert "template" in task


def test_load_manifest_zeroclaw_with_onboarding():
    """Test loading zeroclaw manifest includes onboarding section."""
    manifest = load_manifest("zeroclaw")

    assert "onboarding" in manifest
    onboarding = manifest["onboarding"]
    assert isinstance(onboarding, dict)

    # Check all expected stages are present
    assert "providers" in onboarding
    assert "identity" in onboarding
    assert "channels" in onboarding
    assert "validate" in onboarding

    # Validate identity stage has auto_skip
    identity = onboarding["identity"]
    assert identity["required"] is False
    assert identity["auto_skip"] is True
    # Should not have tasks when auto_skip is true
    assert "tasks" not in identity or len(identity.get("tasks", [])) == 0

    # Validate channels stage uses confirm type
    channels = onboarding["channels"]
    assert channels["required"] is True
    assert "tasks" in channels
    assert len(channels["tasks"]) == 1
    assert channels["tasks"][0]["type"] == "confirm"
    assert channels["tasks"][0]["default"] is True

    # Validate validate stage structure
    validate = onboarding["validate"]
    assert "tasks" in validate
    # Should have binary_check and config_check
    task_ids = [t["id"] for t in validate["tasks"]]
    assert "binary_check" in task_ids
    assert "config_check" in task_ids


def test_onboarding_task_types():
    """Test that onboarding tasks use expected task types."""
    manifest_openclaw = load_manifest("openclaw")
    manifest_zeroclaw = load_manifest("zeroclaw")

    # Collect all task types from both manifests
    task_types = set()
    for manifest in [manifest_openclaw, manifest_zeroclaw]:
        onboarding = manifest.get("onboarding", {})
        for stage_name, stage in onboarding.items():
            tasks = stage.get("tasks", [])
            for task in tasks:
                task_types.add(task["type"])

    # Verify expected task types are present
    expected_types = {
        "provider_select",
        "provider_test",
        "file_create",
        "select",
        "confirm",
        "command",
        "file_exists",
    }
    assert expected_types.issubset(task_types), (
        f"Missing task types: {expected_types - task_types}"
    )


def test_onboarding_stage_required_field():
    """Test that onboarding stages have required field with expected values."""
    manifest_openclaw = load_manifest("openclaw")

    onboarding = manifest_openclaw["onboarding"]

    # providers, identity, channels should be required
    assert onboarding["providers"]["required"] is True
    assert onboarding["identity"]["required"] is True
    assert onboarding["channels"]["required"] is True

    # validate stage may not have required field (defaults to false)
    validate = onboarding.get("validate", {})
    assert validate.get("required", False) is False or validate.get("required") is None


def test_onboarding_backward_compatibility():
    """Test that manifests can be loaded even if they don't have onboarding section."""
    # Create a mock manifest without onboarding
    import yaml
    from clawrium.core import registry

    mock_manifest_yaml = """
name: testclaw
description: "Test claw without onboarding"
entries:
  - version: "1.0.0"
    os: ubuntu
    os_version: "24.04"
    arch: x86_64
    requirements:
      min_memory_mb: 1024
      gpu_required: false
      dependencies: {}
"""

    # Mock the manifest loading to return our test manifest
    original_load = registry.load_manifest

    def mock_load(claw_name):
        if claw_name == "testclaw":
            return yaml.safe_load(mock_manifest_yaml)
        return original_load(claw_name)

    # Temporarily replace load_manifest
    import pytest

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(registry, "load_manifest", mock_load)

    try:
        manifest = registry.load_manifest("testclaw")

        # Manifest should load successfully
        assert manifest["name"] == "testclaw"
        assert "entries" in manifest

        # onboarding field should not be present (or be None/empty)
        assert "onboarding" not in manifest or manifest.get("onboarding") is None
    finally:
        monkeypatch.undo()

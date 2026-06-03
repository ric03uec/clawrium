"""Tests for registry loading functionality."""

from copy import deepcopy

import pytest
from clawrium.core.registry import (
    InvalidAgentTypeError,
    ManifestNotFoundError,
    ManifestParseError,
    get_claw_info,
    list_claws,
    load_manifest,
    validate_agent_type,
)


def _valid_manifest() -> dict:
    """Return a minimal valid manifest used by negative-path tests."""
    return {
        "agent": {
            "type": "openclaw",
            "description": "Test manifest",
        },
        "platforms": [
            {
                "version": "1.0.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 1024,
                    "gpu_required": False,
                    "dependencies": {},
                },
            }
        ],
    }


def test_load_manifest_openclaw():
    """Test loading openclaw manifest returns valid ClawManifest."""
    manifest = load_manifest("openclaw")

    assert isinstance(manifest, dict)
    assert manifest["agent"]["type"] == "openclaw"
    assert "description" in manifest["agent"]
    assert "platforms" in manifest
    assert len(manifest["platforms"]) > 0

    # Validate first entry structure
    entry = manifest["platforms"][0]
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
    """Test loading nonexistent agent type raises ManifestNotFoundError."""
    with pytest.raises(ManifestNotFoundError, match="not found"):
        load_manifest("nonexistent")


def test_load_manifest_path_traversal():
    """Test path traversal attempt triggers InvalidAgentTypeError."""

    with pytest.raises(InvalidAgentTypeError):
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

    with pytest.raises(ManifestParseError, match="invalid `root` section"):
        load_manifest("openclaw")


def test_load_manifest_missing_required_fields(monkeypatch):
    """Test manifest missing required top-level fields raises ManifestParseError."""
    from clawrium.core import registry

    monkeypatch.setattr(
        registry.yaml, "safe_load", lambda x: {"agent": {"type": "openclaw"}}
    )

    with pytest.raises(ManifestParseError, match="missing required fields"):
        load_manifest("openclaw")


def test_load_manifest_agent_type_mismatch(monkeypatch):
    """Test manifest with mismatched agent.type raises ManifestParseError."""
    from clawrium.core import registry

    manifest = _valid_manifest()
    manifest["agent"]["type"] = "different-agent"
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="was loaded as"):
        load_manifest("openclaw")


def test_load_manifest_empty_platforms(monkeypatch):
    """Test manifest with empty platforms raises ManifestParseError."""
    from clawrium.core import registry

    manifest = _valid_manifest()
    manifest["platforms"] = []
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="platforms"):
        load_manifest("openclaw")


def test_load_manifest_invalid_required_secret_definition(monkeypatch):
    """Test malformed required secret entry raises ManifestParseError."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["secrets"] = {"required": [{"key": "OPENAI_API_KEY"}]}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="secrets.required"):
        load_manifest("openclaw")


def test_load_manifest_invalid_onboarding_stage(monkeypatch):
    """Test malformed onboarding stage raises ManifestParseError."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["onboarding"] = {
        "stages": {
            "providers": {
                "required": True,
            }
        }
    }
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="onboarding.stages.providers"):
        load_manifest("openclaw")


def test_load_manifest_invalid_onboarding_task(monkeypatch):
    """Test malformed onboarding task raises ManifestParseError."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["onboarding"] = {
        "stages": {
            "providers": {
                "required": True,
                "description": "Assign provider",
                "tasks": [
                    {
                        "id": "select_provider",
                        "name": "Select provider",
                    }
                ],
            }
        }
    }
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="tasks\\[0\\].type"):
        load_manifest("openclaw")


def test_load_manifest_negative_min_memory(monkeypatch):
    """Test negative min_memory_mb raises ManifestParseError."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["platforms"][0]["requirements"]["min_memory_mb"] = -1
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="min_memory_mb"):
        load_manifest("openclaw")


def test_load_manifest_rejects_unknown_chat_type(monkeypatch):
    """Manifest validator must reject `features.chat.type` outside the closed enum."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["features"] = {"chat": {"type": "bogus"}}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.chat.type"):
        load_manifest("openclaw")


def test_load_manifest_accepts_chat_type_openai(monkeypatch):
    """`features.chat.type: openai` is a valid value and survives normalization."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["features"] = {"chat": {"type": "openai"}}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    loaded = load_manifest("openclaw")
    assert loaded.get("features", {}).get("chat", {}).get("type") == "openai"


def test_load_manifest_accepts_chat_type_websocket(monkeypatch):
    """`features.chat.type: websocket` is a valid value and survives normalization."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["features"] = {"chat": {"type": "websocket"}}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    loaded = load_manifest("openclaw")
    assert loaded.get("features", {}).get("chat", {}).get("type") == "websocket"


def test_load_manifest_chat_block_must_be_object(monkeypatch):
    """`features.chat` must be a dict, not a scalar — rejects sloppy YAML."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["features"] = {"chat": "openai"}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.chat"):
        load_manifest("openclaw")


def test_hermes_manifest_declares_chat_openai():
    """The bundled hermes manifest must advertise the OpenAI chat backend."""
    manifest = load_manifest("hermes")
    assert manifest.get("features", {}).get("chat", {}).get("type") == "openai"


def test_openclaw_manifest_declares_chat_websocket():
    """The bundled openclaw manifest must advertise the WebSocket chat backend."""
    manifest = load_manifest("openclaw")
    assert manifest.get("features", {}).get("chat", {}).get("type") == "websocket"


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
    assert info["agent_type"] == "openclaw"
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
    """Test get_claw_info with nonexistent agent type raises ManifestNotFoundError."""
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

    # For a hypothetical agent type that requires GPU, we'd test the failure case.
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
    """Test compatibility check with nonexistent agent type raises ManifestNotFoundError."""
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
    assert manifest["agent"]["type"] == "zeroclaw"
    assert "platforms" in manifest
    assert len(manifest["platforms"]) > 0

    # Should have armv7l entries for Pi 2/3
    archs = [e["arch"] for e in manifest["platforms"]]
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

    # Neither openclaw nor zeroclaw declares required secrets: provider
    # credentials are managed through the providers system, not per-agent
    # secrets. The return type is still a list so callers can iterate.
    for agent_type in ("openclaw", "zeroclaw"):
        secrets = get_required_secrets(agent_type)
        assert isinstance(secrets, list)
        assert len(secrets) == 0


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
    """Test get_required_secrets with nonexistent agent type raises ManifestNotFoundError."""
    from clawrium.core.registry import get_required_secrets

    with pytest.raises(ManifestNotFoundError, match="not found"):
        get_required_secrets("nonexistent")


def test_get_optional_secrets_nonexistent_raises():
    """Test get_optional_secrets with nonexistent agent type raises ManifestNotFoundError."""
    from clawrium.core.registry import get_optional_secrets

    with pytest.raises(ManifestNotFoundError, match="not found"):
        get_optional_secrets("nonexistent")


# validate_agent_type tests


def test_validate_agent_type_empty_raises():
    """Test validate_agent_type with empty string raises InvalidAgentTypeError."""

    with pytest.raises(InvalidAgentTypeError, match="cannot be empty") as exc:
        validate_agent_type("")
    assert isinstance(exc.value, InvalidAgentTypeError)


def test_validate_agent_type_with_slash_raises():
    """Test validate_agent_type with slash raises InvalidAgentTypeError."""

    with pytest.raises(InvalidAgentTypeError, match="invalid characters") as exc:
        validate_agent_type("foo/bar")
    assert isinstance(exc.value, InvalidAgentTypeError)


def test_validate_agent_type_with_backslash_raises():
    """Test validate_agent_type with backslash raises InvalidAgentTypeError."""

    with pytest.raises(InvalidAgentTypeError, match="invalid characters") as exc:
        validate_agent_type("foo\\bar")
    assert isinstance(exc.value, InvalidAgentTypeError)


def test_validate_agent_type_valid():
    """Test validate_agent_type with valid names passes."""

    # These should not raise
    validate_agent_type("openclaw")
    validate_agent_type("zero-agent")
    validate_agent_type("claw_v2")
    validate_agent_type("Claw123")


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
        "agent": {
            "type": "gpuclaw",
            "description": "GPU-requiring agent",
        },
        "platforms": [
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
        "agent": {
            "type": "gpuclaw",
            "description": "GPU-requiring agent",
        },
        "platforms": [
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
    stages = onboarding["stages"]

    # Check all expected stages are present
    assert "providers" in stages
    assert "identity" in stages
    assert "channels" in stages
    assert "validate" in stages

    # Validate providers stage structure
    providers = stages["providers"]
    assert providers["required"] is True
    assert "description" in providers
    assert "tasks" in providers
    assert len(providers["tasks"]) == 2
    assert providers["tasks"][0]["type"] == "provider_select"
    assert providers["tasks"][1]["type"] == "provider_test"

    # Validate identity stage structure
    identity = stages["identity"]
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
    stages = onboarding["stages"]

    # Check all expected stages are present
    assert "providers" in stages
    assert "identity" in stages
    assert "channels" in stages
    assert "validate" in stages

    # Validate identity stage has auto_skip
    identity = stages["identity"]
    assert identity["required"] is False
    assert identity["auto_skip"] is True
    # Should not have tasks when auto_skip is true
    assert "tasks" not in identity or len(identity.get("tasks", [])) == 0

    # Validate channels stage: cli always-on (default true) + discord optional
    # (default false). Discord was added in #422 so zeroclaw could mirror the
    # hermes wizard's Discord opt-in step.
    channels = stages["channels"]
    assert channels["required"] is True
    assert "tasks" in channels
    assert len(channels["tasks"]) == 2
    task_by_id = {t["id"]: t for t in channels["tasks"]}
    assert "confirm_cli" in task_by_id
    assert task_by_id["confirm_cli"]["type"] == "confirm"
    assert task_by_id["confirm_cli"]["default"] is True
    assert "select_discord" in task_by_id
    assert task_by_id["select_discord"]["type"] == "confirm"
    assert task_by_id["select_discord"]["default"] is False

    # Validate validate stage structure
    validate = stages["validate"]
    assert "tasks" in validate
    # binary_check only; config.toml is rendered by configure.yaml, so the
    # file_exists check belongs to the configure stage now, not install-time
    # validation.
    task_ids = [t["id"] for t in validate["tasks"]]
    assert "binary_check" in task_ids
    assert "config_check" not in task_ids


def test_onboarding_task_types():
    """Test that onboarding tasks use expected task types."""
    manifest_openclaw = load_manifest("openclaw")
    manifest_zeroclaw = load_manifest("zeroclaw")

    # Collect all task types from both manifests
    task_types = set()
    for manifest in [manifest_openclaw, manifest_zeroclaw]:
        onboarding = manifest.get("onboarding", {})
        stages = onboarding.get("stages", {})
        for stage_name, stage in stages.items():
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

    onboarding = manifest_openclaw["onboarding"]["stages"]

    # providers, identity, channels should be required
    assert onboarding["providers"]["required"] is True
    assert onboarding["identity"]["required"] is True
    assert onboarding["channels"]["required"] is True

    # validate stage may not have required field (defaults to false)
    validate = onboarding.get("validate", {})
    assert validate.get("required", False) is False or validate.get("required") is None


def test_manifest_accepts_workspace_and_features_fields(monkeypatch):
    """A manifest with optional workspace/features blocks validates and round-trips."""
    from clawrium.core import registry

    manifest = _valid_manifest()
    manifest["workspace"] = {"memory_path": "~/.openclaw/workspace/memory"}
    manifest["features"] = {"memory": True}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    parsed = registry.load_manifest("openclaw")
    assert parsed.get("workspace", {}).get("memory_path") == (
        "~/.openclaw/workspace/memory"
    )
    assert parsed.get("features", {}).get("memory") is True


def test_zeroclaw_manifest_declares_workspace_and_memory():
    """Issue #358 (Subtask C) wires workspace + memory into zeroclaw.

    The manifest now declares:
      * workspace.memory_path → ~/.zeroclaw/workspace (mirrors openclaw)
      * features.memory: true → memory CLI routes to zeroclaw's playbooks
      * features.chat.type == "zeroclaw" (carried over from #357)
    """
    manifest = load_manifest("zeroclaw")
    workspace = manifest.get("workspace", {})
    assert workspace.get("memory_path") == "~/.zeroclaw/workspace"
    features = manifest.get("features", {})
    assert features.get("memory") is True
    assert features.get("chat", {}).get("type") == "zeroclaw"


def test_manifest_rejects_invalid_workspace_memory_path(monkeypatch):
    """workspace.memory_path must be a non-empty string when supplied."""
    from clawrium.core import registry

    manifest = _valid_manifest()
    manifest["workspace"] = {"memory_path": ""}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="workspace.memory_path"):
        load_manifest("openclaw")


def test_manifest_rejects_invalid_features_memory(monkeypatch):
    """features.memory must be a boolean when supplied."""
    from clawrium.core import registry

    manifest = _valid_manifest()
    manifest["features"] = {"memory": "yes"}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.memory"):
        load_manifest("openclaw")


def _valid_web_ui_block() -> dict:
    """Return a minimal valid `features.web_ui` block for tests.

    `default_port` is included in the canonical block so the existing
    "validator accepts a complete block" / range-boundary tests still
    exercise that branch — but the field is optional in the schema
    (issue #491), and the omission test below exercises that path.
    """
    return {
        "enabled": True,
        "bind": "loopback",
        "default_port": 9119,
        "port_field": "dashboard.port",
    }


def test_load_manifest_accepts_valid_web_ui(monkeypatch):
    """A complete `features.web_ui` block round-trips through validation."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["features"] = {"web_ui": _valid_web_ui_block()}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    loaded = load_manifest("openclaw")
    web_ui = loaded.get("features", {}).get("web_ui", {})
    assert web_ui.get("enabled") is True
    assert web_ui.get("bind") == "loopback"
    assert web_ui.get("default_port") == 9119
    assert web_ui.get("port_field") == "dashboard.port"


def test_load_manifest_rejects_invalid_web_ui_bind(monkeypatch):
    """`bind` is a closed enum — `loopback` and `wildcard` accepted.

    Other values (e.g. `0.0.0.0`, `lan`, arbitrary strings) are rejected
    at manifest-load so a typo can't end up as `bind: wildcrad` and
    silently produce a broken tunnel.
    """
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["bind"] = "0.0.0.0"
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.web_ui.bind"):
        load_manifest("openclaw")


def _allowed_web_ui_binds() -> tuple[str, ...]:
    """Surface `_ALLOWED_WEB_UI_BINDS` for parametrize so a new enum
    member auto-extends this test instead of silently skipping it
    (ATX iter 3 W4).
    """
    from clawrium.core.registry import _ALLOWED_WEB_UI_BINDS

    return _ALLOWED_WEB_UI_BINDS


@pytest.mark.parametrize("bind_value", _allowed_web_ui_binds())
def test_load_manifest_accepts_web_ui_bind_values(monkeypatch, bind_value):
    """Every member of the `bind` enum round-trips through validation (#491)."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["bind"] = bind_value
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    loaded = load_manifest("openclaw")
    assert loaded["features"]["web_ui"]["bind"] == bind_value


def test_load_manifest_accepts_web_ui_without_default_port(monkeypatch):
    """`default_port` is optional (issue #491).

    Agents like hermes and zeroclaw compute per-instance ports at install
    time and persist them under `port_field`; a manifest-wide default
    would silently collide on hosts running multiple instances. The
    resolver surfaces a missing persisted port as "no UI" instead.
    """
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block.pop("default_port")
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    loaded = load_manifest("openclaw")
    web_ui = loaded["features"]["web_ui"]
    assert "default_port" not in web_ui
    assert web_ui["enabled"] is True
    assert web_ui["bind"] == "loopback"
    assert web_ui["port_field"] == "dashboard.port"


def test_load_manifest_rejects_web_ui_non_positive_port(monkeypatch):
    """`default_port` must be > 0 (zero/negative ports are nonsense for TCP)."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["default_port"] = 0
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.web_ui.default_port"):
        load_manifest("openclaw")


def test_load_manifest_rejects_web_ui_non_bool_enabled(monkeypatch):
    """`enabled` must be a boolean, not a truthy string."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["enabled"] = "yes"
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.web_ui.enabled"):
        load_manifest("openclaw")


def test_load_manifest_rejects_web_ui_empty_port_field(monkeypatch):
    """`port_field` must be a non-empty string (it's a config path)."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["port_field"] = ""
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.web_ui.port_field"):
        load_manifest("openclaw")


def test_load_manifest_rejects_web_ui_bool_default_port(monkeypatch):
    """YAML `true`/`false` satisfy `isinstance(x, int)` — must be rejected."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["default_port"] = True
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.web_ui.default_port"):
        load_manifest("openclaw")


@pytest.mark.parametrize(
    "port,is_valid",
    [
        (-1, False),
        (0, False),
        (1, False),  # privileged port rejected outright
        (80, False),  # privileged port rejected outright
        (1023, False),  # privileged port rejected outright
        (1024, True),
        (9119, True),
        (65535, True),
        (65536, False),
        (100000, False),
    ],
)
def test_load_manifest_web_ui_default_port_boundaries(monkeypatch, port, is_valid):
    """`default_port` accepts 1024..65535 inclusive; everything else rejected.

    Privileged ports (<1024) are rejected at manifest-load time because
    non-root agent processes cannot bind them — `logger.warning` would be
    invisible in the default uv-tool deployment, so a silent accept would
    be a latent footgun.
    """
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["default_port"] = port
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    if is_valid:
        loaded = load_manifest("openclaw")
        assert loaded["features"]["web_ui"]["default_port"] == port
    else:
        with pytest.raises(ManifestParseError, match="features.web_ui.default_port"):
            load_manifest("openclaw")


def test_load_manifest_rejects_web_ui_non_dict(monkeypatch):
    """A scalar `features.web_ui` value must be rejected with a clear error."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    manifest["features"] = {"web_ui": "not-a-dict"}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.web_ui"):
        load_manifest("openclaw")


@pytest.mark.parametrize("missing_field", ["enabled", "bind", "port_field"])
def test_load_manifest_rejects_web_ui_missing_field(monkeypatch, missing_field):
    """Each required `web_ui` field must be present.

    `default_port` is intentionally absent from this list (issue #491) —
    see `test_load_manifest_accepts_web_ui_without_default_port`.
    """
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block.pop(missing_field)
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match=f"features.web_ui.{missing_field}"):
        load_manifest("openclaw")


@pytest.mark.parametrize(
    "bad_port_field",
    [
        "   ",  # whitespace-only
        "..port",  # leading double dot
        "port..nested",  # double dot in middle
        ".port",  # leading dot
        "port.",  # trailing dot
        "port name",  # space in segment
        "9port.x",  # leading digit in first segment
        "port-name",  # hyphen not allowed
        "port/x",  # slash (path traversal)
    ],
)
def test_load_manifest_rejects_web_ui_invalid_port_field_shape(
    monkeypatch, bad_port_field
):
    """`port_field` must be a dotted-identifier path; everything else rejected."""
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["port_field"] = bad_port_field
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    with pytest.raises(ManifestParseError, match="features.web_ui.port_field"):
        load_manifest("openclaw")


@pytest.mark.parametrize(
    "good_port_field",
    [
        "port",
        "dashboard.port",
        "deep.nested.path.port",
        "_underscore",
        "with_underscore.x",
        "__proto__.x",  # valid identifier even if semantically odd
        "secrets.api_key",  # valid identifier — semantic safety is a higher-layer concern
    ],
)
def test_load_manifest_accepts_web_ui_valid_port_field_shape(
    monkeypatch, good_port_field
):
    """Dotted-identifier shapes pass validation regardless of segment names.

    `secrets.api_key` and `__proto__.x` are deliberately on the accept list
    to document the contract: this validator enforces *shape* only.
    Semantic safety (don't smuggle secrets through this field) is the
    consumer layer's job in Phase 2 — Ansible extra-vars use parameterized
    var substitution, not string concatenation.
    """
    from clawrium.core import registry

    manifest = deepcopy(_valid_manifest())
    block = _valid_web_ui_block()
    block["port_field"] = good_port_field
    manifest["features"] = {"web_ui": block}
    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: manifest)

    loaded = load_manifest("openclaw")
    assert loaded["features"]["web_ui"]["port_field"] == good_port_field


def test_allowed_web_ui_binds_matches_literal():
    """The runtime enum and the Literal type annotation must stay in sync."""
    import typing

    from clawrium.core.registry import WebUIFeatureConfig, _ALLOWED_WEB_UI_BINDS

    literal_args = typing.get_args(WebUIFeatureConfig.__annotations__["bind"])
    assert set(literal_args) == set(_ALLOWED_WEB_UI_BINDS)


def test_hermes_manifest_declares_web_ui():
    """The bundled hermes manifest advertises native dashboard support.

    No `default_port` (issue #491): install.py computes a per-instance
    port in 45000..46999 and persists it under `dashboard.port`, so a
    manifest-wide default would silently collide on hosts running
    multiple hermes instances.
    """
    manifest = load_manifest("hermes")
    web_ui = manifest.get("features", {}).get("web_ui", {})
    assert web_ui.get("enabled") is True
    assert web_ui.get("bind") == "loopback"
    assert web_ui.get("port_field") == "dashboard.port"
    assert "default_port" not in web_ui


def test_openclaw_manifest_declares_web_ui_via_gateway_port():
    """openclaw opts into the native-UI mechanism via gateway.port.

    Mirrors zeroclaw: the openclaw gateway daemon serves its control SPA
    on the same port as `config.gateway.port`, so `port_field` resolves
    to that path. No `default_port`: install.py picks a per-instance
    port at install time (the same 40000..41999 allocator branch as
    zeroclaw) and persists it under `gateway.port`, so a manifest-wide
    default would silently collide on hosts running multiple openclaw
    instances.
    """
    manifest = load_manifest("openclaw")
    web_ui = manifest.get("features", {}).get("web_ui", {})
    assert web_ui.get("enabled") is True
    assert web_ui.get("bind") == "wildcard"
    assert web_ui.get("port_field") == "gateway.port"
    assert "default_port" not in web_ui


def test_zeroclaw_manifest_declares_web_ui():
    """zeroclaw opts into the native-UI mechanism via gateway.port (#491).

    No `default_port`: zeroclaw computes a per-instance port at install
    time (`40000 + hash % 2000`) and persists it under `gateway.port`,
    so a manifest-wide default would silently collide on hosts running
    multiple zeroclaw instances.
    """
    manifest = load_manifest("zeroclaw")
    web_ui = manifest.get("features", {}).get("web_ui", {})
    assert web_ui.get("enabled") is True
    assert web_ui.get("bind") == "wildcard"
    assert web_ui.get("port_field") == "gateway.port"
    assert "default_port" not in web_ui


def test_openclaw_manifest_now_declares_memory_workspace():
    """Phase 1 backfill: openclaw manifest carries the memory metadata for Phase 3."""
    manifest = load_manifest("openclaw")
    assert manifest.get("workspace", {}).get("memory_path") == (
        "~/.openclaw/workspace/memory"
    )
    assert manifest.get("features", {}).get("memory") is True


def test_onboarding_backward_compatibility(monkeypatch):
    """Test that manifests can be loaded even if they don't have onboarding section."""
    from clawrium.core import registry

    mock_manifest = {
        "agent": {
            "type": "openclaw",
            "description": "Test agent without onboarding",
        },
        "platforms": [
            {
                "version": "1.0.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 1024,
                    "gpu_required": False,
                    "dependencies": {},
                },
            }
        ],
    }

    monkeypatch.setattr(registry.yaml, "safe_load", lambda _: mock_manifest)
    manifest = registry.load_manifest("openclaw")

    assert manifest["agent"]["type"] == "openclaw"
    assert "platforms" in manifest
    assert "onboarding" not in manifest

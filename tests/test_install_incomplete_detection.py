"""Tests for incomplete installation detection during install retries."""

from unittest.mock import Mock

import pytest


def _setup_common(monkeypatch, tmp_path, host_record: dict) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "sha256": "abc123",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"python": ">=3.9"},
                },
            }
        ],
    }

    import clawrium.core.install

    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)
    monkeypatch.setattr(
        clawrium.core.install,
        "check_compatibility",
        lambda *args, **kwargs: {
            "compatible": True,
            "matched_entry": mock_manifest["entries"][0],
            "reasons": [],
        },
    )
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: host_record)

    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")
    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda x: key_file
    )
    monkeypatch.setattr(
        clawrium.core.install,
        "update_host",
        lambda h, u: u(clawrium.core.install.get_host(h)),
    )
    monkeypatch.setattr(
        clawrium.core.install, "initialize_onboarding", lambda h, c: True
    )

    class SuccessfulResult:
        status = "successful"

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", Mock(return_value=SuccessfulResult()))


def test_detect_incomplete_installing(monkeypatch, tmp_path):
    from clawrium.core.install import IncompleteInstallationError, run_installation

    host = {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
        "agents": {
            "openclaw": {
                "status": "installing",
                "installed_at": None,
                "error": None,
                "agent_name": "work-assistant",
                "version": "0.1.0",
            }
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    with pytest.raises(IncompleteInstallationError) as exc_info:
        run_installation("openclaw", "test-host")

    assert exc_info.value.details["status"] == "installing"
    assert exc_info.value.details["agent_name"] == "work-assistant"


def test_detect_incomplete_failed(monkeypatch, tmp_path):
    from clawrium.core.install import run_installation

    host = {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
        "agents": {
            "openclaw": {
                "status": "failed",
                "installed_at": None,
                "error": "base playbook failed",
                "agent_name": "work-assistant",
                "version": "0.1.0",
            }
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    result = run_installation("openclaw", "test-host")
    assert result["success"] is True
    assert result["incomplete_installation"]["status"] == "failed"


def test_detect_incomplete_installed_without_timestamp(monkeypatch, tmp_path):
    from clawrium.core.install import run_installation

    host = {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
        "agents": {
            "openclaw": {
                "status": "installed",
                "installed_at": None,
                "error": None,
                "agent_name": "work-assistant",
                "version": "0.1.0",
            }
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    result = run_installation("openclaw", "test-host")
    assert result["success"] is True
    assert result["incomplete_installation"]["status"] == "installed"


def test_no_detection_for_installed(monkeypatch, tmp_path):
    from clawrium.core.install import run_installation

    host = {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
        "agents": {
            "openclaw": {
                "status": "installed",
                "installed_at": "2026-04-10T00:00:00+00:00",
                "error": None,
                "agent_name": "existing-agent",
                "version": "0.1.0",
            }
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    result = run_installation("openclaw", "test-host")
    assert result["success"] is True
    assert result["incomplete_installation"] is None

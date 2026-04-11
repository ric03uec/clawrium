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

    # Agents are keyed by agent_name, with "type" field indicating claw type
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
            "work-assistant": {
                "type": "openclaw",
                "status": "installing",
                "installed_at": None,
                "error": None,
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

    # Agents are keyed by agent_name, with "type" field indicating claw type
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
            "work-assistant": {
                "type": "openclaw",
                "status": "failed",
                "installed_at": None,
                "error": "base playbook failed",
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

    # Agents are keyed by agent_name, with "type" field indicating claw type
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
            "work-assistant": {
                "type": "openclaw",
                "status": "installed",
                "installed_at": None,
                "error": None,
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

    # Agents are keyed by agent_name, with "type" field indicating claw type
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
            "existing-agent": {
                "type": "openclaw",
                "status": "installed",
                "installed_at": "2026-04-10T00:00:00+00:00",
                "error": None,
                "version": "0.1.0",
            }
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    result = run_installation("openclaw", "test-host")
    assert result["success"] is True
    assert result["incomplete_installation"] is None

def test_resume_multiple_incomplete_raises_error(monkeypatch, tmp_path):
    """B7: Resume with multiple incomplete installations should raise error."""
    from clawrium.core.install import InstallationError, run_installation

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
            "work-assistant": {
                "type": "openclaw",
                "status": "installing",
                "installed_at": None,
                "error": None,
                "version": "0.1.0",
            },
            "home-assistant": {
                "type": "openclaw",
                "status": "installing",
                "installed_at": None,
                "error": None,
                "version": "0.1.0",
            },
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    with pytest.raises(InstallationError) as exc_info:
        run_installation("openclaw", "test-host", resume=True)

    assert "Multiple incomplete installations" in str(exc_info.value)
    assert "work-assistant" in str(exc_info.value)
    assert "home-assistant" in str(exc_info.value)


def test_cleanup_multiple_incomplete_installations(monkeypatch, tmp_path):
    """B6: Cleanup should remove ALL incomplete installations."""
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
            "work-assistant": {
                "type": "openclaw",
                "status": "failed",
                "installed_at": None,
                "error": "some error",
                "version": "0.1.0",
            },
            "home-assistant": {
                "type": "openclaw",
                "status": "installing",
                "installed_at": None,
                "error": None,
                "version": "0.1.0",
            },
        },
    }

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

    host_state = [host.copy()]
    host_state[0]["agents"] = host["agents"].copy()

    def mock_get_host(_):
        return host_state[0]

    def mock_update_host(_, updater):
        host_state[0] = updater(host_state[0])
        return True

    monkeypatch.setattr(clawrium.core.install, "get_host", mock_get_host)
    monkeypatch.setattr(clawrium.core.install, "update_host", mock_update_host)

    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")
    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda _: key_file
    )
    monkeypatch.setattr(
        clawrium.core.install, "initialize_onboarding", lambda h, c: True
    )

    # Mock secrets functions
    monkeypatch.setattr("clawrium.core.secrets.load_secrets", lambda: {})
    monkeypatch.setattr("clawrium.core.secrets.save_secrets", lambda x: None)

    class SuccessfulResult:
        status = "successful"

    import ansible_runner
    monkeypatch.setattr(ansible_runner, "run", Mock(return_value=SuccessfulResult()))

    result = run_installation("openclaw", "test-host", cleanup_failed=True)

    assert result["success"] is True
    # Both old agents should be removed
    assert "work-assistant" not in host_state[0]["agents"]
    assert "home-assistant" not in host_state[0]["agents"]
    # A new agent should be created
    new_agents = [k for k, v in host_state[0]["agents"].items() if v.get("type") == "openclaw"]
    assert len(new_agents) == 1


def test_cannot_resume_from_failed_state(monkeypatch, tmp_path):
    """B6 state validation: Resume from failed state should raise error."""
    from clawrium.core.install import InstallationError, run_installation

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
            "work-assistant": {
                "type": "openclaw",
                "status": "failed",
                "installed_at": None,
                "error": "playbook failed",
                "version": "0.1.0",
            },
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    with pytest.raises(InstallationError) as exc_info:
        run_installation("openclaw", "test-host", resume=True)

    assert "Cannot resume from 'failed' state" in str(exc_info.value)


def test_cannot_resume_from_installed_without_timestamp(monkeypatch, tmp_path):
    """B6 state validation: Resume from installed state (incomplete) should raise error."""
    from clawrium.core.install import InstallationError, run_installation

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
            "work-assistant": {
                "type": "openclaw",
                "status": "installed",
                "installed_at": None,  # Incomplete - installed but no timestamp
                "error": None,
                "version": "0.1.0",
            },
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    with pytest.raises(InstallationError) as exc_info:
        run_installation("openclaw", "test-host", resume=True)

    assert "Cannot resume from 'installed' state" in str(exc_info.value)

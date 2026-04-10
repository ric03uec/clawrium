"""Tests for interactive prompts when handling incomplete installations."""

from unittest.mock import Mock, patch

import pytest


def _setup_common(monkeypatch, tmp_path, host_record: dict) -> None:
    """Setup common mocks for installation tests."""
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
        clawrium.core.install, "initialize_onboarding", lambda h, c: True
    )

    class SuccessfulResult:
        status = "successful"

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", Mock(return_value=SuccessfulResult()))


def test_prompt_resume_incomplete(monkeypatch, tmp_path):
    """Test that user can resume installation with existing agent name."""
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
                "status": "installing",
                "installed_at": None,
                "error": None,
                "agent_name": "work-assistant",
                "version": "0.1.0",
            }
        },
    }

    updated_host = [host.copy()]

    def mock_update_host(hostname, updater):
        updated_host[0] = updater(updated_host[0])

    _setup_common(monkeypatch, tmp_path, host)
    monkeypatch.setattr("clawrium.core.install.get_host", lambda x: updated_host[0])
    monkeypatch.setattr("clawrium.core.install.update_host", mock_update_host)

    # Test resume flag
    result = run_installation("openclaw", "test-host", resume=True)

    assert result["success"] is True
    # Verify that installation used existing agent name
    assert updated_host[0]["agents"]["openclaw"]["agent_name"] == "work-assistant"
    assert updated_host[0]["agents"]["openclaw"]["status"] == "installed"


def test_prompt_cleanup_retry(monkeypatch, tmp_path):
    """Test that user can clean up and start fresh installation."""
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

    updated_host = [host.copy()]

    def mock_update_host(hostname, updater):
        updated_host[0] = updater(updated_host[0])

    _setup_common(monkeypatch, tmp_path, host)
    monkeypatch.setattr("clawrium.core.install.get_host", lambda x: updated_host[0])
    monkeypatch.setattr("clawrium.core.install.update_host", mock_update_host)

    # Mock secrets functions for cleanup
    monkeypatch.setattr(
        "clawrium.core.secrets.load_secrets", lambda: {"test-host:openclaw:work-assistant": {}}
    )
    monkeypatch.setattr("clawrium.core.secrets.save_secrets", lambda x: None)

    # Test cleanup flag
    result = run_installation("openclaw", "test-host", cleanup_failed=True)

    assert result["success"] is True
    # Verify that installation started fresh with new agent name
    new_agent_name = updated_host[0]["agents"]["openclaw"]["agent_name"]
    assert new_agent_name != "work-assistant"  # Should be different name
    assert updated_host[0]["agents"]["openclaw"]["status"] == "installed"


def test_prompt_abort(monkeypatch):
    """Test that user can abort operation via CLI prompt."""
    from clawrium.cli.install import _handle_incomplete_installation
    from clawrium.core.install import IncompleteInstallationError
    import typer

    # Create an incomplete installation error
    details = {
        "status": "failed",
        "agent_name": "work-assistant",
        "error": "base playbook failed",
        "version": "0.1.0",
    }
    error = IncompleteInstallationError("test-host", "openclaw", details)

    # Mock user selecting option 3 (Abort)
    with patch("typer.prompt", return_value=3):
        with pytest.raises(typer.Exit) as exc_info:
            _handle_incomplete_installation(error)

    assert exc_info.value.exit_code == 0


def test_handle_incomplete_installation_resume(monkeypatch):
    """Test _handle_incomplete_installation returns correct flags for resume."""
    from clawrium.cli.install import _handle_incomplete_installation
    from clawrium.core.install import IncompleteInstallationError

    details = {
        "status": "installing",
        "agent_name": "work-assistant",
        "error": None,
        "version": "0.1.0",
    }
    error = IncompleteInstallationError("test-host", "openclaw", details)

    # Mock user selecting option 1 (Resume)
    with patch("typer.prompt", return_value=1):
        cleanup_failed, resume = _handle_incomplete_installation(error)

    assert cleanup_failed is False
    assert resume is True


def test_handle_incomplete_installation_cleanup(monkeypatch):
    """Test _handle_incomplete_installation returns correct flags for cleanup."""
    from clawrium.cli.install import _handle_incomplete_installation
    from clawrium.core.install import IncompleteInstallationError

    details = {
        "status": "failed",
        "agent_name": "work-assistant",
        "error": "base playbook failed",
        "version": "0.1.0",
    }
    error = IncompleteInstallationError("test-host", "openclaw", details)

    # Mock user selecting option 2 (Clean up and retry)
    with patch("typer.prompt", return_value=2):
        cleanup_failed, resume = _handle_incomplete_installation(error)

    assert cleanup_failed is True
    assert resume is False


def test_handle_incomplete_installation_invalid_choice(monkeypatch):
    """Test _handle_incomplete_installation handles invalid choice."""
    from clawrium.cli.install import _handle_incomplete_installation
    from clawrium.core.install import IncompleteInstallationError
    import typer

    details = {
        "status": "failed",
        "agent_name": "work-assistant",
        "error": "base playbook failed",
        "version": "0.1.0",
    }
    error = IncompleteInstallationError("test-host", "openclaw", details)

    # Mock user selecting invalid option
    with patch("typer.prompt", return_value=99):
        with pytest.raises(typer.Exit) as exc_info:
            _handle_incomplete_installation(error)

    assert exc_info.value.exit_code == 1

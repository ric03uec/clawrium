"""Tests for installation orchestration."""

import pytest
from unittest.mock import Mock, patch


def test_install_invalid_claw_raises():
    """Test that install with invalid claw raises InstallationError."""
    from clawrium.core.install import run_installation, InstallationError

    with pytest.raises(InstallationError, match="not found"):
        run_installation("nonexistent_claw", "test-host")


def test_install_host_not_found_raises(monkeypatch):
    """Test that install with unknown host raises InstallationError."""
    from clawrium.core.install import run_installation, InstallationError

    # Mock load_manifest to succeed
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
                },
            }
        ],
    }

    import clawrium.core.install
    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    # Mock get_host to return None
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: None)

    with pytest.raises(InstallationError, match="not found"):
        run_installation("openclaw", "unknown-host")


def test_install_incompatible_host_raises(monkeypatch):
    """Test that install with incompatible host raises InstallationError."""
    from clawrium.core.install import run_installation, InstallationError

    # Mock load_manifest
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
                },
            }
        ],
    }

    import clawrium.core.install
    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    # Mock get_host with incompatible hardware
    incompatible_host = {
        "hostname": "test-host",
        "user": "xclm",
        "port": 22,
        "hardware": {
            "architecture": "arm64",  # Wrong arch
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: incompatible_host)

    # Mock check_compatibility to return incompatible
    compat_result = {
        "compatible": False,
        "matched_entry": None,
        "reasons": ["Requires x86_64, host has arm64"],
    }
    monkeypatch.setattr(
        clawrium.core.install, "check_compatibility", lambda *args, **kwargs: compat_result
    )

    with pytest.raises(InstallationError, match="incompatible.*arm64"):
        run_installation("openclaw", "test-host")


def test_install_success(monkeypatch, tmp_path):
    """Test successful installation flow."""
    from clawrium.core.install import run_installation

    # Mock load_manifest
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
                },
            }
        ],
    }

    import clawrium.core.install
    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    # Create a mock SSH key
    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")

    # Mock get_host
    compatible_host = {
        "hostname": "test-host",
        "user": "xclm",
        "port": 22,
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: compatible_host)

    # Mock check_compatibility
    compat_result = {
        "compatible": True,
        "matched_entry": mock_manifest["entries"][0],
        "reasons": [],
    }
    monkeypatch.setattr(
        clawrium.core.install, "check_compatibility", lambda *args, **kwargs: compat_result
    )

    # Mock get_host_private_key
    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda x: key_file
    )

    # Mock ansible_runner.run
    class SuccessfulResult:
        status = "successful"

    mock_run = Mock(return_value=SuccessfulResult())

    import ansible_runner
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    # Run installation
    result = run_installation("openclaw", "test-host")

    # Verify result
    assert result["success"] is True
    assert result["claw"] == "openclaw"
    assert result["version"] == "0.1.0"
    assert result["host"] == "test-host"
    assert len(result["playbooks_run"]) == 2
    assert result["error"] is None

    # Verify ansible_runner.run was called twice (base + claw playbook)
    assert mock_run.call_count == 2


def test_install_emits_events(monkeypatch, tmp_path):
    """Test that installation emits progress events."""
    from clawrium.core.install import run_installation

    # Mock dependencies (same as test_install_success)
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
                },
            }
        ],
    }

    import clawrium.core.install
    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")

    compatible_host = {
        "hostname": "test-host",
        "user": "xclm",
        "port": 22,
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: compatible_host)

    compat_result = {
        "compatible": True,
        "matched_entry": mock_manifest["entries"][0],
        "reasons": [],
    }
    monkeypatch.setattr(
        clawrium.core.install, "check_compatibility", lambda *args, **kwargs: compat_result
    )

    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda x: key_file
    )

    class SuccessfulResult:
        status = "successful"

    mock_run = Mock(return_value=SuccessfulResult())

    import ansible_runner
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    # Capture events
    events = []

    def on_event(stage, message):
        events.append((stage, message))

    # Run installation with event callback
    run_installation("openclaw", "test-host", on_event=on_event)

    # Verify events were emitted
    assert len(events) > 0
    stages = [stage for stage, _ in events]
    assert "validate" in stages
    assert "base" in stages
    assert "claw" in stages


def test_install_base_playbook_fails(monkeypatch, tmp_path):
    """Test that base playbook failure raises InstallationError."""
    from clawrium.core.install import run_installation, InstallationError

    # Mock dependencies
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
                },
            }
        ],
    }

    import clawrium.core.install
    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")

    compatible_host = {
        "hostname": "test-host",
        "user": "xclm",
        "port": 22,
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: compatible_host)

    compat_result = {
        "compatible": True,
        "matched_entry": mock_manifest["entries"][0],
        "reasons": [],
    }
    monkeypatch.setattr(
        clawrium.core.install, "check_compatibility", lambda *args, **kwargs: compat_result
    )

    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda x: key_file
    )

    # Mock ansible_runner.run to fail
    class FailedResult:
        status = "failed"

    mock_run = Mock(return_value=FailedResult())

    import ansible_runner
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    with pytest.raises(InstallationError, match="Base playbook failed"):
        run_installation("openclaw", "test-host")


def test_install_missing_ssh_key_raises(monkeypatch):
    """Test that missing SSH key raises InstallationError."""
    from clawrium.core.install import run_installation, InstallationError

    # Mock dependencies
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
                },
            }
        ],
    }

    import clawrium.core.install
    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    compatible_host = {
        "hostname": "test-host",
        "user": "xclm",
        "port": 22,
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: compatible_host)

    compat_result = {
        "compatible": True,
        "matched_entry": mock_manifest["entries"][0],
        "reasons": [],
    }
    monkeypatch.setattr(
        clawrium.core.install, "check_compatibility", lambda *args, **kwargs: compat_result
    )

    # Mock get_host_private_key to return None
    monkeypatch.setattr(clawrium.core.install, "get_host_private_key", lambda x: None)

    with pytest.raises(InstallationError, match="No SSH key found"):
        run_installation("openclaw", "test-host")


def test_install_updates_host_on_success(monkeypatch, tmp_path):
    """Test that install.py calls update_host with installed status on success."""
    from clawrium.core.install import run_installation

    # Mock dependencies
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
                },
            }
        ],
    }

    import clawrium.core.install
    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")

    compatible_host = {
        "hostname": "test-host",
        "user": "xclm",
        "port": 22,
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: compatible_host)

    compat_result = {
        "compatible": True,
        "matched_entry": mock_manifest["entries"][0],
        "reasons": [],
    }
    monkeypatch.setattr(
        clawrium.core.install, "check_compatibility", lambda *args, **kwargs: compat_result
    )

    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda x: key_file
    )

    class SuccessfulResult:
        status = "successful"

    mock_run = Mock(return_value=SuccessfulResult())

    import ansible_runner
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    # Mock update_host to track calls and simulate persistent state
    update_calls = []
    persistent_host = compatible_host.copy()

    def mock_update_host(hostname, updater):
        nonlocal persistent_host
        # Capture before state
        before_status = None
        if "claws" in persistent_host and "openclaw" in persistent_host.get("claws", {}):
            before_status = persistent_host["claws"]["openclaw"].get("status")

        # Apply updater to persistent host state (simulates real update_host behavior)
        persistent_host = updater(persistent_host)

        # Capture after state
        after_status = None
        if "claws" in persistent_host and "openclaw" in persistent_host.get("claws", {}):
            after_status = persistent_host["claws"]["openclaw"].get("status")

        # Store the before/after snapshot
        update_calls.append((hostname, before_status, after_status, persistent_host.copy()))
        return True

    monkeypatch.setattr(clawrium.core.install, "update_host", mock_update_host)

    # Run installation
    run_installation("openclaw", "test-host")

    # Verify update_host was called with installing and installed status
    assert len(update_calls) >= 2

    # Extract after-statuses from calls (what was set by each update)
    after_statuses = [call[2] for call in update_calls]

    # Should have: installing -> installed
    assert after_statuses[0] == "installing", f"First update should set 'installing', got {after_statuses}"
    assert after_statuses[-1] == "installed", f"Last update should set 'installed', got {after_statuses}"

    # Verify final state has all required fields
    last_call = update_calls[-1]
    last_hostname = last_call[0]
    last_updated = last_call[3]

    assert last_hostname == "test-host"
    assert "claws" in last_updated
    assert "openclaw" in last_updated["claws"]
    assert last_updated["claws"]["openclaw"]["status"] == "installed"
    assert last_updated["claws"]["openclaw"]["version"] == "0.1.0"
    assert last_updated["claws"]["openclaw"]["installed_at"] is not None


def test_install_updates_host_on_failure(monkeypatch, tmp_path):
    """Test that install.py calls update_host with failed status on failure."""
    from clawrium.core.install import run_installation, InstallationError

    # Mock dependencies
    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": "0.1.0",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
                },
            }
        ],
    }

    import clawrium.core.install
    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)

    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")

    compatible_host = {
        "hostname": "test-host",
        "user": "xclm",
        "port": 22,
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    monkeypatch.setattr(clawrium.core.install, "get_host", lambda x: compatible_host)

    compat_result = {
        "compatible": True,
        "matched_entry": mock_manifest["entries"][0],
        "reasons": [],
    }
    monkeypatch.setattr(
        clawrium.core.install, "check_compatibility", lambda *args, **kwargs: compat_result
    )

    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda x: key_file
    )

    # Mock ansible_runner.run to fail
    class FailedResult:
        status = "failed"

    mock_run = Mock(return_value=FailedResult())

    import ansible_runner
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    # Mock update_host to track calls
    update_calls = []

    def mock_update_host(hostname, updater):
        # Call the updater to capture the update
        test_host = compatible_host.copy()
        if "claws" not in test_host:
            test_host["claws"] = {}
        updated = updater(test_host)
        update_calls.append((hostname, updated))
        return True

    monkeypatch.setattr(clawrium.core.install, "update_host", mock_update_host)

    # Run installation (should fail and update host with error)
    with pytest.raises(InstallationError):
        run_installation("openclaw", "test-host")

    # Verify update_host was called with failed status
    assert len(update_calls) >= 1

    # Check if any call has failed status
    found_failed = False
    for hostname, updated in update_calls:
        if "claws" in updated and "openclaw" in updated["claws"]:
            if updated["claws"]["openclaw"]["status"] == "failed":
                found_failed = True
                assert updated["claws"]["openclaw"]["error"] is not None
                assert "failed" in updated["claws"]["openclaw"]["error"].lower()
                break

    assert found_failed, "Expected update_host to be called with failed status"

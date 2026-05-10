"""Tests for installed-version skip behavior during install."""

from unittest.mock import Mock

import pytest


def _setup_common(monkeypatch, tmp_path, host_record: dict, version: str = "2026.4.2"):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": version,
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "sha256": "abc123",
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
    monkeypatch.setattr(
        clawrium.core.install,
        "check_compatibility",
        lambda *args, **kwargs: {
            "compatible": True,
            "matched_entry": mock_manifest["entries"][0],
            "reasons": [],
        },
    )

    host_state = [host_record]

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

    return host_state


def _result_with_events(tmp_path, events):
    class SuccessfulResult:
        status = "successful"

        class Config:
            artifact_dir = str(tmp_path / "artifacts")

        config = Config()

    SuccessfulResult.events = events

    return SuccessfulResult()


def test_install_reuses_existing_installed_name_and_reports_skip(monkeypatch, tmp_path):
    from clawrium.core.install import run_installation

    preserved_device = {
        "id": "device-abc",
        "token": "token-xyz",
        "privateKey": "PEM-DATA-HERE",
    }
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
                "version": "2026.4.2",
                "config": {
                    "gateway": {
                        "url": "ws://example:40001",
                        "auth": "preserved-gateway-token-aaaaaaaaaaaaaa",
                        "device": preserved_device,
                    }
                },
            }
        },
    }

    host_state = _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Discover openclaw binary in PATH",
                        "res": {"stdout": "/usr/local/bin/openclaw", "rc": 0},
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Get installed openclaw version",
                        "res": {"stdout": "openclaw 2026.4.2", "rc": 0},
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Parse installed openclaw version",
                        "res": {
                            "ansible_facts": {
                                "openclaw_installed_version": "2026.4.2",
                            }
                        },
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Set install skip condition",
                        "res": {
                            "ansible_facts": {
                                "openclaw_already_installed": True,
                                "openclaw_runtime_binary": "/usr/local/bin/openclaw",
                            }
                        },
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Mark install as skipped when already installed",
                        "res": {
                            "msg": "OpenClaw v2026.4.2 already installed at /usr/local/bin/openclaw. Skipping binary install."
                        },
                    },
                },
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skip_reason"] == "already_installed"
    assert host_state[0]["agents"]["openclaw"]["agent_name"] == "existing-agent"
    # Existing gateway URL, auth token, and device credentials must be byte-identical
    # after the skip — proves pairing did not re-run and rotate credentials.
    gateway = host_state[0]["agents"]["openclaw"]["config"]["gateway"]
    assert gateway["url"] == "ws://example:40001"
    assert gateway["auth"] == "preserved-gateway-token-aaaaaaaaaaaaaa"
    assert gateway["device"] == preserved_device
    assert mock_run.call_count == 2


def test_install_existing_agent_different_version_proceeds_with_install(
    monkeypatch, tmp_path
):
    """When the installed version differs from the requested version, the
    playbook does NOT emit the skip marker (openclaw_already_installed=false),
    so installation proceeds. Validates the version-aware skip introduced in
    issue #163.
    """
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
                "version": "2026.3.1",
            }
        },
    }

    _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    # Mismatched version: installed=2026.3.1, target=2026.4.2 (from manifest in
    # _setup_common). Playbook emits the version facts but NOT the skip marker.
    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Discover openclaw binary in PATH",
                        "res": {"stdout": "/usr/local/bin/openclaw", "rc": 0},
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Get installed openclaw version",
                        "res": {"stdout": "openclaw 2026.3.1", "rc": 0},
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Parse installed openclaw version",
                        "res": {
                            "ansible_facts": {
                                "openclaw_installed_version": "2026.3.1",
                            }
                        },
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Set install skip condition",
                        "res": {
                            "ansible_facts": {
                                "openclaw_already_installed": False,
                                "openclaw_runtime_binary": "/usr/local/bin/openclaw",
                            }
                        },
                    },
                },
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host")

    assert result["success"] is True
    assert result.get("skipped") is not True
    assert result.get("skip_reason") is None
    assert mock_run.call_count == 2


def test_openclaw_skip_detection_matches_fact_and_marker():
    from clawrium.core.install import _openclaw_install_was_skipped

    class Result:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"openclaw_already_installed": True}},
                },
            }
        ]

    assert _openclaw_install_was_skipped(Result()) is True

    class ResultByTask:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Mark install as skipped when already installed",
                    "res": {"msg": "already installed at /usr/local/bin/openclaw"},
                },
            }
        ]

    assert _openclaw_install_was_skipped(ResultByTask()) is True

    class ResultNoSkip:
        events = []

    assert _openclaw_install_was_skipped(ResultNoSkip()) is False

    class ResultFalsePositive:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Download OpenClaw installer script",
                    "res": {
                        "msg": "Package already installed by another process, skipping"
                    },
                },
            }
        ]

    assert _openclaw_install_was_skipped(ResultFalsePositive()) is False


def test_install_failure_sets_failed_status_without_installed_timestamp(
    monkeypatch, tmp_path
):
    from clawrium.core.install import InstallationError, run_installation

    # Use a fixed name to make assertions deterministic
    test_agent_name = "test-agent"

    host = {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    host_state = _setup_common(monkeypatch, tmp_path, host)

    import clawrium.core.install

    monkeypatch.setattr(
        clawrium.core.install,
        "_get_base_playbook_path",
        lambda: tmp_path / "missing-base.yaml",
    )

    with pytest.raises(InstallationError, match="Base playbook not found"):
        run_installation("openclaw", "test-host", name=test_agent_name)

    assert host_state[0]["agents"][test_agent_name]["status"] == "failed"
    assert host_state[0]["agents"][test_agent_name]["installed_at"] is None


def _capture_inventory_run(captured: list):
    """Build a mock for ansible_runner.run that captures the inventory it
    receives so tests can assert on extra_vars (e.g., force_install)."""

    def _runner(*args, **kwargs):
        captured.append(kwargs.get("inventory"))

        class Result:
            status = "successful"

            class Config:
                artifact_dir = "/tmp/nonexistent"

            config = Config()
            events = []

        return Result()

    return _runner


def test_install_with_force_skips_skip_logic(monkeypatch, tmp_path):
    """force=True must inject force_install=true into the playbook inventory
    AND not result in skipped=True even when the installed version matches.
    """
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
                "version": "2026.4.2",
                "config": {
                    "gateway": {
                        "url": "ws://example:40001",
                        "auth": "preserved-gateway-token-aaaaaaaaaaaaaa",
                        "device": {
                            "id": "d",
                            "token": "t",
                            "privateKey": "k",
                        },
                    }
                },
            }
        },
    }

    _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    captured_inventories: list = []
    monkeypatch.setattr(
        ansible_runner, "run", _capture_inventory_run(captured_inventories)
    )

    result = run_installation("openclaw", "test-host", force=True)

    # Two playbooks run: base + agent. Both receive the same inventory vars.
    assert len(captured_inventories) == 2
    for inv in captured_inventories:
        assert inv["all"]["vars"]["force_install"] is True

    # No skip marker in the (empty) event stream -> not skipped.
    assert result["success"] is True
    assert result.get("skipped") is not True


def test_install_without_force_passes_force_install_false(monkeypatch, tmp_path):
    """Default force=False propagates as force_install=false into inventory."""
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
    }
    _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    captured_inventories: list = []
    monkeypatch.setattr(
        ansible_runner, "run", _capture_inventory_run(captured_inventories)
    )

    run_installation("openclaw", "test-host", name="fresh-agent")

    assert len(captured_inventories) == 2
    for inv in captured_inventories:
        assert inv["all"]["vars"]["force_install"] is False


def test_install_with_unparseable_version_proceeds_with_install(monkeypatch, tmp_path):
    """If `openclaw --version` produces output that doesn't match the SemVer
    regex, the playbook treats installed_version as empty -> not equal to
    target -> installation proceeds (safe default to reinstall).

    This test exercises the Python-side detection: when the playbook does NOT
    emit the skip marker (because version parsing failed and produced empty
    string != target), the result is not skipped.
    """
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
                "version": "2026.4.2",
            }
        },
    }
    _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    # Playbook reports binary exists but version output is garbage; skip marker
    # is NOT emitted because installed_version != target_version.
    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Discover openclaw binary in PATH",
                        "res": {"stdout": "/usr/local/bin/openclaw", "rc": 0},
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Get installed openclaw version",
                        "res": {
                            "stdout": "openclaw: command moved, please reinstall",
                            "rc": 0,
                        },
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Parse installed openclaw version",
                        "res": {
                            "ansible_facts": {
                                "openclaw_installed_version": "",
                            }
                        },
                    },
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Set install skip condition",
                        "res": {
                            "ansible_facts": {
                                "openclaw_already_installed": False,
                                "openclaw_runtime_binary": "/usr/local/bin/openclaw",
                            }
                        },
                    },
                },
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host")

    assert result["success"] is True
    assert result.get("skipped") is not True

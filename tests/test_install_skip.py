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
                "config": {"gateway": {"url": "ws://example:40001"}},
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
                        "task": "Mark install as skipped when already installed",
                        "res": {
                            "msg": "OpenClaw already installed with matching version 2026.4.2."
                        },
                    },
                }
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skip_reason"] == "already_installed_version_match"
    assert host_state[0]["agents"]["openclaw"]["agent_name"] == "existing-agent"
    assert (
        host_state[0]["agents"]["openclaw"]["config"]["gateway"]["url"]
        == "ws://example:40001"
    )
    assert mock_run.call_count == 2


def test_install_existing_agent_with_mismatch_version_does_not_report_skip(
    monkeypatch, tmp_path
):
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

    mock_run = Mock(
        side_effect=[
            _result_with_events(tmp_path, []),
            _result_with_events(tmp_path, []),
        ]
    )
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host")

    assert result["success"] is True
    assert result["skipped"] is False
    assert result["skip_reason"] is None
    assert mock_run.call_count == 2


def test_openclaw_skip_detection_matches_fact_and_marker():
    from clawrium.core.install import _openclaw_install_was_skipped

    class Result:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Compute OpenClaw install skip condition",
                    "res": {
                        "ansible_facts": {
                            "openclaw_already_installed_and_matching": True
                        }
                    },
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
                    "res": {"msg": "already installed with matching version"},
                },
            }
        ]

    assert _openclaw_install_was_skipped(ResultByTask()) is True

    class ResultNoSkip:
        events = []

    assert _openclaw_install_was_skipped(ResultNoSkip()) is False


def test_install_failure_sets_failed_status_without_installed_timestamp(
    monkeypatch, tmp_path
):
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
    }
    host_state = _setup_common(monkeypatch, tmp_path, host)

    import clawrium.core.install

    monkeypatch.setattr(
        clawrium.core.install,
        "_get_base_playbook_path",
        lambda: tmp_path / "missing-base.yaml",
    )

    with pytest.raises(InstallationError, match="Base playbook not found"):
        run_installation("openclaw", "test-host")

    assert host_state[0]["agents"]["openclaw"]["status"] == "failed"
    assert host_state[0]["agents"]["openclaw"]["installed_at"] is None

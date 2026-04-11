"""Tests for claw lifecycle management module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawrium.core.lifecycle import (
    start_agent,
    stop_agent,
    restart_agent,
    remove_agent,
    LifecycleError,
    _get_lifecycle_playbook_path,
    _run_lifecycle_playbook,
    _resolve_agent_record,
)


class TestGetLifecyclePlaybookPath:
    """Tests for playbook path resolution."""

    def test_returns_path_for_start_operation(self):
        path = _get_lifecycle_playbook_path("openclaw", "start")
        assert "openclaw" in str(path)
        assert "start.yaml" in str(path)

    def test_returns_path_for_stop_operation(self):
        path = _get_lifecycle_playbook_path("zeroclaw", "stop")
        assert "zeroclaw" in str(path)
        assert "stop.yaml" in str(path)


class TestRunLifecyclePlaybook:
    """Tests for _run_lifecycle_playbook helper."""

    def test_returns_false_when_playbook_missing(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"opc-work": {"type": "openclaw"}},
        }

        with patch("clawrium.core.lifecycle._get_lifecycle_playbook_path") as mock_path:
            mock_path.return_value = tmp_path / "nonexistent.yaml"
            success, error = _run_lifecycle_playbook(
                "openclaw", "opc-work", "192.168.1.100", "start", host
            )

        assert success is False
        assert "not found" in error

    def test_returns_false_when_ssh_key_missing(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "missing-key",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"opc-work": {"type": "openclaw"}},
        }

        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        with patch("clawrium.core.lifecycle._get_lifecycle_playbook_path") as mock_path:
            mock_path.return_value = playbook_path
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=None
            ):
                success, error = _run_lifecycle_playbook(
                    "openclaw", "opc-work", "192.168.1.100", "start", host
                )

        assert success is False
        assert "SSH key not found" in error


class TestStartClaw:
    """Tests for start_claw function."""

    def test_raises_error_when_host_not_found(self):
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                start_agent("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                start_agent("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_raises_error_when_onboarding_incomplete(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "pending"},
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                start_agent("192.168.1.100", "openclaw")

        assert "incomplete" in str(exc_info.value)

    def test_returns_success_on_successful_start(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = start_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "start"


class TestStopClaw:
    """Tests for stop_claw function."""

    def test_raises_error_when_host_not_found(self):
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                stop_agent("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self):
        host = {
            "hostname": "192.168.1.100",
            "agents": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                stop_agent("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_returns_success_on_successful_stop(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "stop.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = stop_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "stop"


class TestRestartClaw:
    """Tests for restart_claw function."""

    def test_returns_stop_failure_when_stop_fails(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "stop.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "failed"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"msg": "Stop failed"}}}
        ]

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            result = restart_agent("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert "Stop failed" in result["error"]

    def test_returns_success_on_successful_restart(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "test.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = restart_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "restart"


class TestRemoveClaw:
    """Tests for remove_claw function."""

    def test_raises_error_when_host_not_found(self):
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                remove_agent("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                remove_agent("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_stops_running_claw_before_removal(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "running"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "test.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                with patch(
                                    "clawrium.core.lifecycle.remove_agent_from_host",
                                    return_value=True,
                                ):
                                    result = remove_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "remove"

    def test_continues_removal_when_stop_fails(self, tmp_path: Path):
        """Should continue with removal even if stop fails."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "running"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "test.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner_fail = MagicMock()
        mock_runner_fail.status = "failed"
        mock_runner_fail.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "Stop failed"}},
            }
        ]

        mock_runner_success = MagicMock()
        mock_runner_success.status = "successful"
        mock_runner_success.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        side_effect=[mock_runner_fail, mock_runner_success],
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                with patch(
                                    "clawrium.core.lifecycle.remove_agent_from_host",
                                    return_value=True,
                                ):
                                    result = remove_agent("192.168.1.100", "openclaw")

        # Should still succeed with removal
        assert result["success"] is True

    def test_returns_failure_when_playbook_fails(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "stopped"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "remove.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "failed"
        mock_runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "Removal failed"}},
            }
        ]

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            result = remove_agent("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert "Removal failed" in result["error"]

    def test_removes_claw_from_host_config(self, tmp_path: Path):
        """Verify claw is removed from hosts.json."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "stopped"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "remove.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.remove_agent_from_host"
                            ) as mock_remove:
                                mock_remove.return_value = True
                                result = remove_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        # Now removes by agent_name (opc-work), not claw_type (openclaw)
        mock_remove.assert_called_once_with("192.168.1.100", "opc-work")

    def test_event_callbacks_invoked(self, tmp_path: Path):
        """Verify on_event callback is called with appropriate messages."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "stopped"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "remove.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        events = []

        def on_event(stage, message):
            events.append((stage, message))

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.remove_agent_from_host",
                                return_value=True,
                            ):
                                result = remove_agent(
                                    "192.168.1.100", "openclaw", on_event=on_event
                                )

        assert result["success"] is True
        # Should have validate and remove events
        assert any(stage == "validate" for stage, _ in events)
        assert any(stage == "remove" for stage, _ in events)

class TestResolveAgentRecord:
    """Tests for _resolve_agent_record function."""

    def test_multiple_agents_same_type_raises_error(self):
        """B7: Multiple agents of same type should raise LifecycleError."""
        host = {
            "hostname": "test-host",
            "agents": {
                "assistant-1": {"type": "openclaw", "status": "installed"},
                "assistant-2": {"type": "openclaw", "status": "installed"},
            },
        }

        with pytest.raises(LifecycleError) as exc_info:
            _resolve_agent_record(host, "openclaw", expected_type="openclaw")

        assert "Multiple" in str(exc_info.value)
        assert "assistant-1" in str(exc_info.value)
        assert "assistant-2" in str(exc_info.value)

    def test_agent_without_type_field_skipped(self):
        """B8: Agents without explicit 'type' field should be skipped."""
        host = {
            "hostname": "test-host",
            "agents": {
                "old-agent": {
                    "status": "installed",
                    # Missing "type" field - should be skipped
                },
            },
        }

        result = _resolve_agent_record(host, "openclaw", expected_type="openclaw")
        assert result is None

    def test_direct_key_lookup_without_type_returns_none(self):
        """Direct lookup by agent_name also requires type field."""
        host = {
            "hostname": "test-host",
            "agents": {
                "my-assistant": {
                    "status": "installed",
                    # Missing "type" field
                },
            },
        }

        result = _resolve_agent_record(host, "my-assistant")
        assert result is None

    def test_matches_single_agent_by_type(self):
        """Single agent of expected type should be found."""
        host = {
            "hostname": "test-host",
            "agents": {
                "work-bot": {"type": "openclaw", "status": "installed"},
            },
        }

        result = _resolve_agent_record(host, "openclaw", expected_type="openclaw")
        assert result is not None
        agent_name, agent_type, record = result
        assert agent_name == "work-bot"
        assert agent_type == "openclaw"

    def test_matches_by_direct_key(self):
        """Direct lookup by agent_name works when type is present."""
        host = {
            "hostname": "test-host",
            "agents": {
                "work-bot": {"type": "openclaw", "status": "installed"},
            },
        }

        result = _resolve_agent_record(host, "work-bot")
        assert result is not None
        agent_name, agent_type, record = result
        assert agent_name == "work-bot"
        assert agent_type == "openclaw"

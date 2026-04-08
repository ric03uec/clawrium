"""Tests for claw lifecycle management module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawrium.core.lifecycle import (
    start_claw,
    stop_claw,
    restart_claw,
    LifecycleError,
    _get_lifecycle_playbook_path,
    _run_lifecycle_playbook,
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
            "user": "xclm",
            "port": 22,
            "claws": {"openclaw": {"user": "opc-work"}},
        }

        with patch("clawrium.core.lifecycle._get_lifecycle_playbook_path") as mock_path:
            mock_path.return_value = tmp_path / "nonexistent.yaml"
            success, error = _run_lifecycle_playbook(
                "openclaw", "192.168.1.100", "start", host
            )

        assert success is False
        assert "not found" in error

    def test_returns_false_when_ssh_key_missing(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "missing-key",
            "user": "xclm",
            "port": 22,
            "claws": {"openclaw": {"user": "opc-work"}},
        }

        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        with patch("clawrium.core.lifecycle._get_lifecycle_playbook_path") as mock_path:
            mock_path.return_value = playbook_path
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=None
            ):
                success, error = _run_lifecycle_playbook(
                    "openclaw", "192.168.1.100", "start", host
                )

        assert success is False
        assert "SSH key not found" in error


class TestStartClaw:
    """Tests for start_claw function."""

    def test_raises_error_when_host_not_found(self):
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                start_claw("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "claws": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                start_claw("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_raises_error_when_onboarding_incomplete(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "claws": {
                "openclaw": {
                    "user": "opc-work",
                    "onboarding": {"state": "pending"},
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                start_claw("192.168.1.100", "openclaw")

        assert "incomplete" in str(exc_info.value)

    def test_returns_success_on_successful_start(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "user": "xclm",
            "port": 22,
            "claws": {
                "openclaw": {
                    "user": "opc-work",
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
                            "clawrium.core.lifecycle._update_claw_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = start_claw("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "start"


class TestStopClaw:
    """Tests for stop_claw function."""

    def test_raises_error_when_host_not_found(self):
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                stop_claw("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self):
        host = {
            "hostname": "192.168.1.100",
            "claws": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                stop_claw("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_returns_success_on_successful_stop(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "user": "xclm",
            "port": 22,
            "claws": {
                "openclaw": {
                    "user": "opc-work",
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
                            "clawrium.core.lifecycle._update_claw_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = stop_claw("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "stop"


class TestRestartClaw:
    """Tests for restart_claw function."""

    def test_returns_stop_failure_when_stop_fails(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "user": "xclm",
            "port": 22,
            "claws": {
                "openclaw": {
                    "user": "opc-work",
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
                            result = restart_claw("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert "Stop failed" in result["error"]

    def test_returns_success_on_successful_restart(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "user": "xclm",
            "port": 22,
            "claws": {
                "openclaw": {
                    "user": "opc-work",
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
                            "clawrium.core.lifecycle._update_claw_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = restart_claw("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "restart"

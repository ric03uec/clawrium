"""Tests for configure_claw function."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawrium.core.lifecycle import configure_claw, LifecycleError


class TestConfigureClaw:
    """Tests for configure_claw function."""

    def test_raises_error_when_host_not_found(self):
        """Test that LifecycleError is raised when host doesn't exist."""
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                configure_claw("nonexistent", "zeroclaw", {})

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self):
        """Test that LifecycleError is raised when claw not installed."""
        host = {"hostname": "test-host", "claws": {}}

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                configure_claw("test-host", "zeroclaw", {})

        assert "not installed" in str(exc_info.value)

    def test_returns_false_when_invalid_model_name(self):
        """Test that invalid Ollama model names are rejected."""
        host = {
            "hostname": "test-host",
            "claws": {"zeroclaw": {"user": "zer-test"}},
        }
        config_data = {
            "provider": {
                "type": "ollama",
                "default_model": "malicious\nINJECTED=value",
            }
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_claw("test-host", "zeroclaw", config_data)

        assert success is False
        assert "Invalid model name" in error

    def test_returns_false_when_update_host_fails_after_ansible(self, tmp_path: Path):
        """Test that failure to update hosts.json after Ansible is handled."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "user": "xclm",
            "port": 22,
            "claws": {"zeroclaw": {"user": "zer-test"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host", return_value=False
                        ):
                            success, error = configure_claw(
                                "test-host", "zeroclaw", config_data
                            )

        assert success is False
        assert "failed to update local state" in error

    def test_returns_false_when_playbook_missing(self, tmp_path: Path):
        """Test that missing configure playbook is detected."""
        host = {
            "hostname": "test-host",
            "claws": {"zeroclaw": {"user": "zer-test"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path"
            ) as mock_playbook:
                mock_playbook.return_value = tmp_path / "nonexistent.yaml"

                success, error = configure_claw("test-host", "zeroclaw", config_data)

        assert success is False
        assert "playbook not found" in error

    def test_returns_false_when_ssh_key_missing(self, tmp_path: Path):
        """Test that missing SSH key is detected."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "claws": {"zeroclaw": {"user": "zer-test"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch("clawrium.core.lifecycle.get_host_private_key", return_value=None):
                    success, error = configure_claw("test-host", "zeroclaw", config_data)

        assert success is False
        assert "SSH key not found" in error

    def test_returns_false_when_invalid_claw_user_format(self, tmp_path: Path):
        """Test that invalid claw_user format is detected."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "claws": {"zeroclaw": {"user": "Invalid User!"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
                ):
                    success, error = configure_claw("test-host", "zeroclaw", config_data)

        assert success is False
        assert "Invalid claw_user format" in error

    def test_returns_false_when_ansible_times_out(self, tmp_path: Path):
        """Test that Ansible timeout is handled."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "user": "xclm",
            "port": 22,
            "claws": {"zeroclaw": {"user": "zer-test"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "timeout"

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        success, error = configure_claw(
                            "test-host", "zeroclaw", config_data
                        )

        assert success is False
        assert "timed out" in error

    def test_returns_false_when_ansible_fails(self, tmp_path: Path):
        """Test that Ansible failure is handled and hosts.json is NOT updated."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "user": "xclm",
            "port": 22,
            "claws": {"zeroclaw": {"user": "zer-test"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "failed"
        mock_runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "Task failed"}},
            }
        ]

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
                            success, error = configure_claw(
                                "test-host", "zeroclaw", config_data
                            )

                            # Verify hosts.json was NOT updated since Ansible failed
                            mock_update.assert_not_called()

        assert success is False
        assert "Task failed" in error

    def test_happy_path_returns_true(self, tmp_path: Path):
        """Test successful configuration flow."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "user": "xclm",
            "port": 22,
            "claws": {"zeroclaw": {"user": "zer-test"}},
        }
        config_data = {
            "gateway": {"host": "0.0.0.0", "port": 40000, "allow_public_bind": True},
            "provider": {
                "name": "test-provider",
                "type": "ollama",
                "endpoint": "http://localhost:11434",
                "default_model": "llama3",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch("clawrium.core.lifecycle.update_host") as mock_update:
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="",
                            ):
                                mock_update.return_value = True
                                success, error = configure_claw(
                                    "test-host", "zeroclaw", config_data
                                )

                                # Verify hosts.json WAS updated after Ansible succeeded
                                mock_update.assert_called_once()

        assert success is True
        assert error is None

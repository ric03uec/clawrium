"""Tests for configure_claw function."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from jinja2 import Environment, FileSystemLoader

from clawrium.core.lifecycle import configure_agent, LifecycleError


class TestConfigureClaw:
    """Tests for configure_claw function."""

    def test_raises_error_when_host_not_found(self):
        """Test that LifecycleError is raised when host doesn't exist."""
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                configure_agent("nonexistent", "zeroclaw", {})

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self):
        """Test that LifecycleError is raised when claw not installed."""
        host = {"hostname": "test-host", "agents": {}}

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                configure_agent("test-host", "zeroclaw", {})

        assert "not installed" in str(exc_info.value)

    def test_returns_false_when_invalid_model_name(self):
        """Test that invalid Ollama model names are rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"zeroclaw": {"agent_name": "zer-test"}},
        }
        config_data = {
            "provider": {
                "type": "ollama",
                "default_model": "malicious\nINJECTED=value",
            }
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent("test-host", "zeroclaw", config_data)

        assert success is False
        assert "Invalid model name" in error

    def test_returns_false_when_update_host_fails_after_ansible(self, tmp_path: Path):
        """Test that failure to update hosts.json after Ansible is handled."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zeroclaw": {"agent_name": "zer-test"}},
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
                            success, error = configure_agent(
                                "test-host", "zeroclaw", config_data
                            )

        assert success is False
        assert "failed to update local state" in error

    def test_returns_false_when_playbook_missing(self, tmp_path: Path):
        """Test that missing configure playbook is detected."""
        host = {
            "hostname": "test-host",
            "agents": {"zeroclaw": {"agent_name": "zer-test"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path"
            ) as mock_playbook:
                mock_playbook.return_value = tmp_path / "nonexistent.yaml"

                success, error = configure_agent("test-host", "zeroclaw", config_data)

        assert success is False
        assert "playbook not found" in error

    def test_returns_false_when_ssh_key_missing(self, tmp_path: Path):
        """Test that missing SSH key is detected."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {"zeroclaw": {"agent_name": "zer-test"}},
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
                    success, error = configure_agent("test-host", "zeroclaw", config_data)

        assert success is False
        assert "SSH key not found" in error

    def test_returns_false_when_invalid_claw_user_format(self, tmp_path: Path):
        """Test that invalid claw_user format is detected."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {"zeroclaw": {"agent_name": "Invalid User!"}},
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
                    success, error = configure_agent("test-host", "zeroclaw", config_data)

        assert success is False
        assert "Invalid agent_name format" in error

    def test_returns_false_when_ansible_times_out(self, tmp_path: Path):
        """Test that Ansible timeout is handled."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zeroclaw": {"agent_name": "zer-test"}},
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
                        success, error = configure_agent(
                            "test-host", "zeroclaw", config_data
                        )

        assert success is False
        assert "timed out" in error

    def test_returns_false_when_ansible_fails(self, tmp_path: Path):
        """Test that Ansible failure is handled and hosts.json is NOT updated."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zeroclaw": {"agent_name": "zer-test"}},
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
                            success, error = configure_agent(
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
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zeroclaw": {"agent_name": "zer-test"}},
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
                                success, error = configure_agent(
                                    "test-host", "zeroclaw", config_data
                                )

                                # Verify hosts.json WAS updated after Ansible succeeded
                                mock_update.assert_called_once()

        assert success is True
        assert error is None


class TestOpenClawTemplate:
    """Tests for OpenClaw openclaw.json.j2 template rendering."""

    def _render_template(self, config):
        """Helper to render the openclaw.json.j2 template."""
        template_dir = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/templates"
        )
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("openclaw.json.j2")
        rendered = template.render(config=config)
        return json.loads(rendered)

    def test_template_renders_minimal_config(self):
        """Test template renders valid JSON with minimal config."""
        config = {
            "provider": {"default_model": "anthropic/claude-sonnet-4-6"},
        }
        result = self._render_template(config)

        assert result["agents"]["defaults"]["model"] == "anthropic/claude-sonnet-4-6"
        assert result["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"
        assert result["agents"]["defaults"]["maxConcurrent"] == 4
        assert result["gateway"]["port"] == 18789
        assert result["gateway"]["bind"] == "0.0.0.0"

    def test_template_renders_full_config(self):
        """Test template renders with all optional fields."""
        config = {
            "provider": {"default_model": "openai/gpt-5.4"},
            "gateway": {
                "port": 40123,
                "bind": "loopback",
                "auth": {"token": "secret"},
            },
            "max_concurrent": 8,
            "skills": ["researcher", "coder"],
            "sandbox_mode": "all",
            "heartbeat_interval": "15m",
            "session_dm_scope": "per-peer",
            "session_reset_hour": 6,
            "session_idle_minutes": 60,
            "channels": {"telegram": {"enabled": True}},
        }
        result = self._render_template(config)

        assert result["agents"]["defaults"]["model"] == "openai/gpt-5.4"
        assert result["agents"]["defaults"]["maxConcurrent"] == 8
        assert result["agents"]["defaults"]["skills"] == ["researcher", "coder"]
        assert result["gateway"]["port"] == 40123
        assert result["gateway"]["bind"] == "loopback"
        assert result["gateway"]["auth"]["token"] == "secret"
        assert result["session"]["dmScope"] == "per-peer"
        assert result["session"]["reset"]["atHour"] == 6
        assert result["session"]["reset"]["idleMinutes"] == 60
        # Verify channels rendered correctly
        assert "channels" in result
        assert result["channels"]["telegram"]["enabled"] is True

    def test_template_defaults_match_openclaw_docs(self):
        """Test that defaults match OpenClaw official documentation."""
        config = {"provider": {"default_model": "anthropic/claude-opus-4-6"}}
        result = self._render_template(config)

        assert result["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"
        assert result["agents"]["defaults"]["maxConcurrent"] == 4
        assert result["agents"]["defaults"]["sandbox"]["mode"] == "non-main"
        assert result["agents"]["defaults"]["heartbeat"]["every"] == "30m"
        assert result["agents"]["defaults"]["heartbeat"]["target"] == "last"
        assert result["gateway"]["port"] == 18789
        assert result["gateway"]["bind"] == "0.0.0.0"
        assert result["gateway"]["reload"]["mode"] == "hybrid"
        assert result["gateway"]["reload"]["debounceMs"] == 300
        assert result["gateway"]["channelHealthCheckMinutes"] == 5
        assert result["session"]["dmScope"] == "per-channel-peer"
        assert result["session"]["reset"]["mode"] == "daily"
        assert result["session"]["reset"]["atHour"] == 4
        assert result["session"]["reset"]["idleMinutes"] == 120

    def test_template_handles_missing_provider(self):
        """Test template renders without provider (model field omitted)."""
        config = {"gateway": {"port": 40000}}
        result = self._render_template(config)

        # Model field should not be present
        assert "model" not in result["agents"]["defaults"]
        # Other defaults should still be present
        assert result["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"

    def test_template_handles_missing_gateway(self):
        """Test template renders with missing gateway config."""
        config = {"provider": {"default_model": "anthropic/claude-sonnet-4-6"}}
        result = self._render_template(config)

        # Should use gateway defaults
        assert result["gateway"]["port"] == 18789
        assert result["gateway"]["bind"] == "0.0.0.0"

    def test_template_handles_empty_optional_fields(self):
        """Test template with empty lists/dicts."""
        config = {
            "provider": {"default_model": "anthropic/claude-sonnet-4-6"},
            "skills": [],
            "agent_list": [],
            "channels": {},
        }
        result = self._render_template(config)

        # Empty arrays/objects should be omitted in rendered output
        assert "skills" not in result["agents"]["defaults"]
        assert "list" not in result["agents"]
        # Empty channels object should still be omitted
        assert "channels" not in result or result.get("channels") == {}

    def test_template_escapes_special_characters(self):
        """Test that special characters in strings are properly escaped."""
        config = {
            "provider": {"default_model": 'model"with"quotes'},
            "gateway": {"bind": "bind\nwith\nnewlines"},
        }
        result = self._render_template(config)

        # Should parse as valid JSON (proves escaping worked)
        assert result["agents"]["defaults"]["model"] == 'model"with"quotes'
        assert result["gateway"]["bind"] == "bind\nwith\nnewlines"

    def test_template_renders_agent_list(self):
        """Test that non-empty agent_list renders correctly."""
        config = {
            "provider": {"default_model": "anthropic/claude-sonnet-4-6"},
            "agent_list": [
                {"id": "main", "default": True},
                {"id": "work", "workspace": "/custom/workspace"},
            ],
        }
        result = self._render_template(config)

        # Verify agent list rendered
        assert "list" in result["agents"]
        assert len(result["agents"]["list"]) == 2
        assert result["agents"]["list"][0]["id"] == "main"
        assert result["agents"]["list"][0]["default"] is True
        assert result["agents"]["list"][1]["id"] == "work"
        assert result["agents"]["list"][1]["workspace"] == "/custom/workspace"

    def test_configure_openclaw_with_model(self, tmp_path: Path):
        """Test that OpenClaw configuration passes correct extra_vars to ansible."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"openclaw": {"agent_name": "ocl-test"}},
        }
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "test-provider",
                "type": "openrouter",
                "default_model": "deepseek/deepseek-chat-v3",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
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
                    ) as mock_ansible:
                        with patch("clawrium.core.lifecycle.update_host") as mock_update:
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="sk-or-test",
                            ):
                                mock_update.return_value = True
                                success, error = configure_agent(
                                    "test-host", "openclaw", config_data
                                )

                                # Verify ansible was called with correct inventory vars
                                mock_ansible.assert_called_once()
                                call_args = mock_ansible.call_args
                                inventory = call_args.kwargs.get("inventory", {})

                                # Verify config passed includes model and gateway settings
                                ansible_vars = inventory.get("all", {}).get("vars", {})
                                assert "config" in ansible_vars
                                assert ansible_vars["config"]["provider"]["default_model"] == "deepseek/deepseek-chat-v3"
                                assert ansible_vars["config"]["gateway"]["port"] == 40000
                                assert ansible_vars["config"]["gateway"]["bind"] == "lan"
                                # Verify template_path and agent metadata with exact values
                                assert "template_path" in ansible_vars
                                # Template path should point to openclaw templates directory
                                assert "openclaw/templates" in str(ansible_vars["template_path"])
                                assert ansible_vars["agent_name"] == "ocl-test"
                                assert ansible_vars["agent_type"] == "openclaw"
                                # Verify envvars contains API key
                                envvars = call_args.kwargs.get("envvars", {})
                                assert "CLAWRIUM_PROVIDER_API_KEY" in envvars
                                assert envvars["CLAWRIUM_PROVIDER_API_KEY"] == "sk-or-test"

        assert success is True, f"Configuration failed: {error}"
        assert error is None

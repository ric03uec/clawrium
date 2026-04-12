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
            "agents": {"zer-test": {"type": "zeroclaw"}},
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
            "agents": {"zer-test": {"type": "zeroclaw"}},
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
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
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
            "agents": {"zer-test": {"type": "zeroclaw"}},
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
            "agents": {"zer-test": {"type": "zeroclaw"}},
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
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key", return_value=None
                ):
                    success, error = configure_agent(
                        "test-host", "zeroclaw", config_data
                    )

        assert success is False
        assert "SSH key not found" in error

    def test_returns_false_when_invalid_claw_user_format(self, tmp_path: Path):
        """Test that invalid agent_name format is detected."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {"Invalid User!": {"type": "zeroclaw"}},
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
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    success, error = configure_agent(
                        "test-host", "zeroclaw", config_data, agent_name="Invalid User!"
                    )

        assert success is False
        assert "Invalid agent_name format" in error

    def test_returns_false_when_ansible_times_out(self, tmp_path: Path):
        """Test that Ansible timeout is handled."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
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
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
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
            "agents": {"zer-test": {"type": "zeroclaw"}},
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
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
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
            "agents": {"zer-test": {"type": "zeroclaw"}},
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
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
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
        assert result["gateway"]["bind"] == "lan"

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
        assert result["gateway"]["bind"] == "lan"
        assert result["gateway"]["reload"]["mode"] == "hybrid"
        assert result["gateway"]["reload"]["debounceMs"] == 300
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
        assert result["gateway"]["bind"] == "lan"

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
            "agents": {"ocl-test": {"type": "openclaw"}},
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
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ) as mock_ansible:
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
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
                                assert (
                                    ansible_vars["config"]["provider"]["default_model"]
                                    == "deepseek/deepseek-chat-v3"
                                )
                                assert (
                                    ansible_vars["config"]["gateway"]["port"] == 40000
                                )
                                assert (
                                    ansible_vars["config"]["gateway"]["bind"] == "lan"
                                )
                                # Verify template_path and agent metadata with exact values
                                assert "template_path" in ansible_vars
                                # Template path should point to openclaw templates directory
                                assert "openclaw/templates" in str(
                                    ansible_vars["template_path"]
                                )
                                assert ansible_vars["agent_name"] == "ocl-test"
                                assert ansible_vars["agent_type"] == "openclaw"
                                # Verify API key is passed in inventory vars
                                assert "provider_api_key" in ansible_vars
                                assert ansible_vars["provider_api_key"] == "sk-or-test"

        assert success is True, f"Configuration failed: {error}"
        assert error is None


class TestEnvTemplate:
    """Tests for OpenClaw .env.j2 template rendering."""

    def _render_env_template(self, config, provider_api_key=""):
        """Helper to render the .env.j2 template."""
        template_dir = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/templates"
        )
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template(".env.j2")
        return template.render(config=config, provider_api_key=provider_api_key)

    @staticmethod
    def _parse_env(rendered):
        """Parse rendered env file into key/value map."""
        result = {}
        for line in rendered.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key] = value
        return result

    def test_env_anthropic_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "anthropic",
                "default_model": "anthropic/claude-opus-4-6",
            },
        }
        rendered = self._render_env_template(config, provider_api_key="anthropic-key")
        env_map = self._parse_env(rendered)

        assert env_map["ANTHROPIC_API_KEY"] == "anthropic-key"
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "anthropic/claude-opus-4-6"

    def test_env_openai_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {"type": "openai", "default_model": "openai/gpt-5.4"},
        }
        rendered = self._render_env_template(config, provider_api_key="openai-key")
        env_map = self._parse_env(rendered)

        assert env_map["OPENAI_API_KEY"] == "openai-key"
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "openai/gpt-5.4"

    def test_env_ollama_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "ollama",
                "endpoint": "http://localhost:11434",
                "default_model": "llama3.1:8b",
            },
        }
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert env_map["OPENCLAW_OLLAMA_URL"] == "http://localhost:11434"
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "llama3.1:8b"

    def test_env_openrouter_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "openrouter",
                "default_model": "deepseek/deepseek-chat-v3",
            },
        }
        rendered = self._render_env_template(config, provider_api_key="openrouter-key")
        env_map = self._parse_env(rendered)

        assert env_map["OPENROUTER_API_KEY"] == "openrouter-key"
        # OpenRouter models get prefixed with openrouter/
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "openrouter/deepseek/deepseek-chat-v3"

    def test_env_bedrock_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "bedrock",
                "default_model": "anthropic.claude-3-7-sonnet-20250219-v1:0",
            },
        }
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert "# Bedrock uses AWS credentials from environment/profile" in rendered
        assert "AWS_ACCESS_KEY_ID" not in env_map
        assert "AWS_SECRET_ACCESS_KEY" not in env_map
        assert (
            env_map["OPENCLAW_DEFAULT_MODEL"]
            == "anthropic.claude-3-7-sonnet-20250219-v1:0"
        )

    def test_env_vertex_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "vertex",
                "default_model": "google/gemini-2.5-pro",
            },
        }
        rendered = self._render_env_template(
            config, provider_api_key="/etc/gcp/service-account.json"
        )
        env_map = self._parse_env(rendered)

        assert (
            env_map["GOOGLE_APPLICATION_CREDENTIALS"] == "/etc/gcp/service-account.json"
        )
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "google/gemini-2.5-pro"

    def test_env_zai_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {"type": "zai", "default_model": "zai/glm-4.6"},
        }
        rendered = self._render_env_template(config, provider_api_key="zai-key")
        env_map = self._parse_env(rendered)

        assert env_map["ZAI_API_KEY"] == "zai-key"
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "zai/glm-4.6"

    def test_env_missing_api_key(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "openrouter",
                "default_model": "deepseek/deepseek-chat-v3",
            },
        }
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert "OPENROUTER_API_KEY" not in env_map
        # OpenRouter models get prefixed with openrouter/ for OpenClaw
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "openrouter/deepseek/deepseek-chat-v3"

    def test_env_missing_default_model(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {"type": "openai"},
        }
        rendered = self._render_env_template(config, provider_api_key="openai-key")
        env_map = self._parse_env(rendered)

        assert env_map["OPENAI_API_KEY"] == "openai-key"
        assert "OPENCLAW_DEFAULT_MODEL" not in env_map

    def test_env_gateway_config(self):
        config = {"gateway": {"bind": "loopback", "port": 40123}}
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert env_map["OPENCLAW_GATEWAY_BIND"] == "loopback"
        assert env_map["OPENCLAW_GATEWAY_PORT"] == "40123"

    def test_env_gateway_auth(self):
        config = {"gateway": {"bind": "lan", "port": 40209, "auth": "secret-token"}}
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert env_map["OPENCLAW_GATEWAY_AUTH_MODE"] == "token"
        assert env_map["OPENCLAW_GATEWAY_AUTH_TOKEN"] == "secret-token"

    def test_env_no_provider(self):
        config = {"gateway": {"bind": "lan", "port": 40209}}
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert env_map["OPENCLAW_GATEWAY_BIND"] == "lan"
        assert env_map["OPENCLAW_GATEWAY_PORT"] == "40209"
        assert "OPENCLAW_DEFAULT_MODEL" not in env_map
        assert "ANTHROPIC_API_KEY" not in env_map
        assert "OPENAI_API_KEY" not in env_map
        assert "OPENROUTER_API_KEY" not in env_map
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in env_map
        assert "ZAI_API_KEY" not in env_map


class TestDevicePairingValidation:
    """Tests for device pairing credential validation in Ansible playbook."""

    def _load_playbook(self):
        """Load the install playbook."""
        playbook_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/playbooks/install.yaml"
        )
        import yaml
        with open(playbook_path) as f:
            return yaml.safe_load(f)

    def test_playbook_validates_device_token_exists(self):
        """Test that playbook has validation for missing deviceToken."""
        playbook = self._load_playbook()
        tasks = playbook[0]["tasks"]

        # Find the validation task
        validate_task = None
        for task in tasks:
            if task.get("name") == "Validate device credentials":
                validate_task = task
                break

        assert validate_task is not None, "Missing device credentials validation task"
        assert "device_credentials.deviceToken is not defined" in validate_task["ansible.builtin.fail"]["msg"] or \
               "device_credentials.deviceToken" in str(validate_task.get("when", ""))

    def test_playbook_validates_device_token_length(self):
        """Test that playbook validates deviceToken minimum length."""
        playbook = self._load_playbook()
        tasks = playbook[0]["tasks"]

        # Find the validation task
        validate_task = None
        for task in tasks:
            if task.get("name") == "Validate device credentials":
                validate_task = task
                break

        assert validate_task is not None
        when_condition = str(validate_task.get("when", ""))
        assert "length" in when_condition or "< 10" in when_condition

    def test_pairing_script_handles_malformed_json(self):
        """Test that pair_device.mjs logs parse errors instead of silently ignoring."""
        script_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs"
        )
        content = script_path.read_text()

        # Verify parse errors are logged, not silently ignored
        assert "Failed to parse gateway message" in content or "parse" in content.lower()
        assert "// Ignore parse errors" not in content, "Parse errors should not be silently ignored"

    def test_pairing_script_validates_challenge_nonce(self):
        """Test that pair_device.mjs validates challengeNonce before use."""
        script_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs"
        )
        content = script_path.read_text()

        # Verify null check exists for challengeNonce
        assert "!challengeNonce" in content or "challengeNonce ==" in content, \
            "Missing null check for challengeNonce"

    def test_pairing_script_has_timeout(self):
        """Test that pair_device.mjs has a timeout for pairing."""
        script_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs"
        )
        content = script_path.read_text()

        assert "setTimeout" in content, "Pairing script should have timeout"
        assert "30000" in content or "timeout" in content.lower()

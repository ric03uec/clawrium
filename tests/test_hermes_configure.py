"""Tests for the Hermes configure playbook + template + API_SERVER_KEY persistence.

These cover:
- `.env.j2` rendering across openrouter / anthropic / openai / ollama branches
- `config.yaml.j2` rendering for ollama (model.provider=custom, base_url with /v1)
- `configure.yaml` playbook structure: handler triggers, /health probe, credential
  verification, missing-API_SERVER_KEY guard
- `configure_agent()` rejects hermes agents missing api_server.key in hosts.json
- `configure_agent()` reuses persisted api_server.key across reconfigures
  (idempotency contract)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from jinja2 import Environment, FileSystemLoader

from clawrium.core.lifecycle import configure_agent

HERMES_TEMPLATES = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "hermes"
    / "templates"
)
HERMES_PLAYBOOKS = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "hermes"
    / "playbooks"
)


def _render_env(config: dict, provider_api_key: str = "", agent_name: str = "h") -> str:
    env = Environment(
        loader=FileSystemLoader(str(HERMES_TEMPLATES)),
        keep_trailing_newline=True,
    )
    template = env.get_template(".env.j2")
    return template.render(
        config=config, provider_api_key=provider_api_key, agent_name=agent_name
    )


def _render_config_yaml(config: dict, agent_name: str = "h") -> str:
    env = Environment(
        loader=FileSystemLoader(str(HERMES_TEMPLATES)),
        keep_trailing_newline=True,
    )
    template = env.get_template("config.yaml.j2")
    return template.render(config=config, agent_name=agent_name)


# ---------------------------------------------------------------------------
# .env.j2 rendering — provider branches
# ---------------------------------------------------------------------------


class TestEnvTemplateProviderBranches:
    """Verify each provider branch emits the right credential line and only that one."""

    def _api_server(self) -> dict:
        return {"key": "a" * 64, "host": "127.0.0.1", "port": 8642, "enabled": True}

    def test_openrouter_branch_emits_only_openrouter_key(self):
        rendered = _render_env(
            {
                "provider": {
                    "type": "openrouter",
                    "default_model": "anthropic/claude-opus-4.6",
                },
                "api_server": self._api_server(),
            },
            provider_api_key="sk-or-test-123",
        )
        assert "OPENROUTER_API_KEY=sk-or-test-123" in rendered
        assert "ANTHROPIC_API_KEY=" not in rendered
        assert "OPENAI_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER=openrouter" in rendered

    def test_anthropic_branch_emits_only_anthropic_key(self):
        rendered = _render_env(
            {
                "provider": {"type": "anthropic", "default_model": "claude-opus-4.6"},
                "api_server": self._api_server(),
            },
            provider_api_key="sk-ant-test-456",
        )
        assert "ANTHROPIC_API_KEY=sk-ant-test-456" in rendered
        assert "OPENROUTER_API_KEY=" not in rendered
        assert "OPENAI_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER=anthropic" in rendered

    def test_openai_branch_emits_only_openai_key(self):
        rendered = _render_env(
            {
                "provider": {"type": "openai", "default_model": "gpt-4o"},
                "api_server": self._api_server(),
            },
            provider_api_key="sk-openai-test-789",
        )
        assert "OPENAI_API_KEY=sk-openai-test-789" in rendered
        assert "OPENROUTER_API_KEY=" not in rendered
        assert "ANTHROPIC_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER=openai" in rendered

    def test_ollama_branch_emits_no_provider_api_key_and_custom_provider(self):
        """Ollama / custom local endpoint: no API key required; provider maps to 'custom'."""
        rendered = _render_env(
            {
                "provider": {
                    "type": "ollama",
                    "endpoint": "http://192.168.1.17:11434",
                    "default_model": "qwen3-coder:30b-128k",
                },
                "api_server": self._api_server(),
            },
            provider_api_key="",  # no key for local endpoints
        )
        assert "OPENAI_API_KEY=" not in rendered
        assert "ANTHROPIC_API_KEY=" not in rendered
        assert "OPENROUTER_API_KEY=" not in rendered
        # HERMES_INFERENCE_PROVIDER is the alias 'custom', not 'ollama' (matches
        # hermes_cli/providers.py CUSTOM_ALIASES at v2026.5.7).
        assert "HERMES_INFERENCE_PROVIDER=custom" in rendered

    def test_api_server_block_always_rendered(self):
        rendered = _render_env(
            {
                "provider": {"type": "openrouter", "default_model": "x"},
                "api_server": self._api_server(),
            },
            provider_api_key="k",
        )
        assert "API_SERVER_ENABLED=1" in rendered
        assert "API_SERVER_HOST=127.0.0.1" in rendered
        assert "API_SERVER_PORT=8642" in rendered
        assert "API_SERVER_KEY=" + ("a" * 64) in rendered

    def test_no_provider_api_key_omits_credential_line(self):
        """If provider_api_key is empty, the cloud-provider line is omitted entirely."""
        rendered = _render_env(
            {
                "provider": {"type": "openrouter", "default_model": "x"},
                "api_server": self._api_server(),
            },
            provider_api_key="",
        )
        assert "OPENROUTER_API_KEY=" not in rendered


# ---------------------------------------------------------------------------
# config.yaml.j2 rendering
# ---------------------------------------------------------------------------


class TestConfigYamlTemplate:
    """The model: block is the canonical source of truth for provider / base_url / default."""

    def test_ollama_renders_custom_provider_with_v1_suffix_appended(self):
        rendered = _render_config_yaml(
            {
                "provider": {
                    "type": "ollama",
                    "endpoint": "http://192.168.1.17:11434",
                    "default_model": "qwen3-coder:30b-128k",
                }
            }
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "custom"
        assert parsed["model"]["base_url"] == "http://192.168.1.17:11434/v1"
        assert parsed["model"]["default"] == "qwen3-coder:30b-128k"

    def test_ollama_endpoint_already_has_v1_suffix_not_doubled(self):
        rendered = _render_config_yaml(
            {
                "provider": {
                    "type": "ollama",
                    "endpoint": "http://10.0.0.5:8000/v1",
                    "default_model": "any",
                }
            }
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["base_url"] == "http://10.0.0.5:8000/v1"

    def test_openrouter_renders_provider_and_base_url(self):
        rendered = _render_config_yaml(
            {
                "provider": {
                    "type": "openrouter",
                    "default_model": "anthropic/claude-opus-4.6",
                }
            }
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "openrouter"
        assert parsed["model"]["base_url"] == "https://openrouter.ai/api/v1"
        assert parsed["model"]["default"] == "anthropic/claude-opus-4.6"

    def test_anthropic_omits_base_url(self):
        rendered = _render_config_yaml(
            {"provider": {"type": "anthropic", "default_model": "claude-opus-4.6"}}
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "anthropic"
        assert "base_url" not in parsed["model"]

    def test_openai_omits_base_url(self):
        rendered = _render_config_yaml(
            {"provider": {"type": "openai", "default_model": "gpt-4o"}}
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "openai"
        assert "base_url" not in parsed["model"]


# ---------------------------------------------------------------------------
# configure.yaml playbook shape
# ---------------------------------------------------------------------------


class TestConfigurePlaybookShape:
    """Static checks on the configure playbook contract."""

    def _load_playbook(self) -> dict:
        return yaml.safe_load((HERMES_PLAYBOOKS / "configure.yaml").read_text())[0]

    def test_playbook_renders_env_and_config_yaml(self):
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("Render ~/.hermes/.env" in n for n in names)
        assert any("Render ~/.hermes/config.yaml" in n for n in names)

    def test_playbook_guards_missing_api_server_key(self):
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("Verify API_SERVER_KEY is present in config" == n for n in names)

    def test_playbook_has_health_probe(self):
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("Probe hermes /health endpoint" in n for n in names)

    def test_playbook_restart_handler_triggers_systemd(self):
        play = self._load_playbook()
        handlers = play.get("handlers", [])
        restart = [
            h for h in handlers if "Restart hermes service" in h.get("name", "")
        ]
        assert restart, "configure.yaml must declare a Restart hermes service handler"
        sysd = restart[0]["ansible.builtin.systemd"]
        assert sysd["state"] == "restarted"
        assert sysd["enabled"] is True

    def test_env_template_is_referenced_by_render_task(self):
        play = self._load_playbook()
        tasks = play["tasks"]
        env_render = next(
            (t for t in tasks if "Render ~/.hermes/.env" in t.get("name", "")), None
        )
        assert env_render is not None
        tpl = env_render["ansible.builtin.template"]
        assert tpl["src"].endswith(".env.j2")
        assert tpl["dest"] == "/home/{{ agent_name }}/.hermes/.env"
        assert tpl["mode"] == "0600"
        assert tpl["force"] is True

    def test_ollama_branch_verifies_config_yaml_provider_and_base_url(self):
        """The ollama branch must verify both `provider: custom` and a base_url line."""
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("custom provider for Ollama" in n for n in names)
        assert any("base_url for Ollama" in n for n in names)

    def test_systemd_unit_uses_gateway_run_not_start(self):
        """The Phase 2 unit MUST use `hermes gateway run` — `gateway start`
        delegates to a per-user systemd unit that does not exist in our setup."""
        content = (HERMES_PLAYBOOKS / "configure.yaml").read_text()
        assert "ExecStart=/home/{{ agent_name }}/.local/bin/hermes gateway run" in content
        # Ensure the broken `gateway start` form is NOT what configure.yaml writes.
        # (Phase 1's install.yaml dropped a placeholder using `gateway start`;
        # configure.yaml owns the runtime ExecStart.)
        configure_content = content.split("hermes systemd unit")[1] if "hermes systemd unit" in content else ""
        assert "gateway start" not in configure_content


# ---------------------------------------------------------------------------
# configure_agent() — api_server.key persistence + idempotency
# ---------------------------------------------------------------------------


class TestConfigureAgentApiServerKey:
    """configure_agent() must enforce + reuse the persisted api_server.key for hermes."""

    def test_hermes_without_persisted_key_returns_error(self):
        """Reject configure when hermes agent record has no api_server.key."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {},  # no api_server block
                }
            },
        }
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )
        assert success is False
        assert "api_server.key" in error
        assert "install" in error  # remediation pointer

    def test_hermes_with_persisted_key_passes_to_ansible(self, tmp_path: Path):
        """When a key is persisted, configure_agent merges it into the ansible config var."""
        persisted_key = "b" * 64
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                            "key": persisted_key,
                        }
                    },
                }
            },
        }
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            mock = MagicMock()
            mock.status = "successful"
            mock.events = []
            return mock

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        # api_server.key must reach the playbook unchanged (idempotency contract).
        sent_config = captured["inventory"]["all"]["vars"]["config"]
        assert sent_config["api_server"]["key"] == persisted_key
        assert sent_config["api_server"]["host"] == "127.0.0.1"
        assert sent_config["api_server"]["port"] == 8642

    def test_hermes_reconfigure_does_not_rotate_persisted_key(self, tmp_path: Path):
        """A second configure call with the same persisted record must use the same key
        (idempotency: keys never rotate on reconfigure)."""
        persisted_key = "c" * 64
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                            "key": persisted_key,
                        }
                    },
                }
            },
        }
        # Caller passes config_data WITHOUT api_server (simulates _sync_provider_config
        # forgetting to carry it through). configure_agent must hydrate from hosts.json.
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {"name": "p", "type": "ollama", "default_model": "x", "endpoint": "http://h:1/v1"},
        }

        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        seen_keys = []

        def fake_run(**kwargs):
            seen_keys.append(
                kwargs["inventory"]["all"]["vars"]["config"]["api_server"]["key"]
            )
            mock = MagicMock()
            mock.status = "successful"
            mock.events = []
            return mock

        for _ in range(2):
            with (
                patch("clawrium.core.lifecycle.get_host", return_value=host),
                patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook,
                ),
                patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ),
                patch(
                    "clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run
                ),
                patch("clawrium.core.lifecycle.update_host", return_value=True),
            ):
                success, error = configure_agent(
                    "test-host", "hermes", dict(config_data), agent_name="hermes-test"
                )
                assert success is True, error

        assert len(seen_keys) == 2
        assert seen_keys[0] == seen_keys[1] == persisted_key

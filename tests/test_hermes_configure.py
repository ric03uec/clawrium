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
        assert "OPENROUTER_API_KEY='sk-or-test-123'" in rendered
        assert "ANTHROPIC_API_KEY=" not in rendered
        assert "OPENAI_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER='openrouter'" in rendered

    def test_anthropic_branch_emits_only_anthropic_key(self):
        rendered = _render_env(
            {
                "provider": {"type": "anthropic", "default_model": "claude-opus-4.6"},
                "api_server": self._api_server(),
            },
            provider_api_key="sk-ant-test-456",
        )
        assert "ANTHROPIC_API_KEY='sk-ant-test-456'" in rendered
        assert "OPENROUTER_API_KEY=" not in rendered
        assert "OPENAI_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER='anthropic'" in rendered

    def test_openai_branch_emits_only_openai_key(self):
        rendered = _render_env(
            {
                "provider": {"type": "openai", "default_model": "gpt-4o"},
                "api_server": self._api_server(),
            },
            provider_api_key="sk-openai-test-789",
        )
        assert "OPENAI_API_KEY='sk-openai-test-789'" in rendered
        assert "OPENROUTER_API_KEY=" not in rendered
        assert "ANTHROPIC_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER='openai'" in rendered

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
        assert "API_SERVER_HOST='127.0.0.1'" in rendered
        assert "API_SERVER_PORT=8642" in rendered
        assert "API_SERVER_KEY='" + ("a" * 64) + "'" in rendered

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

    def test_hermes_malformed_secret_entry_missing_value_returns_error(self):
        """A secrets.json entry that exists but is missing the 'value' field
        must NOT raise KeyError out of configure_agent. The existing missing-
        key error path catches it via the validity check (value resolves to
        None) and returns a friendly remediation tuple."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {},
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
        # Truthy dict, no "value" key — the original `secret_entry["value"]`
        # access would raise KeyError before the validity check ran.
        malformed_secrets = {
            "HERMES_API_SERVER_KEY": {"key": "HERMES_API_SERVER_KEY"}
        }
        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=malformed_secrets,
            ):
                success, error = configure_agent(
                    "test-host", "hermes", config_data, agent_name="hermes-test"
                )
        assert success is False
        assert "HERMES_API_SERVER_KEY" in error
        assert "install" in error

    def test_hermes_without_persisted_key_returns_error(self):
        """Reject configure when secrets.json has no HERMES_API_SERVER_KEY."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {},
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
            # Empty secrets.json for this instance — should trigger the
            # "missing HERMES_API_SERVER_KEY" branch.
            with patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value={}
            ):
                success, error = configure_agent(
                    "test-host", "hermes", config_data, agent_name="hermes-test"
                )
        assert success is False
        assert "HERMES_API_SERVER_KEY" in error
        assert "install" in error  # remediation pointer

    def test_hermes_with_persisted_key_passes_to_ansible(self, tmp_path: Path):
        """When the bearer token is persisted in secrets.json, configure_agent
        hydrates it into the ansible config var alongside the non-sensitive
        shape from hosts.json."""
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
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={
                    "HERMES_API_SERVER_KEY": {
                        "key": "HERMES_API_SERVER_KEY",
                        "value": persisted_key,
                        "created_at": "2026-05-10T00:00:00+00:00",
                        "updated_at": "2026-05-10T00:00:00+00:00",
                        "description": "",
                    }
                },
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        # api_server.key must reach the playbook (idempotency contract);
        # value is now sourced from secrets.json, not hosts.json.
        sent_config = captured["inventory"]["all"]["vars"]["config"]
        assert sent_config["api_server"]["key"] == persisted_key
        # Migration: legacy 127.0.0.1 is rewritten to 0.0.0.0 so hermes binds a
        # reachable interface (Phase 1 of #322 — `clm chat <hermes>` over LAN).
        assert sent_config["api_server"]["host"] == "0.0.0.0"
        assert sent_config["api_server"]["port"] == 8642

    def test_hermes_reconfigure_does_not_rotate_persisted_key(self, tmp_path: Path):
        """A second configure call with the same persisted record must use the same key
        (idempotency: keys never rotate on reconfigure). Key lives in secrets.json."""
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
                        }
                    },
                }
            },
        }
        # Caller passes config_data WITHOUT api_server (simulates
        # _sync_provider_config not carrying it through). configure_agent must
        # hydrate the shape from hosts.json and the bearer token from secrets.json.
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {"name": "p", "type": "ollama", "default_model": "x", "endpoint": "http://h:1/v1"},
        }

        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        secret_entry = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": persisted_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }

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
                patch(
                    "clawrium.core.lifecycle.get_instance_secrets",
                    return_value=secret_entry,
                ),
            ):
                success, error = configure_agent(
                    "test-host", "hermes", dict(config_data), agent_name="hermes-test"
                )
                assert success is True, error

        assert len(seen_keys) == 2
        assert seen_keys[0] == seen_keys[1] == persisted_key


class TestHermesApiServerKeySecretsHygiene:
    """Regression guards for the B3 migration and its iter-2 follow-ups."""

    def test_is_valid_hermes_api_server_key_accepts_canonical(self):
        """64-char lowercase hex is accepted."""
        from clawrium.core.install import _is_valid_hermes_api_server_key

        assert _is_valid_hermes_api_server_key("a" * 64) is True
        assert _is_valid_hermes_api_server_key("0123456789abcdef" * 4) is True

    def test_is_valid_hermes_api_server_key_rejects_invalid(self):
        """Anything non-64-lowercase-hex is rejected."""
        from clawrium.core.install import _is_valid_hermes_api_server_key

        assert _is_valid_hermes_api_server_key("a" * 63) is False  # short
        assert _is_valid_hermes_api_server_key("a" * 65) is False  # long
        assert _is_valid_hermes_api_server_key("A" * 64) is False  # uppercase
        assert _is_valid_hermes_api_server_key("g" * 64) is False  # non-hex
        assert _is_valid_hermes_api_server_key(None) is False
        assert _is_valid_hermes_api_server_key(123) is False
        assert _is_valid_hermes_api_server_key("") is False

    def test_configure_strips_api_server_key_from_persisted_hosts_json(
        self, tmp_path: Path
    ):
        """B3 invariant: the bearer token must NOT land in hosts.json after configure.

        The hydration path puts it on config_data['api_server']['key'] for
        Ansible, but the updater closure must strip it before persisting.
        """
        persisted_key = "d" * 64
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

        captured_updater_arg = {}

        def fake_update_host(hostname_arg, updater):
            # Run the updater on a copy of the host fixture to capture what
            # configure_agent intends to persist.
            updated = updater({"agents": dict(host["agents"])})
            captured_updater_arg["agents"] = updated["agents"]
            return True

        secrets_fixture = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": persisted_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch("clawrium.core.lifecycle.get_host_private_key", return_value=key_path),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch(
                "clawrium.core.lifecycle.update_host", side_effect=fake_update_host
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=secrets_fixture,
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        persisted_api_server = (
            captured_updater_arg["agents"]["hermes-test"]
            .get("config", {})
            .get("api_server", {})
        )
        # B3 invariant — the bearer token must not be persisted to hosts.json.
        assert "key" not in persisted_api_server, (
            "hermes bearer token leaked into hosts.json: " f"{persisted_api_server}"
        )
        # Non-sensitive shape is preserved (with the host migration applied).
        assert persisted_api_server.get("enabled") is True
        assert persisted_api_server.get("host") == "0.0.0.0"
        assert persisted_api_server.get("port") == 8642

    def test_configure_rejects_invalid_hex_key_in_secrets(self, tmp_path: Path):
        """A corrupted (non-hex / wrong length) HERMES_API_SERVER_KEY is rejected
        before reaching the Ansible playbook."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {"api_server": {"enabled": True, "host": "127.0.0.1", "port": 8642}},
                }
            },
        }
        bad_secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "G" * 64,  # uppercase / non-hex
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }
        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=bad_secrets,
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {"provider": {"name": "p", "type": "openrouter", "default_model": "x"}},
                agent_name="hermes-test",
            )
        assert success is False
        assert "invalid" in error.lower()
        assert "HERMES_API_SERVER_KEY" in error

    def test_configure_uses_canonical_hostname_for_instance_key(self, tmp_path: Path):
        """Regression guard for commit 27d1ea8 + W1 from ATX iter 2: instance_key
        must derive from host['hostname'], not the alias passed by the CLI."""
        persisted_key = "e" * 64
        host = {
            "hostname": "192.168.1.100",  # canonical
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {"api_server": {"enabled": True, "host": "127.0.0.1", "port": 8642}},
                }
            },
        }
        secrets_fixture = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": persisted_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        get_secrets_mock = MagicMock(return_value=secrets_fixture)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch("clawrium.core.lifecycle.get_host_private_key", return_value=key_path),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                side_effect=get_secrets_mock,
            ),
        ):
            # Caller passes the ALIAS form. Internally configure_agent must
            # resolve via host['hostname'] (canonical) for the instance_key.
            success, _ = configure_agent(
                "wolf-i",
                "hermes",
                {"provider": {"name": "p", "type": "openrouter", "default_model": "x"}},
                agent_name="hermes-test",
            )
        assert success is True
        # instance_key passed to get_instance_secrets must be the canonical form.
        # Ignore additional calls (lifecycle queries secrets for other purposes).
        called_keys = [args[0] for args, _ in get_secrets_mock.call_args_list]
        assert "192.168.1.100:hermes:hermes-test" in called_keys, called_keys
        assert "wolf-i:hermes:hermes-test" not in called_keys, called_keys


class TestConfigureYamlHandlerShape:
    """B1 (iter 1) regression guard: configure.yaml must have exactly one
    restart handler — having two caused a double restart on first configure."""

    def test_configure_playbook_has_single_restart_handler(self):
        playbook_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/hermes/playbooks/configure.yaml"
        )
        data = yaml.safe_load(playbook_path.read_text())
        assert isinstance(data, list) and len(data) == 1
        play = data[0]
        handlers = play.get("handlers", [])
        # All handlers must be restarts (no daemon-only handlers).
        restart_handlers = [
            h for h in handlers if "Restart" in h.get("name", "")
        ]
        assert len(handlers) == len(restart_handlers) == 1, (
            f"expected exactly 1 restart handler, got {len(handlers)} total / "
            f"{len(restart_handlers)} restart: "
            f"{[h.get('name') for h in handlers]}"
        )


# ---------------------------------------------------------------------------
# Discord channel — .env.j2 rendering + lifecycle hydration + B3 strip
# ---------------------------------------------------------------------------


class TestEnvTemplateDiscordBranch:
    """Verify the Discord block in .env.j2 emits the right env vars under
    each config shape (issue #324)."""

    def _base_config(self) -> dict:
        return {
            "provider": {"type": "openrouter", "default_model": "anthropic/x"},
            "api_server": {
                "key": "a" * 64,
                "host": "127.0.0.1",
                "port": 8642,
                "enabled": True,
            },
        }

    def test_discord_block_omitted_when_disabled(self):
        cfg = self._base_config()
        cfg["channels"] = {"discord": {"enabled": False}}
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_BOT_TOKEN" not in rendered
        assert "DISCORD_ALLOWED_USERS" not in rendered

    def test_discord_block_omitted_when_channels_missing(self):
        rendered = _render_env(self._base_config(), provider_api_key="sk-x")
        assert "DISCORD_" not in rendered

    def test_discord_block_omitted_when_enabled_but_no_token(self):
        """Partial config — enabled but token missing — must not emit an
        empty DISCORD_BOT_TOKEN= line that would crash discord.py."""
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "allowed_users": ["740723459344302120"],
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_BOT_TOKEN" not in rendered
        # Other DISCORD_* lines guarded behind the same `if` should also be absent.
        assert "DISCORD_ALLOWED_USERS" not in rendered

    def test_discord_minimal_renders_token_and_allowed_users(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "bot_token": "BOT.TOKEN.VALUE",
                "allowed_users": ["740723459344302120"],
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_BOT_TOKEN='BOT.TOKEN.VALUE'" in rendered
        assert "DISCORD_ALLOWED_USERS='740723459344302120'" in rendered
        # Optional vars not provided should not appear as empty lines.
        assert "DISCORD_HOME_CHANNEL=" not in rendered
        assert "DISCORD_ALLOWED_CHANNELS=" not in rendered

    def test_discord_full_renders_all_envvars(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "bot_token": "BOT.TOKEN.VALUE",
                "allowed_users": ["111111111111111111", "222222222222222222"],
                "home_channel": "333333333333333333",
                "home_channel_name": "General",
                "home_channel_thread_id": "444444444444444444",
                "allowed_channels": ["555555555555555555", "666666666666666666"],
                "require_mention": True,
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_BOT_TOKEN='BOT.TOKEN.VALUE'" in rendered
        assert (
            "DISCORD_ALLOWED_USERS='111111111111111111,222222222222222222'"
            in rendered
        )
        assert "DISCORD_HOME_CHANNEL='333333333333333333'" in rendered
        assert "DISCORD_HOME_CHANNEL_NAME='General'" in rendered
        assert "DISCORD_HOME_CHANNEL_THREAD_ID='444444444444444444'" in rendered
        assert (
            "DISCORD_ALLOWED_CHANNELS='555555555555555555,666666666666666666'"
            in rendered
        )
        assert "DISCORD_REQUIRE_MENTION='true'" in rendered
        # allow_all_users defaults absent
        assert "DISCORD_ALLOW_ALL_USERS" not in rendered

    def test_discord_allow_all_users_renders_when_true(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "bot_token": "BOT.TOKEN.VALUE",
                "allow_all_users": True,
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_ALLOW_ALL_USERS=true" in rendered

    def test_discord_require_mention_false_renders_lowercase(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "bot_token": "BOT.TOKEN.VALUE",
                "allowed_users": ["111111111111111111"],
                "require_mention": False,
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_REQUIRE_MENTION='false'" in rendered


class TestHermesDiscordHydration:
    """lifecycle.configure_agent hydrates DISCORD_BOT_TOKEN from secrets.json
    and threads it onto config_data['channels']['discord']['bot_token'] when
    the user has enabled the Discord channel for the agent."""

    def _make_host(self, discord_persisted: dict | None = None) -> dict:
        agent_config: dict = {
            "api_server": {"enabled": True, "host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        if discord_persisted is not None:
            agent_config["channels"] = {"discord": discord_persisted}
        return {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": agent_config,
                }
            },
        }

    def _secrets_with(self, api_key: str, discord_token: str | None) -> dict:
        s = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": api_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }
        if discord_token is not None:
            s["DISCORD_BOT_TOKEN"] = {
                "key": "DISCORD_BOT_TOKEN",
                "value": discord_token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Discord bot token",
            }
        return s

    def test_discord_token_hydrated_into_ansible_config(self, tmp_path: Path):
        token = "B" * 64
        host = self._make_host(
            discord_persisted={
                "enabled": True,
                "allowed_users": ["740723459344302120"],
                "home_channel": "1503238729962356777",
                "home_channel_name": "Home",
                "require_mention": True,
            }
        )
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        secrets = self._secrets_with("a" * 64, token)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run
            ),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["channels"]["discord"]["bot_token"] == token
        # Persisted shape from hosts.json is merged onto config_data.
        assert sent["channels"]["discord"]["allowed_users"] == ["740723459344302120"]
        assert sent["channels"]["discord"]["home_channel"] == "1503238729962356777"

    def test_discord_disabled_does_not_hydrate(self, tmp_path: Path):
        """When discord.enabled is False (or missing), no DISCORD_BOT_TOKEN is
        threaded onto config_data, even if the token exists in secrets.json."""
        host = self._make_host(discord_persisted=None)
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        # Discord secret exists but channels.discord block doesn't — hydration
        # block should be a no-op.
        secrets = self._secrets_with("a" * 64, "Z" * 64)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run
            ),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        # channels block either absent or, if present, no bot_token field.
        discord = sent.get("channels", {}).get("discord", {})
        assert "bot_token" not in discord

    def test_discord_enabled_without_token_rejected(self, tmp_path: Path):
        host = self._make_host(
            discord_persisted={
                "enabled": True,
                "allowed_users": ["740723459344302120"],
            }
        )
        # secrets.json has only api_server key, no DISCORD_BOT_TOKEN
        secrets = self._secrets_with("a" * 64, None)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )
        assert success is False
        assert "DISCORD_BOT_TOKEN" in error
        assert "secrets.json" in error or "configure" in error.lower()

    def test_discord_reconfigure_does_not_rotate_token(self, tmp_path: Path):
        """Two configure calls must hydrate the byte-identical token from
        secrets.json (idempotency)."""
        token = "C" * 64
        host = self._make_host(
            discord_persisted={
                "enabled": True,
                "allowed_users": ["740723459344302120"],
            }
        )
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        secrets = self._secrets_with("a" * 64, token)
        seen_tokens = []

        def fake_run(**kwargs):
            sent = kwargs["inventory"]["all"]["vars"]["config"]
            seen_tokens.append(sent["channels"]["discord"]["bot_token"])
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

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
                    "clawrium.core.lifecycle.ansible_runner.run",
                    side_effect=fake_run,
                ),
                patch("clawrium.core.lifecycle.update_host", return_value=True),
                patch(
                    "clawrium.core.lifecycle.get_instance_secrets",
                    return_value=secrets,
                ),
            ):
                success, error = configure_agent(
                    "test-host",
                    "hermes",
                    {
                        "provider": {
                            "name": "p",
                            "type": "openrouter",
                            "default_model": "x",
                        }
                    },
                    agent_name="hermes-test",
                )
                assert success is True, error

        assert len(seen_tokens) == 2
        assert seen_tokens[0] == seen_tokens[1] == token


class TestHermesDiscordSecretsHygiene:
    """B3 invariant for Discord: bot_token must never appear in hosts.json
    after configure (mirror of the api_server.key strip)."""

    def test_configure_strips_discord_bot_token_from_persisted_hosts_json(
        self, tmp_path: Path
    ):
        token = "D" * 64
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
                        },
                        "channels": {
                            "discord": {
                                "enabled": True,
                                "allowed_users": ["740723459344302120"],
                                "home_channel": "1503238729962356777",
                            }
                        },
                    },
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {}

        def fake_update_host(hostname_arg, updater):
            updated = updater({"agents": dict(host["agents"])})
            captured["agents"] = updated["agents"]
            return True

        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "DISCORD_BOT_TOKEN": {
                "key": "DISCORD_BOT_TOKEN",
                "value": token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Discord bot token",
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch(
                "clawrium.core.lifecycle.update_host", side_effect=fake_update_host
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        persisted_discord = (
            captured["agents"]["hermes-test"]
            .get("config", {})
            .get("channels", {})
            .get("discord", {})
        )
        # B3 invariant: bot_token must NOT be persisted.
        assert "bot_token" not in persisted_discord, (
            "Discord bot token leaked into hosts.json: " f"{persisted_discord}"
        )
        # Non-sensitive shape preserved.
        assert persisted_discord.get("enabled") is True
        assert persisted_discord.get("allowed_users") == ["740723459344302120"]
        assert persisted_discord.get("home_channel") == "1503238729962356777"


class TestConfigureYamlDiscordVerifyTasks:
    """The configure.yaml playbook gates Discord verification tasks on the
    enabled flag — they must not run for cli-only agents."""

    def _playbook(self) -> dict:
        playbook_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/hermes/playbooks/configure.yaml"
        )
        return yaml.safe_load(playbook_path.read_text())[0]

    def test_discord_token_verify_task_gated_on_enabled(self):
        play = self._playbook()
        tasks = play.get("tasks", [])
        names = [t.get("name", "") for t in tasks]
        token_tasks = [
            t for t in tasks if "DISCORD_BOT_TOKEN" in t.get("name", "")
        ]
        assert token_tasks, (
            "expected a DISCORD_BOT_TOKEN verify task in configure.yaml: " f"{names}"
        )
        for task in token_tasks:
            when_clauses = task.get("when") or []
            joined = " ".join(when_clauses) if isinstance(when_clauses, list) else str(
                when_clauses
            )
            assert "channels" in joined and "discord" in joined and "enabled" in joined, (
                f"DISCORD_BOT_TOKEN task missing gating clause: {when_clauses}"
            )

    def test_discord_allowlist_verify_task_gated_on_enabled(self):
        play = self._playbook()
        tasks = play.get("tasks", [])
        allowlist_tasks = [
            t for t in tasks if "allowlist" in t.get("name", "").lower()
        ]
        assert allowlist_tasks, "expected a Discord allowlist verify task"
        for task in allowlist_tasks:
            when_clauses = task.get("when") or []
            joined = " ".join(when_clauses) if isinstance(when_clauses, list) else str(
                when_clauses
            )
            assert "channels" in joined and "discord" in joined and "enabled" in joined


class TestHermesDiscordSecretsHygieneNegative:
    """B3 negative guard: even if an upstream caller injects bot_token into
    config_data directly, the updater closure strips it before persisting."""

    def test_strip_runs_even_when_bot_token_injected_into_config_data(
        self, tmp_path: Path
    ):
        """Simulate a future code path (or test harness) that accidentally
        passes config_data with bot_token already set — the updater closure
        MUST still strip it. This is the failure mode the strip exists to
        guard against; we test it explicitly here."""
        token = "E" * 64
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
                        },
                        "channels": {
                            "discord": {
                                "enabled": True,
                                "allowed_users": ["111111111111111111"],
                            }
                        },
                    },
                }
            },
        }
        # Caller passes config_data with bot_token already inlined — this is
        # the leaky scenario the strip exists to defeat.
        config_data = {
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
            "channels": {
                "discord": {
                    "enabled": True,
                    "allowed_users": ["111111111111111111"],
                    "bot_token": "INJECTED-FROM-CALLER",  # must be stripped
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured: dict = {}

        def fake_update_host(hostname_arg, updater):
            updated = updater({"agents": dict(host["agents"])})
            captured["agents"] = updated["agents"]
            return True

        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "DISCORD_BOT_TOKEN": {
                "key": "DISCORD_BOT_TOKEN",
                "value": token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Discord bot token",
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch(
                "clawrium.core.lifecycle.update_host", side_effect=fake_update_host
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        persisted_discord = (
            captured["agents"]["hermes-test"]
            .get("config", {})
            .get("channels", {})
            .get("discord", {})
        )
        # Even though the caller passed bot_token, the strip layer caught it.
        assert "bot_token" not in persisted_discord, (
            f"Strip layer failed to catch injected bot_token: {persisted_discord}"
        )


class TestHermesDiscordIdempotency:
    """Re-running channels configure with the same inputs must produce
    byte-identical .env output and same DISCORD_BOT_TOKEN value."""

    def test_reconfigure_renders_byte_identical_env(self, tmp_path: Path):
        """Two configure calls hydrate the same DISCORD_BOT_TOKEN value and
        the same channels.discord shape; .env.j2 against both produces
        byte-identical output (no field reordering, no whitespace drift)."""
        token = "F" * 64
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
                        },
                        "channels": {
                            "discord": {
                                "enabled": True,
                                "allowed_users": ["111111111111111111"],
                                "home_channel": "222222222222222222",
                                "home_channel_name": "Home",
                                "require_mention": True,
                            }
                        },
                    },
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "DISCORD_BOT_TOKEN": {
                "key": "DISCORD_BOT_TOKEN",
                "value": token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Discord bot token",
            },
        }
        renders: list[str] = []

        def fake_run(**kwargs):
            sent = kwargs["inventory"]["all"]["vars"]["config"]
            # Render .env.j2 with the hydrated config and capture the output.
            from jinja2 import Environment, FileSystemLoader

            env_jinja = Environment(
                loader=FileSystemLoader(str(HERMES_TEMPLATES)),
                keep_trailing_newline=True,
            )
            tpl = env_jinja.get_template(".env.j2")
            renders.append(
                tpl.render(config=sent, provider_api_key="sk-x", agent_name="h")
            )
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

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
                    "clawrium.core.lifecycle.ansible_runner.run",
                    side_effect=fake_run,
                ),
                patch("clawrium.core.lifecycle.update_host", return_value=True),
                patch(
                    "clawrium.core.lifecycle.get_instance_secrets",
                    return_value=secrets,
                ),
            ):
                success, error = configure_agent(
                    "test-host",
                    "hermes",
                    {
                        "provider": {
                            "name": "p",
                            "type": "openrouter",
                            "default_model": "x",
                        }
                    },
                    agent_name="hermes-test",
                )
                assert success is True, error

        assert len(renders) == 2
        assert renders[0] == renders[1], "non-idempotent .env render"
        # And the rendered token is the expected value.
        assert f"DISCORD_BOT_TOKEN='{token}'" in renders[0]


class TestDiscordSecretRemoval:
    """clm agent remove purges DISCORD_BOT_TOKEN alongside HERMES_API_SERVER_KEY
    via remove_instance_secrets() — no Discord-specific code path needed."""

    def test_remove_instance_secrets_purges_discord_token(self, tmp_path: Path):
        import os

        from clawrium.core.secrets import (
            list_instances_with_secrets,
            remove_instance_secrets,
            set_instance_secret,
        )

        os.environ["CLAWRIUM_CONFIG_DIR"] = str(tmp_path)
        try:
            ik = "host:hermes:agent"
            set_instance_secret(ik, "HERMES_API_SERVER_KEY", "a" * 64, "")
            set_instance_secret(ik, "DISCORD_BOT_TOKEN", "B" * 64, "Discord")
            assert ik in list_instances_with_secrets()

            assert remove_instance_secrets(ik) is True
            assert ik not in list_instances_with_secrets()
        finally:
            os.environ.pop("CLAWRIUM_CONFIG_DIR", None)


# ---------------------------------------------------------------------------
# Bind migration (Phase 1 of #322) — opportunistically rewrite legacy
# host="127.0.0.1" to "0.0.0.0" in hosts.json on the next configure call.
# ---------------------------------------------------------------------------


class TestHermesBindMigration:
    """Existing hermes installs with loopback bind get rewritten on configure."""

    def _persisted_key_secret(self, key_value: str) -> dict:
        return {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": key_value,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }

    def _make_host(self, host_value: str) -> dict:
        return {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": host_value,
                            "port": 8642,
                        }
                    },
                }
            },
        }

    def _run_configure(self, host_value: str, tmp_path: Path):
        host = self._make_host(host_value)
        config_data = {
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

        captured = {"inventory": None, "update_calls": []}

        def fake_update_host(hostname_arg, updater):
            # Mutate the in-memory fixture so subsequent reads see the migration.
            updated = updater(host)
            captured["update_calls"].append(
                updated["agents"]["hermes-test"]["config"]["api_server"].copy()
            )
            return True

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
            patch(
                "clawrium.core.lifecycle.update_host", side_effect=fake_update_host
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=self._persisted_key_secret("a" * 64),
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )
        assert success is True, error
        return host, captured

    def test_legacy_loopback_is_rewritten_to_zero_bind(self, tmp_path: Path):
        """Persisted host=127.0.0.1 must be rewritten to 0.0.0.0 on configure."""
        host, captured = self._run_configure("127.0.0.1", tmp_path)

        # The in-memory fixture was mutated by the migration's update_host call.
        assert (
            host["agents"]["hermes-test"]["config"]["api_server"]["host"] == "0.0.0.0"
        )
        # The config sent to the playbook reflects the migrated bind.
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["api_server"]["host"] == "0.0.0.0"

    def test_migration_is_idempotent(self, tmp_path: Path):
        """A second configure on an already-migrated record makes no migration
        write. configure_agent still performs its single post-Ansible persist
        of the agent record (line 1137), so we expect exactly one update_host
        call total — the persist, not a migration rewrite. A no-op migration
        write would push the count to two and this assertion would catch it."""
        host, captured = self._run_configure("0.0.0.0", tmp_path)

        assert (
            host["agents"]["hermes-test"]["config"]["api_server"]["host"] == "0.0.0.0"
        )
        # Exactly one update_host call: the final post-Ansible persist.
        # If the migration block ever fires unnecessarily, count goes to 2.
        assert len(captured["update_calls"]) == 1, (
            f"expected 1 update_host call (post-Ansible persist only), "
            f"got {len(captured['update_calls'])}: {captured['update_calls']}"
        )
        # And the persisted value is still 0.0.0.0 (sanity check).
        assert captured["update_calls"][0]["host"] == "0.0.0.0"

    def test_migration_pass_writes_twice(self, tmp_path: Path):
        """On a legacy 127.0.0.1 record, configure_agent calls update_host
        exactly twice: once for the migration rewrite, once for the
        post-Ansible persist. This pairs with `test_migration_is_idempotent`
        — together they prove the migration runs exactly when it should."""
        _host, captured = self._run_configure("127.0.0.1", tmp_path)

        assert len(captured["update_calls"]) == 2, (
            f"expected 2 update_host calls (migration + post-Ansible persist), "
            f"got {len(captured['update_calls'])}: {captured['update_calls']}"
        )
        # The migration write (first) and the persist (second) both end with
        # host=0.0.0.0 because the migration mutates the fixture in place.
        assert captured["update_calls"][0]["host"] == "0.0.0.0"
        assert captured["update_calls"][1]["host"] == "0.0.0.0"

    def test_legacy_missing_api_server_block_uses_zero_bind_default(
        self, tmp_path: Path
    ):
        """If hosts.json has no api_server block at all (legacy/corrupted),
        configure rebuilds defaults with host=0.0.0.0 — not the loopback we
        used to ship with."""
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
            "provider": {"name": "p", "type": "openrouter", "default_model": "x"},
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
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=self._persisted_key_secret("b" * 64),
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["api_server"]["host"] == "0.0.0.0"
        assert sent["api_server"]["port"] == 8642


# ---------------------------------------------------------------------------
# Slack template + hydration tests (mirrors Discord test classes above)
# ---------------------------------------------------------------------------


class TestEnvTemplateSlackBranch:
    """Verify the Slack block in .env.j2 emits the right env vars under
    each config shape."""

    def _base_config(self) -> dict:
        return {
            "provider": {"type": "openrouter", "default_model": "anthropic/x"},
            "api_server": {
                "key": "a" * 64,
                "host": "127.0.0.1",
                "port": 8642,
                "enabled": True,
            },
        }

    def test_slack_block_omitted_when_disabled(self):
        cfg = self._base_config()
        cfg["channels"] = {"slack": {"enabled": False}}
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "SLACK_BOT_TOKEN" not in rendered
        assert "SLACK_APP_TOKEN" not in rendered
        assert "SLACK_ALLOWED_USERS" not in rendered

    def test_slack_block_omitted_when_channels_missing(self):
        rendered = _render_env(self._base_config(), provider_api_key="sk-x")
        assert "SLACK_" not in rendered

    def test_slack_block_omitted_when_enabled_but_no_tokens(self):
        """Partial config — enabled but tokens missing — must not emit empty
        SLACK_BOT_TOKEN= line that would crash the Slack connector."""
        cfg = self._base_config()
        cfg["channels"] = {
            "slack": {
                "enabled": True,
                "allowed_users": ["U01ABC2DEF3"],
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "SLACK_BOT_TOKEN" not in rendered
        assert "SLACK_APP_TOKEN" not in rendered
        assert "SLACK_ALLOWED_USERS" not in rendered

    def test_slack_minimal_renders_tokens_and_allowed_users(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "slack": {
                "enabled": True,
                "bot_token": "xoxb-TOKEN-VALUE",
                "app_token": "xapp-TOKEN-VALUE",
                "allowed_users": ["U01ABC2DEF3"],
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "SLACK_BOT_TOKEN='xoxb-TOKEN-VALUE'" in rendered
        assert "SLACK_APP_TOKEN='xapp-TOKEN-VALUE'" in rendered
        assert "SLACK_ALLOWED_USERS='U01ABC2DEF3'" in rendered
        # Optional vars not provided should not appear as empty lines.
        assert "SLACK_HOME_CHANNEL=" not in rendered
        assert "SLACK_HOME_CHANNEL_NAME=" not in rendered

    def test_slack_full_renders_all_envvars(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "slack": {
                "enabled": True,
                "bot_token": "xoxb-TOKEN-VALUE",
                "app_token": "xapp-TOKEN-VALUE",
                "allowed_users": ["U01ABC2DEF3", "U99XYZ8PQRS"],
                "home_channel": "C01234567890",
                "home_channel_name": "general",
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "SLACK_BOT_TOKEN='xoxb-TOKEN-VALUE'" in rendered
        assert "SLACK_APP_TOKEN='xapp-TOKEN-VALUE'" in rendered
        assert "SLACK_ALLOWED_USERS='U01ABC2DEF3,U99XYZ8PQRS'" in rendered
        assert "SLACK_HOME_CHANNEL='C01234567890'" in rendered
        assert "SLACK_HOME_CHANNEL_NAME='general'" in rendered


class TestHermesSlackHydration:
    """lifecycle.configure_agent hydrates SLACK_BOT_TOKEN and SLACK_APP_TOKEN
    from secrets.json and threads them onto config_data['channels']['slack']
    when the user has enabled the Slack channel for the agent."""

    def _make_host(self, slack_persisted: dict | None = None) -> dict:
        agent_config: dict = {
            "api_server": {"enabled": True, "host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        if slack_persisted is not None:
            agent_config["channels"] = {"slack": slack_persisted}
        return {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": agent_config,
                }
            },
        }

    def _secrets_with(
        self, api_key: str, slack_bot: str | None, slack_app: str | None
    ) -> dict:
        s = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": api_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }
        if slack_bot is not None:
            s["SLACK_BOT_TOKEN"] = {
                "key": "SLACK_BOT_TOKEN",
                "value": slack_bot,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack bot token",
            }
        if slack_app is not None:
            s["SLACK_APP_TOKEN"] = {
                "key": "SLACK_APP_TOKEN",
                "value": slack_app,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack app token",
            }
        return s

    def test_slack_tokens_hydrated_into_ansible_config(self, tmp_path: Path):
        bot_token = "xoxb-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        app_token = "xapp-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        host = self._make_host(
            slack_persisted={
                "enabled": True,
                "allowed_users": ["U01ABC2DEF3"],
                "home_channel": "C01234567890",
                "home_channel_name": "general",
            }
        )
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        secrets = self._secrets_with("a" * 64, bot_token, app_token)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run
            ),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["channels"]["slack"]["bot_token"] == bot_token
        assert sent["channels"]["slack"]["app_token"] == app_token
        # Persisted shape from hosts.json is merged onto config_data.
        assert sent["channels"]["slack"]["allowed_users"] == ["U01ABC2DEF3"]
        assert sent["channels"]["slack"]["home_channel"] == "C01234567890"

    def test_slack_disabled_does_not_hydrate(self, tmp_path: Path):
        """When slack.enabled is False (or missing), no SLACK_BOT_TOKEN is
        threaded onto config_data, even if the tokens exist in secrets.json."""
        host = self._make_host(slack_persisted=None)
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        secrets = self._secrets_with(
            "a" * 64,
            "xoxb-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS",
            "xapp-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS",
        )

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run
            ),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        # No slack key in channels at all (or if present, no bot_token hydrated)
        slack_cfg = sent.get("channels", {}).get("slack", {})
        assert "bot_token" not in slack_cfg
        assert "app_token" not in slack_cfg

    def test_slack_enabled_without_bot_token_rejected(self, tmp_path: Path):
        """Slack enabled but token missing from secrets must fail with a clear
        error message pointing to re-configure."""
        host = self._make_host(
            slack_persisted={
                "enabled": True,
                "allowed_users": ["U01ABC2DEF3"],
            }
        )
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        # No Slack tokens in secrets
        secrets = self._secrets_with("a" * 64, None, None)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is False
        assert "SLACK_BOT_TOKEN" in error
        assert "secrets.json" in error


class TestHermesSlackSecretsHygiene:
    """B3 invariant for Slack: bot_token and app_token must never appear in
    hosts.json after configure (mirror of the Discord strip)."""

    def test_configure_strips_slack_tokens_from_persisted_hosts_json(
        self, tmp_path: Path
    ):
        bot_token = "xoxb-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        app_token = "xapp-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
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
                        },
                        "channels": {
                            "slack": {
                                "enabled": True,
                                "allowed_users": ["U01ABC2DEF3"],
                                "home_channel": "C01234567890",
                                "home_channel_name": "general",
                            }
                        },
                    },
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {}

        def fake_update_host(hostname_arg, updater):
            updated = updater({"agents": dict(host["agents"])})
            captured["agents"] = updated["agents"]
            return True

        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "SLACK_BOT_TOKEN": {
                "key": "SLACK_BOT_TOKEN",
                "value": bot_token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack bot token",
            },
            "SLACK_APP_TOKEN": {
                "key": "SLACK_APP_TOKEN",
                "value": app_token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack app token",
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch(
                "clawrium.core.lifecycle.update_host", side_effect=fake_update_host
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        persisted_slack = (
            captured["agents"]["hermes-test"]
            .get("config", {})
            .get("channels", {})
            .get("slack", {})
        )
        assert "bot_token" not in persisted_slack, (
            f"Slack bot_token leaked into hosts.json: {persisted_slack}"
        )
        assert "app_token" not in persisted_slack, (
            f"Slack app_token leaked into hosts.json: {persisted_slack}"
        )
        # Non-sensitive shape preserved.
        assert persisted_slack.get("enabled") is True
        assert persisted_slack.get("allowed_users") == ["U01ABC2DEF3"]
        assert persisted_slack.get("home_channel") == "C01234567890"
        assert persisted_slack.get("home_channel_name") == "general"

    def test_strip_runs_when_slack_tokens_injected_into_config_data(
        self, tmp_path: Path
    ):
        """Defense-in-depth: even if a caller passes config_data with Slack
        tokens already inlined, the persist-time strip removes them before
        hosts.json is written."""
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
                        }
                    },
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_update_host(hostname_arg, updater):
            updated = updater({"agents": dict(host["agents"])})
            captured["agents"] = updated["agents"]
            return True

        valid_bot = "xoxb-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        valid_app = "xapp-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "SLACK_BOT_TOKEN": {
                "key": "SLACK_BOT_TOKEN",
                "value": valid_bot,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack bot token",
            },
            "SLACK_APP_TOKEN": {
                "key": "SLACK_APP_TOKEN",
                "value": valid_app,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack app token",
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch(
                "clawrium.core.lifecycle.update_host", side_effect=fake_update_host
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets", return_value=secrets
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    },
                    "channels": {
                        "slack": {
                            "enabled": True,
                            "bot_token": "INJECTED-BOT",
                            "app_token": "INJECTED-APP",
                            "allowed_users": ["U01ABC2DEF3"],
                        }
                    },
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        persisted_slack = (
            captured["agents"]["hermes-test"]
            .get("config", {})
            .get("channels", {})
            .get("slack", {})
        )
        assert "bot_token" not in persisted_slack, (
            f"Strip layer failed to catch injected bot_token: {persisted_slack}"
        )
        assert "app_token" not in persisted_slack, (
            f"Strip layer failed to catch injected app_token: {persisted_slack}"
        )

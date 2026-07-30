"""Tests for the openclaw `--provider` mandate at `agent create` time.

The mandate lives at the CLI boundary (`cli/clawctl/agent/create.py`):
openclaw creates without `--provider` must exit non-zero with a hint
pointing at `clawctl provider registry get`. Other agent types
(hermes, zeroclaw, ethos) keep the split lifecycle intact — provider
stays optional at create for them.

The core-layer (`core.install.run_installation`) validates the provider
only if one was passed — this lets tests + direct callers exercise the
install path without needing a full provider fixture, while the runbook
itself fail-fast surfaces the same error when invoked without extravars.

See:
- `core.nemoclaw.CLAWRIUM_TO_NEMOCLAW_PROVIDER` — the mapping table.
- `platform/registry/openclaw/playbooks/install_nemoclaw.yaml` —
  the fail-fast task-0 that mirrors the mandate at runbook layer.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.install import InstallationError, run_installation
from clawrium.core.nemoclaw import (
    CLAWRIUM_TO_NEMOCLAW_PROVIDER,
    UnmappedProviderError,
    clawrium_provider_type_to_nemoclaw,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# CLI-layer mandate
# ---------------------------------------------------------------------------


class TestOpenclawProviderMandate:
    """`clawctl agent create --type openclaw` requires --provider."""

    def test_openclaw_create_without_provider_exits_nonzero_with_hint(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        # Write a bare hosts.json so `--host wolf-i` resolves before the
        # mandate check would run. The mandate should fire regardless.
        (tmp_path / "clawrium").mkdir(parents=True, exist_ok=True)
        (tmp_path / "clawrium" / "hosts.json").write_text(
            json.dumps(
                [
                    {
                        "hostname": "wolf-i",
                        "alias": "wolf-i",
                        "port": 22,
                        "agent_name": "xclm",
                        "key_id": "wolf-i",
                        "hardware": {
                            "architecture": "x86_64",
                            "os": "ubuntu",
                            "os_version": "24.04",
                            "memtotal_mb": 8192,
                        },
                        "agents": {},
                    }
                ]
            )
        )
        result = runner.invoke(
            app,
            ["agent", "create", "e2e-oc", "--type", "openclaw", "--host", "wolf-i"],
        )
        assert result.exit_code != 0, result.output
        assert "--provider is required for openclaw" in result.output
        assert "clawctl provider registry get" in result.output

    def test_hermes_create_without_provider_still_allowed(self, tmp_path, monkeypatch):
        """Regression guard: mandate is openclaw-scoped, not global."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        (tmp_path / "clawrium").mkdir(parents=True, exist_ok=True)
        (tmp_path / "clawrium" / "hosts.json").write_text("[]")
        # We only need to check that the mandate error doesn't fire — a
        # later validation (missing host) is fine. What we're proving: no
        # "--provider is required" gate for hermes.
        result = runner.invoke(
            app,
            ["agent", "create", "e2e-h", "--type", "hermes", "--host", "wolf-i"],
        )
        assert "--provider is required" not in result.output

    def test_zeroclaw_create_without_provider_still_allowed(
        self, tmp_path, monkeypatch
    ):
        """Regression guard: mandate is openclaw-scoped, not global."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        (tmp_path / "clawrium").mkdir(parents=True, exist_ok=True)
        (tmp_path / "clawrium" / "hosts.json").write_text("[]")
        result = runner.invoke(
            app,
            ["agent", "create", "e2e-z", "--type", "zeroclaw", "--host", "wolf-i"],
        )
        assert "--provider is required" not in result.output


# ---------------------------------------------------------------------------
# core.install provider validation (only fires when provider is passed)
# ---------------------------------------------------------------------------


def _write_isolated_host(config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "192.168.1.100",
                    "alias": "server1",
                    "port": 22,
                    "agent_name": "xclm",
                    "key_id": "192.168.1.100",
                    "hardware": {
                        "architecture": "x86_64",
                        "os": "ubuntu",
                        "os_version": "24.04",
                        "memtotal_mb": 8192,
                    },
                    "agents": {},
                }
            ]
        )
    )


@pytest.fixture
def isolated_openclaw_env(tmp_path, monkeypatch):
    """Isolate config dir + stub the manifest lookup + SSH key so
    `run_installation` runs Python-only without touching the network."""
    config_dir = tmp_path / "clawrium"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _write_isolated_host(config_dir)

    import clawrium.core.install as install_mod

    monkeypatch.setattr(install_mod, "get_host_private_key", lambda _: "fake-ssh-key")
    monkeypatch.setattr(
        install_mod,
        "load_manifest",
        lambda _: {
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
                        "dependencies": {"python": ">=3.9"},
                    },
                }
            ],
        },
    )
    return config_dir


class TestOpenclawProviderResolveAtCoreLayer:
    """When `provider=...` is passed, core validates before ansible runs."""

    def test_unknown_provider_raises_with_hint(self, isolated_openclaw_env):
        with pytest.raises(InstallationError, match="not registered"):
            run_installation(
                "openclaw",
                "192.168.1.100",
                name="oc-nemo",
                provider="does-not-exist",
            )

    def test_provider_with_no_api_key_raises_with_hint(
        self, isolated_openclaw_env, tmp_path
    ):
        # Register the provider but leave no secret → validation must fail
        # with the "clawctl secret set" hint.
        (tmp_path / "clawrium" / "providers.json").write_text(
            json.dumps(
                [{"name": "test-or", "type": "openrouter", "default_model": "x"}]
            )
        )
        with pytest.raises(InstallationError, match="no API_KEY"):
            run_installation(
                "openclaw",
                "192.168.1.100",
                name="oc-nemo",
                provider="test-or",
            )

    def test_valid_provider_threads_nemoclaw_envvars(
        self, isolated_openclaw_env, tmp_path
    ):
        # Register a valid provider + API key, then spy on ansible_runner.run
        # to assert NEMOCLAW_PROVIDER + NEMOCLAW_PROVIDER_KEY +
        # NEMOCLAW_POLICY_MODE + NEMOCLAW_SANDBOX_NAME are threaded through.
        (tmp_path / "clawrium" / "providers.json").write_text(
            json.dumps(
                [{"name": "test-or", "type": "openrouter", "default_model": "x"}]
            )
        )
        (tmp_path / "clawrium" / "secrets.json").write_text(
            json.dumps(
                {
                    "provider:test-or": {
                        "API_KEY": {
                            "value": "sk-or-test-abc123",
                            "description": "test key",
                        }
                    }
                }
            )
        )

        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.rc = 0
        with patch(
            "clawrium.core.install.ansible_runner.run",
            return_value=mock_result,
        ) as ansible_spy:
            run_installation(
                "openclaw",
                "192.168.1.100",
                name="oc-nemo",
                provider="test-or",
            )

        # First call is base playbook (no nemoclaw env), second is claw playbook.
        assert ansible_spy.call_count >= 2
        claw_call_envvars = ansible_spy.call_args_list[1].kwargs.get("envvars", {})
        assert claw_call_envvars.get("NEMOCLAW_PROVIDER") == "openrouter"
        assert claw_call_envvars.get("NEMOCLAW_PROVIDER_KEY") == "sk-or-test-abc123"
        assert claw_call_envvars.get("NEMOCLAW_POLICY_MODE") == "suggested"
        assert claw_call_envvars.get("NEMOCLAW_SANDBOX_NAME") == "oc-nemo"

    def test_valid_provider_auto_attaches_to_hosts_json(
        self, isolated_openclaw_env, tmp_path
    ):
        (tmp_path / "clawrium" / "providers.json").write_text(
            json.dumps(
                [{"name": "test-or", "type": "openrouter", "default_model": "x"}]
            )
        )
        (tmp_path / "clawrium" / "secrets.json").write_text(
            json.dumps(
                {
                    "provider:test-or": {
                        "API_KEY": {
                            "value": "sk-or-test-abc123",
                            "description": "test key",
                        }
                    }
                }
            )
        )
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.rc = 0
        with patch(
            "clawrium.core.install.ansible_runner.run",
            return_value=mock_result,
        ):
            run_installation(
                "openclaw",
                "192.168.1.100",
                name="oc-nemo",
                provider="test-or",
            )
        hosts = json.loads(
            (tmp_path / "clawrium" / "hosts.json").read_text()
        )
        agent = hosts[0]["agents"]["oc-nemo"]
        # Auto-attach must persist the canonical provider name.
        assert agent.get("providers") == ["test-or"]

    def test_no_provider_kwarg_does_not_thread_nemoclaw_envvars(
        self, isolated_openclaw_env
    ):
        """Direct callers of run_installation without provider still work —
        the runbook fail-fast fires instead of a Python-side error. Tests
        that mock ansible_runner therefore run clean."""
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.rc = 0
        with patch(
            "clawrium.core.install.ansible_runner.run",
            return_value=mock_result,
        ) as ansible_spy:
            run_installation(
                "openclaw",
                "192.168.1.100",
                name="oc-nemo",
            )
        claw_call_envvars = ansible_spy.call_args_list[1].kwargs.get("envvars", {})
        assert "NEMOCLAW_PROVIDER" not in claw_call_envvars
        assert "NEMOCLAW_PROVIDER_KEY" not in claw_call_envvars


# ---------------------------------------------------------------------------
# core.nemoclaw provider mapping table
# ---------------------------------------------------------------------------


class TestClawriumToNemoclawProviderMapping:
    def test_openrouter_maps_to_openrouter(self):
        assert clawrium_provider_type_to_nemoclaw("openrouter") == "openrouter"

    def test_openai_maps_to_openai(self):
        assert clawrium_provider_type_to_nemoclaw("openai") == "openai"

    def test_anthropic_maps_to_anthropic(self):
        assert clawrium_provider_type_to_nemoclaw("anthropic") == "anthropic"

    def test_anthropic_compatible_normalises_camelcase(self):
        assert (
            clawrium_provider_type_to_nemoclaw("anthropic-compatible")
            == "anthropicCompatible"
        )

    def test_litellm_anthropic_maps_to_anthropic_compatible(self):
        assert (
            clawrium_provider_type_to_nemoclaw("litellm-anthropic")
            == "anthropicCompatible"
        )

    def test_ollama_maps_to_ollama(self):
        assert clawrium_provider_type_to_nemoclaw("ollama") == "ollama"

    def test_vllm_maps_to_vllm(self):
        assert clawrium_provider_type_to_nemoclaw("vllm") == "vllm"

    def test_vllm_inx_alias_maps_to_vllm(self):
        assert clawrium_provider_type_to_nemoclaw("vllm-inx") == "vllm"

    def test_unmapped_type_raises_loudly(self):
        with pytest.raises(UnmappedProviderError) as exc:
            clawrium_provider_type_to_nemoclaw("does-not-exist")
        # Error must list the supported types so operators can self-serve.
        assert "does-not-exist" in str(exc.value)
        assert "openrouter" in str(exc.value)

    def test_empty_string_raises(self):
        with pytest.raises(UnmappedProviderError):
            clawrium_provider_type_to_nemoclaw("")

    def test_mapping_table_values_are_nemoclaw_vocab(self):
        """Guard against a typo like 'anthorpicCompatible' silently
        drifting the table. The full set of known-valid values from
        NemoClaw's install.sh --help:
        build/openrouter/openai/anthropic/anthropicCompatible/gemini/
        ollama/custom/nim-local/vllm/routed/hermes-provider.
        """
        NEMOCLAW_VOCAB = {
            "build",
            "openrouter",
            "openai",
            "anthropic",
            "anthropicCompatible",
            "gemini",
            "ollama",
            "custom",
            "nim-local",
            "vllm",
            "routed",
            "hermes-provider",
        }
        for clawrium_type, nemoclaw_value in CLAWRIUM_TO_NEMOCLAW_PROVIDER.items():
            assert nemoclaw_value in NEMOCLAW_VOCAB, (
                f"mapping {clawrium_type!r}→{nemoclaw_value!r} uses a value "
                f"not in NemoClaw's install.sh vocabulary. Check the enum in "
                f"https://raw.githubusercontent.com/NVIDIA/NemoClaw/main/install.sh"
            )

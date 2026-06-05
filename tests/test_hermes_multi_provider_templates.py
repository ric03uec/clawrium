"""Snapshot-style coverage for hermes multi-provider template rendering (#614).

Both template families MUST render auxiliary.<role> + per-type env keys
when `config.providers[]` (legacy) / `auxiliary_providers` (canonical)
carries non-primary attachments. Single-provider regression pins also
live here so the back-compat invariant is verified next to the
multi-provider assertions instead of buried in test_hermes_configure.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from clawrium.core.render import (
    AuxiliaryProviderInputs,
    ProviderInputs,
    RenderInputs,
    render_hermes,
)


def _ansible_regex_replace(value, pattern, replacement=""):
    return re.sub(pattern, replacement, str(value))


HERMES_TEMPLATES = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "hermes"
    / "templates"
)


def _legacy_env(env_name: str = "hermes.env.j2"):
    env = Environment(
        loader=FileSystemLoader(str(HERMES_TEMPLATES)),
        keep_trailing_newline=True,
    )
    env.filters["regex_replace"] = _ansible_regex_replace
    return env.get_template(env_name)


def _legacy_yaml(yaml_name: str = "hermes-config.yaml.j2"):
    env = Environment(
        loader=FileSystemLoader(str(HERMES_TEMPLATES)),
        keep_trailing_newline=True,
    )
    return env.get_template(yaml_name)


# ---------------------------------------------------------------------------
# Legacy templates (ansible-driven)
# ---------------------------------------------------------------------------


class TestLegacyConfigMultiProvider:
    def test_emits_one_auxiliary_block_with_explicit_and_default(self):
        """Primary anthropic + aux openrouter (role=vision) + aux bedrock
        (role=web_extract). One `auxiliary:` block carrying the default
        title_generation for anthropic plus per-aux entries."""
        rendered = _legacy_yaml().render(
            agent_name="h",
            config={
                "provider": {
                    "type": "anthropic",
                    "default_model": "claude-opus-4-5",
                },
                "providers": [
                    {
                        "name": "ant-primary",
                        "type": "anthropic",
                        "role": "primary",
                        "model": "claude-opus-4-5",
                        "default_model": "claude-opus-4-5",
                    },
                    {
                        "name": "or-vision",
                        "type": "openrouter",
                        "role": "vision",
                        "model": "anthropic/claude-opus-4.6",
                    },
                    {
                        "name": "bedrock-extract",
                        "type": "bedrock",
                        "role": "web_extract",
                        "model": "anthropic.claude-haiku-4-5-20251001-v1:0",
                        "region": "us-west-2",
                    },
                ],
            },
        )
        parsed = yaml.safe_load(rendered)
        # Primary block intact.
        assert parsed["model"]["provider"] == "anthropic"
        assert parsed["model"]["default"] == "claude-opus-4-5"
        # Default title_generation present (anthropic primary, no override).
        aux = parsed["auxiliary"]
        assert aux["title_generation"]["model"] == "claude-haiku-4-5-20251001"
        # Aux entries.
        assert aux["vision"]["provider"] == "openrouter"
        assert aux["vision"]["model"] == "anthropic/claude-opus-4.6"
        assert aux["web_extract"]["provider"] == "bedrock"
        assert (
            aux["web_extract"]["model"]
            == "anthropic.claude-haiku-4-5-20251001-v1:0"
        )

    def test_explicit_title_generation_shadows_default(self):
        """A non-primary attachment with role=title_generation suppresses
        the per-primary-type default."""
        rendered = _legacy_yaml().render(
            agent_name="h",
            config={
                "provider": {"type": "anthropic", "default_model": "p"},
                "providers": [
                    {
                        "name": "ant",
                        "type": "anthropic",
                        "role": "primary",
                        "model": "p",
                    },
                    {
                        "name": "or-tg",
                        "type": "openrouter",
                        "role": "title_generation",
                        "model": "openai/gpt-4o-mini",
                    },
                ],
            },
        )
        parsed = yaml.safe_load(rendered)
        # Operator's choice wins — not the anthropic default.
        assert (
            parsed["auxiliary"]["title_generation"]["model"]
            == "openai/gpt-4o-mini"
        )
        assert parsed["auxiliary"]["title_generation"]["provider"] == "openrouter"

    def test_single_provider_byte_identical_to_legacy_shape(self):
        """Regression pin: a hermes agent with no `providers` list (only
        `config.provider`) renders the same auxiliary.title_generation
        default as before #614 — no spurious `providers` iteration breaks
        un-migrated hosts."""
        rendered = _legacy_yaml().render(
            agent_name="h",
            config={
                "provider": {
                    "type": "anthropic",
                    "default_model": "claude-opus-4-5",
                },
            },
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "anthropic"
        assert (
            parsed["auxiliary"]["title_generation"]["model"]
            == "claude-haiku-4-5-20251001"
        )
        # No phantom aux slots.
        assert set(parsed["auxiliary"].keys()) == {"title_generation"}


class TestLegacyEnvMultiProvider:
    def _api_server(self) -> dict:
        return {"key": "a" * 64, "host": "127.0.0.1", "port": 8642, "enabled": True}

    def test_emits_one_key_per_unique_provider_type(self):
        rendered = _legacy_env().render(
            agent_name="h",
            integrations={},
            config={
                "provider": {"type": "anthropic", "default_model": "p"},
                "providers": [
                    {"name": "ant", "type": "anthropic", "role": "primary"},
                    {"name": "or", "type": "openrouter", "role": "vision"},
                    {
                        "name": "br",
                        "type": "bedrock",
                        "role": "web_extract",
                        "region": "eu-west-1",
                    },
                ],
                "api_server": self._api_server(),
            },
            provider_api_keys={
                "ant": "sk-ant-primary",
                "or": "sk-or-aux",
            },
            provider_aws_credentials={
                "br": {
                    "access_key": "AKIA-AUX",
                    "secret_key": "secret-aux",
                    "region": "eu-west-1",
                }
            },
        )
        assert "ANTHROPIC_API_KEY='sk-ant-primary'" in rendered
        assert "OPENROUTER_API_KEY='sk-or-aux'" in rendered
        assert "AWS_ACCESS_KEY_ID='AKIA-AUX'" in rendered
        assert "AWS_SECRET_ACCESS_KEY='secret-aux'" in rendered
        assert "AWS_DEFAULT_REGION='eu-west-1'" in rendered
        # Primary remains the source of HERMES_INFERENCE_PROVIDER.
        assert "HERMES_INFERENCE_PROVIDER='anthropic'" in rendered

    def test_dedupe_same_type_attachments_emit_one_line(self):
        """Two openrouter attachments share one OPENROUTER_API_KEY line —
        primary's key wins."""
        rendered = _legacy_env().render(
            agent_name="h",
            integrations={},
            config={
                "provider": {"type": "openrouter", "default_model": "p"},
                "providers": [
                    {"name": "or-primary", "type": "openrouter", "role": "primary"},
                    {"name": "or-aux", "type": "openrouter", "role": "vision"},
                ],
                "api_server": self._api_server(),
            },
            provider_api_keys={
                "or-primary": "sk-or-PRIMARY",
                "or-aux": "sk-or-PRIMARY",
            },
            provider_aws_credentials={},
        )
        assert rendered.count("OPENROUTER_API_KEY=") == 1
        assert "OPENROUTER_API_KEY='sk-or-PRIMARY'" in rendered
        # No conflict comment.
        assert "WARNING:" not in rendered

    def test_same_type_different_keys_emits_warning_with_primary_key(self):
        rendered = _legacy_env().render(
            agent_name="h",
            integrations={},
            config={
                "provider": {"type": "openrouter", "default_model": "p"},
                "providers": [
                    {"name": "or-primary", "type": "openrouter", "role": "primary"},
                    {"name": "or-aux", "type": "openrouter", "role": "vision"},
                ],
                "api_server": self._api_server(),
            },
            provider_api_keys={
                "or-primary": "sk-or-PRIMARY",
                "or-aux": "sk-or-DIFFERENT",
            },
            provider_aws_credentials={},
        )
        assert "OPENROUTER_API_KEY='sk-or-PRIMARY'" in rendered
        assert "sk-or-DIFFERENT" not in rendered
        assert "WARNING: multiple openrouter providers attached" in rendered

    def test_single_provider_legacy_path_unchanged(self):
        """When `config.providers` is absent the template falls back to
        the singleton `provider_api_key` scalar — back-compat with tests
        and pre-#613 hosts.json shapes."""
        rendered = _legacy_env().render(
            agent_name="h",
            integrations={},
            config={
                "provider": {"type": "anthropic", "default_model": "p"},
                "api_server": self._api_server(),
            },
            provider_api_key="sk-ant-legacy",
        )
        assert "ANTHROPIC_API_KEY='sk-ant-legacy'" in rendered


# ---------------------------------------------------------------------------
# Canonical templates (pure-Python render_hermes pipeline)
# ---------------------------------------------------------------------------


def _hermes_inputs(
    primary: ProviderInputs,
    auxiliary: tuple[AuxiliaryProviderInputs, ...] = (),
) -> RenderInputs:
    return RenderInputs(
        agent_name="h",
        agent_type="hermes",
        provider=primary,
        auxiliary_providers=auxiliary,
    )


class TestCanonicalMultiProvider:
    def test_yaml_emits_consolidated_auxiliary_block(self):
        rendered = render_hermes(
            _hermes_inputs(
                ProviderInputs(
                    name="ant",
                    type="anthropic",
                    default_model="claude-opus-4-5",
                    api_key="sk-ant",
                ),
                auxiliary=(
                    AuxiliaryProviderInputs(
                        name="or-vision",
                        type="openrouter",
                        role="vision",
                        model="anthropic/claude-opus-4.6",
                        api_key="sk-or",
                    ),
                ),
            )
        ).files[".hermes/config.yaml"]
        parsed = yaml.safe_load(rendered)
        aux = parsed["auxiliary"]
        # Default title_generation for anthropic primary survives.
        assert aux["title_generation"]["model"] == "claude-haiku-4-5-20251001"
        # Aux vision slot.
        assert aux["vision"]["provider"] == "openrouter"
        assert aux["vision"]["model"] == "anthropic/claude-opus-4.6"

    def test_env_dedupe_and_warning_on_conflict(self):
        rendered = render_hermes(
            _hermes_inputs(
                ProviderInputs(
                    name="or-p",
                    type="openrouter",
                    default_model="m",
                    api_key="sk-or-PRIMARY",
                ),
                auxiliary=(
                    AuxiliaryProviderInputs(
                        name="or-aux",
                        type="openrouter",
                        role="vision",
                        model="m2",
                        api_key="sk-or-DIFFERENT",
                    ),
                ),
            )
        ).files[".hermes/.env"]
        assert rendered.count("OPENROUTER_API_KEY=") == 1
        assert "OPENROUTER_API_KEY='sk-or-PRIMARY'" in rendered
        assert "WARNING: multiple openrouter providers" in rendered

    def test_explicit_title_generation_aux_shadows_default(self):
        rendered = render_hermes(
            _hermes_inputs(
                ProviderInputs(
                    name="ant",
                    type="anthropic",
                    default_model="claude-opus-4-5",
                    api_key="sk-ant",
                ),
                auxiliary=(
                    AuxiliaryProviderInputs(
                        name="or-tg",
                        type="openrouter",
                        role="title_generation",
                        model="openai/gpt-4o-mini",
                        api_key="sk-or",
                    ),
                ),
            )
        ).files[".hermes/config.yaml"]
        parsed = yaml.safe_load(rendered)
        tg = parsed["auxiliary"]["title_generation"]
        assert tg["model"] == "openai/gpt-4o-mini"
        assert tg["provider"] == "openrouter"

    def test_single_provider_byte_identical_yaml_shape(self):
        """No auxiliary attachments → yaml shape matches the pre-#614
        canonical render path (default title_generation only)."""
        rendered = render_hermes(
            _hermes_inputs(
                ProviderInputs(
                    name="ant",
                    type="anthropic",
                    default_model="claude-opus-4-5",
                    api_key="sk-ant",
                )
            )
        ).files[".hermes/config.yaml"]
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "anthropic"
        assert (
            parsed["auxiliary"]["title_generation"]["model"]
            == "claude-haiku-4-5-20251001"
        )
        assert set(parsed["auxiliary"].keys()) == {"title_generation"}

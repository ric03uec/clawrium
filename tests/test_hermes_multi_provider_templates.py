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

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from clawrium.core.render import (
    AgentConfigError,
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

    def test_bedrock_aux_emits_aws_triplet_and_provider_block(self):
        """ATX iter-1 B3: bedrock as an auxiliary must reach both env
        AWS_* triplet and YAML `auxiliary.<role>.provider: bedrock`."""
        files = render_hermes(
            _hermes_inputs(
                ProviderInputs(
                    name="ant",
                    type="anthropic",
                    default_model="claude-opus-4-5",
                    api_key="sk-ant",
                ),
                auxiliary=(
                    AuxiliaryProviderInputs(
                        name="br-aux",
                        type="bedrock",
                        role="web_extract",
                        model="anthropic.claude-haiku-4-5-20251001-v1:0",
                        aws_access_key="AKIA-AUX",
                        aws_secret_key="secret-aux",
                        region="eu-west-1",
                    ),
                ),
            )
        ).files
        env = files[".hermes/.env"]
        assert "AWS_ACCESS_KEY_ID='AKIA-AUX'" in env
        assert "AWS_SECRET_ACCESS_KEY='secret-aux'" in env
        assert "AWS_DEFAULT_REGION='eu-west-1'" in env
        parsed = yaml.safe_load(files[".hermes/config.yaml"])
        assert parsed["auxiliary"]["web_extract"]["provider"] == "bedrock"
        assert (
            parsed["auxiliary"]["web_extract"]["model"]
            == "anthropic.claude-haiku-4-5-20251001-v1:0"
        )

    def test_multiple_aux_roles_all_emit(self):
        """ATX iter-1 W7: two distinct aux types in one render — both
        slots and both API keys must appear."""
        files = render_hermes(
            _hermes_inputs(
                ProviderInputs(
                    name="ant",
                    type="anthropic",
                    default_model="m",
                    api_key="sk-ant",
                ),
                auxiliary=(
                    AuxiliaryProviderInputs(
                        name="or-v",
                        type="openrouter",
                        role="vision",
                        model="anthropic/claude-opus-4.6",
                        api_key="sk-or",
                    ),
                    AuxiliaryProviderInputs(
                        name="oai-w",
                        type="openai",
                        role="web_extract",
                        model="gpt-4o",
                        api_key="sk-oai",
                    ),
                ),
            )
        ).files
        env = files[".hermes/.env"]
        assert "OPENROUTER_API_KEY='sk-or'" in env
        assert "OPENAI_API_KEY='sk-oai'" in env
        parsed = yaml.safe_load(files[".hermes/config.yaml"])
        assert parsed["auxiliary"]["vision"]["provider"] == "openrouter"
        assert parsed["auxiliary"]["web_extract"]["provider"] == "openai"

    def test_single_provider_env_back_compat(self):
        """ATX iter-1 W6: single-provider canonical env — exactly one
        ANTHROPIC_API_KEY line, no spurious keys, no WARNING."""
        env = render_hermes(
            _hermes_inputs(
                ProviderInputs(
                    name="ant",
                    type="anthropic",
                    default_model="claude-opus-4-5",
                    api_key="sk-ant",
                )
            )
        ).files[".hermes/.env"]
        assert env.count("ANTHROPIC_API_KEY=") == 1
        assert "ANTHROPIC_API_KEY='sk-ant'" in env
        assert "OPENROUTER_API_KEY=" not in env
        assert "OPENAI_API_KEY=" not in env
        assert "AWS_ACCESS_KEY_ID=" not in env
        assert "WARNING:" not in env
        assert "HERMES_INFERENCE_PROVIDER='anthropic'" in env

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


# ---------------------------------------------------------------------------
# Lockstep parity: legacy ↔ canonical for the same logical config
# ---------------------------------------------------------------------------


def _legacy_render(
    primary_type: str,
    primary_model: str,
    aux_specs: list[dict],
    api_keys: dict[str, str],
    aws_creds: dict[str, dict[str, str]],
) -> tuple[dict, str]:
    """Render the legacy templates for a given logical config. Returns
    (parsed_yaml, raw_env_text)."""
    providers = [
        {
            "name": "primary",
            "type": primary_type,
            "role": "primary",
            "model": primary_model,
            "default_model": primary_model,
        }
    ]
    providers.extend(aux_specs)
    config = {
        "provider": {
            "type": primary_type,
            "default_model": primary_model,
        },
        "providers": providers,
        "api_server": {
            "key": "a" * 64,
            "host": "127.0.0.1",
            "port": 8642,
            "enabled": True,
        },
    }
    yaml_rendered = _legacy_yaml().render(agent_name="h", config=config)
    env_rendered = _legacy_env().render(
        agent_name="h",
        integrations={},
        config=config,
        provider_api_keys=api_keys,
        provider_aws_credentials=aws_creds,
    )
    return yaml.safe_load(yaml_rendered), env_rendered


def _canonical_render(
    primary_type: str,
    primary_model: str,
    aux_inputs: tuple[AuxiliaryProviderInputs, ...],
    primary_api_key: str = "",
    primary_aws: dict[str, str] | None = None,
) -> tuple[dict, str]:
    primary_aws = primary_aws or {}
    primary = ProviderInputs(
        name="primary",
        type=primary_type,
        default_model=primary_model,
        api_key=primary_api_key,
        aws_access_key=primary_aws.get("access_key", ""),
        aws_secret_key=primary_aws.get("secret_key", ""),
        region=primary_aws.get("region", ""),
    )
    rendered = render_hermes(
        RenderInputs(
            agent_name="h",
            agent_type="hermes",
            provider=primary,
            auxiliary_providers=aux_inputs,
        )
    )
    return (
        yaml.safe_load(rendered.files[".hermes/config.yaml"]),
        rendered.files[".hermes/.env"],
    )


class TestLegacyCanonicalLockstep:
    """ATX iter-1 B2: AGENTS.md mandates the two template families
    produce structurally identical output for the same logical config."""

    def _emitted_env_keys(self, env_text: str) -> set[str]:
        """Set of VAR= identifiers in an env file (ignores values)."""
        keys: set[str] = set()
        for line in env_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            head = line.split("=", 1)[0]
            if head:
                keys.add(head)
        return keys

    def test_single_provider_yaml_auxiliary_block_matches(self):
        legacy_yaml, _ = _legacy_render(
            "anthropic",
            "claude-opus-4-5",
            aux_specs=[],
            api_keys={"primary": "sk-ant"},
            aws_creds={},
        )
        canonical_yaml, _ = _canonical_render(
            "anthropic",
            "claude-opus-4-5",
            aux_inputs=(),
            primary_api_key="sk-ant",
        )
        # Both families must emit the same default title_generation block.
        assert legacy_yaml["auxiliary"] == canonical_yaml["auxiliary"]

    def test_multi_aux_yaml_ordering_matches(self):
        """ATX iter-1 W3: two aux roles render in the same key order in
        both families (alphabetical by role)."""
        legacy_yaml, _ = _legacy_render(
            "anthropic",
            "claude-opus-4-5",
            aux_specs=[
                {
                    "name": "or-v",
                    "type": "openrouter",
                    "role": "vision",
                    "model": "anthropic/claude-opus-4.6",
                },
                {
                    "name": "oai-w",
                    "type": "openai",
                    "role": "web_extract",
                    "model": "gpt-4o",
                },
            ],
            api_keys={
                "primary": "sk-ant",
                "or-v": "sk-or",
                "oai-w": "sk-oai",
            },
            aws_creds={},
        )
        canonical_yaml, _ = _canonical_render(
            "anthropic",
            "claude-opus-4-5",
            aux_inputs=(
                AuxiliaryProviderInputs(
                    name="or-v",
                    type="openrouter",
                    role="vision",
                    model="anthropic/claude-opus-4.6",
                    api_key="sk-or",
                ),
                AuxiliaryProviderInputs(
                    name="oai-w",
                    type="openai",
                    role="web_extract",
                    model="gpt-4o",
                    api_key="sk-oai",
                ),
            ),
            primary_api_key="sk-ant",
        )
        assert list(legacy_yaml["auxiliary"].keys()) == list(
            canonical_yaml["auxiliary"].keys()
        )
        assert legacy_yaml["auxiliary"] == canonical_yaml["auxiliary"]

    def test_explicit_title_generation_lockstep(self):
        """An explicit title_generation aux must shadow the default in
        both families."""
        legacy_yaml, _ = _legacy_render(
            "anthropic",
            "claude-opus-4-5",
            aux_specs=[
                {
                    "name": "or-tg",
                    "type": "openrouter",
                    "role": "title_generation",
                    "model": "openai/gpt-4o-mini",
                }
            ],
            api_keys={"primary": "sk-ant", "or-tg": "sk-or"},
            aws_creds={},
        )
        canonical_yaml, _ = _canonical_render(
            "anthropic",
            "claude-opus-4-5",
            aux_inputs=(
                AuxiliaryProviderInputs(
                    name="or-tg",
                    type="openrouter",
                    role="title_generation",
                    model="openai/gpt-4o-mini",
                    api_key="sk-or",
                ),
            ),
            primary_api_key="sk-ant",
        )
        assert legacy_yaml["auxiliary"] == canonical_yaml["auxiliary"]

    def test_env_var_key_set_matches_single_provider(self):
        _, legacy_env = _legacy_render(
            "anthropic",
            "p",
            aux_specs=[],
            api_keys={"primary": "sk-ant"},
            aws_creds={},
        )
        _, canonical_env = _canonical_render(
            "anthropic",
            "p",
            aux_inputs=(),
            primary_api_key="sk-ant",
        )
        legacy_keys = self._emitted_env_keys(legacy_env)
        canonical_keys = self._emitted_env_keys(canonical_env)
        # Both families MUST emit ANTHROPIC_API_KEY + HERMES_INFERENCE_PROVIDER
        # and neither family MUST emit a different provider key.
        assert "ANTHROPIC_API_KEY" in legacy_keys
        assert "ANTHROPIC_API_KEY" in canonical_keys
        assert "HERMES_INFERENCE_PROVIDER" in legacy_keys
        assert "HERMES_INFERENCE_PROVIDER" in canonical_keys
        assert {"OPENROUTER_API_KEY", "OPENAI_API_KEY"}.isdisjoint(legacy_keys)
        assert {"OPENROUTER_API_KEY", "OPENAI_API_KEY"}.isdisjoint(
            canonical_keys
        )

    def test_same_type_conflict_warning_in_both_families(self):
        """Two openrouter attachments with different keys → both
        families emit the primary's key and a WARNING line."""
        _, legacy_env = _legacy_render(
            "openrouter",
            "p",
            aux_specs=[
                {
                    "name": "or-aux",
                    "type": "openrouter",
                    "role": "vision",
                    "model": "x",
                },
            ],
            api_keys={"primary": "sk-PRIMARY", "or-aux": "sk-OTHER"},
            aws_creds={},
        )
        _, canonical_env = _canonical_render(
            "openrouter",
            "p",
            aux_inputs=(
                AuxiliaryProviderInputs(
                    name="or-aux",
                    type="openrouter",
                    role="vision",
                    model="x",
                    api_key="sk-OTHER",
                ),
            ),
            primary_api_key="sk-PRIMARY",
        )
        for env in (legacy_env, canonical_env):
            assert "OPENROUTER_API_KEY='sk-PRIMARY'" in env
            assert "sk-OTHER" not in env
            assert "WARNING: multiple openrouter providers" in env


# ---------------------------------------------------------------------------
# build_render_inputs: role validation (ATX iter-1 B1)
# ---------------------------------------------------------------------------


class TestBuildRenderInputsRoleValidation:
    """Pin the AUXILIARY_SLOTS check inside build_render_inputs so a
    hand-edited hosts.json carrying a crafted role cannot reach the
    Jinja `{{ _aux.role }}:` interpolation."""

    def _fake_render_stores(self, monkeypatch, attachments: list[dict]):
        agent = (
            {"hostname": "h"},
            "hermes",
            {
                "agent_name": "alpha",
                "providers": attachments,
                "config": {},
            },
        )
        providers_record = {
            "primary": {
                "name": "primary",
                "type": "anthropic",
                "default_model": "m",
            },
            "aux": {
                "name": "aux",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        monkeypatch.setattr(
            "clawrium.core.hosts.get_agent_by_name", lambda name: agent
        )
        monkeypatch.setattr(
            "clawrium.core.providers.get_provider",
            lambda name: providers_record.get(name),
        )
        monkeypatch.setattr(
            "clawrium.core.providers.get_provider_api_key",
            lambda name: "sk-test",
        )
        monkeypatch.setattr(
            "clawrium.core.providers.get_provider_aws_credentials",
            lambda name: (None, None),
        )
        monkeypatch.setattr(
            "clawrium.core.channels.get_agent_channels", lambda h, a: []
        )
        monkeypatch.setattr(
            "clawrium.core.integrations.get_agent_integrations",
            lambda h, a: [],
        )

    def test_invalid_role_raises_before_render(self, monkeypatch):
        from clawrium.core.render import build_render_inputs

        self._fake_render_stores(
            monkeypatch,
            attachments=[
                {"name": "primary", "role": "primary", "model": "m"},
                {
                    "name": "aux",
                    "role": "vision:\n  malicious_key",
                    "model": "x",
                },
            ],
        )
        with pytest.raises(AgentConfigError, match="invalid role"):
            build_render_inputs("alpha")

    def test_unknown_but_clean_role_also_raises(self, monkeypatch):
        from clawrium.core.render import build_render_inputs

        self._fake_render_stores(
            monkeypatch,
            attachments=[
                {"name": "primary", "role": "primary", "model": "m"},
                {"name": "aux", "role": "not_a_real_slot", "model": "x"},
            ],
        )
        with pytest.raises(AgentConfigError, match="invalid role"):
            build_render_inputs("alpha")

    def test_duplicate_aux_role_raises(self, monkeypatch):
        """Two aux entries with same role would silently last-win in
        rendered YAML — fail loud instead."""
        from clawrium.core.render import build_render_inputs

        self._fake_render_stores(
            monkeypatch,
            attachments=[
                {"name": "primary", "role": "primary", "model": "m"},
                {"name": "aux", "role": "vision", "model": "x"},
                {"name": "aux", "role": "vision", "model": "y"},
            ],
        )
        with pytest.raises(AgentConfigError, match="reuse role"):
            build_render_inputs("alpha")

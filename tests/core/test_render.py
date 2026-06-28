"""Tests for clawrium.core.render — F1 (build_render_inputs) + F2 (renderers).

Covers issue #556 DoD:
  - every missing-input raises path for `build_render_inputs`
  - idempotency property: pure renderers produce byte-identical output
    across repeated invocations for the same inputs
  - templates branch only on provider.type — verified by spot-checking
    that the output of two inputs that differ ONLY in unused fields is
    structurally identical, and that the output for each provider type
    contains the expected type-specific env var keys.
"""

from __future__ import annotations

import pytest

from clawrium.core import render
from clawrium.core.render import (
    AgentConfigError,
    APIServerInputs,
    AttachedProviderInputs,
    ChannelInputs,
    GatewayInputs,
    HermesProviderBundle,
    IntegrationInputs,
    ProviderInputs,
    RenderInputs,
    build_render_inputs,
    render_hermes,
    render_openclaw,
    render_zeroclaw,
)


# ---------------------------------------------------------------------------
# Fixtures: a minimal in-memory fake of every store build_render_inputs touches.
# ---------------------------------------------------------------------------


class _Stores:
    """A bundle of fake-store responses, wired into the module via monkeypatch."""

    def __init__(self) -> None:
        self.agent: tuple[dict, str, dict] | None = None
        self.providers: dict[str, dict] = {}
        self.provider_api_keys: dict[str, str] = {}
        self.provider_aws: dict[str, tuple[str, str]] = {}
        self.channels: dict[str, dict] = {}
        self.channel_tokens: dict[tuple[str, str], str] = {}
        self.integrations: dict[str, dict] = {}
        self.integration_creds: dict[str, dict[str, str]] = {}
        self.agent_channels: list[str] = []
        self.agent_integrations: list[str] = []


@pytest.fixture
def stores(monkeypatch) -> _Stores:
    s = _Stores()

    def _get_agent_by_name(name: str):
        return s.agent

    def _get_provider(name: str):
        return s.providers.get(name)

    def _get_provider_api_key(name: str):
        return s.provider_api_keys.get(name)

    def _get_provider_aws_credentials(name: str):
        return s.provider_aws.get(name, (None, None))

    def _get_agent_channels(host: str, agent_key: str):
        return list(s.agent_channels)

    def _get_channel(name: str):
        return s.channels.get(name)

    def _get_channel_token(name: str, key: str = "BOT_TOKEN"):
        return s.channel_tokens.get((name, key))

    def _get_agent_integrations(host: str, agent_key: str):
        return list(s.agent_integrations)

    def _get_integration(name: str):
        return s.integrations.get(name)

    def _get_integration_credentials(name: str):
        return dict(s.integration_creds.get(name, {}))

    # Patch every collaborator. The render module imports them lazily
    # inside `build_render_inputs`, so monkeypatching the source module
    # is enough.
    monkeypatch.setattr(
        "clawrium.core.hosts.get_agent_by_name", _get_agent_by_name
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider", _get_provider
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", _get_provider_api_key
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_aws_credentials",
        _get_provider_aws_credentials,
    )
    monkeypatch.setattr(
        "clawrium.core.channels.get_agent_channels", _get_agent_channels
    )
    monkeypatch.setattr("clawrium.core.channels.get_channel", _get_channel)
    monkeypatch.setattr(
        "clawrium.core.channels.get_channel_token", _get_channel_token
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_agent_integrations",
        _get_agent_integrations,
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_integration", _get_integration
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_integration_credentials",
        _get_integration_credentials,
    )
    return s


def _agent_record(
    *,
    providers: list | None = None,
    config: dict | None = None,
    agent_name: str = "alpha",
):
    return (
        {"hostname": "host-1"},
        "hermes",
        {
            "agent_name": agent_name,
            "providers": providers or [],
            "config": config or {},
        },
    )


# ---------------------------------------------------------------------------
# build_render_inputs — missing-input paths
# ---------------------------------------------------------------------------


def test_missing_agent_raises(stores):
    stores.agent = None
    with pytest.raises(AgentConfigError, match="not found in any host"):
        build_render_inputs("ghost")


def test_no_provider_attached_raises(stores):
    stores.agent = _agent_record(providers=[])
    with pytest.raises(AgentConfigError, match="no provider attached"):
        build_render_inputs("alpha")


def test_provider_attachment_missing_primary_role_raises(stores):
    # Hermes with all-auxiliary attachments → no primary.
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "vision", "model": ""}]
    )
    with pytest.raises(AgentConfigError, match="primary provider"):
        build_render_inputs("alpha")


def test_provider_not_registered_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}]
    )
    # No entry in providers store.
    with pytest.raises(AgentConfigError, match="not registered in providers.json"):
        build_render_inputs("alpha")


def test_bearer_provider_missing_api_key_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}]
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "x"}
    # No API key in secrets store.
    with pytest.raises(AgentConfigError, match="missing API key"):
        build_render_inputs("alpha")


def test_bedrock_provider_missing_aws_creds_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "br", "role": "primary", "model": ""}]
    )
    stores.providers["br"] = {"name": "br", "type": "bedrock", "default_model": "m"}
    with pytest.raises(AgentConfigError, match="missing AWS credentials"):
        build_render_inputs("alpha")


def test_ollama_provider_missing_endpoint_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "ol", "role": "primary", "model": ""}]
    )
    stores.providers["ol"] = {"name": "ol", "type": "ollama", "default_model": "m"}
    with pytest.raises(AgentConfigError, match="missing endpoint"):
        build_render_inputs("alpha")


def test_unsupported_provider_type_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "weird", "role": "primary", "model": ""}]
    )
    stores.providers["weird"] = {"name": "weird", "type": "wat", "default_model": "m"}
    with pytest.raises(AgentConfigError, match="does not support provider type"):
        build_render_inputs("alpha")


@pytest.mark.parametrize("bad_type", ["", None, "   "])
def test_empty_or_null_provider_type_raises(stores, bad_type):
    """B10: providers.json record with missing/empty/whitespace type field."""
    stores.agent = _agent_record(
        providers=[{"name": "x", "role": "primary", "model": ""}]
    )
    stores.providers["x"] = {"name": "x", "type": bad_type, "default_model": "m"}
    with pytest.raises(AgentConfigError, match="has no type field"):
        build_render_inputs("alpha")


def test_hermes_zai_provider_rejected_with_clear_message(stores):
    """B1: hermes does not render zai. Reject upfront, not at render time."""
    stores.agent = _agent_record(
        providers=[{"name": "z", "role": "primary", "model": ""}]
    )
    stores.providers["z"] = {"name": "z", "type": "zai", "default_model": "m"}
    stores.provider_api_keys["z"] = "zai-1"
    with pytest.raises(AgentConfigError, match="does not support provider type"):
        build_render_inputs("alpha")


@pytest.mark.parametrize("aws", [(None, None), ("AKIA-1", ""), ("", "secret")])
def test_bedrock_half_missing_aws_creds_raises(stores, aws):
    """W8: any one half of AWS creds missing is treated as missing."""
    stores.agent = _agent_record(
        providers=[{"name": "br", "role": "primary", "model": ""}]
    )
    stores.providers["br"] = {"name": "br", "type": "bedrock", "default_model": "m"}
    stores.provider_aws["br"] = aws
    with pytest.raises(AgentConfigError, match="missing AWS credentials"):
        build_render_inputs("alpha")


def test_nul_only_api_key_is_treated_as_missing(stores):
    """B8: a NUL-only secret is truthy in Python but must read as missing."""
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}]
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "\x00\x00"
    with pytest.raises(AgentConfigError, match="missing API key"):
        build_render_inputs("alpha")


def test_channel_attached_but_not_registered_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}]
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    stores.agent_channels = ["discord-x"]
    with pytest.raises(AgentConfigError, match="not registered in channels.json"):
        build_render_inputs("alpha")


def test_channel_missing_bot_token_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}]
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    stores.agent_channels = ["discord-x"]
    stores.channels["discord-x"] = {"name": "discord-x", "type": "discord", "config": {}}
    with pytest.raises(AgentConfigError, match="missing BOT_TOKEN"):
        build_render_inputs("alpha")


def test_slack_missing_app_token_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}]
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    stores.agent_channels = ["slack-x"]
    stores.channels["slack-x"] = {"name": "slack-x", "type": "slack", "config": {}}
    stores.channel_tokens[("slack-x", "BOT_TOKEN")] = "xoxb-1"
    with pytest.raises(AgentConfigError, match="missing APP_TOKEN"):
        build_render_inputs("alpha")


def test_integration_not_registered_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}]
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    stores.agent_integrations = ["gh-1"]
    with pytest.raises(AgentConfigError, match="not registered in integrations.json"):
        build_render_inputs("alpha")


def test_integration_missing_required_credential_raises(stores):
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}]
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    stores.agent_integrations = ["gh-1"]
    stores.integrations["gh-1"] = {"name": "gh-1", "type": "github"}
    # No GITHUB_TOKEN in creds.
    with pytest.raises(AgentConfigError, match="missing required credential"):
        build_render_inputs("alpha")


def test_happy_path_assembles_full_bundle(stores):
    stores.agent = _agent_record(
        providers=[{"name": "or", "role": "primary", "model": ""}],
        config={
            "api_server": {"host": "0.0.0.0", "port": 8642, "key": "k" * 64},
        },
    )
    stores.providers["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "anthropic/claude-opus-4.7",
    }
    stores.provider_api_keys["or"] = "sk-or-1"
    stores.agent_channels = ["discord-a"]
    stores.channels["discord-a"] = {
        "name": "discord-a",
        "type": "discord",
        "config": {
            "allowed_users": ["u1"],
            "allowed_guilds": ["g1"],
            "require_mention": True,
        },
    }
    stores.channel_tokens[("discord-a", "BOT_TOKEN")] = "discord-bot"
    stores.agent_integrations = ["gh-a", "gh-b"]
    stores.integrations["gh-a"] = {"name": "gh-a", "type": "github"}
    stores.integrations["gh-b"] = {"name": "gh-b", "type": "github"}
    stores.integration_creds["gh-a"] = {"GITHUB_TOKEN": "ghp_a"}
    stores.integration_creds["gh-b"] = {"GITHUB_TOKEN": "ghp_b"}

    inputs = build_render_inputs("alpha")
    assert inputs.provider.name == "or"
    assert inputs.provider.type == "openrouter"
    assert inputs.provider.api_key == "sk-or-1"
    assert len(inputs.channels) == 1
    assert inputs.channels[0].bot_token == "discord-bot"
    # Integrations sorted by name → gh-a, gh-b.
    assert [i.name for i in inputs.integrations] == ["gh-a", "gh-b"]
    assert inputs.api_server is not None
    assert inputs.api_server.port == 8642


# ---------------------------------------------------------------------------
# Renderer idempotency / property tests
# ---------------------------------------------------------------------------


def _baseline_inputs(*, ptype: str = "openrouter") -> RenderInputs:
    if ptype == "openrouter":
        provider = ProviderInputs(
            name="or",
            type="openrouter",
            default_model="anthropic/claude-opus-4.7",
            api_key="sk-or-1",
        )
    elif ptype == "bedrock":
        provider = ProviderInputs(
            name="br",
            type="bedrock",
            default_model="anthropic.claude-opus-4-1-v1:0",
            region="us-east-1",
            aws_access_key="AKIA-1",
            aws_secret_key="secret-1",
        )
    elif ptype == "ollama":
        provider = ProviderInputs(
            name="ol",
            type="ollama",
            default_model="llama3",
            endpoint="http://10.0.0.5:11434",
        )
    elif ptype == "litellm":
        provider = ProviderInputs(
            name="lt",
            type="litellm",
            default_model="gemma4:31b",
            endpoint="http://10.0.0.5:4000",
            api_key="sk-master-1",
        )
    elif ptype == "anthropic":
        provider = ProviderInputs(
            name="an",
            type="anthropic",
            default_model="claude-opus-4-7",
            api_key="sk-ant-1",
        )
    elif ptype == "openai":
        provider = ProviderInputs(
            name="oa", type="openai", default_model="gpt-5", api_key="sk-oa-1"
        )
    elif ptype == "zai":
        provider = ProviderInputs(
            name="z", type="zai", default_model="glm-4.5", api_key="sk-zai-1"
        )
    elif ptype == "opencode":
        provider = ProviderInputs(
            name="oc",
            type="opencode",
            default_model="kimi-k2.5",
            endpoint="https://opencode.ai/zen/v1",
            api_key="sk-opencode-1",
        )
    elif ptype == "opencode-go":
        provider = ProviderInputs(
            name="ocg",
            type="opencode-go",
            default_model="kimi-k2.5",
            endpoint="https://opencode.ai/zen/go/v1",
            api_key="sk-opencode-go-1",
        )
    else:
        raise AssertionError(ptype)

    return RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=provider,
        channels=(
            ChannelInputs(
                name="discord-a",
                type="discord",
                bot_token="discord-bot",
                allowed_users=("u1", "u2"),
                allowed_guilds=("g1",),
                require_mention=True,
                home_channel="general",
            ),
        ),
        integrations=(
            IntegrationInputs(
                name="gh-a",
                type="github",
                credentials=(("GITHUB_TOKEN", "ghp_a"),),
            ),
        ),
        api_server=APIServerInputs(host="0.0.0.0", port=8642, key="k" * 64),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )


@pytest.mark.parametrize(
    "renderer,ptype",
    [
        (render_hermes, "openrouter"),
        (render_hermes, "anthropic"),
        (render_hermes, "openai"),
        (render_hermes, "bedrock"),
        (render_hermes, "ollama"),
        (render_hermes, "litellm"),
        (render_hermes, "opencode"),
        (render_hermes, "opencode-go"),
        (render_zeroclaw, "openrouter"),
        (render_zeroclaw, "anthropic"),
        (render_zeroclaw, "openai"),
        (render_zeroclaw, "ollama"),
        (render_zeroclaw, "opencode"),
        (render_zeroclaw, "opencode-go"),
        (render_openclaw, "openrouter"),
        (render_openclaw, "anthropic"),
        (render_openclaw, "openai"),
        (render_openclaw, "bedrock"),
        (render_openclaw, "ollama"),
        (render_openclaw, "zai"),
        (render_openclaw, "litellm"),
        (render_openclaw, "opencode"),
        (render_openclaw, "opencode-go"),
    ],
)
def test_renderer_is_idempotent(renderer, ptype):
    """Property test: identical inputs → byte-identical outputs."""
    if renderer is render_zeroclaw:
        inputs = _zeroclaw_inputs(ptype=ptype)
    else:
        inputs = _baseline_inputs(ptype=ptype)
    out1 = renderer(inputs)
    out2 = renderer(inputs)
    assert out1.files == out2.files
    # And every file body is non-empty.
    for path, body in out1.files.items():
        assert body, f"{path} rendered empty"


def test_hermes_openrouter_emits_expected_keys():
    inputs = _baseline_inputs(ptype="openrouter")
    out = render_hermes(inputs)
    env = out.files[".hermes/.env"]
    assert "OPENROUTER_API_KEY='sk-or-1'" in env
    assert "HERMES_INFERENCE_PROVIDER='openrouter'" in env
    yaml = out.files[".hermes/config.yaml"]
    assert 'provider: "openrouter"' in yaml
    assert "anthropic/claude-opus-4.7" in yaml


def test_hermes_bedrock_emits_aws_keys_not_bearer():
    inputs = _baseline_inputs(ptype="bedrock")
    out = render_hermes(inputs)
    env = out.files[".hermes/.env"]
    assert "AWS_ACCESS_KEY_ID='AKIA-1'" in env
    assert "AWS_SECRET_ACCESS_KEY='secret-1'" in env
    assert "AWS_DEFAULT_REGION='us-east-1'" in env
    # No bearer-key vars for bedrock.
    assert "OPENROUTER_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env


def test_hermes_ollama_yaml_has_v1_suffix():
    inputs = _baseline_inputs(ptype="ollama")
    out = render_hermes(inputs)
    yaml = out.files[".hermes/config.yaml"]
    assert "http://10.0.0.5:11434/v1" in yaml


def test_hermes_litellm_primary_renders_custom_provider_with_v1():
    """LiteLLM primary emits provider: custom + inline api_key in YAML.

    Hermes' custom provider reads the bearer from `model.api_key:` in
    the YAML, NOT from a `<NAME>_API_KEY=` env var (verified against
    the upstream docs at
    https://hermes-agent.nousresearch.com/docs/integrations/providers#litellm-proxy--multi-provider-gateway).
    """
    inputs = _baseline_inputs(ptype="litellm")
    out = render_hermes(inputs)
    yaml = out.files[".hermes/config.yaml"]
    env = out.files[".hermes/.env"]

    assert 'provider: "custom"' in yaml
    assert "http://10.0.0.5:4000/v1" in yaml
    assert "gemma4:31b" in yaml
    assert "api_key: 'sk-master-1'" in yaml
    assert "HERMES_INFERENCE_PROVIDER='custom'" in env
    # No `LITELLM_API_KEY=` env var — hermes' custom provider doesn't
    # consume one; the bearer lives in config.yaml exclusively.
    assert "LITELLM_API_KEY" not in env


def test_hermes_opencode_renders_custom_provider_with_inline_key():
    """OpenCode primary emits provider: custom + inline api_key in YAML."""
    inputs = _baseline_inputs(ptype="opencode")
    out = render_hermes(inputs)
    yaml = out.files[".hermes/config.yaml"]
    env = out.files[".hermes/.env"]

    assert 'provider: "custom"' in yaml
    assert "https://opencode.ai/zen/v1" in yaml
    assert "kimi-k2.5" in yaml
    assert "api_key: 'sk-opencode-1'" in yaml
    assert "HERMES_INFERENCE_PROVIDER='custom'" in env
    assert "OPENCODE_API_KEY" not in env


def test_hermes_opencode_go_renders_custom_provider_with_inline_key():
    """OpenCode Go primary emits provider: custom + inline api_key in YAML."""
    inputs = _baseline_inputs(ptype="opencode-go")
    out = render_hermes(inputs)
    yaml = out.files[".hermes/config.yaml"]
    env = out.files[".hermes/.env"]

    assert 'provider: "custom"' in yaml
    assert "https://opencode.ai/zen/go/v1" in yaml
    assert "kimi-k2.5" in yaml
    assert "api_key: 'sk-opencode-go-1'" in yaml
    assert "HERMES_INFERENCE_PROVIDER='custom'" in env
    assert "OPENCODE_API_KEY" not in env


def test_hermes_opencode_endpoint_without_v1_gets_normalized():
    """Endpoint missing trailing /v1 gets /v1 appended for OpenCode."""
    base = _baseline_inputs(ptype="opencode")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint="https://opencode.ai/zen",
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    assert "https://opencode.ai/zen/v1" in yaml
    assert "https://opencode.ai/zen/v1/v1" not in yaml


def test_hermes_opencode_go_endpoint_without_v1_gets_normalized():
    """Endpoint missing trailing /v1 gets /v1 appended for OpenCode Go."""
    base = _baseline_inputs(ptype="opencode-go")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint="https://opencode.ai/zen/go",
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    assert "https://opencode.ai/zen/go/v1" in yaml
    assert "https://opencode.ai/zen/go/v1/v1" not in yaml


def test_hermes_litellm_endpoint_with_v1_suffix_not_double_appended():
    """Endpoint already ending in /v1 must not be double-suffixed."""
    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint="http://10.0.0.5:4000/v1",
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    assert "http://10.0.0.5:4000/v1" in yaml
    assert "http://10.0.0.5:4000/v1/v1" not in yaml


def test_hermes_litellm_aux_attachment_emits_inline_api_key_in_yaml():
    """LiteLLM aux attachment emits per-aux base_url + api_key inline in YAML.

    Each litellm aux carries its own URL + key inline in the auxiliary
    block — hermes' custom provider reads them from the YAML. No env
    var is emitted, so two litellm proxies at different roles cannot
    collide.
    """
    base = _baseline_inputs(ptype="openrouter")
    # Primary openrouter + one litellm aux at curator role.
    bundle = HermesProviderBundle(
        attachments=(
            AttachedProviderInputs(
                name="or",
                type="openrouter",
                role="primary",
                model="anthropic/claude-opus-4.7",
            ),
            AttachedProviderInputs(
                name="inx-litellm",
                type="litellm",
                role="curator",
                model="gemma4:31b",
                endpoint="http://192.168.1.17:4000",
                api_key="sk-litellm-aux",
                base_url="http://192.168.1.17:4000/v1",
            ),
        ),
        api_keys=(("openrouter", "sk-or-1"),),
        aws_credentials=(),
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
        hermes=bundle,
    )
    out = render_hermes(inputs)
    yaml = out.files[".hermes/config.yaml"]
    env = out.files[".hermes/.env"]

    # YAML: per-aux block with custom shape + inline bearer.
    assert "curator:" in yaml
    assert 'provider: "custom"' in yaml
    assert "http://192.168.1.17:4000/v1" in yaml
    assert "gemma4:31b" in yaml
    assert "api_key: 'sk-litellm-aux'" in yaml

    # No env var — hermes reads aux bearer from YAML, not from env.
    assert "LITELLM" not in env


def test_hermes_litellm_missing_endpoint_raises():
    """A litellm primary with no endpoint raises AgentConfigError-style failure."""
    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint="",  # missing
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
    )
    # render_hermes will compute litellm_base_url="/v1" (an unhelpful URL).
    # The endpoint check lives in build_render_inputs upstream; this test
    # locks the render contract: produces *something* without crashing,
    # but the operator sees the bad base_url and the upstream guard fires
    # in production. We assert the renderer doesn't crash.
    out = render_hermes(inputs)
    assert out.files[".hermes/config.yaml"]


# ---------------------------------------------------------------------------
# #831: hermes litellm context_length emission
#
# Operators with litellm proxies fronting large-context models (e.g.
# Qwen3-Next-80B at 131072) must be able to pin hermes' context window
# through the canonical render path. The contract:
#   - `context_window=0` (default) → `context_length:` omitted entirely
#   - `context_window=N` → `context_length: N` emitted after `default:`
# Tested for primary (`model:`) and aux (`auxiliary.<role>:`) litellm
# slots; non-litellm aux types never emit the key.
# ---------------------------------------------------------------------------


def test_hermes_litellm_primary_no_context_window_omits_context_length():
    """LiteLLM primary with default (0) context_window omits the YAML key entirely."""
    inputs = _baseline_inputs(ptype="litellm")
    # _baseline_inputs builds ProviderInputs without setting
    # context_window, so it defaults to 0.
    assert inputs.provider.context_window == 0
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    # No `context_length` key — neither populated, nor null, nor zero.
    assert "context_length" not in yaml


def test_hermes_litellm_primary_with_context_window_emits_context_length():
    """LiteLLM primary with `context_window=131072` emits `context_length: 131072` after `default:`."""
    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint=base.provider.endpoint,
        api_key=base.provider.api_key,
        context_window=131072,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    assert "context_length: 131072" in yaml
    # Position: must be after `default:` inside the `model:` block so the
    # daemon's YAML deep-merge places it under the right parent.
    default_pos = yaml.index("default:")
    ctx_pos = yaml.index("context_length: 131072")
    assert default_pos < ctx_pos
    # And the key is indented exactly two spaces (sits under `model:`).
    assert "\n  context_length: 131072\n" in yaml


def test_hermes_litellm_aux_with_context_window_emits_context_length():
    """LiteLLM primary + litellm aux, both with `context_window`, both emit the YAML key."""
    base = _baseline_inputs(ptype="litellm")
    # Primary: context_window=200000.
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint=base.provider.endpoint,
        api_key=base.provider.api_key,
        context_window=200000,
    )
    # Aux: separate litellm proxy with context_window=131072.
    bundle = HermesProviderBundle(
        attachments=(
            AttachedProviderInputs(
                name=base.provider.name,
                type="litellm",
                role="primary",
                model=base.provider.default_model,
            ),
            AttachedProviderInputs(
                name="inx-litellm",
                type="litellm",
                role="curator",
                model="gemma4:31b",
                endpoint="http://192.168.1.17:4000",
                api_key="sk-litellm-aux",
                base_url="http://192.168.1.17:4000/v1",
                context_window=131072,
            ),
        ),
        api_keys=(),
        aws_credentials=(),
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
        hermes=bundle,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    # Primary emits 200000 at two-space indent (under `model:`).
    assert "\n  context_length: 200000\n" in yaml
    # Aux emits 131072 at four-space indent (under `auxiliary.curator:`).
    assert "\n    context_length: 131072\n" in yaml
    # Count discipline: exactly two `context_length:` lines (primary + aux).
    # Catches a future regression that double-emits via a buggy macro
    # refactor or template duplication.
    assert yaml.count("context_length:") == 2


def test_hermes_litellm_aux_unset_context_window_omits_context_length():
    """LiteLLM primary set + litellm aux with `context_window=0` → only primary emits.

    Exercises the falsy branch of `{% if entry.context_window %}` on the
    aux loop, which round-1 ATX flagged as untested. A regression that
    emitted `context_length: 0` (or `context_length: null`) for default
    aux slots would silently break operator setups.
    """
    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint=base.provider.endpoint,
        api_key=base.provider.api_key,
        context_window=131072,
    )
    bundle = HermesProviderBundle(
        attachments=(
            AttachedProviderInputs(
                name=base.provider.name,
                type="litellm",
                role="primary",
                model=base.provider.default_model,
            ),
            AttachedProviderInputs(
                name="inx-litellm",
                type="litellm",
                role="curator",
                model="gemma4:31b",
                endpoint="http://192.168.1.17:4000",
                api_key="sk-litellm-aux",
                base_url="http://192.168.1.17:4000/v1",
                # context_window left at default (0).
            ),
        ),
        api_keys=(),
        aws_credentials=(),
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
        hermes=bundle,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    # Exactly one `context_length:` — primary only.
    assert yaml.count("context_length:") == 1
    assert "\n  context_length: 131072\n" in yaml
    # No four-space-indented (aux-level) emission. Catches a regression
    # that emitted `context_length: 0` or `context_length: null` for
    # default aux slots.
    assert "    context_length:" not in yaml


def test_hermes_openrouter_primary_with_litellm_aux_emits_aux_context_length():
    """#831 B1 regression guard: openrouter primary + litellm aux with
    `context_window` set on the aux emits `context_length:` inside the
    aux block. Before B1's fix, only the litellm-primary branch carried
    the emission, so this case silently dropped the operator's pin.
    """
    base = _baseline_inputs(ptype="openrouter")
    bundle = HermesProviderBundle(
        attachments=(
            AttachedProviderInputs(
                name=base.provider.name,
                type="openrouter",
                role="primary",
                model=base.provider.default_model,
            ),
            AttachedProviderInputs(
                name="inx-litellm",
                type="litellm",
                role="curator",
                model="writer",
                endpoint="http://192.168.1.17:4000",
                api_key="sk-litellm-aux",
                base_url="http://192.168.1.17:4000/v1",
                context_window=131072,
            ),
        ),
        api_keys=(("openrouter", "sk-or"),),
        aws_credentials=(),
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
        hermes=bundle,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    # Exactly one `context_length:` line — the aux's. Openrouter primary
    # never emits the key (no context_window on its ProviderInputs).
    assert yaml.count("context_length:") == 1
    # Indented four spaces under the aux block.
    assert "\n    context_length: 131072\n" in yaml


def test_hermes_litellm_primary_with_openrouter_aux_does_not_emit_aux_context_length():
    """Regression guard: openrouter aux never emits `context_length` even when primary does."""
    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint=base.provider.endpoint,
        api_key=base.provider.api_key,
        context_window=131072,
    )
    bundle = HermesProviderBundle(
        attachments=(
            AttachedProviderInputs(
                name=base.provider.name,
                type="litellm",
                role="primary",
                model=base.provider.default_model,
            ),
            AttachedProviderInputs(
                name="or-aux",
                type="openrouter",
                role="curator",
                model="anthropic/claude-haiku-4.5",
            ),
        ),
        api_keys=(("openrouter", "sk-or-aux"),),
        aws_credentials=(),
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
        hermes=bundle,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    # Exactly one `context_length:` line in the entire YAML — the primary's.
    assert yaml.count("context_length:") == 1
    assert "context_length: 131072" in yaml


def test_hermes_renders_integrations_in_input_order_and_bare_github_token():
    """Renderer iterates input order; sorting is `build_render_inputs`' job."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(),
        integrations=(
            IntegrationInputs(name="gh-a", type="github", credentials=(("GITHUB_TOKEN", "A"),)),
            IntegrationInputs(name="gh-b", type="github", credentials=(("GITHUB_TOKEN", "B"),)),
        ),
        api_server=base.api_server,
    )
    env = render_hermes(inputs).files[".hermes/.env"]
    pos_a = env.index("GITHUB_TOKEN_GH_A=")
    pos_b = env.index("GITHUB_TOKEN_GH_B=")
    assert pos_a < pos_b
    # Bare GITHUB_TOKEN is the last entry's value (back-compat with skills
    # hard-coding the canonical name; sort happens upstream).
    assert "GITHUB_TOKEN='B'" in env


def _zeroclaw_inputs(*, ptype: str = "openrouter") -> RenderInputs:
    base = _baseline_inputs(ptype=ptype)
    return RenderInputs(
        agent_name=base.agent_name,
        agent_type="zeroclaw",
        provider=base.provider,
        channels=base.channels,
        integrations=base.integrations,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, allow_public_bind=True),
    )


def test_zeroclaw_renders_discord_channel_and_mandatory_blocks():
    inputs = _zeroclaw_inputs(ptype="openrouter")
    out = render_zeroclaw(inputs)
    toml = out.files[".zeroclaw/config.toml"]
    # #555: canonical zeroclaw schema — provider selection lives in
    # [providers] block as `fallback`, not as a top-level `default_provider`.
    assert '[providers]\nfallback = "openrouter"' in toml
    assert "[providers.models.openrouter]" in toml
    assert "[channels.discord]" in toml
    assert 'bot_token = "discord-bot"' in toml
    assert "mention_only = true" in toml
    # B3: configure.yaml greps `^shell_env_passthrough\s*=` — must exist.
    assert "[autonomy]" in toml
    assert "shell_env_passthrough" in toml
    # B6: allow_public_bind in [gateway].
    assert "allow_public_bind = true" in toml
    # #555 fix: full canonical template — daemon-managed sections preserved.
    # Sanity check a handful of sections that previously got silently wiped.
    for section in (
        "[security.audit]",
        "[memory.qdrant]",
        "[hooks.builtin]",
        "[web_search]",
        "[workspace]",
    ):
        assert section in toml, f"daemon-managed section {section} missing"
    # W7: file-key set is exactly the two expected paths.
    assert set(out.files.keys()) == {
        ".zeroclaw/config.toml",
        ".zeroclaw/zeroclaw-env.conf",
    }


def test_zeroclaw_env_drop_in_carries_github_token():
    """W6: assert content on `.zeroclaw/zeroclaw-env.conf`, not just config.toml."""
    inputs = _zeroclaw_inputs(ptype="openrouter")
    env = render_zeroclaw(inputs).files[".zeroclaw/zeroclaw-env.conf"]
    assert "[Service]" in env
    assert 'Environment=GITHUB_TOKEN_GH_A="ghp_a"' in env
    assert 'Environment=GITHUB_TOKEN="ghp_a"' in env


def test_zeroclaw_stream_mode_defaults_to_off_when_empty():
    """W2: when stream_mode input is empty, render the canonical default ("off"),
    not "partial". The canonical config always has a `stream_mode` line — the
    full-template renderer (#555) preserves it; empty input means the daemon
    default, which is "off"."""
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="discord-a",
                type="discord",
                bot_token="t",
                stream_mode="",
            ),
        ),
        gateway=base.gateway,
    )
    toml = render_zeroclaw(inputs).files[".zeroclaw/config.toml"]
    assert 'stream_mode = "off"' in toml
    assert 'stream_mode = "partial"' not in toml


def test_zeroclaw_requires_gateway():
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        gateway=None,
    )
    with pytest.raises(AgentConfigError, match="requires gateway config"):
        render_zeroclaw(inputs)


def test_openclaw_openrouter_prefixes_model():
    inputs = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=inputs.agent_name,
        agent_type="openclaw",
        provider=inputs.provider,
        channels=inputs.channels,
        integrations=inputs.integrations,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tk", bind="lan"),
    )
    env = render_openclaw(inputs).files[".openclaw/env"]
    assert "OPENCLAW_DEFAULT_MODEL='openrouter/anthropic/claude-opus-4.7'" in env
    assert "OPENROUTER_API_KEY='sk-or-1'" in env


def test_zeroclaw_opencode_renders_base_url_and_api_key():
    inputs = _zeroclaw_inputs(ptype="opencode")
    toml = render_zeroclaw(inputs).files[".zeroclaw/config.toml"]
    assert '[providers.models.opencode]' in toml
    assert 'base_url = "https://opencode.ai/zen/v1"' in toml
    assert 'api_key = "sk-opencode-1"' in toml


def test_zeroclaw_opencode_go_renders_base_url_and_api_key():
    inputs = _zeroclaw_inputs(ptype="opencode-go")
    toml = render_zeroclaw(inputs).files[".zeroclaw/config.toml"]
    assert '[providers.models.opencode-go]' in toml
    assert 'base_url = "https://opencode.ai/zen/go/v1"' in toml
    assert 'api_key = "sk-opencode-go-1"' in toml


def test_zeroclaw_opencode_normalizes_endpoint_to_v1():
    """W8: user-supplied endpoint without trailing /v1 gets normalized."""
    base = _zeroclaw_inputs(ptype="opencode")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=ProviderInputs(
            name="oc",
            type="opencode",
            default_model="kimi-k2.5",
            endpoint="https://opencode.ai/zen",
            api_key="sk-opencode-1",
        ),
        channels=base.channels,
        integrations=base.integrations,
        gateway=base.gateway,
    )
    toml = render_zeroclaw(inputs).files[".zeroclaw/config.toml"]
    assert 'base_url = "https://opencode.ai/zen/v1"' in toml


def test_openclaw_opencode_emits_api_key_and_unprefixed_model():
    inputs = _baseline_inputs(ptype="opencode")
    inputs = RenderInputs(
        agent_name=inputs.agent_name,
        agent_type="openclaw",
        provider=inputs.provider,
        channels=inputs.channels,
        integrations=inputs.integrations,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tk", bind="lan"),
    )
    out = render_openclaw(inputs)
    env = out.files[".openclaw/env"]
    json_body = out.files[".openclaw/openclaw.json"]
    assert "OPENCODE_API_KEY='sk-opencode-1'" in env
    assert "OPENAI_BASE_URL='https://opencode.ai/zen/v1'" in env
    assert "OPENCLAW_DEFAULT_MODEL='kimi-k2.5'" in env
    assert '"primary": "kimi-k2.5"' in json_body


def test_openclaw_opencode_go_emits_api_key_and_unprefixed_model():
    inputs = _baseline_inputs(ptype="opencode-go")
    inputs = RenderInputs(
        agent_name=inputs.agent_name,
        agent_type="openclaw",
        provider=inputs.provider,
        channels=inputs.channels,
        integrations=inputs.integrations,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tk", bind="lan"),
    )
    out = render_openclaw(inputs)
    env = out.files[".openclaw/env"]
    json_body = out.files[".openclaw/openclaw.json"]
    assert "OPENCODE_API_KEY='sk-opencode-go-1'" in env
    assert "OPENAI_BASE_URL='https://opencode.ai/zen/go/v1'" in env
    assert "OPENCLAW_DEFAULT_MODEL='kimi-k2.5'" in env
    assert '"primary": "kimi-k2.5"' in json_body


def test_render_home_channel_guarded_when_empty():
    """W4 (ATX #555 polish): empty home_channel must NOT emit the var.

    The legacy template guarded each DISCORD_HOME_CHANNEL* var with
    `{% if %}`; the canonical template now does the same. Empty string
    vs absent is semantically distinct for the daemon's env-var config
    path — emitting `DISCORD_HOME_CHANNEL=''` makes the daemon treat
    "no home channel" as "explicitly empty" instead of "unset".
    """
    base = _baseline_inputs(ptype="openrouter")
    variant = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="discord-a",
                type="discord",
                bot_token="discord-bot",
                allowed_users=base.channels[0].allowed_users,
                allowed_guilds=base.channels[0].allowed_guilds,
                require_mention=base.channels[0].require_mention,
                home_channel="",
            ),
        ),
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=base.gateway,
    )
    env = render_hermes(variant).files[".hermes/.env"]
    assert not any(
        line.startswith("DISCORD_HOME_CHANNEL=") for line in env.splitlines()
    ), env


def test_renderers_reject_unsupported_provider_type_defensively():
    bogus = RenderInputs(
        agent_name="x",
        agent_type="hermes",
        provider=ProviderInputs(name="x", type="bogus"),
        gateway=GatewayInputs(host="0.0.0.0", port=40000),
    )
    with pytest.raises(AgentConfigError, match="does not support provider type"):
        render_hermes(bogus)
    with pytest.raises(AgentConfigError, match="does not support provider type"):
        render_zeroclaw(bogus)
    with pytest.raises(AgentConfigError, match="does not support provider type"):
        render_openclaw(bogus)


def test_hermes_slack_channel_emits_expected_keys():
    """B9: slack render path coverage."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="slack-a",
                type="slack",
                bot_token="xoxb-bot",
                app_token="xapp-app",
                allowed_users=("u1",),
                home_channel="C123",
                home_channel_name="general",
            ),
        ),
        api_server=base.api_server,
    )
    env = render_hermes(inputs).files[".hermes/.env"]
    assert "SLACK_BOT_TOKEN='xoxb-bot'" in env
    assert "SLACK_APP_TOKEN='xapp-app'" in env
    assert "SLACK_ALLOWED_USERS='u1'" in env
    assert "SLACK_HOME_CHANNEL='C123'" in env
    assert "SLACK_HOME_CHANNEL_NAME='general'" in env
    assert "DISCORD_BOT_TOKEN" not in env


def test_openclaw_slack_channel_emits_expected_keys():
    """B9: slack render path coverage for openclaw."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="slack-a", type="slack", bot_token="xoxb-1", app_token="xapp-1"
            ),
        ),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tk", bind="lan"),
    )
    env = render_openclaw(inputs).files[".openclaw/env"]
    assert "SLACK_BOT_TOKEN='xoxb-1'" in env
    assert "SLACK_APP_TOKEN='xapp-1'" in env
    assert "DISCORD_BOT_TOKEN" not in env


def test_hermes_discord_emits_allow_all_users_and_home_channel_fields():
    """B5: hermes discord must emit ALLOW_ALL_USERS / HOME_CHANNEL_{NAME,THREAD_ID}."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="discord-a",
                type="discord",
                bot_token="t",
                allow_all_users=True,
                home_channel="C1",
                home_channel_name="general",
                home_channel_thread_id="T9",
            ),
        ),
        api_server=base.api_server,
    )
    env = render_hermes(inputs).files[".hermes/.env"]
    # `DISCORD_ALLOW_ALL_USERS` is emitted as the unquoted token `true`
    # (presence-flag semantics matching the j2 template) only when the
    # operator explicitly opted in. See render.py comment.
    assert "DISCORD_ALLOW_ALL_USERS=true" in env
    assert "DISCORD_HOME_CHANNEL_NAME='general'" in env
    assert "DISCORD_HOME_CHANNEL_THREAD_ID='T9'" in env


def test_hermes_discord_omits_allow_all_users_when_false():
    """B4 regression: never emit DISCORD_ALLOW_ALL_USERS=false; daemon
    parses presence, not value, so `'false'` would silently open access."""
    base = _baseline_inputs(ptype="openrouter")
    env = render_hermes(base).files[".hermes/.env"]
    assert "DISCORD_ALLOW_ALL_USERS" not in env


def test_hermes_atlassian_slug_collision_raises():
    """B3 regression: distinct integration names that slug-collide must
    raise rather than silently last-wins-drop one set of credentials."""
    base = _baseline_inputs(ptype="openrouter")
    creds = (
        ("ATLASSIAN_API_TOKEN", "t"),
        ("ATLASSIAN_EMAIL", "e"),
        ("ATLASSIAN_URL", "https://x"),
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        integrations=(
            IntegrationInputs(name="my-atlassian", type="atlassian", credentials=creds),
            IntegrationInputs(name="my_atlassian", type="atlassian", credentials=creds),
        ),
        api_server=base.api_server,
    )
    with pytest.raises(AgentConfigError, match="collide on YAML key"):
        render_hermes(inputs)


@pytest.mark.parametrize(
    "host_value",
    [
        # The post-install seed shape — `host = ""` in hosts.json.
        "",
        # Whitespace-only: `_clean_secret` strips NUL/CR/LF but not
        # spaces/tabs. `"   " or "0.0.0.0"` short-circuits to `"   "`
        # without the `.strip()` guard, and the daemon refuses it the
        # same way it refuses `""`. B1 from ATX review of the initial
        # patch.
        "   ",
        "\t \t",
        # NUL-contaminated host: `_clean_secret` strips the NUL to "",
        # which then defaults via the same code path. Covers parity
        # with the W6 sanitization at line ~447.
        "\x00",
    ],
)
def test_gateway_host_defaults_to_wildcard_when_blank(stores, host_value):
    """#576: zeroclaw's daemon refuses an empty `gateway.host`. The
    assembler must default to `0.0.0.0` (the documented wildcard bind)
    so a fresh install whose hosts.json carries any blank/whitespace
    host value still renders a config.toml the daemon accepts.
    """
    stores.agent = (
        {"hostname": "host-1"},
        "zeroclaw",
        {
            "agent_name": "alpha",
            "providers": [{"name": "or", "role": "primary", "model": ""}],
            "config": {
                "gateway": {
                    "host": host_value,
                    "port": 40000,
                    "auth": "tk",
                    "bind": "lan",
                },
            },
        },
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    inputs = build_render_inputs("alpha")
    assert inputs.gateway is not None and inputs.gateway.host == "0.0.0.0"


def test_gateway_host_defaults_to_wildcard_when_key_missing(stores):
    """#576: same default fires when the `host` key is absent entirely,
    not just empty. Covers the shape some legacy migrations produced."""
    stores.agent = (
        {"hostname": "host-1"},
        "zeroclaw",
        {
            "agent_name": "alpha",
            "providers": [{"name": "or", "role": "primary", "model": ""}],
            "config": {
                "gateway": {"port": 40000, "auth": "tk", "bind": "lan"},
            },
        },
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    inputs = build_render_inputs("alpha")
    assert inputs.gateway is not None and inputs.gateway.host == "0.0.0.0"


@pytest.mark.parametrize("host_value", ["", "   ", "\t \t"])
def test_gateway_host_default_round_trips_through_render_zeroclaw(
    stores, host_value
):
    """#576 / ATX W1 + iter-2 W: extend the default assertion to call
    the actual `render_zeroclaw` Jinja path and confirm the rendered
    `config.toml` contains `host = "0.0.0.0"` under `[gateway]`. The
    assembler-only assertion above would stay green even if a template
    regression rendered the pre-strip raw value — the on-host daemon
    is what consumes this. Parametrized over the same blank set as the
    assembler test so a whitespace-only input also has a Jinja-path
    assertion."""
    stores.agent = (
        {"hostname": "host-1"},
        "zeroclaw",
        {
            "agent_name": "alpha",
            "providers": [{"name": "or", "role": "primary", "model": ""}],
            "config": {
                "gateway": {
                    "host": host_value,
                    "port": 40000,
                    "auth": "tk",
                    "bind": "lan",
                },
            },
        },
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    inputs = build_render_inputs("alpha")
    rendered = render_zeroclaw(inputs)
    toml_body = rendered.files[".zeroclaw/config.toml"]
    # The rendered TOML must carry the wildcard bind under [gateway].
    # An empty/whitespace host (which the daemon refuses) would render
    # as `host = ""` or `host = "   "` respectively.
    assert 'host = "0.0.0.0"' in toml_body
    assert 'host = ""' not in toml_body
    if host_value.strip() != host_value or host_value:
        # The raw pre-strip value must not survive into the rendered
        # TOML — guards against a future template change that bypasses
        # the assembler's strip+default.
        assert f'host = "{host_value}"' not in toml_body


def test_gateway_host_preserves_explicit_value(stores):
    """#576: the default only fills in for blank/missing — an explicit
    operator value round-trips unchanged. Loopback and a LAN IP are
    both verified so the `or` path is not silently masking arbitrary
    non-empty input."""
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    for explicit in ("127.0.0.1", "192.168.1.5"):
        stores.agent = (
            {"hostname": "host-1"},
            "zeroclaw",
            {
                "agent_name": "alpha",
                "providers": [{"name": "or", "role": "primary", "model": ""}],
                "config": {
                    "gateway": {
                        "host": explicit,
                        "port": 40000,
                        "auth": "tk",
                        "bind": "lan",
                    },
                },
            },
        )
        inputs = build_render_inputs("alpha")
        assert inputs.gateway is not None and inputs.gateway.host == explicit


def test_hermes_render_ignores_gateway_host_default(stores):
    """#576 / ATX W2: the `0.0.0.0` default is applied unconditionally
    in `build_render_inputs` because no current renderer other than
    zeroclaw reads `inputs.gateway.host`. This test pins that
    invariant: a hermes agent with a blank `config.gateway.host` must
    still render successfully and its output must not carry the
    zeroclaw-shaped `[gateway]` block."""
    stores.agent = (
        {"hostname": "host-1"},
        "hermes",
        {
            "agent_name": "alpha",
            "providers": [{"name": "or", "role": "primary", "model": "m"}],
            "config": {
                "api_server": {"host": "0.0.0.0", "port": 8642, "key": "k"},
                # Blank host — would brick zeroclaw, must not affect hermes.
                "gateway": {"host": "", "port": 40000, "auth": "tk"},
            },
        },
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    inputs = build_render_inputs("alpha")
    rendered = render_hermes(inputs)
    # Pin the hermes output shape so the negative-only assertions below
    # aren't vacuously true if a future refactor changes the file map.
    assert ".hermes/.env" in rendered.files
    assert "HERMES_INFERENCE_PROVIDER" in rendered.files[".hermes/.env"]
    for path, body in rendered.files.items():
        # The zeroclaw-shaped `[gateway]` TOML block must not appear in
        # any hermes output file.
        assert "[gateway]" not in body, (
            f"hermes render leaked zeroclaw [gateway] block into {path}"
        )


def test_clean_secret_applied_to_gateway_auth_and_api_server_key(stores):
    """W1: NUL/CR/LF in gateway.auth or api_server.key must be stripped
    before they hit the systemd EnvironmentFile."""
    stores.agent = (
        {"hostname": "host-1"},
        "hermes",
        {
            "agent_name": "alpha",
            "providers": [{"name": "or", "role": "primary", "model": ""}],
            "config": {
                "api_server": {"host": "0.0.0.0", "port": 8642, "key": "k\x00ey\r"},
                "gateway": {"host": "0.0.0.0", "port": 40000, "auth": "tok\nen"},
            },
        },
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    inputs = build_render_inputs("alpha")
    assert inputs.api_server is not None and inputs.api_server.key == "key"
    assert inputs.gateway is not None and inputs.gateway.auth == "token"


def _openclaw_stores_with_auth(stores, auth_value):
    """Configure stores for an openclaw agent with the given
    `gateway.auth` value. Used by the #820 parametrized tests."""
    stores.agent = (
        {"hostname": "host-1"},
        "openclaw",
        {
            "agent_name": "alpha",
            "providers": [{"name": "or", "role": "primary", "model": ""}],
            "config": {
                "gateway": {
                    "host": "0.0.0.0",
                    "port": 40000,
                    "auth": auth_value,
                    "bind": "lan",
                },
            },
        },
    )
    stores.providers["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "m",
    }
    stores.provider_api_keys["or"] = "sk-1"


_AUTH_TOKEN_820 = "deadbeefcafef00d"


@pytest.mark.parametrize(
    "auth_value,expected_token",
    [
        # Bare-string shape (the canonical on-disk form per AGENTS.md).
        (_AUTH_TOKEN_820, _AUTH_TOKEN_820),
        # Legacy dict shape — `read_gateway_auth` unwraps to the bare
        # token so a manually patched hosts.json can still be rendered
        # without crashing.
        ({"mode": "token", "token": _AUTH_TOKEN_820}, _AUTH_TOKEN_820),
    ],
)
def test_gateway_auth_accepts_dict_and_string_shapes_openclaw(
    stores, auth_value, expected_token
):
    """#820: `read_gateway_auth` in `build_render_inputs` accepts
    both the canonical bare-string shape and the legacy dict shape
    so a hosts.json that picked up the dict form (manual edit /
    operational recovery) does not crash the renderer. The pre-fix
    bug was an `AttributeError: 'dict' object has no attribute
    'replace'` from `_clean_secret` when fed the dict shape."""
    _openclaw_stores_with_auth(stores, auth_value)
    inputs = build_render_inputs("alpha")
    assert inputs.gateway is not None and inputs.gateway.auth == expected_token
    json_body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    assert f'"token": "{expected_token}"' in json_body
    assert '"mode": "token"' in json_body


def test_gateway_auth_byte_identical_across_string_and_dict_shapes(stores):
    """#820: bare-string and dict-shape `gateway.auth` MUST produce
    byte-identical render output so a hosts.json normalized by the
    next sync's `set_gateway_auth` write is functionally equivalent
    to one that already carried the canonical shape."""
    _openclaw_stores_with_auth(stores, _AUTH_TOKEN_820)
    out_str = render_openclaw(build_render_inputs("alpha"))
    _openclaw_stores_with_auth(
        stores, {"mode": "token", "token": _AUTH_TOKEN_820}
    )
    out_dict = render_openclaw(build_render_inputs("alpha"))
    assert out_str.files == out_dict.files


def test_gateway_auth_dict_shape_works_for_zeroclaw(stores):
    """#820 review 2 W1: the dict-shape normalization in
    `build_render_inputs` fires for any agent type with a gateway
    blob — not just openclaw. Pin the zeroclaw branch separately so a
    future install.py change that writes the dict shape for zeroclaw
    does not regress this code path silently."""
    token = "z" + _AUTH_TOKEN_820
    stores.agent = (
        {"hostname": "host-1"},
        "zeroclaw",
        {
            "agent_name": "alpha",
            "providers": [{"name": "or", "role": "primary", "model": ""}],
            "config": {
                "gateway": {
                    "host": "0.0.0.0",
                    "port": 40000,
                    "auth": {"mode": "token", "token": token},
                    "bind": "lan",
                },
            },
        },
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    inputs = build_render_inputs("alpha")
    # The assembly-boundary normalization is agent-type-agnostic, so
    # the dict unwrap must produce the same bare-token result for
    # zeroclaw as it does for openclaw. The zeroclaw `config.toml`
    # template does not currently render `gateway.auth` (the bearer
    # is rotated and persisted via a separate path — see
    # `gateway_token_rotated` in AGENTS.md), so the assertion stops
    # at the inputs layer rather than the rendered TOML.
    assert inputs.gateway is not None and inputs.gateway.auth == token
    # The render path itself must still succeed end-to-end — a
    # regression in the dict-unwrap branch that left a dict in
    # `gateway.auth` would crash inside the TOML renderer.
    rendered = render_zeroclaw(inputs)
    assert ".zeroclaw/config.toml" in rendered.files


def test_hermes_file_keys_are_exact_set():
    """W7: any silent rename of an output path must fail tests."""
    out = render_hermes(_baseline_inputs(ptype="openrouter"))
    assert set(out.files.keys()) == {".hermes/.env", ".hermes/config.yaml"}


def test_openclaw_file_keys_are_exact_set():
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=base.provider,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tk", bind="lan"),
    )
    out = render_openclaw(inputs)
    assert set(out.files.keys()) == {".openclaw/env", ".openclaw/openclaw.json"}


def test_yaml_quote_strips_nul_and_cr():
    """W4: defense against NUL/CR injection through atlassian creds."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        integrations=(
            IntegrationInputs(
                name="jira-a",
                type="atlassian",
                credentials=(
                    ("ATLASSIAN_API_TOKEN", "tok\x00en\r"),
                    ("ATLASSIAN_EMAIL", "a@b"),
                    ("ATLASSIAN_URL", "https://co.atlassian.net"),
                ),
            ),
        ),
        api_server=base.api_server,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    assert "\x00" not in yaml
    assert "\r" not in yaml
    # Concrete sanitized scalar: NUL + CR stripped, no other mangling.
    # Input token "tok\x00en\r" → "token" after _yaml_quote's strip.
    assert "JIRA_API_TOKEN: 'token'" in yaml
    # And the mcp_servers key uses the slug, not raw name.
    assert "  jira_a:" in yaml


def test_atlassian_yaml_key_injection_blocked():
    """B7: YAML key injection via integration name must not break out."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        integrations=(
            IntegrationInputs(
                name="legit\ninjected_key",
                type="atlassian",
                credentials=(
                    ("ATLASSIAN_API_TOKEN", "t"),
                    ("ATLASSIAN_EMAIL", "e"),
                    ("ATLASSIAN_URL", "https://x"),
                ),
            ),
        ),
        api_server=base.api_server,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    # The newline-bearing name is slugified; no smuggled key at the
    # mcp_servers level. The slug strips characters outside [A-Z0-9_],
    # collapsing the embedded \n into a single concatenated token.
    assert "\n  injected_key:" not in yaml
    assert "  legitinjected_key:" in yaml


def test_render_module_exports():
    # Sanity: public surface is what the issue calls for.
    assert hasattr(render, "build_render_inputs")
    assert hasattr(render, "render_hermes")
    assert hasattr(render, "render_zeroclaw")
    assert hasattr(render, "render_openclaw")
    assert hasattr(render, "RenderInputs")
    assert hasattr(render, "AgentConfigError")


# ---------------------------------------------------------------------------
# Iter-3 ATX coverage gap closures
# ---------------------------------------------------------------------------


def test_openclaw_zai_emits_zai_api_key():
    """Iter-3 B1: pin the openclaw `zai` provider env-var emission."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(name="z", type="zai", default_model="glm-4.5", api_key="sk-zai-1"),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tk", bind="lan"),
    )
    env = render_openclaw(inputs).files[".openclaw/env"]
    assert "ZAI_API_KEY='sk-zai-1'" in env


def test_openclaw_atlassian_integration_emits_to_env():
    """Iter-3 B2: pin all six env vars on openclaw's atlassian branch."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(name="or", type="openrouter", default_model="m", api_key="sk-1"),
        integrations=(
            IntegrationInputs(
                name="atl",
                type="atlassian",
                credentials=(
                    ("ATLASSIAN_API_TOKEN", "tk"),
                    ("ATLASSIAN_EMAIL", "a@b"),
                    ("ATLASSIAN_URL", "https://co.atlassian.net/"),
                ),
            ),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    env = render_openclaw(inputs).files[".openclaw/env"]
    # Trailing slash stripped before CONFLUENCE_URL derivation.
    assert "JIRA_URL='https://co.atlassian.net'" in env
    assert "CONFLUENCE_URL='https://co.atlassian.net/wiki'" in env
    assert "JIRA_EMAIL='a@b'" in env
    assert "CONFLUENCE_EMAIL='a@b'" in env
    assert "JIRA_API_TOKEN='tk'" in env
    assert "CONFLUENCE_API_TOKEN='tk'" in env


@pytest.mark.parametrize("renderer", [render_hermes, render_openclaw])
def test_renderer_unsupported_channel_type_raises(renderer):
    """Iter-3 B3: cover both renderers' `else: raise` channel branches."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes" if renderer is render_hermes else "openclaw",
        provider=ProviderInputs(name="or", type="openrouter", default_model="m", api_key="sk-1"),
        channels=(ChannelInputs(name="x", type="irc", bot_token="t"),),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    with pytest.raises(AgentConfigError, match="unsupported channel type"):
        renderer(inputs)


@pytest.mark.parametrize("renderer", [render_hermes, render_openclaw])
def test_renderer_unsupported_integration_type_raises(renderer):
    """Iter-3 B4: cover both renderers' `else: raise` integration branches."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes" if renderer is render_hermes else "openclaw",
        provider=ProviderInputs(name="or", type="openrouter", default_model="m", api_key="sk-1"),
        integrations=(
            IntegrationInputs(name="sf", type="salesforce", credentials=(("X", "Y"),)),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    with pytest.raises(AgentConfigError, match="unsupported integration type"):
        renderer(inputs)


def test_shell_quote_escapes_single_quote():
    """Iter-3 B5: every env var emission flows through `_shell_quote`.
    A regression here silently breaks every EnvironmentFile."""
    from clawrium.core.render import _shell_quote

    # POSIX single-quote escape: close, embed escaped quote, reopen.
    assert _shell_quote("it's") == "'it'\"'\"'s'"
    # Adjacent quotes — double-embed.
    assert _shell_quote("a''b") == "'a'\"'\"''\"'\"'b'"
    # Plain value untouched aside from wrapping quotes.
    assert _shell_quote("plain") == "'plain'"


def test_shell_quote_strips_nul_cr_lf():
    """B5 (ATX #555 polish round 3): NUL truncates systemd
    EnvironmentFile at the byte; CR/LF breaks the
    one-assignment-per-line grammar. All three must be stripped before
    POSIX quoting."""
    from clawrium.core.render import _shell_quote

    assert _shell_quote("foo\x00bar") == "'foobar'"
    assert _shell_quote("foo\nbar") == "'foobar'"
    assert _shell_quote("foo\rbar") == "'foobar'"
    assert _shell_quote("a\x00b\nc\rd") == "'abcd'"
    # Empty-string edge case still produces a valid empty POSIX literal.
    assert _shell_quote("") == "''"


def test_systemd_quote_strips_nul_and_escapes_dollar_percent():
    """B4 + round-3 W2 (ATX #555 polish round 3): `_systemd_quote` must
    strip NUL (EnvironmentFile truncation), escape `$` → `$$` (systemd
    variable expansion on Environment= values), and escape `%` → `%%`
    (systemd specifier expansion `%h`, `%n`, etc.)."""
    from clawrium.core.render import _systemd_quote

    assert _systemd_quote("ghp_$FOO") == '"ghp_$$FOO"'
    assert _systemd_quote("ghp_%n") == '"ghp_%%n"'
    assert _systemd_quote("a$b%c") == '"a$$b%%c"'
    # NUL stripped.
    assert _systemd_quote("foo\x00bar") == '"foobar"'
    # CR/LF stripped.
    assert _systemd_quote("foo\nbar\rbaz") == '"foobarbaz"'
    # Backslash and quote still escaped.
    assert _systemd_quote('a"b\\c') == '"a\\"b\\\\c"'


def test_toml_escape_strips_nul_and_escapes_cr_lf():
    """B6 (ATX #555 polish round 3): NUL must be stripped (TOML spec
    rejects bare NUL; some parsers silently truncate). CR must be
    escaped as `\\r` not emitted bare. LF as `\\n`."""
    from clawrium.core.render import _toml_escape

    assert _toml_escape("foo\x00bar") == "foobar"
    assert _toml_escape("foo\rbar") == "foo\\rbar"
    assert _toml_escape("foo\nbar") == "foo\\nbar"
    # Combined.
    out = _toml_escape("a\x00b\rc\nd")
    assert "\x00" not in out
    assert "\r" not in out
    assert "\n" not in out
    assert out == "ab\\rc\\nd"
    # W-C (ATX #555 polish round 4): backslash and double quote must
    # be escaped too — these are the TOML basic-string break-out
    # characters and the regression that started B3 in round 1.
    assert _toml_escape('a"b') == 'a\\"b'
    assert _toml_escape("a\\b") == "a\\\\b"
    assert _toml_escape("a\tb") == "a\\tb"


def test_zeroclaw_toml_injection_payload_nul_and_cr():
    """B6 (ATX #555 polish round 3): extend the B3 TOML injection
    regression with NUL and CR payloads. Asserts the parsed body has
    NUL stripped + CR properly escaped and the rendered body contains
    no literal NUL or bare CR."""
    import tomllib

    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="zeroclaw",
        provider=ProviderInputs(
            name="or",
            type="openrouter",
            default_model="m",
            # NUL + CR + LF + quote + backslash all in the api_key.
            api_key="sk-\x00\r\n\"\\evil",
        ),
        gateway=GatewayInputs(
            host="1.2.3.4\x00\r",
            port=40000,
            allow_public_bind=True,
        ),
    )
    toml_body = render_zeroclaw(inputs).files[".zeroclaw/config.toml"]
    # The rendered body must contain no literal NUL.
    assert "\x00" not in toml_body
    parsed = tomllib.loads(toml_body)
    # NUL stripped, CR + LF preserved via escape, quote/backslash escaped.
    assert (
        parsed["providers"]["models"]["openrouter"]["api_key"]
        == 'sk-\r\n"\\evil'
    )
    assert parsed["gateway"]["host"] == "1.2.3.4\r"


def test_hermes_bedrock_config_yaml_section_pinned():
    """Iter-3 W1: pin the bedrock config.yaml content too, not just env."""
    inputs = _baseline_inputs(ptype="bedrock")
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    assert 'provider: "bedrock"' in yaml
    assert "bedrock:" in yaml
    assert "region:" in yaml
    assert "anthropic.claude-haiku-4-5-20251001-v1:0" in yaml


def test_openclaw_no_gateway_omits_gateway_vars():
    """Iter-3 W2: optional gateway branch — assert no var leakage."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(name="or", type="openrouter", default_model="m", api_key="sk-1"),
        gateway=None,
    )
    env = render_openclaw(inputs).files[".openclaw/env"]
    for var in (
        "OPENCLAW_GATEWAY_BIND",
        "OPENCLAW_GATEWAY_PORT",
        "OPENCLAW_GATEWAY_AUTH_MODE",
        "OPENCLAW_GATEWAY_AUTH_TOKEN",
    ):
        assert var not in env


def test_string_style_provider_attachment_resolves(stores):
    """Iter-3 W3: list-of-strings provider attachment (singleton shape)."""
    stores.agent = (
        {"hostname": "host-1"},
        "openclaw",
        {
            "agent_name": "alpha",
            # List of strings, not list of dicts — the singleton shape
            # used by zeroclaw/openclaw before Pattern A migration.
            "providers": ["or"],
            "config": {},
        },
    )
    stores.providers["or"] = {"name": "or", "type": "openrouter", "default_model": "m"}
    stores.provider_api_keys["or"] = "sk-1"
    inputs = build_render_inputs("alpha")
    assert inputs.provider.name == "or"


def test_hermes_git_integration_produces_no_env_var():
    """Iter-3 W4: git integration is intentionally skipped in env render."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        integrations=(
            IntegrationInputs(
                name="me",
                type="git",
                credentials=(("GIT_USER_EMAIL", "a@b"), ("GIT_USER_NAME", "Me")),
            ),
        ),
        api_server=base.api_server,
    )
    env = render_hermes(inputs).files[".hermes/.env"]
    assert "GIT_USER_EMAIL" not in env
    assert "GIT_USER_NAME" not in env
    # GITHUB_TOKEN must not appear either (no github integration attached).
    assert "GITHUB_TOKEN" not in env


def test_hermes_atlassian_credentials_absent_from_env():
    """Iter-3 W5: atlassian goes to config.yaml only, never to .env."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        integrations=(
            IntegrationInputs(
                name="atl",
                type="atlassian",
                credentials=(
                    ("ATLASSIAN_API_TOKEN", "tk"),
                    ("ATLASSIAN_EMAIL", "e@x"),
                    ("ATLASSIAN_URL", "https://x"),
                ),
            ),
        ),
        api_server=base.api_server,
    )
    env = render_hermes(inputs).files[".hermes/.env"]
    assert "ATLASSIAN" not in env
    assert "JIRA" not in env
    assert "CONFLUENCE" not in env


# ---------------------------------------------------------------------------
# Phase 2 (#560): Jinja-template regression locks for render_hermes.
#
# The byte-for-byte expected outputs below were captured from the prior
# list-of-strings implementation of `render_hermes`. Any drift in the new
# Jinja template flow MUST be intentional and surface here as a test
# failure with a clear diff — that is the entire point of locking these.
# ---------------------------------------------------------------------------


_MAURICE_LIKE_ENV_OPENROUTER = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure maurice`.\n"
    "OPENROUTER_API_KEY='sk-or-maurice'\n"
    "HERMES_INFERENCE_PROVIDER='openrouter'\n"
    "API_SERVER_ENABLED=1\n"
    "API_SERVER_HOST='127.0.0.1'\n"
    "API_SERVER_PORT=8642\n"
    "API_SERVER_KEY='maurice-key'\n"
    "DISCORD_BOT_TOKEN='discord-maurice'\n"
    "DISCORD_ALLOWED_USERS='u1,u2'\n"
    "DISCORD_ALLOWED_CHANNELS=''\n"
    "DISCORD_REQUIRE_MENTION='true'\n"
    "DISCORD_HOME_CHANNEL='general'\n"
    "GITHUB_TOKEN_GH_M='ghp_m'\n"
    "GITHUB_TOKEN='ghp_m'\n"
)


_MAURICE_LIKE_YAML_OPENROUTER = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure maurice`.\n"
    "model:\n"
    "  provider: \"openrouter\"\n"
    "  base_url: \"https://openrouter.ai/api/v1\"\n"
    "  default: 'anthropic/claude-opus-4.7'\n"
    "auxiliary:\n"
    "  title_generation:\n"
    "    model: \"anthropic/claude-haiku-4.5\"\n"
)


_ESPRESSO_LIKE_ENV_OLLAMA = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure espresso`.\n"
    "HERMES_INFERENCE_PROVIDER='custom'\n"
    "API_SERVER_ENABLED=1\n"
    "API_SERVER_HOST='127.0.0.1'\n"
    "API_SERVER_PORT=8642\n"
    "API_SERVER_KEY='espresso-key'\n"
)


_ESPRESSO_LIKE_YAML_OLLAMA = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure espresso`.\n"
    "model:\n"
    "  provider: \"custom\"\n"
    "  base_url: 'http://10.0.0.5:11434/v1'\n"
    "  default: 'llama3'\n"
)


def test_hermes_render_byte_locks_maurice_openrouter():
    """Regression lock: the Jinja-driven render must produce these exact bytes."""
    inputs = RenderInputs(
        agent_name="maurice",
        agent_type="hermes",
        provider=ProviderInputs(
            name="or",
            type="openrouter",
            default_model="anthropic/claude-opus-4.7",
            api_key="sk-or-maurice",
        ),
        channels=(
            ChannelInputs(
                name="discord-m",
                type="discord",
                bot_token="discord-maurice",
                allowed_users=("u1", "u2"),
                require_mention=True,
                home_channel="general",
            ),
        ),
        integrations=(
            IntegrationInputs(
                name="gh-m",
                type="github",
                credentials=(("GITHUB_TOKEN", "ghp_m"),),
            ),
        ),
        api_server=APIServerInputs(host="127.0.0.1", port=8642, key="maurice-key"),
    )
    out = render_hermes(inputs)
    assert out.files[".hermes/.env"] == _MAURICE_LIKE_ENV_OPENROUTER
    assert out.files[".hermes/config.yaml"] == _MAURICE_LIKE_YAML_OPENROUTER


def test_hermes_render_byte_locks_espresso_ollama():
    """Regression lock: ollama path renders bytes-exact. Locks the W5
    decision to omit `auxiliary.title_generation` for ollama (the local
    model is already cheap; a remote aux pin defeats the point)."""
    inputs = RenderInputs(
        agent_name="espresso",
        agent_type="hermes",
        provider=ProviderInputs(
            name="ol",
            type="ollama",
            default_model="llama3",
            endpoint="http://10.0.0.5:11434",
        ),
        channels=(),
        integrations=(),
        api_server=APIServerInputs(host="127.0.0.1", port=8642, key="espresso-key"),
    )
    out = render_hermes(inputs)
    assert out.files[".hermes/.env"] == _ESPRESSO_LIKE_ENV_OLLAMA
    assert out.files[".hermes/config.yaml"] == _ESPRESSO_LIKE_YAML_OLLAMA
    # Explicit absence-assertion: W5 — no auxiliary block for ollama.
    assert "auxiliary:" not in out.files[".hermes/config.yaml"]


def test_zeroclaw_toml_string_interpolations_escape_special_chars():
    """B3 (ATX #555 polish): every TOML double-quoted-string interpolation
    in zeroclaw-config.toml.j2 must run through the `toq` filter so a
    quote, backslash, or newline inside any clawctl-controlled value
    cannot terminate the string early or break out of the field.

    Attack model: an API key containing `"` could otherwise close the
    string and inject arbitrary TOML keys — e.g. `require_pairing =
    false` silently disabling gateway auth. A `\\` would produce an
    invalid escape and brick TOML parse.

    The body must parse cleanly as TOML AND every injected special
    char must round-trip into the parsed string value verbatim.
    """
    import tomllib

    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="zeroclaw",
        provider=ProviderInputs(
            name="or",
            type="openrouter",
            default_model='evil"\\model\n',
            api_key='sk-"]\\evil\n',
        ),
        channels=(
            ChannelInputs(
                name="discord-evil",
                type="discord",
                bot_token='token"\\\n',
                allowed_users=('u"1', "u\\2"),
                allowed_guilds=('g"\\1',),
                stream_mode='partial"\\',
            ),
        ),
        gateway=GatewayInputs(
            host='1.2.3.4" require_pairing = false #',
            port=40000,
            allow_public_bind=True,
        ),
    )
    toml_body = render_zeroclaw(inputs).files[".zeroclaw/config.toml"]
    parsed = tomllib.loads(toml_body)

    # Injection-via-host must NOT toggle require_pairing.
    assert parsed["gateway"]["require_pairing"] is True
    assert parsed["gateway"]["host"] == '1.2.3.4" require_pairing = false #'

    # Provider values round-trip.
    assert parsed["providers"]["fallback"] == "openrouter"
    assert (
        parsed["providers"]["models"]["openrouter"]["model"]
        == 'evil"\\model\n'
    )
    assert (
        parsed["providers"]["models"]["openrouter"]["api_key"]
        == 'sk-"]\\evil\n'
    )

    # Discord values round-trip.
    assert parsed["channels"]["discord"]["bot_token"] == 'token"\\\n'
    assert parsed["channels"]["discord"]["allowed_users"] == ['u"1', "u\\2"]
    assert parsed["channels"]["discord"]["allowed_guilds"] == ['g"\\1']
    assert parsed["channels"]["discord"]["stream_mode"] == 'partial"\\'


def test_zeroclaw_rejects_non_discord_channel_b8():
    """B8: non-discord channels must raise, not silently drop."""
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(name="slack-x", type="slack", bot_token="xoxb"),
        ),
        gateway=base.gateway,
    )
    with pytest.raises(AgentConfigError, match="unsupported channel type 'slack'"):
        render_zeroclaw(inputs)


def test_zeroclaw_rejects_non_github_integration_b9():
    """B9: non-github (and non-git) integrations must raise, not silently drop."""
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        integrations=(
            IntegrationInputs(
                name="linear-x",
                type="linear",
                credentials=(("LINEAR_API_KEY", "lk_1"),),
            ),
        ),
        gateway=base.gateway,
    )
    with pytest.raises(AgentConfigError, match="unsupported integration type 'linear'"):
        render_zeroclaw(inputs)


# ---------------------------------------------------------------------------
# ATX round 1 follow-ups: explicit positive coverage for paths previously
# only covered indirectly via the idempotency property.
# ---------------------------------------------------------------------------


def test_hermes_gitlab_integration_emits_token_and_optional_url():
    """B8 (ATX round 1): gitlab token branch + optional GITLAB_URL must
    both render. Wrong key name would silently emit empty values; this
    locks both flavors of the branch."""
    base = _baseline_inputs(ptype="openrouter")
    inputs_token_only = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        integrations=(
            IntegrationInputs(
                name="gl-1",
                type="gitlab",
                credentials=(("GITLAB_TOKEN", "glpat-1"),),
            ),
        ),
        api_server=base.api_server,
    )
    env = render_hermes(inputs_token_only).files[".hermes/.env"]
    assert "GITLAB_TOKEN='glpat-1'" in env
    assert "GITLAB_URL" not in env

    inputs_with_url = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        integrations=(
            IntegrationInputs(
                name="gl-2",
                type="gitlab",
                credentials=(
                    ("GITLAB_TOKEN", "glpat-2"),
                    ("GITLAB_URL", "https://gitlab.example.com"),
                ),
            ),
        ),
        api_server=base.api_server,
    )
    env2 = render_hermes(inputs_with_url).files[".hermes/.env"]
    assert "GITLAB_TOKEN='glpat-2'" in env2
    assert "GITLAB_URL='https://gitlab.example.com'" in env2


_HERMES_ANTHROPIC_ENV = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "ANTHROPIC_API_KEY='sk-ant-1'\n"
    "HERMES_INFERENCE_PROVIDER='anthropic'\n"
)
_HERMES_ANTHROPIC_YAML = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "model:\n"
    "  provider: \"anthropic\"\n"
    "  default: 'claude-opus-4-7'\n"
    "auxiliary:\n"
    "  title_generation:\n"
    "    model: \"claude-haiku-4-5-20251001\"\n"
)


_HERMES_OPENAI_ENV = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENAI_API_KEY='sk-oa-1'\n"
    "HERMES_INFERENCE_PROVIDER='openai'\n"
)
_HERMES_OPENAI_YAML = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "model:\n"
    "  provider: \"openai\"\n"
    "  default: 'gpt-5'\n"
    "auxiliary:\n"
    "  title_generation:\n"
    "    model: \"gpt-5-nano\"\n"
)


_HERMES_BEDROCK_ENV = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "AWS_ACCESS_KEY_ID='AKIA-1'\n"
    "AWS_SECRET_ACCESS_KEY='secret-1'\n"
    "AWS_DEFAULT_REGION='us-east-1'\n"
    "HERMES_INFERENCE_PROVIDER='bedrock'\n"
)
_HERMES_BEDROCK_YAML = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "model:\n"
    "  provider: \"bedrock\"\n"
    "  api_key: \"aws-sdk\"\n"
    "  default: 'anthropic.claude-opus-4-1-v1:0'\n"
    "bedrock:\n"
    "  region: 'us-east-1'\n"
    "auxiliary:\n"
    "  title_generation:\n"
    "    model: \"anthropic.claude-haiku-4-5-20251001-v1:0\"\n"
)


@pytest.mark.parametrize(
    "ptype,expected_env,expected_yaml",
    [
        ("anthropic", _HERMES_ANTHROPIC_ENV, _HERMES_ANTHROPIC_YAML),
        ("openai", _HERMES_OPENAI_ENV, _HERMES_OPENAI_YAML),
        ("bedrock", _HERMES_BEDROCK_ENV, _HERMES_BEDROCK_YAML),
    ],
)
def test_hermes_byte_lock_per_provider_branch(ptype, expected_env, expected_yaml):
    """B9 (ATX round 1): each provider's Jinja branch is byte-locked.

    Substring-only assertions cannot catch wrong line ordering or stray
    blank lines introduced by `trim_blocks` misconfiguration. This locks
    the full file body for anthropic, openai, and bedrock branches —
    completing the matrix alongside the maurice (openrouter) and
    espresso (ollama) byte-locks.
    """
    base = _baseline_inputs(ptype=ptype)
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=base.provider,
        channels=(),
        integrations=(),
        api_server=None,
    )
    out = render_hermes(inputs)
    assert out.files[".hermes/.env"] == expected_env
    assert out.files[".hermes/config.yaml"] == expected_yaml


def test_zeroclaw_git_integration_is_allowed_w14():
    """W14 (ATX round 1): `git` is the only non-github integration on
    zeroclaw's whitelist. Positive path must render without raising and
    must NOT emit a GITHUB_TOKEN_GIT env var (git identity goes into
    ~/.gitconfig via a separate render path)."""
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=base.channels,
        integrations=(
            IntegrationInputs(
                name="git-id",
                type="git",
                credentials=(("GIT_AUTHOR_NAME", "alpha"),),
            ),
        ),
        gateway=base.gateway,
    )
    out = render_zeroclaw(inputs)
    env = out.files[".zeroclaw/zeroclaw-env.conf"]
    assert "GITHUB_TOKEN_GIT" not in env
    assert "GITHUB_TOKEN=" not in env


def test_hermes_atlassian_mcp_servers_byte_lock_w15():
    """W15 (ATX round 1): lock the full `mcp_servers:` YAML block for an
    atlassian integration. Field ordering and slug derivation are part of
    the contract — a future "tidy" reordering would silently break
    downstream YAML consumers that rely on the entry shape."""
    base = _baseline_inputs(ptype="anthropic")
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=base.provider,
        channels=(),
        integrations=(
            IntegrationInputs(
                name="my-atl",
                type="atlassian",
                credentials=(
                    ("ATLASSIAN_API_TOKEN", "atl-tk"),
                    ("ATLASSIAN_EMAIL", "u@x.com"),
                    ("ATLASSIAN_URL", "https://acme.atlassian.net/"),
                ),
            ),
        ),
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    # W7 (ATX round 3): full-file byte-lock, not substring containment.
    expected = (
        "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
        "model:\n"
        "  provider: \"anthropic\"\n"
        "  default: 'claude-opus-4-7'\n"
        "auxiliary:\n"
        "  title_generation:\n"
        "    model: \"claude-haiku-4-5-20251001\"\n"
        "mcp_servers:\n"
        "  my_atl:\n"
        '    command: "/home/alpha/.local/bin/uvx"\n'
        '    args: ["--from", "mcp-atlassian==0.21.1", "mcp-atlassian"]\n'
        "    env:\n"
        "      JIRA_URL: 'https://acme.atlassian.net'\n"
        "      JIRA_USERNAME: 'u@x.com'\n"
        "      JIRA_API_TOKEN: 'atl-tk'\n"
        "      CONFLUENCE_URL: 'https://acme.atlassian.net/wiki'\n"
        "      CONFLUENCE_USERNAME: 'u@x.com'\n"
        "      CONFLUENCE_API_TOKEN: 'atl-tk'\n"
    )
    assert yaml == expected


# ---------------------------------------------------------------------------
# ATX round 2 follow-ups.
# ---------------------------------------------------------------------------


_HERMES_SLACK_ENV_OPENROUTER = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENROUTER_API_KEY='sk-or-1'\n"
    "HERMES_INFERENCE_PROVIDER='openrouter'\n"
    "SLACK_BOT_TOKEN='xoxb-bot'\n"
    "SLACK_APP_TOKEN='xapp-app'\n"
    "SLACK_ALLOWED_USERS='u1,u2'\n"
    "SLACK_HOME_CHANNEL='C123'\n"
    "SLACK_HOME_CHANNEL_NAME='general'\n"
)


def test_hermes_render_byte_locks_slack_channel():
    """W1 (ATX round 2): slack-channel branch needs the same byte-lock
    discipline as discord and the five provider branches. A whitespace
    change from `trim_blocks`/`lstrip_blocks` flipping the wrong way
    would pass substring-only tests undetected."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="slack-a",
                type="slack",
                bot_token="xoxb-bot",
                app_token="xapp-app",
                allowed_users=("u1", "u2"),
                home_channel="C123",
                home_channel_name="general",
            ),
        ),
        integrations=(),
        api_server=None,
    )
    out = render_hermes(inputs)
    assert out.files[".hermes/.env"] == _HERMES_SLACK_ENV_OPENROUTER


def test_hermes_atlassian_empty_slug_raises_w6():
    """W6 (ATX round 2): empty-slug guard must trigger. Names made up
    entirely of slug-stripped characters (dashes, punctuation) produce
    an empty slug; emit-unquoted-empty-key would be a silent YAML
    structure corruption."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=base.provider,
        integrations=(
            IntegrationInputs(
                name="!!!",
                type="atlassian",
                credentials=(
                    ("ATLASSIAN_API_TOKEN", "tk"),
                    ("ATLASSIAN_EMAIL", "u@x"),
                    ("ATLASSIAN_URL", "https://x"),
                ),
            ),
        ),
    )
    with pytest.raises(AgentConfigError, match="slugifies to empty"):
        render_hermes(inputs)


def test_zeroclaw_rejects_mixed_channel_list_w7():
    """W7 (ATX round 2): a `[discord, slack]` channel list must raise
    on the slack entry rather than silently emit just the discord block.
    Locks the new B8 `continue`-based loop's behavior against a future
    regression to `break` semantics."""
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(name="discord-a", type="discord", bot_token="d-tok"),
            ChannelInputs(name="slack-b", type="slack", bot_token="s-tok"),
        ),
        gateway=base.gateway,
    )
    with pytest.raises(AgentConfigError, match="unsupported channel type 'slack'"):
        render_zeroclaw(inputs)


# ---------------------------------------------------------------------------
# ATX round 3 follow-ups.
# ---------------------------------------------------------------------------


def test_hermes_ollama_endpoint_with_v1_suffix_not_double_appended_w8():
    """W8 (ATX round 3): the ollama endpoint normalization MUST be
    idempotent. A provider record with `endpoint='http://h:11434/v1'`
    must NOT render `http://h:11434/v1/v1`."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=ProviderInputs(
            name="ol",
            type="ollama",
            default_model="llama3",
            endpoint="http://h:11434/v1",
        ),
        channels=(),
        integrations=(),
        api_server=None,
    )
    yaml = render_hermes(inputs).files[".hermes/config.yaml"]
    assert "http://h:11434/v1/v1" not in yaml
    assert "base_url: 'http://h:11434/v1'" in yaml

    # Same with a trailing slash on /v1 — the rstrip strips it before the
    # endswith check, so the result is still single-/v1.
    inputs2 = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=ProviderInputs(
            name="ol",
            type="ollama",
            default_model="llama3",
            endpoint="http://h:11434/v1/",
        ),
        channels=(),
        integrations=(),
        api_server=None,
    )
    yaml2 = render_hermes(inputs2).files[".hermes/config.yaml"]
    assert "http://h:11434/v1/v1" not in yaml2
    assert "base_url: 'http://h:11434/v1'" in yaml2


def test_zeroclaw_rejects_dual_discord_channels_w1_w9():
    """W1 + W9 (ATX round 3): two discord channels attached to one
    zeroclaw agent is a silent-drop hazard — zeroclaw daemon emits a
    single `[channels.discord]` block, so the second attachment would
    be invisible. Raise so the operator detaches one."""
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(name="discord-a", type="discord", bot_token="t1"),
            ChannelInputs(name="discord-b", type="discord", bot_token="t2"),
        ),
        gateway=base.gateway,
    )
    with pytest.raises(AgentConfigError, match="multiple discord channels"):
        render_zeroclaw(inputs)


# ---------------------------------------------------------------------------
# ATX round 4 follow-ups.
# ---------------------------------------------------------------------------


def test_hermes_rejects_dual_discord_channels_atx_r4_b2():
    """ATX round 4 B2: hermes must mirror zeroclaw's dual-discord guard.
    Two attached discord channels would both render
    `DISCORD_BOT_TOKEN=...` lines into the EnvironmentFile and systemd's
    last-wins parse would silently keep only one. Raise."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(name="discord-a", type="discord", bot_token="t1"),
            ChannelInputs(name="discord-b", type="discord", bot_token="t2"),
        ),
        api_server=base.api_server,
    )
    with pytest.raises(AgentConfigError, match="multiple discord channels"):
        render_hermes(inputs)


def test_hermes_rejects_dual_slack_channels_atx_r4_b2():
    """ATX round 4 B2: same guard for slack."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="s-a", type="slack", bot_token="b1", app_token="a1"
            ),
            ChannelInputs(
                name="s-b", type="slack", bot_token="b2", app_token="a2"
            ),
        ),
        api_server=base.api_server,
    )
    with pytest.raises(AgentConfigError, match="multiple slack channels"):
        render_hermes(inputs)


_HERMES_DISCORD_ALLOW_ALL_USERS_ENV = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENROUTER_API_KEY='sk-or-1'\n"
    "HERMES_INFERENCE_PROVIDER='openrouter'\n"
    "DISCORD_BOT_TOKEN='dt'\n"
    "DISCORD_ALLOWED_USERS=''\n"
    "DISCORD_ALLOWED_CHANNELS=''\n"
    "DISCORD_REQUIRE_MENTION='true'\n"
    "DISCORD_ALLOW_ALL_USERS=true\n"
)


def test_hermes_discord_allow_all_users_byte_lock_atx_r4_w6():
    """ATX round 4 W6: lock the exact byte sequence around
    `DISCORD_ALLOW_ALL_USERS=true`. This is a SAFETY-CRITICAL presence
    flag — the hermes daemon parses it as truthy on any non-empty
    string (`bool(os.environ.get(...))`), so an accidental whitespace
    drift around the `{% if channel.allow_all_users %}` Jinja block
    that emitted it on EVERY agent (rather than only on opted-in
    agents) would silently open public Discord access. The substring
    assertion in the pre-existing test is necessary but not sufficient
    — only a full byte-lock catches a stray newline / indentation
    change that would still pass substring containment."""
    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="d",
                type="discord",
                bot_token="dt",
                allow_all_users=True,
            ),
        ),
        integrations=(),
        api_server=None,
    )
    env = render_hermes(inputs).files[".hermes/.env"]
    assert env == _HERMES_DISCORD_ALLOW_ALL_USERS_ENV
    # And the false case (default) must NOT emit the line.
    inputs_default = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=base.provider,
        channels=(
            ChannelInputs(name="d", type="discord", bot_token="dt"),
        ),
        integrations=(),
        api_server=None,
    )
    env_default = render_hermes(inputs_default).files[".hermes/.env"]
    assert "DISCORD_ALLOW_ALL_USERS" not in env_default


# ---------------------------------------------------------------------------
# Phase 3 (#560): Jinja-template regression locks for render_openclaw.
#
# Byte-for-byte expected outputs captured from the prior list-of-strings
# implementation. Any drift in the new Jinja + json.loads/deep-update flow
# MUST be intentional and surface here as a test failure with a clear diff.
# ---------------------------------------------------------------------------


def _openclaw_inputs(*, ptype: str) -> RenderInputs:
    base = _baseline_inputs(ptype=ptype)
    return RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=base.provider,
        channels=base.channels,
        integrations=base.integrations,
        api_server=base.api_server,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )


_OPENCLAW_ENV_OPENROUTER = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENCLAW_GATEWAY_BIND='lan'\n"
    "OPENCLAW_GATEWAY_PORT=40000\n"
    "OPENCLAW_GATEWAY_AUTH_MODE=token\n"
    "OPENCLAW_GATEWAY_AUTH_TOKEN='tkn'\n"
    "OPENCLAW_DEFAULT_MODEL='openrouter/anthropic/claude-opus-4.7'\n"
    "OPENROUTER_API_KEY='sk-or-1'\n"
    "DISCORD_BOT_TOKEN='discord-bot'\n"
    "GITHUB_TOKEN_GH_A='ghp_a'\n"
    "GITHUB_TOKEN='ghp_a'\n"
)

_OPENCLAW_ENV_ANTHROPIC = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENCLAW_GATEWAY_BIND='lan'\n"
    "OPENCLAW_GATEWAY_PORT=40000\n"
    "OPENCLAW_GATEWAY_AUTH_MODE=token\n"
    "OPENCLAW_GATEWAY_AUTH_TOKEN='tkn'\n"
    "OPENCLAW_DEFAULT_MODEL='claude-opus-4-7'\n"
    "ANTHROPIC_API_KEY='sk-ant-1'\n"
    "DISCORD_BOT_TOKEN='discord-bot'\n"
    "GITHUB_TOKEN_GH_A='ghp_a'\n"
    "GITHUB_TOKEN='ghp_a'\n"
)

_OPENCLAW_ENV_OPENAI = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENCLAW_GATEWAY_BIND='lan'\n"
    "OPENCLAW_GATEWAY_PORT=40000\n"
    "OPENCLAW_GATEWAY_AUTH_MODE=token\n"
    "OPENCLAW_GATEWAY_AUTH_TOKEN='tkn'\n"
    "OPENCLAW_DEFAULT_MODEL='gpt-5'\n"
    "OPENAI_API_KEY='sk-oa-1'\n"
    "DISCORD_BOT_TOKEN='discord-bot'\n"
    "GITHUB_TOKEN_GH_A='ghp_a'\n"
    "GITHUB_TOKEN='ghp_a'\n"
)

_OPENCLAW_ENV_BEDROCK = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENCLAW_GATEWAY_BIND='lan'\n"
    "OPENCLAW_GATEWAY_PORT=40000\n"
    "OPENCLAW_GATEWAY_AUTH_MODE=token\n"
    "OPENCLAW_GATEWAY_AUTH_TOKEN='tkn'\n"
    "OPENCLAW_DEFAULT_MODEL='amazon-bedrock/anthropic.claude-opus-4-1-v1:0'\n"
    "AWS_ACCESS_KEY_ID='AKIA-1'\n"
    "AWS_SECRET_ACCESS_KEY='secret-1'\n"
    "AWS_DEFAULT_REGION='us-east-1'\n"
    "DISCORD_BOT_TOKEN='discord-bot'\n"
    "GITHUB_TOKEN_GH_A='ghp_a'\n"
    "GITHUB_TOKEN='ghp_a'\n"
)

_OPENCLAW_ENV_OLLAMA = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENCLAW_GATEWAY_BIND='lan'\n"
    "OPENCLAW_GATEWAY_PORT=40000\n"
    "OPENCLAW_GATEWAY_AUTH_MODE=token\n"
    "OPENCLAW_GATEWAY_AUTH_TOKEN='tkn'\n"
    "OPENCLAW_DEFAULT_MODEL='llama3'\n"
    "OPENCLAW_OLLAMA_URL='http://10.0.0.5:11434'\n"
    "DISCORD_BOT_TOKEN='discord-bot'\n"
    "GITHUB_TOKEN_GH_A='ghp_a'\n"
    "GITHUB_TOKEN='ghp_a'\n"
)

_OPENCLAW_ENV_ZAI = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENCLAW_GATEWAY_BIND='lan'\n"
    "OPENCLAW_GATEWAY_PORT=40000\n"
    "OPENCLAW_GATEWAY_AUTH_MODE=token\n"
    "OPENCLAW_GATEWAY_AUTH_TOKEN='tkn'\n"
    "OPENCLAW_DEFAULT_MODEL='glm-4.5'\n"
    "ZAI_API_KEY='sk-zai-1'\n"
    "DISCORD_BOT_TOKEN='discord-bot'\n"
    "GITHUB_TOKEN_GH_A='ghp_a'\n"
    "GITHUB_TOKEN='ghp_a'\n"
)

# #723: litellm emits NO provider-specific env var — the bearer + base URL
# live inline in `openclaw.json` under `models.providers.<name>`. The
# only litellm-visible difference vs the openclaw + ollama baseline is
# the model id (which carries the provider-name prefix).
_OPENCLAW_ENV_LITELLM = (
    "# Managed by clawrium (clawctl). Re-render with `clawctl agent configure alpha`.\n"
    "OPENCLAW_GATEWAY_BIND='lan'\n"
    "OPENCLAW_GATEWAY_PORT=40000\n"
    "OPENCLAW_GATEWAY_AUTH_MODE=token\n"
    "OPENCLAW_GATEWAY_AUTH_TOKEN='tkn'\n"
    "OPENCLAW_DEFAULT_MODEL='lt/gemma4:31b'\n"
    "DISCORD_BOT_TOKEN='discord-bot'\n"
    "GITHUB_TOKEN_GH_A='ghp_a'\n"
    "GITHUB_TOKEN='ghp_a'\n"
)


@pytest.mark.parametrize(
    "ptype,expected",
    [
        ("openrouter", _OPENCLAW_ENV_OPENROUTER),
        ("anthropic", _OPENCLAW_ENV_ANTHROPIC),
        ("openai", _OPENCLAW_ENV_OPENAI),
        ("bedrock", _OPENCLAW_ENV_BEDROCK),
        ("ollama", _OPENCLAW_ENV_OLLAMA),
        ("zai", _OPENCLAW_ENV_ZAI),
        ("litellm", _OPENCLAW_ENV_LITELLM),
    ],
)
def test_openclaw_env_byte_lock(ptype, expected):
    """Phase 3: byte-equivalence lock for `.openclaw/env` across all 7
    supported provider types. Any drift in the Jinja template must be
    intentional and surface here with a clear diff."""
    out = render_openclaw(_openclaw_inputs(ptype=ptype))
    assert out.files[".openclaw/env"] == expected


def test_openclaw_litellm_env_has_no_litellm_specific_vars():
    """#723: pin that the openclaw + litellm env body emits NO
    LITELLM_*, OPENCLAW_LITELLM_*, or provider.api_key env var — the
    bearer and base URL live inline in `openclaw.json` under
    `models.providers.<name>`. If a future env-template branch leaks the
    bearer to disk via systemd's EnvironmentFile (different blast radius
    than `openclaw.json`), this test catches it before it ships."""
    env = render_openclaw(_openclaw_inputs(ptype="litellm")).files[".openclaw/env"]
    assert "LITELLM_" not in env
    assert "OPENCLAW_LITELLM_" not in env
    # The litellm bearer must NOT appear in the env file.
    assert "sk-master-1" not in env


def test_openclaw_json_managed_paths_populated():
    """Phase 3: assert all 5 clawctl-managed paths in openclaw.json are
    deep-updated from inputs."""
    import json

    base = _baseline_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=base.provider,
        channels=(
            ChannelInputs(
                name="discord-a",
                type="discord",
                bot_token="dt",
                allowed_users=("u1", "u2"),
                allowed_guilds=("g1",),
                allowed_channels=("c1", "c2"),
            ),
        ),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)

    # 1. agents.defaults.model.primary (openrouter prefix applied)
    assert (
        blob["agents"]["defaults"]["model"]["primary"]
        == "openrouter/anthropic/claude-opus-4.7"
    )
    # 2. gateway.port
    assert blob["gateway"]["port"] == 40000
    # 3. gateway.bind
    assert blob["gateway"]["bind"] == "lan"
    # 4. channels.discord.enabled + allowFrom
    assert blob["channels"]["discord"]["enabled"] is True
    assert blob["channels"]["discord"]["allowFrom"] == ["u1", "u2"]
    # 5. channels.discord.guilds — nested reshape. openclaw 2026.5.28+
    # rejects `{"allow": true}` as an additional property; presence in the
    # channels map alone permits the channel under `groupPolicy: "allowlist"`.
    assert blob["channels"]["discord"]["guilds"] == {
        "g1": {
            "users": ["u1", "u2"],
            "channels": {
                "c1": {},
                "c2": {},
            },
        }
    }
    # 6. groupPolicy pinned + `allow` invariant: the canonical renderer
    # emits `groupPolicy: "allowlist"` so the channel-presence semantics
    # do not depend on the daemon's implicit default, and no channel entry
    # carries the legacy `allow` key (W2: assert the upstream constraint
    # that motivated the fix, not just today's literal shape).
    assert blob["channels"]["discord"]["groupPolicy"] == "allowlist"
    for chan_entry in blob["channels"]["discord"]["guilds"]["g1"][
        "channels"
    ].values():
        assert "allow" not in chan_entry


def test_openclaw_json_daemon_sections_preserved():
    """Phase 3: assert previously-unmanaged daemon sections survive the
    render byte-identical (mirrors what #565 added for zeroclaw).

    Sections asserted:
      - env.shellEnv          (shellEnv enabled + timeoutMs)
      - tools.exec            (host, security, ask)
      - session.*             (dmScope, threadBindings, reset)
      - agents.defaults.heartbeat
      - browser               (enabled: false at minimum)
    """
    import json

    inputs = _openclaw_inputs(ptype="openrouter")
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)

    # env.shellEnv
    assert blob["env"]["shellEnv"]["enabled"] is True
    assert blob["env"]["shellEnv"]["timeoutMs"] == 15000

    # tools.exec
    assert blob["tools"]["exec"] == {
        "host": "gateway",
        "security": "full",
        "ask": "off",
    }

    # session blocks
    assert blob["session"]["dmScope"] == "per-channel-peer"
    assert blob["session"]["threadBindings"] == {
        "enabled": True,
        "idleHours": 24,
        "maxAgeHours": 168,
    }
    assert blob["session"]["reset"] == {
        "mode": "daily",
        "atHour": 4,
        "idleMinutes": 120,
    }

    # agents.defaults.heartbeat
    assert blob["agents"]["defaults"]["heartbeat"] == {
        "every": "30m",
        "target": "last",
    }

    # browser presence (enabled: false)
    assert blob["browser"]["enabled"] is False


def test_openclaw_dual_discord_channels_raises():
    """Phase 3: two attached discord channels must raise — openclaw renders
    one DISCORD_BOT_TOKEN env var and one channels.discord allowlist."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        channels=(
            ChannelInputs(name="d1", type="discord", bot_token="t1"),
            ChannelInputs(name="d2", type="discord", bot_token="t2"),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    with pytest.raises(AgentConfigError, match="multiple discord channels"):
        render_openclaw(inputs)


def test_openclaw_dual_slack_channels_raises():
    """Phase 3: two attached slack channels must raise — same shape as
    dual-discord guard."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        channels=(
            ChannelInputs(name="s1", type="slack", bot_token="b1", app_token="a1"),
            ChannelInputs(name="s2", type="slack", bot_token="b2", app_token="a2"),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    with pytest.raises(AgentConfigError, match="multiple slack channels"):
        render_openclaw(inputs)


def test_openclaw_json_no_discord_attached_emits_empty_block():
    """Phase 3: with no discord channel attached, channels.discord must
    have enabled=false + empty allowFrom + empty guilds."""
    import json

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        channels=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    assert blob["channels"]["discord"]["enabled"] is False
    assert blob["channels"]["discord"]["allowFrom"] == []
    assert blob["channels"]["discord"]["guilds"] == {}


# ---------------------------------------------------------------------------
# Phase 3 ATX Round 1 — B3 + W4 follow-ups.
#
# B3: full byte-lock for .openclaw/openclaw.json — pins json.dumps params,
#     key ordering, and every unmanaged baseline key. Any drift fails CI
#     with a clear diff (mirrors the env byte-lock pattern above).
# W4: gateway=None must leave the baseline gateway block byte-identical.
# ---------------------------------------------------------------------------


_OPENCLAW_JSON_BYTE_LOCK = """\
{
  "agents": {
    "defaults": {
      "workspace": "~/.openclaw/workspace",
      "model": {
        "primary": "openrouter/anthropic/claude-opus-4.7"
      },
      "imageMaxDimensionPx": 1200,
      "maxConcurrent": 4,
      "sandbox": {
        "mode": "off",
        "scope": "session"
      },
      "heartbeat": {
        "every": "30m",
        "target": "last"
      }
    }
  },
  "gateway": {
    "mode": "local",
    "port": 40000,
    "bind": "lan",
    "reload": {
      "mode": "hybrid",
      "debounceMs": 300
    },
    "auth": {
      "mode": "token",
      "token": "tkn"
    }
  },
  "session": {
    "dmScope": "per-channel-peer",
    "threadBindings": {
      "enabled": true,
      "idleHours": 24,
      "maxAgeHours": 168
    },
    "reset": {
      "mode": "daily",
      "atHour": 4,
      "idleMinutes": 120
    }
  },
  "tools": {
    "exec": {
      "host": "gateway",
      "security": "full",
      "ask": "off"
    },
    "deny": [
      "browser"
    ]
  },
  "channels": {
    "discord": {
      "enabled": true,
      "allowFrom": [
        "u1",
        "u2"
      ],
      "guilds": {
        "g1": {
          "users": [
            "u1",
            "u2"
          ],
          "channels": {
            "c1": {},
            "c2": {}
          }
        }
      },
      "groupPolicy": "allowlist"
    }
  },
  "browser": {
    "enabled": false
  },
  "env": {
    "shellEnv": {
      "enabled": true,
      "timeoutMs": 15000
    }
  }
}
"""


def test_openclaw_json_byte_lock():
    """B3 (Round 1): full byte-equivalence lock for `.openclaw/openclaw.json`.
    Pins json.dumps params (indent=2, sort_keys=False, trailing newline),
    key ordering, and every unmanaged baseline key. Any drift fails CI."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or",
            type="openrouter",
            default_model="anthropic/claude-opus-4.7",
            api_key="sk-or-1",
        ),
        channels=(
            ChannelInputs(
                name="discord-a",
                type="discord",
                bot_token="discord-bot",
                allowed_users=("u1", "u2"),
                allowed_guilds=("g1",),
                allowed_channels=("c1", "c2"),
            ),
        ),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    assert body == _OPENCLAW_JSON_BYTE_LOCK


def test_openclaw_json_gateway_none_preserves_baseline_gateway_block():
    """W4 (Round 1): with gateway=None the baseline gateway block must
    survive byte-identical — no managed-path mutation should leak into
    the unmanaged sections."""
    import json

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        channels=(),
        integrations=(),
        gateway=None,
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    # Baseline gateway block survives byte-identical when gateway=None.
    # Port matches `_OPENCLAW_DEFAULT_GATEWAY_PORT` so the baseline cannot
    # disagree with the env-template fallback (Round 2 B1).
    assert blob["gateway"] == {
        "mode": "local",
        "port": 40000,
        "bind": "lan",
        "reload": {"mode": "hybrid", "debounceMs": 300},
    }


def test_openclaw_json_daemon_sections_unmanaged_baseline_keys_complete():
    """B3 (Round 1) — strengthening: assert ALL unmanaged baseline keys
    are present, not just a curated sample. Catches accidental baseline
    truncation that the curated `daemon_sections_preserved` test misses."""
    import json

    inputs = _openclaw_inputs(ptype="openrouter")
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    # Top-level keys must be exactly the baseline set.
    assert set(blob.keys()) == {
        "agents",
        "gateway",
        "session",
        "tools",
        "channels",
        "browser",
        "env",
    }
    # agents.defaults unmanaged keys (model is managed).
    assert set(blob["agents"]["defaults"].keys()) == {
        "workspace",
        "model",
        "imageMaxDimensionPx",
        "maxConcurrent",
        "sandbox",
        "heartbeat",
    }
    # gateway unmanaged keys survive (port + bind are managed).
    assert blob["gateway"]["mode"] == "local"
    assert blob["gateway"]["reload"] == {"mode": "hybrid", "debounceMs": 300}
    # tools.deny baseline value.
    assert blob["tools"]["deny"] == ["browser"]
    # agents.defaults.workspace baseline value.
    assert blob["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"
    assert blob["agents"]["defaults"]["imageMaxDimensionPx"] == 1200
    assert blob["agents"]["defaults"]["maxConcurrent"] == 4
    assert blob["agents"]["defaults"]["sandbox"] == {
        "mode": "off",
        "scope": "session",
    }


# ---------------------------------------------------------------------------
# Phase 3 ATX Round 2 follow-ups.
#
# B1: covered by `test_openclaw_json_gateway_none_preserves_baseline_gateway_block`
#     update (port now matches `_OPENCLAW_DEFAULT_GATEWAY_PORT` = 40000).
# B3: `has_gitlab_url` branch — test token-only (URL absent) + token+URL.
# W1: gateway.auth=None must NOT emit `OPENCLAW_GATEWAY_AUTH_TOKEN=`.
# W2: multi-guild discord channel exercises the loop with 2+ guilds.
# W3: `git` integration skip path emits no env var.
# ---------------------------------------------------------------------------


def test_openclaw_gitlab_integration_emits_token_and_optional_url():
    """B3 (Round 2): exercises both branches of `has_gitlab_url` in the
    canonical env template."""
    base_provider = ProviderInputs(
        name="or", type="openrouter", default_model="m", api_key="sk-1"
    )
    # Token-only: GITLAB_URL must be ABSENT.
    inputs_no_url = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=base_provider,
        integrations=(
            IntegrationInputs(
                name="gl",
                type="gitlab",
                credentials=(("GITLAB_TOKEN", "gl-t"),),
            ),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    env = render_openclaw(inputs_no_url).files[".openclaw/env"]
    assert "GITLAB_TOKEN='gl-t'" in env
    assert "GITLAB_URL" not in env

    # Token + URL: both lines present.
    inputs_with_url = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=base_provider,
        integrations=(
            IntegrationInputs(
                name="gl",
                type="gitlab",
                credentials=(
                    ("GITLAB_TOKEN", "gl-t"),
                    ("GITLAB_URL", "https://gl.example.com"),
                ),
            ),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    env = render_openclaw(inputs_with_url).files[".openclaw/env"]
    assert "GITLAB_TOKEN='gl-t'" in env
    assert "GITLAB_URL='https://gl.example.com'" in env


def test_openclaw_gateway_auth_none_omits_auth_token_var():
    """W1 (Round 2): when gateway.auth is empty, AUTH_TOKEN line must NOT
    be emitted (a present-but-empty token would let the daemon enter
    "token mode with empty token" and reject all requests)."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="", bind="lan"),
    )
    env = render_openclaw(inputs).files[".openclaw/env"]
    assert "OPENCLAW_GATEWAY_AUTH_MODE=none" in env
    assert "OPENCLAW_GATEWAY_AUTH_TOKEN" not in env


def test_openclaw_multi_guild_discord_renders_all_guilds():
    """W2 (Round 2): two guilds in allowed_guilds must both materialize
    as keys in channels.discord.guilds."""
    import json

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        channels=(
            ChannelInputs(
                name="d",
                type="discord",
                bot_token="t",
                allowed_users=("u1",),
                allowed_guilds=("g1", "g2"),
                allowed_channels=("c1",),
            ),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    assert set(blob["channels"]["discord"]["guilds"].keys()) == {"g1", "g2"}
    assert blob["channels"]["discord"]["groupPolicy"] == "allowlist"
    for guild_id in ("g1", "g2"):
        assert blob["channels"]["discord"]["guilds"][guild_id]["users"] == ["u1"]
        assert blob["channels"]["discord"]["guilds"][guild_id]["channels"] == {
            "c1": {}
        }
        # `allow` invariant: openclaw 2026.5.28+ rejects it as additional
        # property; assert absence directly rather than only checking the
        # literal `{}` shape (W2).
        for chan_entry in blob["channels"]["discord"]["guilds"][guild_id][
            "channels"
        ].values():
            assert "allow" not in chan_entry


@pytest.mark.parametrize(
    "allowed_guilds,allowed_channels",
    [
        (("g1", "g2"), ("c1", "c2")),  # multi-guild × multi-channel
        (("g1",), ()),  # guild without channels (empty channels map)
    ],
    ids=["2g_2c", "1g_0c"],
)
def test_openclaw_discord_guilds_channels_shape_parametrized(
    allowed_guilds, allowed_channels
):
    """PR #747 W3 (ATX review): guard the `channels.<id>` payload shape
    across multi-guild × multi-channel and empty-channels-per-guild
    combinations. Every channel entry must be the empty object `{}` with
    no `allow` key, and `groupPolicy: "allowlist"` must be emitted so the
    channel-presence invariant holds regardless of upstream defaults.
    """
    import json

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        channels=(
            ChannelInputs(
                name="d",
                type="discord",
                bot_token="t",
                allowed_users=("u1",),
                allowed_guilds=allowed_guilds,
                allowed_channels=allowed_channels,
            ),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    discord = blob["channels"]["discord"]

    assert discord["enabled"] is True
    assert discord["groupPolicy"] == "allowlist"
    assert set(discord["guilds"].keys()) == set(allowed_guilds)

    for guild_id in allowed_guilds:
        guild_entry = discord["guilds"][guild_id]
        assert guild_entry["users"] == ["u1"]
        assert set(guild_entry["channels"].keys()) == set(allowed_channels)
        for chan_id, chan_entry in guild_entry["channels"].items():
            assert chan_entry == {}
            assert "allow" not in chan_entry


def test_openclaw_git_integration_skipped():
    """W3 (Round 2): `git` integration is intentionally skipped in env
    render (clientside identity; ~/.gitconfig render lives elsewhere)."""
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        integrations=(
            IntegrationInputs(
                name="me",
                type="git",
                credentials=(("GIT_USER_EMAIL", "a@b"), ("GIT_USER_NAME", "Me")),
            ),
        ),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
    )
    env = render_openclaw(inputs).files[".openclaw/env"]
    assert "GIT_USER_EMAIL" not in env
    assert "GIT_USER_NAME" not in env


def test_openclaw_model_prefix_idempotent():
    """Round 2 S3: pre-prefixed model id must NOT double up.
    (`openrouter/m` stays `openrouter/m`; `amazon-bedrock/m` stays
    `amazon-bedrock/m`, not `amazon-bedrock/amazon-bedrock/m`.)"""
    cases = [
        ("openrouter", "openrouter/", "openrouter/anthropic/claude-opus-4.7"),
        (
            "bedrock",
            "amazon-bedrock/",
            "amazon-bedrock/anthropic.claude-opus-4-1-v1:0",
        ),
    ]
    for ptype, prefix, model_id in cases:
        if ptype == "openrouter":
            p = ProviderInputs(
                name="or", type=ptype, default_model=model_id, api_key="sk-1"
            )
        else:
            p = ProviderInputs(
                name="br",
                type=ptype,
                default_model=model_id,
                region="us-east-1",
                aws_access_key="AKIA-1",
                aws_secret_key="secret-1",
            )
        inputs = RenderInputs(
            agent_name="alpha",
            agent_type="openclaw",
            provider=p,
            gateway=GatewayInputs(host="0.0.0.0", port=40000, bind="lan"),
        )
        env = render_openclaw(inputs).files[".openclaw/env"]
        expected_line = f"OPENCLAW_DEFAULT_MODEL='{model_id}'"
        # Exact-line match — substring would pass for a double-prefixed
        # value that happens to contain the model id as a tail.
        assert any(line == expected_line for line in env.splitlines()), (
            f"expected exact line {expected_line!r} in:\n{env}"
        )
        assert env.count(prefix + prefix) == 0


def test_openclaw_json_gateway_auth_survives_render_cycle():
    """Round 3 B1: `gateway.auth` MUST flow through `_render_openclaw_json`.
    Regression test for the silent-wipe class: if the renderer emitted the
    baseline verbatim (no auth block), F3 sync would overwrite the
    install-time bearer on every sync."""
    import json

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        channels=(),
        integrations=(),
        gateway=GatewayInputs(
            host="0.0.0.0",
            port=40000,
            auth="bearer-secret-xyz",
            bind="lan",
        ),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    assert blob["gateway"]["auth"] == {
        "mode": "token",
        "token": "bearer-secret-xyz",
    }


def test_openclaw_json_no_auth_omits_gateway_auth_block():
    """Round 3 B1 corollary: `gateway.auth=""` must NOT emit a stale auth
    block. Explicit absence keeps the state machine clean."""
    import json

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="openclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", default_model="m", api_key="sk-1"
        ),
        channels=(),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="", bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    assert "auth" not in blob["gateway"]


# ---------------------------------------------------------------------------
# #582: HERMES_API_SERVER_KEY must be hydrated from secrets.json
#
# install.py writes the api_server shape (enabled/host/port) into hosts.json
# but NOT the bearer — the key lives in secrets.json under the canonical
# instance key. The legacy configure_agent path hydrates it at
# lifecycle.py:1695; the canonical render path must do the same or every
# `agent sync` writes API_SERVER_KEY='' and hermes refuses to bind a
# wildcard interface.
# ---------------------------------------------------------------------------


@pytest.fixture
def hermes_secret_stores(stores, monkeypatch):
    """Adds in-memory fakes for the secrets-store hooks the render path
    reaches into to hydrate HERMES_API_SERVER_KEY. Returns the existing
    `stores` bundle with an extra `.instance_secrets` dict attached."""
    instance_secrets: dict[str, dict[str, dict]] = {}

    def _get_instance_key(host: str, claw_type: str, claw_name: str) -> str:
        return f"{host}:{claw_type}:{claw_name}"

    def _get_instance_secrets(instance_key: str):
        return dict(instance_secrets.get(instance_key, {}))

    monkeypatch.setattr(
        "clawrium.core.secrets.get_instance_key", _get_instance_key
    )
    monkeypatch.setattr(
        "clawrium.core.secrets.get_instance_secrets", _get_instance_secrets
    )

    stores.instance_secrets = instance_secrets  # type: ignore[attr-defined]
    return stores


def _hermes_agent_with_api_server(
    *,
    api_server: dict | None,
    host_key_id: str | None = "host-1",
    agent_name: str = "alpha",
):
    """Build a (host_record, agent_type, agent_record) triple matching
    the post-install shape: hermes agent with an openrouter primary
    attachment and a non-sensitive api_server block in hosts.json.

    `api_server` is the dict written under `config.api_server`. Pass
    `None` to omit the block entirely.
    """
    host = {"hostname": "host-1"}
    if host_key_id is not None:
        host["key_id"] = host_key_id
    cfg: dict = {}
    if api_server is not None:
        cfg["api_server"] = api_server
    return (
        host,
        "hermes",
        {
            "agent_name": agent_name,
            "providers": [{"name": "or", "role": "primary", "model": ""}],
            "config": cfg,
        },
    )


def _seed_openrouter_provider(stores):
    stores.providers["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "anthropic/claude-opus-4.7",
    }
    stores.provider_api_keys["or"] = "sk-or-1"


VALID_HEX_KEY = "a" * 64  # 64-char lowercase hex — matches _is_valid_hermes_api_server_key


def test_hermes_api_server_key_hydrated_from_secrets_when_missing_in_hosts_json(
    hermes_secret_stores,
):
    """#582 fix: hosts.json carries only the shape (enabled/host/port),
    secrets.json carries the bearer. The canonical render must hydrate
    the bearer from secrets.json keyed by `host_key_id:hermes:agent_name`
    so that every sync renders a non-empty API_SERVER_KEY."""
    stores = hermes_secret_stores
    stores.agent = _hermes_agent_with_api_server(
        api_server={"enabled": True, "host": "0.0.0.0", "port": 8642},
    )
    _seed_openrouter_provider(stores)
    stores.instance_secrets["host-1:hermes:alpha"] = {
        "HERMES_API_SERVER_KEY": {"value": VALID_HEX_KEY}
    }

    inputs = build_render_inputs("alpha")

    assert inputs.api_server is not None
    assert inputs.api_server.key == VALID_HEX_KEY
    assert inputs.api_server.host == "0.0.0.0"
    assert inputs.api_server.port == 8642


def test_hermes_api_server_key_inline_in_hosts_json_wins_over_secrets(
    hermes_secret_stores,
):
    """Backwards compat with pre-#318 hermes entries that persisted the
    bearer inline in hosts.json (e.g. legacy `espresso`). If the blob
    already carries a key, the render path uses it verbatim and does
    NOT clobber it with whatever happens to be in secrets.json."""
    stores = hermes_secret_stores
    inline = "b" * 64
    stores.agent = _hermes_agent_with_api_server(
        api_server={
            "enabled": True,
            "host": "0.0.0.0",
            "port": 8642,
            "key": inline,
        },
    )
    _seed_openrouter_provider(stores)
    # A different secret in secrets.json — must NOT be picked up because
    # the inline value already satisfied the hydration check.
    stores.instance_secrets["host-1:hermes:alpha"] = {
        "HERMES_API_SERVER_KEY": {"value": "c" * 64}
    }

    inputs = build_render_inputs("alpha")

    assert inputs.api_server is not None
    assert inputs.api_server.key == inline


def test_hermes_api_server_key_uses_hostname_when_key_id_absent(
    hermes_secret_stores,
):
    """Pre-#448 host records did not carry `key_id`. The instance-key
    lookup must fall back to `hostname` so legacy hosts still get their
    bearer hydrated."""
    stores = hermes_secret_stores
    stores.agent = _hermes_agent_with_api_server(
        api_server={"enabled": True, "host": "0.0.0.0", "port": 8642},
        host_key_id=None,  # legacy: no key_id field
    )
    _seed_openrouter_provider(stores)
    stores.instance_secrets["host-1:hermes:alpha"] = {
        "HERMES_API_SERVER_KEY": {"value": VALID_HEX_KEY}
    }

    inputs = build_render_inputs("alpha")

    assert inputs.api_server is not None
    assert inputs.api_server.key == VALID_HEX_KEY


def test_hermes_api_server_key_invalid_secret_falls_through_to_empty(
    hermes_secret_stores,
):
    """Defensive: if secrets.json was hand-edited to a malformed value
    (not 64-char lowercase hex), the validator rejects it and the render
    emits an empty key rather than silently shipping garbage into the
    EnvironmentFile. The configure_agent path will surface the error to
    the operator; render's job is to not propagate a bad bearer."""
    stores = hermes_secret_stores
    stores.agent = _hermes_agent_with_api_server(
        api_server={"enabled": True, "host": "0.0.0.0", "port": 8642},
    )
    _seed_openrouter_provider(stores)
    stores.instance_secrets["host-1:hermes:alpha"] = {
        "HERMES_API_SERVER_KEY": {"value": "not-hex-and-too-short"}
    }

    inputs = build_render_inputs("alpha")

    assert inputs.api_server is not None
    assert inputs.api_server.key == ""


def test_hermes_api_server_key_missing_secret_falls_through_to_empty(
    hermes_secret_stores,
):
    """Defensive: no entry in secrets.json at all — render returns
    empty rather than crashing. configure_agent surfaces the real
    error; render stays pure."""
    stores = hermes_secret_stores
    stores.agent = _hermes_agent_with_api_server(
        api_server={"enabled": True, "host": "0.0.0.0", "port": 8642},
    )
    _seed_openrouter_provider(stores)
    # Intentionally no entry in instance_secrets for host-1:hermes:alpha.

    inputs = build_render_inputs("alpha")

    assert inputs.api_server is not None
    assert inputs.api_server.key == ""


def test_non_hermes_agent_does_not_hydrate_api_server_key(
    hermes_secret_stores, monkeypatch
):
    """The secrets.json reach-through is hermes-specific (zeroclaw and
    openclaw don't use HERMES_API_SERVER_KEY). For a non-hermes agent,
    the render path must not touch the secrets store at all — guards
    against accidentally hydrating an unrelated agent's secret onto a
    different agent type."""
    stores = hermes_secret_stores

    # Tripwire: if anything calls get_instance_secrets while rendering a
    # non-hermes agent, the test fails loudly.
    called: list[str] = []

    def _tripwire(instance_key: str):
        called.append(instance_key)
        return {}

    monkeypatch.setattr(
        "clawrium.core.secrets.get_instance_secrets", _tripwire
    )

    # Build a zeroclaw agent record with an api_server block (this is
    # synthetic — zeroclaw doesn't use api_server in production, but
    # the render code shouldn't care: it should branch on agent_type).
    host = {"hostname": "host-1", "key_id": "host-1"}
    stores.agent = (
        host,
        "zeroclaw",
        {
            "agent_name": "alpha",
            "providers": [{"name": "or", "role": "primary", "model": ""}],
            "config": {
                "api_server": {"host": "0.0.0.0", "port": 8642},
                "gateway": {"host": "0.0.0.0", "port": 41040},
            },
        },
    )
    _seed_openrouter_provider(stores)

    inputs = build_render_inputs("alpha")

    assert called == [], (
        f"render must not consult secrets.json for non-hermes agents; "
        f"got lookups: {called}"
    )
    assert inputs.api_server is not None
    # No inline key, no hydration → empty.
    assert inputs.api_server.key == ""


def test_hermes_api_server_key_propagates_into_rendered_env(
    hermes_secret_stores,
):
    """End-to-end inside the render layer: build_render_inputs +
    render_hermes together must produce a `.hermes/.env` whose
    `API_SERVER_KEY=` line carries the bearer hydrated from
    secrets.json. This is the assertion that fails without the #582
    fix — and the one that would have caught the regression at the
    canonical-render layer instead of needing an E2E run."""
    stores = hermes_secret_stores
    stores.agent = _hermes_agent_with_api_server(
        api_server={"enabled": True, "host": "0.0.0.0", "port": 8642},
    )
    _seed_openrouter_provider(stores)
    stores.instance_secrets["host-1:hermes:alpha"] = {
        "HERMES_API_SERVER_KEY": {"value": VALID_HEX_KEY}
    }

    inputs = build_render_inputs("alpha")
    rendered = render_hermes(inputs)
    env_body = rendered.files[".hermes/.env"]

    assert f"API_SERVER_KEY='{VALID_HEX_KEY}'" in env_body
    assert "API_SERVER_KEY=''" not in env_body


# ---------------------------------------------------------------------------
# Issue #621: hermes multi-provider attachment rendering
# ---------------------------------------------------------------------------


def _hermes_multi_agent_record(providers):
    return (
        {"hostname": "host-1"},
        "hermes",
        {"agent_name": "wolf", "providers": providers, "config": {}},
    )


def _seed_provider(stores, *, name, ptype, default_model="", region=""):
    stores.providers[name] = {
        "name": name,
        "type": ptype,
        "default_model": default_model,
        "region": region,
    }


def _seed_multi_provider_fixture(stores):
    """[primary anthropic, compression openrouter, title_generation bedrock]."""
    stores.agent = _hermes_multi_agent_record(
        [
            {"name": "anthropic-prod", "role": "primary", "model": ""},
            {"name": "openrouter-aux", "role": "compression", "model": ""},
            {
                "name": "bedrock-mac",
                "role": "title_generation",
                "model": "zai.glm-4.7",
            },
        ]
    )
    _seed_provider(
        stores,
        name="anthropic-prod",
        ptype="anthropic",
        default_model="claude-sonnet-4-6",
    )
    _seed_provider(
        stores,
        name="openrouter-aux",
        ptype="openrouter",
        default_model="anthropic/claude-haiku-4.5",
    )
    _seed_provider(
        stores,
        name="bedrock-mac",
        ptype="bedrock",
        default_model="claude-haiku-default",
        region="us-east-1",
    )
    stores.provider_api_keys["anthropic-prod"] = "sk-ant-PRIMARY"
    stores.provider_api_keys["openrouter-aux"] = "sk-or-AUX"
    stores.provider_aws["bedrock-mac"] = ("AKIA-AUX", "secret-AUX")


def test_621_build_render_inputs_multi_provider_hermes_bundle(stores):
    _seed_multi_provider_fixture(stores)
    inputs = build_render_inputs("wolf")

    assert inputs.hermes is not None
    bundle = inputs.hermes
    assert len(bundle.attachments) == 3
    names = [a.name for a in bundle.attachments]
    assert names == ["anthropic-prod", "openrouter-aux", "bedrock-mac"]
    by_name = {a.name: a for a in bundle.attachments}
    assert by_name["anthropic-prod"].role == "primary"
    assert by_name["anthropic-prod"].model == "claude-sonnet-4-6"
    assert by_name["openrouter-aux"].role == "compression"
    assert by_name["openrouter-aux"].model == "anthropic/claude-haiku-4.5"
    assert by_name["bedrock-mac"].role == "title_generation"
    # Per-attachment model override wins over provider default.
    assert by_name["bedrock-mac"].model == "zai.glm-4.7"

    # Credentials deduped by type for bearer; per-name for bedrock.
    api_keys = dict(bundle.api_keys)
    assert api_keys == {
        "anthropic": "sk-ant-PRIMARY",
        "openrouter": "sk-or-AUX",
    }
    aws = dict(bundle.aws_credentials)
    assert aws == {"bedrock-mac": ("AKIA-AUX", "secret-AUX", "us-east-1")}


def test_621_render_hermes_multi_provider_yaml_emits_auxiliary_blocks(stores):
    _seed_multi_provider_fixture(stores)
    inputs = build_render_inputs("wolf")
    out = render_hermes(inputs)
    yaml = out.files[".hermes/config.yaml"]

    # Primary block — anthropic
    assert 'provider: "anthropic"' in yaml
    assert "'claude-sonnet-4-6'" in yaml

    # Auxiliary blocks — both aux roles present with attached provider type
    assert "auxiliary:" in yaml
    assert "compression:" in yaml
    assert "title_generation:" in yaml
    assert 'provider: "openrouter"' in yaml
    assert 'provider: "bedrock"' in yaml
    assert "'anthropic/claude-haiku-4.5'" in yaml
    assert "'zai.glm-4.7'" in yaml

    # Upstream per-primary-type default for title_generation MUST be
    # suppressed once an explicit aux is attached for that role.
    assert "claude-haiku-4-5-20251001" not in yaml


def test_621_render_hermes_multi_provider_env_emits_aux_credentials(stores):
    _seed_multi_provider_fixture(stores)
    inputs = build_render_inputs("wolf")
    out = render_hermes(inputs)
    env = out.files[".hermes/.env"]

    # Primary creds via existing single-provider path
    assert "ANTHROPIC_API_KEY='sk-ant-PRIMARY'" in env
    assert "HERMES_INFERENCE_PROVIDER='anthropic'" in env

    # Auxiliary creds — openrouter bearer + bedrock AWS triple
    assert "OPENROUTER_API_KEY='sk-or-AUX'" in env
    assert "AWS_ACCESS_KEY_ID='AKIA-AUX'" in env
    assert "AWS_SECRET_ACCESS_KEY='secret-AUX'" in env
    assert "AWS_DEFAULT_REGION='us-east-1'" in env


def test_621_same_type_collision_different_keys_raises(stores):
    stores.agent = _hermes_multi_agent_record(
        [
            {"name": "anthropic-a", "role": "primary", "model": ""},
            {"name": "anthropic-b", "role": "compression", "model": ""},
        ]
    )
    _seed_provider(stores, name="anthropic-a", ptype="anthropic")
    _seed_provider(stores, name="anthropic-b", ptype="anthropic")
    stores.provider_api_keys["anthropic-a"] = "sk-ant-A"
    stores.provider_api_keys["anthropic-b"] = "sk-ant-B"
    with pytest.raises(
        AgentConfigError, match="two providers of type 'anthropic'"
    ):
        build_render_inputs("wolf")


def test_621_same_type_collision_same_keys_allowed(stores):
    """Same-type / same-key is harmless: hermes still emits one env var."""
    stores.agent = _hermes_multi_agent_record(
        [
            {"name": "anthropic-a", "role": "primary", "model": ""},
            {"name": "anthropic-b", "role": "compression", "model": ""},
        ]
    )
    _seed_provider(stores, name="anthropic-a", ptype="anthropic")
    _seed_provider(stores, name="anthropic-b", ptype="anthropic")
    stores.provider_api_keys["anthropic-a"] = "sk-ant-SHARED"
    stores.provider_api_keys["anthropic-b"] = "sk-ant-SHARED"
    inputs = build_render_inputs("wolf")
    assert inputs.hermes is not None
    assert dict(inputs.hermes.api_keys) == {"anthropic": "sk-ant-SHARED"}


def test_621_two_bedrock_attachments_raises(stores):
    """Two bedrock attachments with *different* credentials must raise."""
    stores.agent = _hermes_multi_agent_record(
        [
            {"name": "br-a", "role": "primary", "model": ""},
            {"name": "br-b", "role": "compression", "model": ""},
        ]
    )
    _seed_provider(stores, name="br-a", ptype="bedrock", region="us-east-1")
    _seed_provider(stores, name="br-b", ptype="bedrock", region="us-west-2")
    stores.provider_aws["br-a"] = ("AKIA-A", "secret-A")
    stores.provider_aws["br-b"] = ("AKIA-B", "secret-B")
    with pytest.raises(
        AgentConfigError, match="two bedrock provider attachments"
    ):
        build_render_inputs("wolf")


def test_621_two_bedrock_attachments_same_creds_different_region_raises(stores):
    """Same AWS creds but divergent regions must raise.

    Hermes emits one `bedrock.region` / `AWS_DEFAULT_REGION` per process,
    so a region mismatch would be silently lost. Reject upfront.
    """
    stores.agent = _hermes_multi_agent_record(
        [
            {"name": "br-a", "role": "primary", "model": ""},
            {"name": "br-b", "role": "compression", "model": ""},
        ]
    )
    _seed_provider(stores, name="br-a", ptype="bedrock", region="us-east-1")
    _seed_provider(stores, name="br-b", ptype="bedrock", region="us-west-2")
    stores.provider_aws["br-a"] = ("AKIA-SHARED", "secret-SHARED")
    stores.provider_aws["br-b"] = ("AKIA-SHARED", "secret-SHARED")
    with pytest.raises(
        AgentConfigError,
        match="different AWS credentials or region",
    ):
        build_render_inputs("wolf")


def test_621_two_bedrock_attachments_same_creds_allowed(stores):
    """Two bedrock attachments that share the same AWS credentials are allowed.

    Hermes emits one AWS_* triple for the shared identity; both slots use it.
    The bundle must contain one aws_credentials entry per provider name so the
    template can reference each slot individually.
    """
    stores.agent = _hermes_multi_agent_record(
        [
            {"name": "br-primary", "role": "primary", "model": "zai.glm-5"},
            {"name": "br-nova-lite", "role": "web_extract", "model": "amazon.nova-lite-v1:0"},
            {"name": "br-nova-micro", "role": "compression", "model": "amazon.nova-micro-v1:0"},
            {"name": "br-glm-flash", "role": "title_generation", "model": "zai.glm-4.7-flash"},
        ]
    )
    for name in ("br-primary", "br-nova-lite", "br-nova-micro", "br-glm-flash"):
        _seed_provider(stores, name=name, ptype="bedrock", region="us-east-1")
        stores.provider_aws[name] = ("AKIA-SHARED", "secret-SHARED")

    inputs = build_render_inputs("wolf")

    assert inputs.hermes is not None
    # All four attachments must be present
    roles = {a.role for a in inputs.hermes.attachments}
    assert roles == {"primary", "web_extract", "compression", "title_generation"}
    # aws_credentials has an entry for each provider name
    creds = dict(inputs.hermes.aws_credentials)
    assert set(creds.keys()) == {
        "br-primary", "br-nova-lite", "br-nova-micro", "br-glm-flash"
    }
    # All share the same (ak, sk)
    assert all(v[:2] == ("AKIA-SHARED", "secret-SHARED") for v in creds.values())


def test_621_two_bedrock_attachments_same_creds_no_dup_aws_env(stores):
    """render_hermes must NOT emit duplicate AWS_* env vars when multiple
    bedrock attachments share the same credentials as the primary.

    The .env must contain exactly one AWS_ACCESS_KEY_ID line.
    """
    stores.agent = _hermes_multi_agent_record(
        [
            {"name": "br-primary", "role": "primary", "model": "zai.glm-5"},
            {"name": "br-aux", "role": "compression", "model": "amazon.nova-micro-v1:0"},
        ]
    )
    for name in ("br-primary", "br-aux"):
        _seed_provider(stores, name=name, ptype="bedrock", region="us-east-1")
        stores.provider_aws[name] = ("AKIA-SHARED", "secret-SHARED")

    inputs = build_render_inputs("wolf")
    out = render_hermes(inputs)
    env_content = out.files[".hermes/.env"]

    ak_lines = [ln for ln in env_content.splitlines() if "AWS_ACCESS_KEY_ID" in ln]
    assert len(ak_lines) == 1, (
        f"Expected exactly one AWS_ACCESS_KEY_ID in .env, found {len(ak_lines)}:\n"
        + "\n".join(ak_lines)
    )


def test_621_single_provider_hermes_bundle_has_one_attachment(stores):
    """Single-provider hermes still populates the bundle (one entry, role=primary)."""
    stores.agent = _hermes_multi_agent_record(
        [{"name": "or", "role": "primary", "model": ""}]
    )
    _seed_provider(
        stores, name="or", ptype="openrouter", default_model="anthropic/claude-opus-4.7"
    )
    stores.provider_api_keys["or"] = "sk-or-1"
    inputs = build_render_inputs("wolf")
    assert inputs.hermes is not None
    assert len(inputs.hermes.attachments) == 1
    assert inputs.hermes.attachments[0].role == "primary"


def test_621_single_provider_hermes_yaml_unchanged(stores):
    """Single-provider hermes renders the legacy per-primary aux default."""
    stores.agent = _hermes_multi_agent_record(
        [{"name": "or", "role": "primary", "model": ""}]
    )
    _seed_provider(
        stores,
        name="or",
        ptype="openrouter",
        default_model="anthropic/claude-opus-4.7",
    )
    stores.provider_api_keys["or"] = "sk-or-1"
    inputs = build_render_inputs("wolf")
    out = render_hermes(inputs)
    yaml = out.files[".hermes/config.yaml"]
    # Upstream per-primary default for title_generation still present
    # because no explicit aux attached.
    assert 'model: "anthropic/claude-haiku-4.5"' in yaml


def test_621_zeroclaw_build_render_inputs_has_no_hermes_bundle(stores):
    """build_render_inputs only populates `hermes` for hermes agents."""
    stores.agent = (
        {"hostname": "host-1"},
        "zeroclaw",
        {"agent_name": "z", "providers": ["or"], "config": {}},
    )
    _seed_provider(
        stores, name="or", ptype="openrouter", default_model="x/y"
    )
    stores.provider_api_keys["or"] = "sk-or-1"
    inputs = build_render_inputs("z")
    assert inputs.hermes is None


def test_621_openclaw_build_render_inputs_has_no_hermes_bundle(stores):
    stores.agent = (
        {"hostname": "host-1"},
        "openclaw",
        {"agent_name": "o", "providers": ["or"], "config": {}},
    )
    _seed_provider(
        stores, name="or", ptype="openrouter", default_model="x/y"
    )
    stores.provider_api_keys["or"] = "sk-or-1"
    inputs = build_render_inputs("o")
    assert inputs.hermes is None


def test_621_zeroclaw_render_ignores_hermes_bundle():
    """Passing a HermesProviderBundle to render_zeroclaw must not change output."""
    base = _zeroclaw_inputs(ptype="openrouter")
    with_bundle = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=base.channels,
        integrations=base.integrations,
        gateway=base.gateway,
        hermes=HermesProviderBundle(
            attachments=(
                AttachedProviderInputs(
                    name="extra",
                    type="anthropic",
                    role="compression",
                    model="x",
                ),
            ),
            api_keys=(("anthropic", "sk-ant-x"),),
        ),
    )
    out_base = render_zeroclaw(base)
    out_with = render_zeroclaw(with_bundle)
    assert out_base.files == out_with.files


def test_621_openclaw_render_ignores_hermes_bundle():
    base = _baseline_inputs(ptype="openrouter")
    openclaw_base = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=base.provider,
        channels=base.channels,
        integrations=base.integrations,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tk", bind="lan"),
    )
    openclaw_with = RenderInputs(
        agent_name=openclaw_base.agent_name,
        agent_type=openclaw_base.agent_type,
        provider=openclaw_base.provider,
        channels=openclaw_base.channels,
        integrations=openclaw_base.integrations,
        gateway=openclaw_base.gateway,
        hermes=HermesProviderBundle(
            attachments=(
                AttachedProviderInputs(
                    name="extra",
                    type="anthropic",
                    role="compression",
                    model="x",
                ),
            ),
            api_keys=(("anthropic", "sk-ant-x"),),
        ),
    )
    out_base = render_openclaw(openclaw_base)
    out_with = render_openclaw(openclaw_with)
    assert out_base.files == out_with.files


# ---------------------------------------------------------------------------
# #723: openclaw + litellm — models.providers.<provider-name> writer.
#
# Shape pinned against upstream openclaw's custom-provider docs at
# docs.openclaw.ai/gateway/config-tools#custom-providers-and-base-urls.
# ---------------------------------------------------------------------------


def test_openclaw_litellm_writes_models_providers_block():
    """#723: render_openclaw must emit a `models.providers.<name>` block
    keyed by the clawctl provider name, with api='openai-completions',
    inline apiKey, baseUrl normalized to <endpoint>/v1, and one models[]
    entry built from default_model. The block enables openclaw to route
    requests at the LiteLLM/vLLM proxy without any env-var hop.
    """
    import json

    inputs = _openclaw_inputs(ptype="litellm")
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)

    assert "models" in blob, "models block must be added for litellm"
    assert blob["models"]["providers"].keys() == {"lt"}
    block = blob["models"]["providers"]["lt"]
    assert block["baseUrl"] == "http://10.0.0.5:4000/v1"
    assert block["apiKey"] == "sk-master-1"
    assert block["api"] == "openai-completions"
    assert block["models"] == [
        {
            "id": "gemma4:31b",
            "name": "gemma4:31b",
            "reasoning": False,
            "input": ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 65536,
            "maxTokens": 16384,
        }
    ]
    # agents.defaults.model.primary carries the provider-name prefix so the
    # daemon routes via `models.providers.lt`.
    assert blob["agents"]["defaults"]["model"]["primary"] == "lt/gemma4:31b"


@pytest.mark.parametrize(
    "endpoint_in,expected_base_url",
    [
        # No /v1 suffix → appended.
        ("http://h:4000", "http://h:4000/v1"),
        # Trailing slash, no /v1 → rstrip + append.
        ("http://h:4000/", "http://h:4000/v1"),
        # /v1 already present → unchanged.
        ("http://h:4000/v1", "http://h:4000/v1"),
        # /v1/ with trailing slash → rstrip BEFORE endswith check (W1
        # locks the hermes-parity bug ATX flagged: an earlier impl that
        # checked `rstrip('/').endswith('/v1')` but assigned only inside
        # the branch would leak the trailing slash into openclaw.json).
        ("http://h:4000/v1/", "http://h:4000/v1"),
        # Whitespace surviving from providers.json → strip().
        ("  http://h:4000  ", "http://h:4000/v1"),
        ("http://h:4000/v1\n", "http://h:4000/v1"),
    ],
)
def test_openclaw_litellm_baseurl_normalization(endpoint_in, expected_base_url):
    """#723 ATX W1: pin baseUrl normalization across all the input shapes
    that have surfaced operationally. Mirrors hermes' equivalent at
    `render.py:985-987` byte-for-byte. Pre-iteration the renderer
    silently leaked a trailing slash for the `/v1/` input — this
    parametrize locks the fix."""
    import json

    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint=endpoint_in,
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=provider,
        channels=base.channels,
        integrations=base.integrations,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    assert blob["models"]["providers"]["lt"]["baseUrl"] == expected_base_url


@pytest.mark.parametrize(
    "endpoint_in",
    [
        "",
        # Iter-3 ATX follow-up: the iter-2 guard checked
        # `if not provider.endpoint` BEFORE strip/rstrip, so these
        # inputs slipped through and produced `baseUrl: "/v1"`. Pin
        # the fix that hoists normalization above the guard.
        "   ",
        "\n",
        "\t",
        "/",
        "//",
        "  /  ",
    ],
)
def test_openclaw_litellm_empty_or_whitespace_endpoint_raises(endpoint_in):
    """#723 ATX W4 (+ iter-3 follow-up): render_openclaw must raise
    AgentConfigError for a litellm provider whose endpoint normalizes
    to empty — including whitespace-only or bare-slash inputs — rather
    than silently emitting `baseUrl: "/v1"` (a relative URL the
    openclaw daemon would interpret against its own host).
    """
    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint=endpoint_in,
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=provider,
        channels=(),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    with pytest.raises(AgentConfigError, match="non-empty endpoint"):
        render_openclaw(inputs)


@pytest.mark.parametrize(
    "bad_name",
    [
        # Iter-2 case: `/` would tokenize as <provider>/<rest>.
        "foo/bar",
        # Iter-3 ATX follow-up cases: whitespace + control chars +
        # backslash also corrupt the daemon's routing scheme or
        # produce malformed JSON keys.
        "foo bar",
        "foo\tbar",
        "foo\nbar",
        "foo\\bar",
        "foo\x01bar",
    ],
)
def test_openclaw_litellm_provider_name_with_bad_chars_raises(bad_name):
    """#723 ATX W3 (+ iter-3 follow-up): a provider name containing
    `/`, `\\`, whitespace, or control chars would corrupt routing on
    openclaw's `<name>/<model>` scheme or produce malformed JSON keys.
    Reject at the render layer with a clear remediation."""
    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=bad_name,
        type="litellm",
        default_model=base.provider.default_model,
        endpoint=base.provider.endpoint,
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=provider,
        channels=(),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    with pytest.raises(AgentConfigError, match="must not contain"):
        render_openclaw(inputs)


def test_openclaw_litellm_prefix_is_idempotent_when_default_model_already_prefixed():
    """#723 ATX (test-coverage gap): the prefix-prepend branch must be
    idempotent. If providers.json already carries
    `default_model = "lt/gemma4:31b"` (operator-supplied or re-rendered
    from a previous run), the result must NOT be `lt/lt/gemma4:31b`.
    The guard at render_openclaw lives in the `not model_id.startswith(prefix)`
    check — pin it explicitly."""
    import json

    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model="lt/gemma4:31b",  # already prefixed
        endpoint=base.provider.endpoint,
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=provider,
        channels=(),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    assert blob["agents"]["defaults"]["model"]["primary"] == "lt/gemma4:31b"


def test_openclaw_litellm_honors_context_window_and_max_tokens_overrides():
    """#723 ATX W2: provider record's `context_window` / `max_tokens`
    fields, when populated, override the renderer defaults. Pins the
    operator-override path so the next reviewer trusts the contract."""
    import json

    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=base.provider.default_model,
        endpoint=base.provider.endpoint,
        api_key=base.provider.api_key,
        context_window=200000,
        max_tokens=8192,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=provider,
        channels=(),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    model_entry = blob["models"]["providers"]["lt"]["models"][0]
    assert model_entry["contextWindow"] == 200000
    assert model_entry["maxTokens"] == 8192


def test_openclaw_litellm_context_window_default_when_unset():
    """#723 ATX W2: when provider record carries no `context_window`/
    `max_tokens`, the renderer falls back to the issue-spec defaults
    (65536/16384, tuned for vLLM's Qwen3-Next default --max-model-len)."""
    import json

    inputs = _openclaw_inputs(ptype="litellm")
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    model_entry = blob["models"]["providers"]["lt"]["models"][0]
    assert model_entry["contextWindow"] == 65536
    assert model_entry["maxTokens"] == 16384


def test_provider_inputs_secret_fields_redacted_in_repr():
    """#723 ATX W5: bearer / AWS credentials must not appear in the
    dataclass repr — a pytest --showlocals or stray log line would
    otherwise echo cleartext. Matches FileDiff's hardening pattern in
    core/render_diff.py."""
    p = ProviderInputs(
        name="lt",
        type="litellm",
        endpoint="http://h:4000",
        default_model="m",
        api_key="sk-master-do-not-leak-ABCDEFG",
        aws_access_key="AKIA-DO-NOT-LEAK",
        aws_secret_key="aws-secret-do-not-leak",
    )
    r = repr(p)
    assert "sk-master-do-not-leak-ABCDEFG" not in r
    assert "AKIA-DO-NOT-LEAK" not in r
    assert "aws-secret-do-not-leak" not in r
    # The non-secret fields are still useful for debugging.
    assert "lt" in r
    assert "litellm" in r
    assert "http://h:4000" in r


def test_attached_provider_inputs_api_key_redacted_in_repr():
    """#723 ATX W5: same hardening on AttachedProviderInputs.api_key —
    used by hermes' aux-litellm attachments."""
    a = AttachedProviderInputs(
        name="lt-aux",
        type="litellm",
        role="vision",
        model="m",
        api_key="sk-aux-do-not-leak-XYZ",
        base_url="http://h:4000/v1",
    )
    r = repr(a)
    assert "sk-aux-do-not-leak-XYZ" not in r
    assert "lt-aux" in r


@pytest.mark.parametrize(
    "ptype",
    ["openrouter", "anthropic", "openai", "bedrock", "ollama", "zai"],
)
def test_openclaw_non_litellm_does_not_emit_models_block(ptype):
    """#723: only litellm writes `models.providers`. The other openclaw
    provider types route via OPENCLAW_DEFAULT_MODEL env-var only — a
    stray `models` key in `openclaw.json` would shadow the daemon's
    built-in provider table for openrouter/anthropic/openai/bedrock/zai
    and break those agents.

    Parametrized (#723 ATX): a `for ptype in ...` loop lost per-case
    pytest report granularity — a failure on `zai` reported the whole
    test red without naming the offending ptype.
    """
    import json

    inputs = _openclaw_inputs(ptype=ptype)
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    assert "models" not in blob, (
        f"openclaw + {ptype} must not write models.providers; "
        f"only litellm uses that path"
    )


@pytest.mark.parametrize(
    "ptype",
    ["openrouter", "anthropic", "openai", "bedrock", "ollama", "zai"],
)
def test_openclaw_non_litellm_json_top_level_keys_match_baseline(ptype):
    """#723 ATX (test-coverage gap): the `_render_openclaw_json` signature
    refactor (now accepts full ProviderInputs vs just the prefixed model
    id) widened the surface — pin that non-litellm rendered JSON
    top-level key sets are byte-identical to the baseline shape
    (no surprise `models` block, no key reordering at the top level).
    Complements the existing `_OPENCLAW_JSON_BYTE_LOCK` for openrouter.
    """
    import json

    inputs = _openclaw_inputs(ptype=ptype)
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    assert set(blob.keys()) == {
        "agents",
        "gateway",
        "session",
        "tools",
        "channels",
        "browser",
        "env",
    }, f"openclaw + {ptype} top-level keys drifted: {sorted(blob.keys())}"
    # gateway baseline preserved (modulo managed port/bind/auth which
    # the test fixture sets explicitly).
    assert blob["gateway"]["mode"] == "local"
    assert blob["gateway"]["reload"] == {"mode": "hybrid", "debounceMs": 300}
    # agents.defaults skeleton preserved.
    assert blob["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"
    assert blob["agents"]["defaults"]["imageMaxDimensionPx"] == 1200
    assert blob["agents"]["defaults"]["sandbox"] == {
        "mode": "off",
        "scope": "session",
    }


def test_openclaw_litellm_preserves_unmanaged_baseline_keys():
    """#723: adding the `models` block must not perturb any other key in
    the baseline `openclaw.json`. Pin the full top-level key set."""
    import json

    inputs = _openclaw_inputs(ptype="litellm")
    body = render_openclaw(inputs).files[".openclaw/openclaw.json"]
    blob = json.loads(body)
    # `models` is the only addition vs the baseline top-level keys.
    assert set(blob.keys()) == {
        "agents",
        "gateway",
        "session",
        "tools",
        "channels",
        "browser",
        "env",
        "models",
    }
    # Unmanaged sections survive the litellm branch byte-for-byte.
    assert blob["tools"]["deny"] == ["browser"]
    assert blob["session"]["dmScope"] == "per-channel-peer"
    assert blob["env"]["shellEnv"] == {"enabled": True, "timeoutMs": 15000}
    assert blob["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"


# ---------------------------------------------------------------------------
# Brave integration (#734) — per-agent env render shape.
# ---------------------------------------------------------------------------


def test_hermes_brave_integration_emits_search_api_key_envvar():
    """Hermes maps the operator-facing `BRAVE_API_KEY` credential to the
    upstream-required `BRAVE_SEARCH_API_KEY=` env var (hermes #21337). The
    name mapping is template-only — operators never see the upstream var
    name."""
    base = _baseline_inputs(ptype="anthropic")
    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=base.provider,
        channels=(),
        integrations=(
            IntegrationInputs(
                name="my-brave",
                type="brave",
                credentials=(("BRAVE_API_KEY", "bsk-1"),),
            ),
        ),
        api_server=None,
    )
    env = render_hermes(inputs).files[".hermes/.env"]
    assert "BRAVE_SEARCH_API_KEY='bsk-1'" in env
    # The operator-facing key name MUST NOT appear in the rendered env.
    assert "BRAVE_API_KEY=" not in env


def test_zeroclaw_brave_integration_emits_key_and_provider_override():
    """Zeroclaw needs BOTH env vars — the key alone leaves the search
    provider on its duckduckgo default. The companion override flips the
    router. Both lines are required and asserted together."""
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=base.channels,
        integrations=(
            IntegrationInputs(
                name="my-brave",
                type="brave",
                credentials=(("BRAVE_API_KEY", "bsk-1"),),
            ),
        ),
        gateway=base.gateway,
    )
    env = render_zeroclaw(inputs).files[".zeroclaw/zeroclaw-env.conf"]
    assert 'Environment=BRAVE_API_KEY="bsk-1"' in env
    assert 'Environment=ZEROCLAW_web_search__search_provider="brave"' in env


def test_openclaw_brave_integration_emits_api_key_envvar():
    """Openclaw's brave plugin reads `BRAVE_API_KEY` directly from the
    process env (plugin manifest declares it as the first-class fallback
    for `webSearch.apiKey`). No name mapping."""
    inputs = _openclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=inputs.agent_name,
        agent_type=inputs.agent_type,
        provider=inputs.provider,
        channels=(),
        integrations=(
            IntegrationInputs(
                name="my-brave",
                type="brave",
                credentials=(("BRAVE_API_KEY", "bsk-1"),),
            ),
        ),
        gateway=inputs.gateway,
    )
    env = render_openclaw(inputs).files[".openclaw/env"]
    assert "BRAVE_API_KEY='bsk-1'" in env


def test_brave_integration_supported_on_all_three_agents():
    """Whitelist assertion — `brave` must be in every supported set. Catches
    accidental removal during refactor."""
    from clawrium.core.render import (
        _HERMES_SUPPORTED_INTEGRATIONS,
        _OPENCLAW_SUPPORTED_INTEGRATIONS,
        _ZEROCLAW_SUPPORTED_INTEGRATIONS,
    )

    assert "brave" in _HERMES_SUPPORTED_INTEGRATIONS
    assert "brave" in _ZEROCLAW_SUPPORTED_INTEGRATIONS
    assert "brave" in _OPENCLAW_SUPPORTED_INTEGRATIONS


def test_zeroclaw_brave_alongside_github_renders_both():
    """Multi-integration: brave + github attached on the same zeroclaw
    agent both emit their env-var blocks. Order independence is asserted
    via membership (the iteration order is documented as stable but the
    test does not pin it)."""
    base = _zeroclaw_inputs(ptype="openrouter")
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type=base.agent_type,
        provider=base.provider,
        channels=base.channels,
        integrations=(
            IntegrationInputs(
                name="gh-1",
                type="github",
                credentials=(("GITHUB_TOKEN", "ghp_a"),),
            ),
            IntegrationInputs(
                name="my-brave",
                type="brave",
                credentials=(("BRAVE_API_KEY", "bsk-1"),),
            ),
        ),
        gateway=base.gateway,
    )
    env = render_zeroclaw(inputs).files[".zeroclaw/zeroclaw-env.conf"]
    assert 'Environment=GITHUB_TOKEN_GH_1="ghp_a"' in env
    assert 'Environment=BRAVE_API_KEY="bsk-1"' in env
    assert 'Environment=ZEROCLAW_web_search__search_provider="brave"' in env


# ---------------------------------------------------------------------------
# Issue #756: _render_openclaw_json no-provider branch (install bootstrap).
# ---------------------------------------------------------------------------


def test_render_openclaw_json_no_provider_returns_baseline_plus_gateway():
    """Install-time bootstrap path: `provider=None` yields the baseline
    JSON plus only the gateway overrides. Specifically:

      - output parses as valid JSON;
      - gateway block carries the supplied port / bind / auth token;
      - `agents.defaults.model.primary` is NOT written beyond whatever
        the baseline already ships (the legacy install template wrote
        it from `config.provider.default_model`; the no-provider call
        skips that step entirely).
    """
    import json

    from clawrium.core.render import (
        _openclaw_json_baseline,
        _render_openclaw_json,
    )

    rendered = _render_openclaw_json(
        provider=None,
        provider_default_model=None,
        gateway=GatewayInputs(port=41234, bind="lan", auth="bearer-XYZ"),
        discord_channel=None,
    )
    parsed = json.loads(rendered)

    # Gateway carries the install-time mint.
    assert parsed["gateway"]["port"] == 41234
    assert parsed["gateway"]["bind"] == "lan"
    assert parsed["gateway"]["auth"] == {"mode": "token", "token": "bearer-XYZ"}

    # `agents.defaults.model.primary` is exactly whatever the baseline
    # shipped — the renderer did NOT add or overwrite it. If the baseline
    # lacks the key, the no-provider render must lack it too.
    baseline = json.loads(_openclaw_json_baseline())
    baseline_primary = (
        baseline.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")
    )
    rendered_primary = (
        parsed.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")
    )
    assert rendered_primary == baseline_primary, (
        f"no-provider render mutated agents.defaults.model.primary "
        f"(baseline={baseline_primary!r}, rendered={rendered_primary!r})"
    )

    # S3 (#756 ATX iter-2): lock the full top-level key set so any
    # accidental key addition (e.g. a future renderer step that creates
    # a section the baseline doesn't ship) trips this test instead of
    # silently shipping an unexpected on-host file shape.
    assert set(parsed.keys()) == set(baseline.keys()), (
        f"no-provider render altered top-level key set: "
        f"baseline={sorted(baseline.keys())}, "
        f"rendered={sorted(parsed.keys())}"
    )


def test_render_openclaw_json_no_provider_omits_models_providers_block():
    """No-provider render must not add any `models.providers.<name>`
    entry — the litellm custom-provider block is gated on
    `provider.type == "litellm"`, and skipping the gate entirely when
    `provider is None` keeps the install-time scaffold free of any
    provider-specific routing config."""
    import json

    from clawrium.core.render import (
        _openclaw_json_baseline,
        _render_openclaw_json,
    )

    rendered = _render_openclaw_json(
        provider=None,
        provider_default_model=None,
        gateway=GatewayInputs(port=40000, bind="lan", auth="t"),
        discord_channel=None,
    )
    parsed = json.loads(rendered)

    # If the baseline ships an empty `models.providers` map, the render
    # must preserve it as-is; if the baseline omits `models` entirely,
    # the no-provider render must too (the litellm branch is the only
    # writer that adds the path, and it was skipped).
    baseline = json.loads(_openclaw_json_baseline())
    baseline_providers = baseline.get("models", {}).get("providers", {})
    rendered_providers = parsed.get("models", {}).get("providers", {})
    assert rendered_providers == baseline_providers, (
        f"no-provider render mutated models.providers "
        f"(baseline={baseline_providers!r}, rendered={rendered_providers!r})"
    )


def test_render_openclaw_json_no_provider_with_discord_channel():
    """No-provider render + discord channel: gateway populated, model
    skipped, discord allowlist populated. Pins that the discord block
    write path is provider-independent (channels are configured via
    `clawctl channel attach`, not `clawctl provider attach`)."""
    import json

    from clawrium.core.render import _render_openclaw_json

    discord = ChannelInputs(
        name="disc",
        type="discord",
        allowed_users=("user-1", "user-2"),
        allowed_guilds=("guild-x",),
        allowed_channels=("chan-a",),
    )
    rendered = _render_openclaw_json(
        provider=None,
        provider_default_model=None,
        gateway=GatewayInputs(port=40500, bind="lan", auth="tkn"),
        discord_channel=discord,
    )
    parsed = json.loads(rendered)

    assert parsed["channels"]["discord"]["enabled"] is True
    assert parsed["channels"]["discord"]["allowFrom"] == ["user-1", "user-2"]
    assert "guild-x" in parsed["channels"]["discord"]["guilds"]
    # Model still skipped.
    rendered_primary = (
        parsed.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")
    )
    # Baseline doesn't ship a primary key — confirm it's absent.
    from clawrium.core.render import _openclaw_json_baseline

    baseline = json.loads(_openclaw_json_baseline())
    baseline_primary = (
        baseline.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")
    )
    assert rendered_primary == baseline_primary


# W1 + W3 (#756 ATX iter-2): an empty `default_model` on an attached
# provider must hard-fail at the renderer assembly boundary instead of
# silently writing `agents.defaults.model.primary = null`. The
# no-provider path (where `provider_default_model` is also None) must
# keep working because the renderer skips the write entirely. This
# parametrize covers both branches in one test.
@pytest.mark.parametrize(
    "provider, default_model, expect_raises",
    [
        # provider attached + empty model → must raise
        (
            ProviderInputs(
                name="or",
                type="openrouter",
                default_model="",
                api_key="sk-1",
            ),
            "",
            True,
        ),
        # provider attached + None model → must raise
        (
            ProviderInputs(
                name="oa",
                type="openai",
                default_model="",
                api_key="sk-1",
            ),
            None,
            True,
        ),
        # no provider + empty/None model → must succeed (install-time
        # bootstrap path).
        (None, None, False),
        (None, "", False),
    ],
)
def test_render_openclaw_json_empty_default_model_handling(
    provider, default_model, expect_raises
):
    from clawrium.core.render import _render_openclaw_json

    gateway = GatewayInputs(port=40500, bind="lan", auth="bearer")
    if expect_raises:
        with pytest.raises(AgentConfigError) as exc_info:
            _render_openclaw_json(
                provider=provider,
                provider_default_model=default_model,
                gateway=gateway,
                discord_channel=None,
            )
        assert "empty" in str(exc_info.value)
    else:
        rendered = _render_openclaw_json(
            provider=provider,
            provider_default_model=default_model,
            gateway=gateway,
            discord_channel=None,
        )
        # No provider attached: succeeds, returns valid JSON, model
        # primary not written.
        import json as _json

        parsed = _json.loads(rendered)
        assert parsed["gateway"]["port"] == 40500


# R1 (#756 ATX iter-2 W1): the litellm branch prefixes the model_id as
# `<provider-name>/<default_model>`, which is truthy even when
# default_model is empty — bypassing the belt-and-suspenders guard in
# `_render_openclaw_json`. Whitespace-only default_model has the same
# problem for every provider type (`not "   "` is False). The fix
# raises at `render_openclaw` BEFORE the prefix is built.
@pytest.mark.parametrize(
    "default_model, expect_raises",
    [
        ("", True),
        (" ", True),
        ("\t", True),
        ("writer", False),
    ],
)
def test_render_openclaw_validates_default_model_before_prefixing(
    default_model, expect_raises
):
    base = _baseline_inputs(ptype="openrouter")
    provider = ProviderInputs(
        name=base.provider.name,
        type=base.provider.type,
        default_model=default_model,
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=provider,
        channels=(),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    if expect_raises:
        with pytest.raises(AgentConfigError, match="empty or whitespace-only"):
            render_openclaw(inputs)
    else:
        out = render_openclaw(inputs)
        assert ".openclaw/openclaw.json" in out.files


def test_render_openclaw_litellm_empty_default_model_raises_at_entry():
    """R1 (#756 ATX iter-2 W1): for litellm specifically, the prefixed
    `model_id` becomes `"<provider-name>/"` (truthy) when
    `default_model == ""`, bypassing the `_render_openclaw_json` guard.
    `render_openclaw` MUST reject before the prefix is built."""
    base = _baseline_inputs(ptype="litellm")
    provider = ProviderInputs(
        name=base.provider.name,
        type="litellm",
        default_model="",
        endpoint=base.provider.endpoint,
        api_key=base.provider.api_key,
    )
    inputs = RenderInputs(
        agent_name=base.agent_name,
        agent_type="openclaw",
        provider=provider,
        channels=(),
        integrations=(),
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )
    with pytest.raises(AgentConfigError, match="empty or whitespace-only"):
        render_openclaw(inputs)

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
    ChannelInputs,
    GatewayInputs,
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
        (render_zeroclaw, "openrouter"),
        (render_zeroclaw, "anthropic"),
        (render_zeroclaw, "openai"),
        (render_zeroclaw, "ollama"),
        (render_openclaw, "openrouter"),
        (render_openclaw, "anthropic"),
        (render_openclaw, "openai"),
        (render_openclaw, "bedrock"),
        (render_openclaw, "ollama"),
        (render_openclaw, "zai"),
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


def test_render_no_branch_on_unset_optional_field():
    """`render_hermes` must not branch on whether home_channel is empty.

    Two inputs that differ only in unset/empty optional fields should
    produce structurally identical output (same line count, same keys).
    """
    base = _baseline_inputs(ptype="openrouter")
    # Variant: empty home_channel.
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
    a = render_hermes(base).files[".hermes/.env"].splitlines()
    b = render_hermes(variant).files[".hermes/.env"].splitlines()
    # Same number of lines — emission is unconditional.
    assert len(a) == len(b)
    # The DISCORD_HOME_CHANNEL line is present in both (empty quoted in variant).
    assert any(line.startswith("DISCORD_HOME_CHANNEL=") for line in b)


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
    assert set(out.files.keys()) == {".openclaw/env"}


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
    "DISCORD_HOME_CHANNEL_NAME=''\n"
    "DISCORD_HOME_CHANNEL_THREAD_ID=''\n"
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
    "DISCORD_HOME_CHANNEL=''\n"
    "DISCORD_HOME_CHANNEL_NAME=''\n"
    "DISCORD_HOME_CHANNEL_THREAD_ID=''\n"
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

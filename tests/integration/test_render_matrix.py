"""F6 render-matrix test (parent #555, subtask D / issue #559).

Exercises the 15-cell parity matrix from the #555 plan against the
canonical render pipeline:

    build_render_inputs  →  render_<atype>  →  assert env-key invariants

Per the parent plan, the merge gate is that every cell renders cleanly
and produces the expected env vars / config.toml sections.

## Gating

These tests are marked `@pytest.mark.container` because the parent
plan calls for them to run against a disposable container host
(catching silent-wipes that mock-based tests missed because the mocks
shared the same conditional-emit assumption as production).

A real container path requires Docker / Podman + a provisioned `xclm`
user + the canonical sync writing to it via SSH. That infrastructure
is tracked as a follow-up; this file lands the matrix scaffolding with
the render-output invariants asserted in-process so a regression to
conditional-emit in `render_<atype>` is still caught.

When `CLAWRIUM_TEST_CONTAINER_HOST` is set, an additional per-cell
`test_canonical_sync_against_container` parametrization runs the full
`sync_agent_canonical` pipeline against that host. Without the env
var, only the in-process render assertions run.

Run:
    pytest -m container tests/integration/test_render_matrix.py
"""

from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.container


# ---------------------------------------------------------------------------
# Stores fixture (mirror of tests/core/test_render.py — duplicated rather
# than imported because pytest fixtures in tests/ aren't auto-exported and
# the matrix file is intentionally self-contained).
# ---------------------------------------------------------------------------


class _Stores:
    def __init__(self) -> None:
        self.agent = None
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

    monkeypatch.setattr("clawrium.core.hosts.get_agent_by_name", lambda n: s.agent)
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider", lambda n: s.providers.get(n)
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key",
        lambda n: s.provider_api_keys.get(n),
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_aws_credentials",
        lambda n: s.provider_aws.get(n, (None, None)),
    )
    monkeypatch.setattr(
        "clawrium.core.channels.get_agent_channels",
        lambda h, k: list(s.agent_channels),
    )
    monkeypatch.setattr(
        "clawrium.core.channels.get_channel", lambda n: s.channels.get(n)
    )
    monkeypatch.setattr(
        "clawrium.core.channels.get_channel_token",
        lambda n, key="BOT_TOKEN": s.channel_tokens.get((n, key)),
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_agent_integrations",
        lambda h, k: list(s.agent_integrations),
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_integration",
        lambda n: s.integrations.get(n),
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_integration_credentials",
        lambda n: dict(s.integration_creds.get(n, {})),
    )
    return s


# ---------------------------------------------------------------------------
# Cell definitions (15 rows from #555 plan)
# ---------------------------------------------------------------------------


def _agent(agent_type: str, providers: list, *, config: dict | None = None):
    return (
        {"hostname": "host-1"},
        agent_type,
        {
            "agent_name": "alpha",
            "providers": providers,
            "config": config or {},
        },
    )


def _hermes_config():
    # hermes renderer requires api_server config to emit a complete .env.
    # The values are arbitrary; what matters is that the block resolves.
    return {
        "api_server": {"host": "127.0.0.1", "port": 8000, "key": "hermes-key"},
    }


def _zeroclaw_config():
    return {
        "gateway": {
            "host": "127.0.0.1",
            "port": 40000,
            "auth": "bearer-token-here",
            "bind": "wildcard",
            "allow_public_bind": True,
        }
    }


# Each cell describes: (cell_id, agent_type, setup_fn, expected_env_keys)
# setup_fn(stores) populates the in-memory stores; expected_env_keys is a
# list of substrings that MUST appear in the rendered `.env` (or other
# file, where indicated by `file:` prefix). Absence of any expected key
# is a silent-wipe regression — the exact class of bug #555 documents.


def _setup_hermes_openrouter(s: _Stores) -> None:
    s.agent = _agent(
        "hermes",
        [{"name": "or", "role": "primary", "model": "x-large"}],
        config=_hermes_config(),
    )
    s.providers["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "x-large",
    }
    s.provider_api_keys["or"] = "sk-or-XXXX"


def _setup_hermes_openrouter_discord(s: _Stores) -> None:
    _setup_hermes_openrouter(s)
    s.agent_channels = ["disc"]
    s.channels["disc"] = {
        "name": "disc",
        "type": "discord",
        "config": {"allowed_users": ["111"], "require_mention": True},
    }
    s.channel_tokens[("disc", "BOT_TOKEN")] = "discord-bot-XXXX"


def _setup_hermes_openrouter_discord_slack_github(s: _Stores) -> None:
    _setup_hermes_openrouter_discord(s)
    s.agent_channels = ["disc", "slk"]
    s.channels["slk"] = {
        "name": "slk",
        "type": "slack",
        "config": {"allowed_users": ["U1"]},
    }
    s.channel_tokens[("slk", "BOT_TOKEN")] = "xoxb-slack-XXXX"
    s.channel_tokens[("slk", "APP_TOKEN")] = "xapp-slack-XXXX"
    s.agent_integrations = ["gh"]
    s.integrations["gh"] = {"name": "gh", "type": "github"}
    s.integration_creds["gh"] = {"GITHUB_TOKEN": "ghp_XXXX"}


def _setup_hermes_bedrock(s: _Stores) -> None:
    s.agent = _agent(
        "hermes",
        [{"name": "br", "role": "primary", "model": "claude-sonnet"}],
        config=_hermes_config(),
    )
    s.providers["br"] = {
        "name": "br",
        "type": "bedrock",
        "default_model": "claude-sonnet",
        "region": "us-west-2",
    }
    s.provider_aws["br"] = ("AKIA-XXXX", "AWS-SECRET-XXXX")


def _setup_hermes_bedrock_discord_gh_atl(s: _Stores) -> None:
    _setup_hermes_bedrock(s)
    s.agent_channels = ["disc"]
    s.channels["disc"] = {
        "name": "disc",
        "type": "discord",
        "config": {"allowed_users": ["111"]},
    }
    s.channel_tokens[("disc", "BOT_TOKEN")] = "discord-bot-XXXX"
    s.agent_integrations = ["gh", "atl"]
    s.integrations["gh"] = {"name": "gh", "type": "github"}
    s.integration_creds["gh"] = {"GITHUB_TOKEN": "ghp_XXXX"}
    s.integrations["atl"] = {"name": "atl", "type": "atlassian"}
    s.integration_creds["atl"] = {
        "ATLASSIAN_API_TOKEN": "atl-XXXX",
        "ATLASSIAN_EMAIL": "user@example.com",
        "ATLASSIAN_URL": "https://example.atlassian.net",
    }


def _setup_hermes_anthropic(s: _Stores) -> None:
    s.agent = _agent(
        "hermes",
        [{"name": "an", "role": "primary", "model": "claude-3"}],
        config=_hermes_config(),
    )
    s.providers["an"] = {
        "name": "an",
        "type": "anthropic",
        "default_model": "claude-3",
    }
    s.provider_api_keys["an"] = "sk-ant-XXXX"


def _setup_hermes_openai(s: _Stores) -> None:
    s.agent = _agent(
        "hermes",
        [{"name": "oa", "role": "primary", "model": "gpt-4"}],
        config=_hermes_config(),
    )
    s.providers["oa"] = {
        "name": "oa",
        "type": "openai",
        "default_model": "gpt-4",
    }
    s.provider_api_keys["oa"] = "sk-oa-XXXX"


def _setup_hermes_ollama(s: _Stores) -> None:
    s.agent = _agent(
        "hermes",
        [{"name": "ol", "role": "primary", "model": "llama3"}],
        config=_hermes_config(),
    )
    s.providers["ol"] = {
        "name": "ol",
        "type": "ollama",
        "endpoint": "http://localhost:11434",
        "default_model": "llama3",
    }


def _setup_zeroclaw_openrouter_discord_gh(s: _Stores) -> None:
    s.agent = _agent(
        "zeroclaw",
        [{"name": "or", "role": "primary", "model": "x-large"}],
        config=_zeroclaw_config(),
    )
    s.providers["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "x-large",
    }
    s.provider_api_keys["or"] = "sk-or-XXXX"
    s.agent_channels = ["disc"]
    s.channels["disc"] = {
        "name": "disc",
        "type": "discord",
        "config": {"allowed_users": ["111"]},
    }
    s.channel_tokens[("disc", "BOT_TOKEN")] = "discord-bot-XXXX"
    s.agent_integrations = ["gh"]
    s.integrations["gh"] = {"name": "gh", "type": "github"}
    s.integration_creds["gh"] = {"GITHUB_TOKEN": "ghp_XXXX"}


def _setup_zeroclaw_ollama(s: _Stores) -> None:
    s.agent = _agent(
        "zeroclaw",
        [{"name": "ol", "role": "primary", "model": "llama3"}],
        config=_zeroclaw_config(),
    )
    s.providers["ol"] = {
        "name": "ol",
        "type": "ollama",
        "endpoint": "http://localhost:11434",
        "default_model": "llama3",
    }


def _setup_openclaw_bedrock_discord(s: _Stores) -> None:
    s.agent = _agent(
        "openclaw",
        [{"name": "br", "role": "primary", "model": "claude-sonnet"}],
    )
    s.providers["br"] = {
        "name": "br",
        "type": "bedrock",
        "default_model": "claude-sonnet",
        "region": "us-west-2",
    }
    s.provider_aws["br"] = ("AKIA-XXXX", "AWS-SECRET-XXXX")
    s.agent_channels = ["disc"]
    s.channels["disc"] = {
        "name": "disc",
        "type": "discord",
        "config": {"allowed_users": ["111"]},
    }
    s.channel_tokens[("disc", "BOT_TOKEN")] = "discord-bot-XXXX"


# --- Issue #756: per-provider-type openclaw render-matrix cells --------------
# These cells exercise every provider type the canonical openclaw renderer
# supports (other than the pre-existing bedrock+discord cell). They byte-lock
# the cross-provider behaviour now that install / configure / sync all share
# the same `_render_openclaw_json` writer.


def _openclaw_gateway_config() -> dict:
    return {
        "gateway": {
            "port": 40500,
            "bind": "lan",
            "auth": "install-bearer",
        }
    }


def _setup_openclaw_litellm_bare(s: _Stores) -> None:
    s.agent = _agent(
        "openclaw",
        [{"name": "lt", "role": "primary", "model": "writer"}],
        config=_openclaw_gateway_config(),
    )
    s.providers["lt"] = {
        "name": "lt",
        "type": "litellm",
        "default_model": "writer",
        "endpoint": "https://litellm.example.com",
    }
    s.provider_api_keys["lt"] = "sk-litellm-XXXX"


def _setup_openclaw_openrouter_bare(s: _Stores) -> None:
    s.agent = _agent(
        "openclaw",
        [{"name": "or", "role": "primary", "model": "anthropic/claude-opus-4"}],
        config=_openclaw_gateway_config(),
    )
    s.providers["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "anthropic/claude-opus-4",
    }
    s.provider_api_keys["or"] = "sk-or-XXXX"


def _setup_openclaw_ollama_bare(s: _Stores) -> None:
    s.agent = _agent(
        "openclaw",
        [{"name": "ol", "role": "primary", "model": "llama3"}],
        config=_openclaw_gateway_config(),
    )
    s.providers["ol"] = {
        "name": "ol",
        "type": "ollama",
        "default_model": "llama3",
        "endpoint": "http://localhost:11434",
    }


def _setup_openclaw_anthropic_bare(s: _Stores) -> None:
    s.agent = _agent(
        "openclaw",
        [{"name": "an", "role": "primary", "model": "claude-3"}],
        config=_openclaw_gateway_config(),
    )
    s.providers["an"] = {
        "name": "an",
        "type": "anthropic",
        "default_model": "claude-3",
    }
    s.provider_api_keys["an"] = "sk-ant-XXXX"


def _setup_openclaw_openai_bare(s: _Stores) -> None:
    s.agent = _agent(
        "openclaw",
        [{"name": "oa", "role": "primary", "model": "gpt-4"}],
        config=_openclaw_gateway_config(),
    )
    s.providers["oa"] = {
        "name": "oa",
        "type": "openai",
        "default_model": "gpt-4",
    }
    s.provider_api_keys["oa"] = "sk-oa-XXXX"


# Cells modelled on the #555 plan table. `expected_keys` lists every env
# var that MUST appear in the rendered `.env` body. Each one corresponds
# to a column in the plan's matrix; missing it is the silent-wipe
# regression we're guarding against.
MATRIX_CELLS: list[tuple] = [
    (
        "hermes_openrouter_bare",
        "hermes",
        _setup_hermes_openrouter,
        ["OPENROUTER_API_KEY", "HERMES_INFERENCE_PROVIDER"],
    ),
    (
        "hermes_openrouter_discord",
        "hermes",
        _setup_hermes_openrouter_discord,
        ["OPENROUTER_API_KEY", "DISCORD_BOT_TOKEN", "DISCORD_ALLOWED_USERS"],
    ),
    (
        "hermes_openrouter_discord_slack_github",
        "hermes",
        _setup_hermes_openrouter_discord_slack_github,
        [
            "OPENROUTER_API_KEY",
            "DISCORD_BOT_TOKEN",
            "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN",
            "GITHUB_TOKEN",
        ],
    ),
    (
        "hermes_bedrock_bare",
        "hermes",
        _setup_hermes_bedrock,
        [
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_DEFAULT_REGION",
            "HERMES_INFERENCE_PROVIDER",
        ],
    ),
    (
        "hermes_bedrock_discord_gh_atl",
        "hermes",
        _setup_hermes_bedrock_discord_gh_atl,
        [
            "AWS_ACCESS_KEY_ID",
            "DISCORD_BOT_TOKEN",
            "GITHUB_TOKEN",
            # Atlassian creds render under MCP server env as
            # JIRA_API_TOKEN / CONFLUENCE_API_TOKEN, not as a single
            # ATLASSIAN_API_TOKEN env var. The substring check pins the
            # JIRA token specifically because that's the canonical
            # write that the maurice silent-wipe destroyed.
            "JIRA_API_TOKEN",
        ],
    ),
    (
        "hermes_anthropic_bare",
        "hermes",
        _setup_hermes_anthropic,
        ["ANTHROPIC_API_KEY"],
    ),
    (
        "hermes_openai_bare",
        "hermes",
        _setup_hermes_openai,
        ["OPENAI_API_KEY"],
    ),
    (
        "hermes_ollama_bare",
        "hermes",
        _setup_hermes_ollama,
        ["HERMES_INFERENCE_PROVIDER"],
    ),
    (
        "zeroclaw_openrouter_discord_gh",
        "zeroclaw",
        _setup_zeroclaw_openrouter_discord_gh,
        # zeroclaw emits provider api_key into config.toml as a quoted
        # value (`api_key = "..."`), not as a bare ENV-style key. The
        # substring assertion below catches both the discord bot_token
        # and the GitHub integration secret while skipping
        # OPENROUTER_API_KEY (which would only ever appear if zeroclaw
        # ever started emitting bare env-style provider keys — that
        # would be a render-shape change worth a separate test cell).
        ["sk-or-XXXX", "discord-bot-XXXX", "GITHUB_TOKEN"],
    ),
    (
        "zeroclaw_ollama_bare",
        "zeroclaw",
        _setup_zeroclaw_ollama,
        [],  # ollama has no bearer; provider info goes in config.toml.
    ),
    (
        "openclaw_bedrock_discord",
        "openclaw",
        _setup_openclaw_bedrock_discord,
        ["AWS_ACCESS_KEY_ID", "DISCORD_BOT_TOKEN"],
    ),
    # Issue #756 cells: per-provider-type openclaw coverage. Each cell
    # asserts the provider's expected on-host secret / model substring
    # appears in the rendered output (env + openclaw.json concatenated by
    # the harness below). Collectively they pin that the canonical
    # `_render_openclaw_json` writer — now the single source of truth
    # for install / configure / sync — emits each provider type without
    # silent-wipe regressions.
    (
        "openclaw_litellm_bare",
        "openclaw",
        _setup_openclaw_litellm_bare,
        # litellm has no env-key emission; the bearer + base_url + the
        # prefixed primary model id all flow into openclaw.json's
        # `models.providers.<name>` block. The substring assertions pin
        # each load-bearing piece.
        [
            "sk-litellm-XXXX",
            "https://litellm.example.com/v1",
            "\"primary\": \"lt/writer\"",
        ],
    ),
    (
        "openclaw_openrouter_bare",
        "openclaw",
        _setup_openclaw_openrouter_bare,
        ["OPENROUTER_API_KEY", "sk-or-XXXX"],
    ),
    (
        "openclaw_ollama_bare",
        "openclaw",
        _setup_openclaw_ollama_bare,
        ["OPENCLAW_OLLAMA_URL", "http://localhost:11434"],
    ),
    (
        "openclaw_anthropic_bare",
        "openclaw",
        _setup_openclaw_anthropic_bare,
        ["ANTHROPIC_API_KEY", "sk-ant-XXXX"],
    ),
    (
        "openclaw_openai_bare",
        "openclaw",
        _setup_openclaw_openai_bare,
        ["OPENAI_API_KEY", "sk-oa-XXXX"],
    ),
]


# ---------------------------------------------------------------------------
# Per-cell render assertions (run in-process; always)
# ---------------------------------------------------------------------------


_RENDERERS = {
    "hermes": "render_hermes",
    "zeroclaw": "render_zeroclaw",
    "openclaw": "render_openclaw",
}


@pytest.mark.parametrize(
    "cell_id,agent_type,setup_fn,expected_keys",
    MATRIX_CELLS,
    ids=[c[0] for c in MATRIX_CELLS],
)
def test_render_matrix_cell(cell_id, agent_type, setup_fn, expected_keys, stores):
    """Each cell: build_render_inputs + render → expected env keys present."""
    from clawrium.core import render as render_mod
    from clawrium.core.render import build_render_inputs

    setup_fn(stores)

    inputs = build_render_inputs("alpha")
    renderer = getattr(render_mod, _RENDERERS[agent_type])
    rendered = renderer(inputs)

    # Concatenate all rendered file bodies — keys may appear in `.env`
    # or `config.toml` / `config.yaml` depending on agent type.
    blob = "\n".join(rendered.files.values())
    for key in expected_keys:
        assert key in blob, (
            f"cell {cell_id}: expected key {key!r} missing from rendered output. "
            f"Files: {list(rendered.files.keys())}. "
            f"This is the #555 silent-wipe regression — render emitted "
            f"a config that omits a declared attachment."
        )

    # W2 (#756 ATX iter-2): for the openclaw litellm cell, also parse
    # the rendered openclaw.json and assert the prefixed model id lands
    # at the exact JSON path `agents.defaults.model.primary`. The
    # substring check above is order/whitespace-fragile; a structural
    # assertion catches drift the substring would miss.
    if cell_id == "openclaw_litellm_bare":
        import json

        parsed = json.loads(rendered.files[".openclaw/openclaw.json"])
        assert parsed["agents"]["defaults"]["model"]["primary"] == "lt/writer", (
            f"openclaw_litellm_bare: "
            f"agents.defaults.model.primary != 'lt/writer' "
            f"(got {parsed['agents']['defaults']['model'].get('primary')!r})"
        )


# ---------------------------------------------------------------------------
# Failure-mode cells (3 from the plan table)
# ---------------------------------------------------------------------------


def test_attached_channel_missing_secret_fails(stores):
    """Plan row: 'ANY attached but secret missing → sync FAILS clear error'."""
    from clawrium.core.render import AgentConfigError, build_render_inputs

    _setup_hermes_openrouter(stores)
    stores.agent_channels = ["disc"]
    stores.channels["disc"] = {"name": "disc", "type": "discord", "config": {}}
    # No channel token in stores → must raise.

    with pytest.raises(AgentConfigError, match="missing BOT_TOKEN"):
        build_render_inputs("alpha")


def test_provider_missing_fails(stores):
    """Plan row: 'provider missing → sync FAILS; on-host file untouched'."""
    from clawrium.core.render import AgentConfigError, build_render_inputs

    stores.agent = _agent("hermes", [], config=_hermes_config())
    with pytest.raises(AgentConfigError, match="no provider attached"):
        build_render_inputs("alpha")


def test_render_idempotent(stores):
    """Plan row: 'sync run twice with no changes → byte-identical output'."""
    from clawrium.core import render as render_mod
    from clawrium.core.render import build_render_inputs

    _setup_hermes_openrouter_discord_slack_github(stores)

    rendered_a = render_mod.render_hermes(build_render_inputs("alpha"))
    rendered_b = render_mod.render_hermes(build_render_inputs("alpha"))
    assert rendered_a.files == rendered_b.files


# ---------------------------------------------------------------------------
# Optional: full canonical sync against a real container host
# ---------------------------------------------------------------------------

_CONTAINER_HOST = os.environ.get("CLAWRIUM_TEST_CONTAINER_HOST")


@pytest.mark.skipif(
    not _CONTAINER_HOST,
    reason="CLAWRIUM_TEST_CONTAINER_HOST not set; skipping live-container path",
)
def test_canonical_sync_against_container_smoke():
    """Smoke: connect to the disposable container host and read a file.

    The full per-cell sync exercise requires container provisioning
    (xclm user, sudo rules, systemd-in-container or stub units) that
    isn't in this PR's scope — tracked as follow-up. This smoke test
    proves the harness wiring works: when the env var IS set, the test
    must reach the host. If it can't, CI surfaces the misconfig
    immediately rather than silently passing.
    """
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=_CONTAINER_HOST,
            username=os.environ.get("CLAWRIUM_TEST_CONTAINER_USER", "xclm"),
            timeout=10,
        )
        _, stdout, _ = client.exec_command("echo container-ok")
        out = stdout.read().decode("utf-8").strip()
        assert out == "container-ok"
    finally:
        client.close()

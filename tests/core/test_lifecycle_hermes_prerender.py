"""Tests for the #622 hermes prerender block in lifecycle.configure_agent.

Validates that `configure_agent` for hermes pre-renders config + env via
`render_hermes` and surfaces the bytes through `ansible_vars` so the
configure playbook can `copy: content:` them. Closes the loop the legacy
ansible templates left open (multi-provider attachments dropped on the
configure path).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clawrium.core import lifecycle
from clawrium.core.render import build_render_inputs, render_hermes


# ---------------------------------------------------------------------------
# Fixture: stub every collaborator configure_agent reaches between argv
# unpacking and the prerender block. Reuses the same monkeypatch surface
# as tests/core/test_render.py so render_hermes itself runs unstubbed.
# ---------------------------------------------------------------------------


@pytest.fixture
def hermes_configure_env(monkeypatch, tmp_path):
    captured = {}

    # 1. Host + agent lookup (lifecycle.get_host, _resolve_agent_record).
    host = {
        "hostname": "host-1",
        "user": "xclm",
        "port": 22,
        "key_id": "host-1",
        "agents": {
            "alpha": {
                "type": "hermes",
                "agent_name": "alpha",
                "providers": [],
                "config": {
                    "api_server": {
                        "host": "127.0.0.1",
                        "port": 8642,
                        "key": "a" * 64,
                    },
                },
            }
        },
    }
    monkeypatch.setattr(lifecycle, "get_host", lambda _h: host)

    # 2. SSH key resolution.
    fake_key = tmp_path / "id_rsa"
    fake_key.write_text("PRIVATE")
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _k: fake_key)

    # 3. Instance secrets — used to hydrate HERMES_API_SERVER_KEY.
    # Tests that need a different shape monkeypatch this in their body.
    monkeypatch.setattr(
        lifecycle,
        "get_instance_secrets",
        lambda _k: {"HERMES_API_SERVER_KEY": {"value": "a" * 64}},
    )

    # 4. Agent integrations / channels — return empty.
    monkeypatch.setattr(
        "clawrium.core.integrations.get_agent_integrations",
        lambda *_a, **_kw: [],
    )

    # 5. Replace ansible_runner.run with a recorder.
    def _record(**kwargs):
        captured["inventory"] = kwargs.get("inventory")
        captured["playbook"] = kwargs.get("playbook")
        return SimpleNamespace(status="successful", rc=0, stats=None)

    monkeypatch.setattr(lifecycle.ansible_runner, "run", MagicMock(side_effect=_record))

    # 6. update_host: configure_agent calls this after the ansible push to
    # persist post-run state (gateway tokens, etc.). Returning True keeps
    # configure_agent on the success path; we don't care about the dict
    # mutations for the prerender-shape assertions in this file.
    monkeypatch.setattr(lifecycle, "update_host", lambda *_a, **_kw: True)

    return SimpleNamespace(host=host, captured=captured, tmp_path=tmp_path)


# ---------------------------------------------------------------------------
# Render-input fixture — uses the same `_Stores` shape as test_render.py.
# ---------------------------------------------------------------------------


@pytest.fixture
def render_stores(monkeypatch):
    """Stub the same set of collaborators build_render_inputs touches."""
    state = {
        "agent": None,
        "providers": {},
        "provider_api_keys": {},
        "provider_aws": {},
        "channels": {},
        "channel_tokens": {},
        "integrations": {},
        "integration_creds": {},
        "agent_channels": [],
        "agent_integrations": [],
    }

    monkeypatch.setattr(
        "clawrium.core.hosts.get_agent_by_name",
        lambda _n: state["agent"],
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider",
        lambda n: state["providers"].get(n),
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key",
        lambda n: state["provider_api_keys"].get(n),
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_aws_credentials",
        lambda n: state["provider_aws"].get(n, (None, None)),
    )
    monkeypatch.setattr(
        "clawrium.core.channels.get_agent_channels",
        lambda *_a: list(state["agent_channels"]),
    )
    monkeypatch.setattr(
        "clawrium.core.channels.get_channel",
        lambda n: state["channels"].get(n),
    )
    monkeypatch.setattr(
        "clawrium.core.channels.get_channel_token",
        lambda n, key="BOT_TOKEN": state["channel_tokens"].get((n, key)),
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_agent_integrations",
        lambda *_a: list(state["agent_integrations"]),
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_integration",
        lambda n: state["integrations"].get(n),
    )
    monkeypatch.setattr(
        "clawrium.core.integrations.get_integration_credentials",
        lambda n: dict(state["integration_creds"].get(n, {})),
    )
    return state


def _hermes_agent_record(providers: list) -> tuple[dict, str, dict]:
    return (
        {"hostname": "host-1"},
        "hermes",
        {
            "agent_name": "alpha",
            "providers": providers,
            "config": {
                "api_server": {
                    "host": "127.0.0.1",
                    "port": 8642,
                    "key": "a" * 64,
                },
            },
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_configure_agent_single_provider_byte_identical_to_render_hermes(
    hermes_configure_env, render_stores
):
    """Configure_agent for single-provider hermes must produce the same
    config.yaml / .env bytes as a direct render_hermes call. Pins the
    invariant that the configure path delegates rendering to the canonical
    renderer and does not drift."""
    render_stores["agent"] = _hermes_agent_record(
        [{"name": "or", "role": "primary", "model": "model-x"}]
    )
    render_stores["providers"]["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "model-x",
    }
    render_stores["provider_api_keys"]["or"] = "sk-or-1"

    # Update the agent record on the host dict too (configure_agent reads
    # this independently of build_render_inputs).
    hermes_configure_env.host["agents"]["alpha"]["providers"] = [
        {"name": "or", "role": "primary", "model": "model-x"}
    ]

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert ok, f"configure_agent failed: {err}"

    inv = hermes_configure_env.captured["inventory"]
    rendered_yaml = inv["all"]["vars"]["prerendered_hermes_config_yaml"]
    rendered_env = inv["all"]["vars"]["prerendered_hermes_env"]

    expected = render_hermes(build_render_inputs("alpha"))
    assert rendered_yaml == expected.files[".hermes/config.yaml"]
    assert rendered_env == expected.files[".hermes/.env"]


def test_configure_agent_multi_provider_emits_auxiliary_blocks(
    hermes_configure_env, render_stores
):
    """Primary openrouter + aux bedrock attachment produces a config.yaml
    with one `auxiliary.<role>:` block per non-primary attachment, and a
    .env carrying the primary bearer key alongside the bedrock AWS
    triple. This is the customer outcome of #622."""
    attachments = [
        {"name": "or", "role": "primary", "model": "primary-model"},
        {
            "name": "br",
            "role": "compression",
            "model": "bedrock-model",
        },
    ]
    render_stores["agent"] = _hermes_agent_record(attachments)
    render_stores["providers"]["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "primary-model",
    }
    render_stores["providers"]["br"] = {
        "name": "br",
        "type": "bedrock",
        "default_model": "bedrock-model",
        "region": "us-east-1",
    }
    render_stores["provider_api_keys"]["or"] = "sk-or-1"
    render_stores["provider_aws"]["br"] = ("AKIA-AAA", "secret-bbb")

    hermes_configure_env.host["agents"]["alpha"]["providers"] = attachments

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "primary-model",
            },
            "providers": attachments,
            "api_server": {
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert ok, f"configure_agent failed: {err}"

    inv = hermes_configure_env.captured["inventory"]
    yaml_body = inv["all"]["vars"]["prerendered_hermes_config_yaml"]
    env_body = inv["all"]["vars"]["prerendered_hermes_env"]

    # Aux block must appear in the yaml.
    assert "auxiliary:" in yaml_body
    assert "compression:" in yaml_body
    assert 'provider: "bedrock"' in yaml_body

    # Env must carry both the primary OPENROUTER_API_KEY and the
    # AWS triple from the bedrock aux attachment, with the exact values
    # the fixture provided (ATX iter-1 W10: blank-value would pass a
    # bare-key substring check).
    assert "OPENROUTER_API_KEY='sk-or-1'" in env_body
    assert "AWS_ACCESS_KEY_ID='AKIA-AAA'" in env_body
    assert "AWS_SECRET_ACCESS_KEY='secret-bbb'" in env_body
    assert "AWS_DEFAULT_REGION='us-east-1'" in env_body


def test_configure_agent_hermes_render_error_surfaces_cleanly(
    hermes_configure_env, render_stores
):
    """AgentConfigError from build_render_inputs / render_hermes (e.g.
    same-type provider with conflicting keys) must surface as a clean
    (False, error_message) return — nothing pushed to the host."""
    # Two openrouter attachments with different API keys → conflict.
    attachments = [
        {"name": "or-a", "role": "primary", "model": "model-a"},
        {"name": "or-b", "role": "compression", "model": "model-b"},
    ]
    render_stores["agent"] = _hermes_agent_record(attachments)
    render_stores["providers"]["or-a"] = {
        "name": "or-a",
        "type": "openrouter",
        "default_model": "model-a",
    }
    render_stores["providers"]["or-b"] = {
        "name": "or-b",
        "type": "openrouter",
        "default_model": "model-b",
    }
    render_stores["provider_api_keys"]["or-a"] = "sk-aaa"
    render_stores["provider_api_keys"]["or-b"] = "sk-bbb"  # different key

    hermes_configure_env.host["agents"]["alpha"]["providers"] = attachments

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or-a",
                "type": "openrouter",
                "default_model": "model-a",
            },
            "providers": attachments,
            "api_server": {
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert not ok
    assert err is not None
    assert "Hermes render failed" in err
    # Ansible-runner.run must not have been invoked — failure is at
    # assembly time, before any push.
    assert "inventory" not in hermes_configure_env.captured


# ---------------------------------------------------------------------------
# ATX iter-1 follow-ups: missing/malformed HERMES_API_SERVER_KEY (B3, W12)
# and non-AgentConfigError render failures (B1).
# ---------------------------------------------------------------------------


def _seed_single_provider(render_stores, hermes_configure_env):
    """Seed a minimal valid single-provider hermes record across both
    fixtures so tests below can focus on the failure mode under test."""
    attachments = [{"name": "or", "role": "primary", "model": "model-x"}]
    render_stores["agent"] = _hermes_agent_record(attachments)
    render_stores["providers"]["or"] = {
        "name": "or",
        "type": "openrouter",
        "default_model": "model-x",
    }
    render_stores["provider_api_keys"]["or"] = "sk-or-1"
    hermes_configure_env.host["agents"]["alpha"]["providers"] = attachments


def test_configure_agent_missing_hermes_api_server_key_returns_error(
    hermes_configure_env, render_stores, monkeypatch
):
    """ATX iter-1 B3 / regression of deleted
    test_hermes_without_persisted_key_returns_error: when secrets.json
    has no HERMES_API_SERVER_KEY entry, configure_agent must return
    (False, msg) naming the missing key and must not invoke
    ansible_runner.run."""
    _seed_single_provider(render_stores, hermes_configure_env)
    monkeypatch.setattr(lifecycle, "get_instance_secrets", lambda _k: {})

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert not ok
    assert err is not None
    assert "HERMES_API_SERVER_KEY" in err
    assert "inventory" not in hermes_configure_env.captured


def test_configure_agent_malformed_hermes_api_server_key_returns_error(
    hermes_configure_env, render_stores, monkeypatch
):
    """ATX iter-1 W12 / regression of deleted malformed-key test: a
    HERMES_API_SERVER_KEY entry missing the 'value' field falls through
    to the validity check and surfaces the same actionable error."""
    _seed_single_provider(render_stores, hermes_configure_env)
    monkeypatch.setattr(
        lifecycle,
        "get_instance_secrets",
        lambda _k: {"HERMES_API_SERVER_KEY": {}},
    )

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert not ok
    assert err is not None
    assert "HERMES_API_SERVER_KEY" in err
    assert "inventory" not in hermes_configure_env.captured


def test_configure_agent_hermes_unexpected_render_exception_surfaces_cleanly(
    hermes_configure_env, render_stores, monkeypatch
):
    """ATX iter-1 B1: non-AgentConfigError from render_hermes must be
    caught by the broad except in the hermes prerender block and
    returned as (False, 'Hermes render failed: ...') — not propagated
    as an unhandled traceback that leaves the lifecycle half-walked."""
    _seed_single_provider(render_stores, hermes_configure_env)

    def _boom(_inputs):
        raise RuntimeError("simulated jinja TemplateError")

    # configure_agent does `from clawrium.core.render import render_hermes`
    # inside the hermes branch, so patch the source module not lifecycle.
    monkeypatch.setattr("clawrium.core.render.render_hermes", _boom)

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert not ok
    assert err is not None
    assert "Hermes render failed" in err
    assert "simulated jinja TemplateError" in err
    assert "inventory" not in hermes_configure_env.captured


# ---------------------------------------------------------------------------
# #625 coverage restoration — lifecycle paths that survived #622's prune of
# test_hermes_configure.py. Each test names the W-NEW-N gap from ATX iter-2
# of #622 and lifecycle.py line range it pins.
# ---------------------------------------------------------------------------


def test_configure_agent_rejects_out_of_range_persisted_port_picks_fresh(
    hermes_configure_env, render_stores, monkeypatch
):
    """W-NEW-1 (lifecycle.py:1884-1895). A hand-edited hosts.json with
    api_server.port=22 must NOT propagate into ansible_vars — the port
    validator must reject it and `_pick_per_instance_port` must mint a
    fresh in-window value. Without this, the offending port would land
    in systemd ExecStart."""
    _seed_single_provider(render_stores, hermes_configure_env)
    # Seed the offending port. agent_record reads from host["agents"][k].
    hermes_configure_env.host["agents"]["alpha"]["config"]["api_server"]["port"] = 22

    # Force the port picker to a deterministic in-window value so the
    # assertion below isn't sensitive to picker internals.
    monkeypatch.setattr(
        "clawrium.core.install._pick_per_instance_port",
        lambda *_a, **_kw: 8642,
    )

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "127.0.0.1",
                "port": 22,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert ok, f"configure_agent failed: {err}"

    inv = hermes_configure_env.captured["inventory"]
    pushed_port = inv["all"]["vars"]["config"]["api_server"]["port"]
    assert 8600 <= pushed_port <= 8699, (
        f"port {pushed_port!r} escaped the 8600..8699 validation window"
    )
    assert pushed_port != 22, "out-of-range port leaked into ansible_vars"


def test_configure_agent_migrates_loopback_bind_to_wildcard(
    hermes_configure_env, render_stores
):
    """W-NEW-2 (lifecycle.py:1856-1875). A persisted api_server.host of
    '127.0.0.1' must be rewritten to '0.0.0.0' before reaching the
    inventory, otherwise `clm chat <hermes>` from a non-loopback host
    silently breaks."""
    _seed_single_provider(render_stores, hermes_configure_env)
    # Fixture already seeds host='127.0.0.1' on the agent record — explicit
    # here for readability.
    hermes_configure_env.host["agents"]["alpha"]["config"]["api_server"]["host"] = (
        "127.0.0.1"
    )

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert ok, f"configure_agent failed: {err}"

    inv = hermes_configure_env.captured["inventory"]
    pushed_host = inv["all"]["vars"]["config"]["api_server"]["host"]
    assert pushed_host == "0.0.0.0", (
        f"loopback bind {pushed_host!r} not migrated to wildcard"
    )


def test_configure_agent_loopback_migration_is_idempotent(
    hermes_configure_env, render_stores
):
    """W-NEW-2 idempotency case. After the first configure rewrites
    host=0.0.0.0, a second configure with the rewritten record must
    keep emitting 0.0.0.0 and must not error."""
    _seed_single_provider(render_stores, hermes_configure_env)
    # Simulate post-migration state: host already 0.0.0.0.
    hermes_configure_env.host["agents"]["alpha"]["config"]["api_server"]["host"] = (
        "0.0.0.0"
    )

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "0.0.0.0",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert ok, f"second configure failed: {err}"

    inv = hermes_configure_env.captured["inventory"]
    assert inv["all"]["vars"]["config"]["api_server"]["host"] == "0.0.0.0"


def test_configure_agent_strips_api_server_key_from_persisted_hosts_json(
    hermes_configure_env, render_stores, monkeypatch
):
    """W-NEW-3 (lifecycle.py:2527-2531). The bearer key flows through
    config_data so the playbook can render it, but the canonical store
    is secrets.json. The updater closure passed to update_host must
    strip api_server.key before mutating hosts.json. A regression would
    persist the bearer to disk on every configure, defeating the B3
    secrets isolation."""
    _seed_single_provider(render_stores, hermes_configure_env)
    # Pre-migrate the fixture record so _migrate_bind at lifecycle.py:1875
    # does NOT fire. Otherwise update_host is called twice (migration +
    # main updater) and the bearer-strip closure we care about is the
    # second one. Pinning host=0.0.0.0 keeps the call count at one and
    # makes the test independent of call ordering. (ATX iter-1 W-NEW-3
    # suggestion S1.)
    hermes_configure_env.host["agents"]["alpha"]["config"]["api_server"]["host"] = (
        "0.0.0.0"
    )

    update_host_calls: list[tuple[str, callable]] = []

    def _capture_update_host(hostname, closure):
        update_host_calls.append((hostname, closure))
        return True

    monkeypatch.setattr(lifecycle, "update_host", _capture_update_host)

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "0.0.0.0",
                "port": 8642,
                "key": "deadbeef" * 8,
            },
        },
        agent_name="alpha",
    )
    assert ok, f"configure_agent failed: {err}"
    assert len(update_host_calls) == 1, (
        f"expected exactly 1 update_host call (main persist), got "
        f"{len(update_host_calls)}; migration path leaked an extra call."
    )

    # Apply the captured closure to a synthetic host shape and assert
    # the bearer key is absent from the persisted api_server block.
    _hostname, persist_closure = update_host_calls[0]
    sample_host = {"hostname": "host-1", "agents": {"alpha": {"config": {}}}}
    mutated = persist_closure(sample_host)
    persisted_api_server = mutated["agents"]["alpha"]["config"]["api_server"]
    assert "key" not in persisted_api_server, (
        f"bearer key leaked into hosts.json: {persisted_api_server!r}"
    )
    # The non-secret fields must still be present so the next configure
    # can read host/port from hosts.json.
    assert "host" in persisted_api_server
    assert "port" in persisted_api_server


def test_configure_agent_hydrates_channel_tokens_via_hydrate_helper(
    hermes_configure_env, render_stores
):
    """W-NEW-4 (lifecycle.py:1968-1990). When a hermes agent has
    discord + slack channel names listed under `agent_record["channels"]`,
    `_hydrate_channels_from_canonical` must read each via
    `channels.get_channel` + `channels.get_channel_token` and write the
    legacy shape `config_data["channels"][<type>]` so the configure
    playbook + render_hermes can consume it. A regression in the helper
    produces a silent broken-token deploy.

    Pins BOTH paths the hydration sources feed into ansible_vars:
      1. config_data["channels"]["discord"|"slack"] populated by the
         helper directly (asserted on the captured inventory's `config`
         dict).
      2. Tokens reach the pre-rendered .env via render_hermes →
         build_render_inputs (separately mocked via the existing
         render_stores fixture).

    The two-path assertion makes the test fail if either the helper OR
    the render pipeline regresses — ATX iter-1 W-NEW-4 flagged that the
    earlier single-path version (env-only) would have passed even if
    `_hydrate_channels_from_canonical` were entirely removed.
    """
    _seed_single_provider(render_stores, hermes_configure_env)

    # Attach the channel names to the agent record. `_hydrate_channels_from_canonical`
    # reads from agent_record["channels"] directly (lifecycle.py:1679),
    # not via get_agent_channels — that's the production contract.
    hermes_configure_env.host["agents"]["alpha"]["channels"] = [
        "primary-discord",
        "ops-slack",
    ]

    # Discord BOT_TOKEN must be ≥ 50 chars to pass
    # _hydrate_channels_from_canonical's prefix-length validation
    # (lifecycle.py:1706). Production discord tokens are ~70-80 chars;
    # the fixture's 64-char string mirrors that envelope.
    discord_token = "discord-bot-token-" + ("x" * 50)
    slack_bot = "xoxb-slack-bot-token-" + ("y" * 24)
    slack_app = "xapp-slack-app-token-" + ("z" * 24)

    # Seed render_stores once. The fixture's lambdas close over this
    # dict so a mutation here is visible to BOTH the helper path
    # (clawrium.core.channels.get_channel / get_channel_token, used by
    # _hydrate_channels_from_canonical) AND the render path
    # (build_render_inputs → get_agent_channels). No double-patching:
    # the fixture's setattr at lines ~133-138 is the single binding.
    # (ATX iter-2 test-coverage W3.)
    render_stores["agent_channels"] = ["primary-discord", "ops-slack"]
    render_stores["channels"]["primary-discord"] = {
        "name": "primary-discord",
        "type": "discord",
        "enabled": True,
        "config": {"allow_all_users": True},
    }
    render_stores["channels"]["ops-slack"] = {
        "name": "ops-slack",
        "type": "slack",
        "enabled": True,
        "config": {},
    }
    render_stores["channel_tokens"][("primary-discord", "BOT_TOKEN")] = discord_token
    render_stores["channel_tokens"][("ops-slack", "BOT_TOKEN")] = slack_bot
    render_stores["channel_tokens"][("ops-slack", "APP_TOKEN")] = slack_app


    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert ok, f"configure_agent failed: {err}"

    inv = hermes_configure_env.captured["inventory"]
    config = inv["all"]["vars"]["config"]
    env_body = inv["all"]["vars"]["prerendered_hermes_env"]

    # ── Path 1: _hydrate_channels_from_canonical populated config["channels"].
    # If the helper regresses to a no-op, these assertions fail before
    # we even look at the rendered env.
    assert "channels" in config, (
        "config.channels not populated by _hydrate_channels_from_canonical"
    )
    assert config["channels"]["discord"]["bot_token"] == discord_token, (
        "discord bot_token not hydrated into config_data via helper"
    )
    assert config["channels"]["discord"]["enabled"] is True
    assert config["channels"]["slack"]["bot_token"] == slack_bot, (
        "slack bot_token not hydrated into config_data via helper"
    )
    assert config["channels"]["slack"]["app_token"] == slack_app, (
        "slack app_token not hydrated into config_data via helper"
    )

    # ── Path 2: render_hermes received the channel tokens via
    # build_render_inputs and wrote them into the pre-rendered .env.
    assert f"DISCORD_BOT_TOKEN='{discord_token}'" in env_body, (
        f"discord token missing from rendered .env:\n{env_body}"
    )
    assert f"SLACK_BOT_TOKEN='{slack_bot}'" in env_body, (
        f"slack bot token missing from rendered .env:\n{env_body}"
    )
    assert f"SLACK_APP_TOKEN='{slack_app}'" in env_body, (
        f"slack app token missing from rendered .env:\n{env_body}"
    )


def test_configure_agent_strips_channel_tokens_from_persisted_hosts_json(
    hermes_configure_env, render_stores, monkeypatch
):
    """W-NEW-4 companion (lifecycle.py:2542-2568). Sibling invariant to
    W-NEW-3: the B3 secret-isolation block in the updater closure must
    strip `discord.bot_token`, `slack.bot_token`, and `slack.app_token`
    before persisting to hosts.json. Without this strip, the tokens
    roundtrip hydrated→persisted→re-hydrated and defeat the secrets.json
    isolation contract. (ATX iter-2 test-coverage B1.)
    """
    _seed_single_provider(render_stores, hermes_configure_env)
    # Pre-migrate the bind so _migrate_bind doesn't fire and inflate
    # update_host's call count (same rationale as W-NEW-3).
    hermes_configure_env.host["agents"]["alpha"]["config"]["api_server"]["host"] = (
        "0.0.0.0"
    )
    # Attach both channel types so the strip branch exercises discord +
    # slack pop paths.
    hermes_configure_env.host["agents"]["alpha"]["channels"] = [
        "primary-discord",
        "ops-slack",
    ]

    discord_token = "discord-bot-token-" + ("x" * 50)
    slack_bot = "xoxb-slack-bot-token-" + ("y" * 24)
    slack_app = "xapp-slack-app-token-" + ("z" * 24)
    render_stores["channels"]["primary-discord"] = {
        "name": "primary-discord",
        "type": "discord",
        "enabled": True,
        "config": {"allow_all_users": True},
    }
    render_stores["channels"]["ops-slack"] = {
        "name": "ops-slack",
        "type": "slack",
        "enabled": True,
        "config": {},
    }
    render_stores["channel_tokens"][("primary-discord", "BOT_TOKEN")] = discord_token
    render_stores["channel_tokens"][("ops-slack", "BOT_TOKEN")] = slack_bot
    render_stores["channel_tokens"][("ops-slack", "APP_TOKEN")] = slack_app
    render_stores["agent_channels"] = ["primary-discord", "ops-slack"]

    update_host_calls: list[tuple[str, callable]] = []

    def _capture_update_host(hostname, closure):
        update_host_calls.append((hostname, closure))
        return True

    monkeypatch.setattr(lifecycle, "update_host", _capture_update_host)

    ok, err = lifecycle.configure_agent(
        hostname="host-1",
        claw_name="hermes",
        config_data={
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "model-x",
            },
            "api_server": {
                "host": "0.0.0.0",
                "port": 8642,
                "key": "a" * 64,
            },
        },
        agent_name="alpha",
    )
    assert ok, f"configure_agent failed: {err}"
    assert len(update_host_calls) == 1

    # Apply the captured closure to a synthetic host shape and assert
    # every token is stripped while non-secret fields survive.
    _hostname, persist_closure = update_host_calls[0]
    sample_host = {"hostname": "host-1", "agents": {"alpha": {"config": {}}}}
    mutated = persist_closure(sample_host)
    persisted_channels = mutated["agents"]["alpha"]["config"]["channels"]

    # Discord: bot_token stripped, enabled flag preserved.
    assert "bot_token" not in persisted_channels["discord"], (
        f"discord bot_token leaked into hosts.json: {persisted_channels['discord']!r}"
    )
    assert persisted_channels["discord"].get("enabled") is True
    # Slack: bot_token + app_token stripped, enabled flag preserved.
    assert "bot_token" not in persisted_channels["slack"], (
        f"slack bot_token leaked into hosts.json: {persisted_channels['slack']!r}"
    )
    assert "app_token" not in persisted_channels["slack"], (
        f"slack app_token leaked into hosts.json: {persisted_channels['slack']!r}"
    )
    assert persisted_channels["slack"].get("enabled") is True
    # api_server.key strip continues to hold on the same closure call.
    assert "key" not in mutated["agents"]["alpha"]["config"]["api_server"]

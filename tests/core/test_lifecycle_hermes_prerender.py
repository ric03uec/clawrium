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

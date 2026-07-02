"""Tests for the #756 openclaw prerender block in lifecycle.configure_agent.

Validates that `configure_agent` for openclaw pre-renders `~/.openclaw/openclaw.json`
via `render_openclaw` and surfaces the bytes through `ansible_vars` so the
configure playbook can `copy: content:` them. Mirrors the hermes coverage at
`tests/core/test_lifecycle_hermes_prerender.py` (issue #622).

The load-bearing assertion is PARITY: for every supported provider type, the
bytes produced by the configure pre-render path must be byte-identical to what
the canonical sync path (`render_openclaw(build_render_inputs(...))`) produces
for the same inputs. If parity ever breaks, the two render paths have diverged
again — exactly the regression #756 fixed.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clawrium.core import lifecycle
from clawrium.core.render import build_render_inputs, render_openclaw


# ---------------------------------------------------------------------------
# Fixture: stub every collaborator configure_agent reaches between argv
# unpacking and the openclaw prerender block. Mirrors the hermes fixture in
# `tests/core/test_lifecycle_hermes_prerender.py`.
# ---------------------------------------------------------------------------


@pytest.fixture
def openclaw_configure_env(monkeypatch, tmp_path):
    captured = {}

    host = {
        "hostname": "host-1",
        "user": "xclm",
        "port": 22,
        "key_id": "host-1",
        "agents": {
            "alpha": {
                "type": "openclaw",
                "agent_name": "alpha",
                "providers": [],
                "config": {
                    "gateway": {
                        "port": 40500,
                        "bind": "lan",
                        # Persisted as a string post-install (install.py:1323
                        # writes `config.gateway.auth = gateway_token`). The
                        # `{mode,token}` dict in install.py's local config
                        # variable is reshaped before persist.
                        "auth": "install-time-bearer",
                    },
                },
            }
        },
    }
    monkeypatch.setattr(lifecycle, "get_host", lambda _h: host)

    fake_key = tmp_path / "id_rsa"
    fake_key.write_text("PRIVATE")
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _k: fake_key)

    monkeypatch.setattr(
        lifecycle,
        "get_instance_secrets",
        lambda _k: {},
    )

    # No integrations attached in the default fixture.
    monkeypatch.setattr(
        "clawrium.core.integrations.get_agent_integrations",
        lambda *_a, **_kw: [],
    )

    # Skip the openclaw brave preflight ssh probe by patching the helper
    # the configure path runs unconditionally for openclaw. Returning a
    # benign pin keeps the configure path on the success branch without
    # touching the network.
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._load_openclaw_brave_pin",
        lambda: {
            "npm_package": "@openclaw/brave-plugin",
            "version": "2026.6.8",
            "min_host_version": (2026, 4, 10),
        },
    )

    # Replace ansible_runner.run with a recorder.
    def _record(**kwargs):
        captured["inventory"] = kwargs.get("inventory")
        captured["playbook"] = kwargs.get("playbook")
        return SimpleNamespace(status="successful", rc=0, stats=None)

    monkeypatch.setattr(lifecycle.ansible_runner, "run", MagicMock(side_effect=_record))

    monkeypatch.setattr(lifecycle, "update_host", lambda *_a, **_kw: True)

    return SimpleNamespace(host=host, captured=captured, tmp_path=tmp_path)


# ---------------------------------------------------------------------------
# Render-input fixture — patches the store accessors used by both
# `build_render_inputs` and the configure_agent secret hydration paths.
# ---------------------------------------------------------------------------


@pytest.fixture
def render_stores(monkeypatch):
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


def _openclaw_agent_record(providers: list) -> tuple[dict, str, dict]:
    return (
        {"hostname": "host-1"},
        "openclaw",
        {
            "agent_name": "alpha",
            "providers": providers,
            "config": {
                "gateway": {
                    "port": 40500,
                    "bind": "lan",
                    "auth": "install-time-bearer",
                },
            },
        },
    )


# ---------------------------------------------------------------------------
# Per-provider-type seeding helpers
# ---------------------------------------------------------------------------


def _seed_openclaw_litellm(render_stores, env, *, name="lt", model="writer"):
    attachments = [{"name": name, "role": "primary", "model": model}]
    render_stores["agent"] = _openclaw_agent_record(attachments)
    render_stores["providers"][name] = {
        "name": name,
        "type": "litellm",
        "default_model": model,
        "endpoint": "https://litellm.example.com",
    }
    render_stores["provider_api_keys"][name] = "sk-litellm-1"
    env.host["agents"]["alpha"]["providers"] = attachments
    return {
        "provider": {
            "name": name,
            "type": "litellm",
            "default_model": model,
            "endpoint": "https://litellm.example.com",
        },
    }


def _seed_openclaw_openrouter(render_stores, env, *, name="or", model="anthropic/claude-opus-4"):
    attachments = [{"name": name, "role": "primary", "model": model}]
    render_stores["agent"] = _openclaw_agent_record(attachments)
    render_stores["providers"][name] = {
        "name": name,
        "type": "openrouter",
        "default_model": model,
    }
    render_stores["provider_api_keys"][name] = "sk-or-1"
    env.host["agents"]["alpha"]["providers"] = attachments
    return {
        "provider": {
            "name": name,
            "type": "openrouter",
            "default_model": model,
        },
    }


def _seed_openclaw_ollama(render_stores, env, *, name="ol", model="llama3"):
    attachments = [{"name": name, "role": "primary", "model": model}]
    render_stores["agent"] = _openclaw_agent_record(attachments)
    render_stores["providers"][name] = {
        "name": name,
        "type": "ollama",
        "default_model": model,
        "endpoint": "http://localhost:11434",
    }
    env.host["agents"]["alpha"]["providers"] = attachments
    return {
        "provider": {
            "name": name,
            "type": "ollama",
            "default_model": model,
            "endpoint": "http://localhost:11434",
        },
    }


def _seed_openclaw_bedrock(render_stores, env, *, name="br", model="claude-sonnet"):
    attachments = [{"name": name, "role": "primary", "model": model}]
    render_stores["agent"] = _openclaw_agent_record(attachments)
    render_stores["providers"][name] = {
        "name": name,
        "type": "bedrock",
        "default_model": model,
        "region": "us-west-2",
    }
    render_stores["provider_aws"][name] = ("AKIA-XXXX", "AWS-SECRET-XXXX")
    env.host["agents"]["alpha"]["providers"] = attachments
    return {
        "provider": {
            "name": name,
            "type": "bedrock",
            "default_model": model,
        },
    }


def _seed_openclaw_anthropic(render_stores, env, *, name="an", model="claude-3"):
    attachments = [{"name": name, "role": "primary", "model": model}]
    render_stores["agent"] = _openclaw_agent_record(attachments)
    render_stores["providers"][name] = {
        "name": name,
        "type": "anthropic",
        "default_model": model,
    }
    render_stores["provider_api_keys"][name] = "sk-ant-1"
    env.host["agents"]["alpha"]["providers"] = attachments
    return {
        "provider": {
            "name": name,
            "type": "anthropic",
            "default_model": model,
        },
    }


def _seed_openclaw_openai(render_stores, env, *, name="oa", model="gpt-4"):
    attachments = [{"name": name, "role": "primary", "model": model}]
    render_stores["agent"] = _openclaw_agent_record(attachments)
    render_stores["providers"][name] = {
        "name": name,
        "type": "openai",
        "default_model": model,
    }
    render_stores["provider_api_keys"][name] = "sk-oa-1"
    env.host["agents"]["alpha"]["providers"] = attachments
    return {
        "provider": {
            "name": name,
            "type": "openai",
            "default_model": model,
        },
    }


SEED_FNS = {
    "litellm": _seed_openclaw_litellm,
    "openrouter": _seed_openclaw_openrouter,
    "ollama": _seed_openclaw_ollama,
    "bedrock": _seed_openclaw_bedrock,
    "anthropic": _seed_openclaw_anthropic,
    "openai": _seed_openclaw_openai,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _invoke_configure(env, provider_config: dict) -> tuple[bool, str | None]:
    config_data = {
        "gateway": {
            "port": 40500,
            "bind": "lan",
            "auth": "install-time-bearer",
        },
        "provider": provider_config["provider"],
    }
    return lifecycle.configure_agent(
        hostname="host-1",
        claw_name="openclaw",
        config_data=config_data,
        agent_name="alpha",
    )


@pytest.mark.parametrize("ptype", sorted(SEED_FNS.keys()))
def test_configure_agent_openclaw_prerenders_canonical_json(
    ptype, openclaw_configure_env, render_stores
):
    """Per-provider-type: configure_agent must populate
    `ansible_vars["prerendered_openclaw_config_json"]` with bytes equal to
    what `render_openclaw(build_render_inputs(...))` produces for the same
    inputs. This is the structural guarantee that the configure path
    delegates rendering to the canonical renderer."""
    seed = SEED_FNS[ptype]
    provider_config = seed(render_stores, openclaw_configure_env)

    ok, err = _invoke_configure(openclaw_configure_env, provider_config)
    assert ok, f"configure_agent failed for {ptype}: {err}"

    inv = openclaw_configure_env.captured["inventory"]
    rendered_json = inv["all"]["vars"]["prerendered_openclaw_config_json"]
    assert rendered_json, (
        f"prerendered_openclaw_config_json empty for {ptype} — the prerender "
        f"branch did not populate the extravar."
    )

    expected = render_openclaw(build_render_inputs("alpha"))
    assert rendered_json == expected.files[".openclaw/openclaw.json"], (
        f"configure_agent prerender for {ptype} drifted from "
        f"render_openclaw(build_render_inputs(...)). Divergence is the "
        f"#756 regression class."
    )


@pytest.mark.parametrize("ptype", sorted(SEED_FNS.keys()))
def test_configure_and_sync_render_byte_identical(
    ptype, openclaw_configure_env, render_stores
):
    """PARITY (load-bearing). For every supported provider type, the
    configure pre-render bytes (extravar) MUST equal the canonical sync
    render bytes (`render_openclaw(build_render_inputs(...))`). If this
    test ever fails, the two render paths #756 collapsed have re-diverged
    and the litellm-primary-model class of bugs is back."""
    seed = SEED_FNS[ptype]
    provider_config = seed(render_stores, openclaw_configure_env)

    ok, err = _invoke_configure(openclaw_configure_env, provider_config)
    assert ok, f"configure_agent failed for {ptype}: {err}"

    inv = openclaw_configure_env.captured["inventory"]
    configure_bytes = inv["all"]["vars"]["prerendered_openclaw_config_json"]

    # Sync path: render_openclaw is what sync_agent_canonical calls.
    sync_bytes = render_openclaw(build_render_inputs("alpha")).files[
        ".openclaw/openclaw.json"
    ]

    assert configure_bytes == sync_bytes, (
        f"configure vs sync rendered bytes diverged for {ptype}. "
        f"This is the #756 regression: two render paths producing "
        f"different on-host openclaw.json. Diff len: "
        f"configure={len(configure_bytes)} sync={len(sync_bytes)}"
    )


def test_configure_agent_openclaw_render_error_surfaces_cleanly(
    openclaw_configure_env, render_stores
):
    """AgentConfigError from build_render_inputs / render_openclaw must
    surface as a clean (False, error_message) return — nothing pushed
    to the host. Trigger via a litellm provider with an empty endpoint
    (renderer raises at the base_url guard)."""
    attachments = [{"name": "lt", "role": "primary", "model": "writer"}]
    render_stores["agent"] = _openclaw_agent_record(attachments)
    render_stores["providers"]["lt"] = {
        "name": "lt",
        "type": "litellm",
        "default_model": "writer",
        # Empty endpoint — build_render_inputs raises here for litellm.
        "endpoint": "",
    }
    render_stores["provider_api_keys"]["lt"] = "sk-1"
    openclaw_configure_env.host["agents"]["alpha"]["providers"] = attachments

    ok, err = _invoke_configure(
        openclaw_configure_env,
        {
            "provider": {
                "name": "lt",
                "type": "litellm",
                "default_model": "writer",
                "endpoint": "",
            }
        },
    )
    assert not ok
    assert err is not None
    assert "Openclaw render failed" in err
    # Ansible-runner.run must not have been invoked.
    assert "inventory" not in openclaw_configure_env.captured


def test_configure_agent_openclaw_unexpected_render_exception_surfaces_cleanly(
    openclaw_configure_env, render_stores, monkeypatch
):
    """Non-AgentConfigError from render_openclaw must be caught by the
    broad except in the openclaw prerender block and returned as
    (False, 'Openclaw render failed: ...') — not propagated as an
    unhandled traceback that leaves the lifecycle half-walked."""
    _seed_openclaw_openrouter(render_stores, openclaw_configure_env)

    def _boom(_inputs, **_kwargs):
        # #835: configure_agent now threads os_family= into render_openclaw.
        # Accept and ignore so the stub raises via the exception under test
        # and not via TypeError on the kwarg.
        raise RuntimeError("simulated json baseline IOError")

    # configure_agent does `from clawrium.core.render import render_openclaw`
    # inside the openclaw branch, so patch the source module.
    monkeypatch.setattr("clawrium.core.render.render_openclaw", _boom)

    ok, err = _invoke_configure(
        openclaw_configure_env,
        {
            "provider": {
                "name": "or",
                "type": "openrouter",
                "default_model": "anthropic/claude-opus-4",
            }
        },
    )
    assert not ok
    assert err is not None
    assert "Openclaw render failed" in err
    assert "simulated json baseline IOError" in err
    assert "inventory" not in openclaw_configure_env.captured



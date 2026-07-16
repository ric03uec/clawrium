"""Tests for the #924 ethos prerender block in lifecycle.configure_agent.

Validates that `configure_agent` for ethos pre-renders all five canonical
config files via `render_ethos` and surfaces the bytes through
`ansible_vars` so the configure playbook can `copy: content:` them.
Mirrors the hermes coverage at `tests/core/test_lifecycle_hermes_prerender.py`
(issue #622) and the openclaw coverage at
`tests/core/test_lifecycle_openclaw_prerender.py` (issue #756).

The load-bearing assertion is PARITY: the bytes produced by the configure
pre-render path must be byte-identical to what the canonical sync path
(`render_ethos(build_render_inputs(...))`) produces for the same inputs.
If parity ever breaks, the two render paths have diverged again — exactly
the dual-render-path regression the #924 ATX review (B1) flagged.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clawrium.core import lifecycle
from clawrium.core.render import build_render_inputs, render_ethos


_GW_KEY = "a" * 64

_ETHOS_FILE_VARS = {
    ".ethos/.env": "prerendered_ethos_env",
    ".ethos/config.yaml": "prerendered_ethos_config_yaml",
    ".ethos/personalities/default/SOUL.md": "prerendered_ethos_soul_md",
    ".ethos/personalities/default/toolset.yaml": "prerendered_ethos_toolset_yaml",
    ".ethos/personalities/default/config.yaml": (
        "prerendered_ethos_personality_config_yaml"
    ),
}


@pytest.fixture
def ethos_configure_env(monkeypatch, tmp_path):
    captured = {}

    host = {
        "hostname": "host-1",
        "user": "xclm",
        "port": 22,
        "key_id": "host-1",
        "agents": {
            "kevin": {
                "type": "ethos",
                "agent_name": "kevin",
                "providers": [],
                "config": {
                    "gateway": {
                        "port": 3000,
                        "internal_port": 44412,
                        "api_key": _GW_KEY,
                    },
                },
            }
        },
    }
    monkeypatch.setattr(lifecycle, "get_host", lambda _h: host)

    fake_key = tmp_path / "id_rsa"
    fake_key.write_text("PRIVATE")
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _k: fake_key)

    # Instance secrets — configure_agent validates ETHOS_GATEWAY_API_KEY
    # against secrets.json (authoritative) before the prerender block.
    monkeypatch.setattr(
        lifecycle,
        "get_instance_secrets",
        lambda _k: {"ETHOS_GATEWAY_API_KEY": {"value": _GW_KEY}},
    )

    monkeypatch.setattr(
        "clawrium.core.integrations.get_agent_integrations",
        lambda *_a, **_kw: [],
    )

    def _record(**kwargs):
        captured["inventory"] = kwargs.get("inventory")
        captured["playbook"] = kwargs.get("playbook")
        return SimpleNamespace(status="successful", rc=0, stats=None)

    monkeypatch.setattr(
        lifecycle.ansible_runner, "run", MagicMock(side_effect=_record)
    )

    monkeypatch.setattr(lifecycle, "update_host", lambda *_a, **_kw: True)

    return SimpleNamespace(host=host, captured=captured, tmp_path=tmp_path)


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


def _seed_ethos_agent(render_stores, env, *, ptype="openrouter"):
    attachments = [{"name": "prov", "role": "primary", "model": ""}]
    render_stores["agent"] = (
        {"hostname": "host-1"},
        "ethos",
        {
            "agent_name": "kevin",
            "providers": attachments,
            "config": {
                "gateway": {
                    "port": 3000,
                    "internal_port": 44412,
                    "api_key": _GW_KEY,
                },
            },
        },
    )
    render_stores["providers"]["prov"] = {
        "name": "prov",
        "type": ptype,
        "default_model": "anthropic/claude-opus-4.7",
    }
    if ptype != "codex":
        render_stores["provider_api_keys"]["prov"] = "sk-test-1"
    env.host["agents"]["kevin"]["providers"] = attachments


def _invoke_configure(env):
    return lifecycle.configure_agent(
        hostname="host-1",
        claw_name="ethos",
        config_data={
            "provider": {
                "name": "prov",
                "type": "openrouter",
                "default_model": "anthropic/claude-opus-4.7",
            },
        },
        agent_name="kevin",
    )


def test_configure_agent_ethos_prerenders_all_five_files(
    ethos_configure_env, render_stores
):
    """configure_agent must populate every `prerendered_ethos_*` extravar
    with non-empty bytes for a healthy openrouter agent."""
    _seed_ethos_agent(render_stores, ethos_configure_env)

    ok, err = _invoke_configure(ethos_configure_env)
    assert ok, f"configure_agent failed: {err}"

    inv = ethos_configure_env.captured["inventory"]
    ansible_vars = inv["all"]["vars"]
    for path, var in _ETHOS_FILE_VARS.items():
        assert ansible_vars.get(var), (
            f"{var} empty — the ethos prerender branch did not populate "
            f"the extravar for {path}"
        )


def test_configure_and_sync_render_byte_identical(
    ethos_configure_env, render_stores
):
    """PARITY (load-bearing, #924 B1). The configure pre-render bytes
    (extravars) MUST equal the canonical sync render bytes
    (`render_ethos(build_render_inputs(...))`) for every file. If this
    test ever fails, the dual-render-path bug class (#622) is back."""
    _seed_ethos_agent(render_stores, ethos_configure_env)

    ok, err = _invoke_configure(ethos_configure_env)
    assert ok, f"configure_agent failed: {err}"

    inv = ethos_configure_env.captured["inventory"]
    ansible_vars = inv["all"]["vars"]

    sync_rendered = render_ethos(build_render_inputs("kevin"))
    for path, var in _ETHOS_FILE_VARS.items():
        assert ansible_vars[var] == sync_rendered.files[path], (
            f"configure vs sync rendered bytes diverged for {path}"
        )


def test_configure_agent_ethos_env_carries_secrets_bearer(
    ethos_configure_env, render_stores
):
    """The pre-rendered .env must carry the secrets.json-validated
    ETHOS_GATEWAY_API_KEY — the value the playbook's verify task greps
    for and the daemon will enforce."""
    _seed_ethos_agent(render_stores, ethos_configure_env)

    ok, err = _invoke_configure(ethos_configure_env)
    assert ok, f"configure_agent failed: {err}"

    env_body = ethos_configure_env.captured["inventory"]["all"]["vars"][
        "prerendered_ethos_env"
    ]
    assert f"ETHOS_GATEWAY_API_KEY='{_GW_KEY}'" in env_body
    assert "ETHOS_GATEWAY_PORT=44412" in env_body


def test_configure_agent_ethos_render_error_surfaces_cleanly(
    ethos_configure_env, render_stores
):
    """AgentConfigError from render_ethos must surface as a clean
    (False, error_message) return — nothing pushed to the host. Trigger
    via an unsupported provider type (bedrock)."""
    _seed_ethos_agent(render_stores, ethos_configure_env, ptype="bedrock")
    render_stores["provider_aws"]["prov"] = ("AKIA-1", "secret-1")

    ok, err = _invoke_configure(ethos_configure_env)
    assert not ok
    assert "Ethos render failed" in (err or "")
    assert "inventory" not in ethos_configure_env.captured

"""Tests for the openclaw prerender branch in `install.run_installation`.

Extended by fix #1 (post-Phase-4 provider-strip regression): the stub
now returns a `(json_body, env_body)` tuple and threads
`provider_record` + `provider_api_key` into the env body so a sandboxed
openclaw is chattable on first `systemctl start` without any configure
step.

Mirrors `tests/core/test_lifecycle_openclaw_prerender.py` for the install
path. `run_installation` itself is too deeply nested (manifest load, SSH
probe, ansible-runner) to call from a unit test, so the extracted stub
carries the coverage.
"""

from __future__ import annotations

import json

from clawrium.core import install
from clawrium.core.render import GatewayInputs


def test_install_openclaw_pre_renders_with_correct_gateway_inputs(monkeypatch):
    """Provider-less install path: stub calls `_render_openclaw_json`
    with provider=None + provider_default_model=None + discord_channel=None
    and a `GatewayInputs` carrying the install-minted port + bearer.
    Env body has gateway lines only, no bearer."""
    captured: dict = {}

    def _spy(*, provider, provider_default_model, gateway, discord_channel):
        captured["provider"] = provider
        captured["provider_default_model"] = provider_default_model
        captured["gateway"] = gateway
        captured["discord_channel"] = discord_channel
        return '{"rendered": true}'

    monkeypatch.setattr("clawrium.core.render._render_openclaw_json", _spy)

    json_body, env_body = install._prerender_openclaw_install_stub(
        openclaw_port=40500,
        gateway_auth_token="install-bearer-xyz",
    )

    assert json_body == '{"rendered": true}'
    assert captured["provider"] is None
    assert captured["provider_default_model"] is None
    assert captured["discord_channel"] is None
    gw = captured["gateway"]
    assert isinstance(gw, GatewayInputs)
    assert gw.port == 40500
    assert gw.bind == "lan"
    assert gw.auth == "install-bearer-xyz"
    # Provider-less env body: gateway lines + empty OPENCLAW_DEFAULT_MODEL
    # only. No bearer, no model prefix magic.
    assert "OPENCLAW_GATEWAY_PORT=40500" in env_body
    assert "OPENCLAW_GATEWAY_AUTH_TOKEN='install-bearer-xyz'" in env_body
    assert "OPENROUTER_API_KEY" not in env_body
    assert "ANTHROPIC_API_KEY" not in env_body


def test_install_openclaw_puts_rendered_bytes_in_ansible_vars():
    """End-to-end (no monkeypatch): the stub returns a `(json, env)` tuple
    whose bodies carry the supplied port + bearer. These are the bytes
    `run_installation` assigns to
    `ansible_vars["prerendered_openclaw_config_json"]` (json) +
    `ansible_vars["prerendered_openclaw_env"]` (env)."""
    json_body, env_body = install._prerender_openclaw_install_stub(
        openclaw_port=41234,
        gateway_auth_token="bearer-abc",
    )

    parsed = json.loads(json_body)
    assert parsed["gateway"]["port"] == 41234
    assert parsed["gateway"]["bind"] == "lan"
    assert parsed["gateway"]["auth"] == {"mode": "token", "token": "bearer-abc"}
    assert "OPENCLAW_GATEWAY_PORT=41234" in env_body


def test_install_openclaw_prerender_with_provider_threads_bearer_into_env():
    """Fix #1: when the operator passes --provider at create time,
    provider_record + provider_api_key flow into the stub. The env body
    includes the canonical bearer line for the provider's type; the json
    body's `agents.defaults.model.primary` gets the type-prefixed model."""
    provider_record = {
        "name": "test-or",
        "type": "openrouter",
        "default_model": "openai/gpt-4o",
    }
    json_body, env_body = install._prerender_openclaw_install_stub(
        openclaw_port=41235,
        gateway_auth_token="bearer-x",
        provider_record=provider_record,
        provider_api_key="sk-or-test-abc",
        agent_name="oc-nemo",
    )

    parsed = json.loads(json_body)
    assert (
        parsed["agents"]["defaults"]["model"]["primary"]
        == "openrouter/openai/gpt-4o"
    )
    assert "OPENROUTER_API_KEY='sk-or-test-abc'" in env_body
    assert "OPENCLAW_DEFAULT_MODEL='openrouter/openai/gpt-4o'" in env_body
    assert "OPENCLAW_GATEWAY_PORT=41235" in env_body


def test_install_openclaw_prerender_anthropic_provider():
    """Fix #1 coverage: anthropic type emits ANTHROPIC_API_KEY (not the
    openrouter/bedrock model prefix magic)."""
    provider_record = {
        "name": "test-anthropic",
        "type": "anthropic",
        "default_model": "claude-opus-4-7",
    }
    _, env_body = install._prerender_openclaw_install_stub(
        openclaw_port=41236,
        gateway_auth_token="bearer-y",
        provider_record=provider_record,
        provider_api_key="sk-ant-real",
        agent_name="oc-anthro",
    )
    assert "ANTHROPIC_API_KEY='sk-ant-real'" in env_body
    assert "OPENCLAW_DEFAULT_MODEL='claude-opus-4-7'" in env_body
    # No cross-type contamination.
    assert "OPENROUTER_API_KEY" not in env_body


def test_install_non_openclaw_passes_empty_string_for_prerendered_var():
    """The `run_installation` openclaw branch initializes both
    prerender vars to empty string and only overwrites them under the
    `claw_name == "openclaw"` guard. For non-openclaw claw_names the
    install ansible vars must carry empty strings for both. Contract
    asserted by source inspection since `run_installation` is too
    deeply nested to call ergonomically."""
    import inspect

    src = inspect.getsource(install.run_installation)
    # Both openclaw prerender vars must initialize to empty string ...
    assert 'prerendered_openclaw_config_json = ""' in src, (
        "install.run_installation no longer initializes the openclaw "
        "prerender var to empty string — non-openclaw installs would "
        "carry stale bytes from a prior iteration."
    )
    assert 'prerendered_openclaw_env = ""' in src, (
        "fix #1 companion var must also default to empty string."
    )
    # ... and only overwrite them under the openclaw guard.
    assert 'if claw_name == "openclaw":' in src
    # Both ansible inventory keys must reference the vars.
    assert (
        '"prerendered_openclaw_config_json": prerendered_openclaw_config_json'
        in src
    )
    assert '"prerendered_openclaw_env": prerendered_openclaw_env' in src

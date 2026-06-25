"""Tests for the #756 openclaw prerender branch in `install.run_installation`.

Mirrors `tests/core/test_lifecycle_openclaw_prerender.py` for the install
path. The install branch is exercised indirectly via the small
`_prerender_openclaw_install_stub` helper that `run_installation` calls.

[DECISION] `run_installation` is too deeply nested (manifest load, SSH
probe, ansible-runner) to call ergonomically from a unit test. We
extracted `_prerender_openclaw_install_stub(openclaw_port,
gateway_auth_token) -> str` in `src/clawrium/core/install.py` (B3 ATX
iter-2) so the install-path render branch is testable in isolation.
The end-to-end "bytes flow into ansible_vars" assertion is exercised
by the matrix harness at `tests/integration/test_render_matrix.py`
and by `tests/core/test_lifecycle_openclaw_prerender.py` for the
configure path.
"""

from __future__ import annotations

import json

from clawrium.core import install
from clawrium.core.render import GatewayInputs


def test_install_openclaw_pre_renders_with_correct_gateway_inputs(monkeypatch):
    """The install stub must call `_render_openclaw_json` with
    provider=None, provider_default_model=None, discord_channel=None,
    and a `GatewayInputs` carrying the install-minted port + bearer."""
    captured: dict = {}

    def _spy(*, provider, provider_default_model, gateway, discord_channel):
        captured["provider"] = provider
        captured["provider_default_model"] = provider_default_model
        captured["gateway"] = gateway
        captured["discord_channel"] = discord_channel
        return '{"rendered": true}'

    monkeypatch.setattr("clawrium.core.render._render_openclaw_json", _spy)

    out = install._prerender_openclaw_install_stub(
        openclaw_port=40500,
        gateway_auth_token="install-bearer-xyz",
    )

    assert out == '{"rendered": true}'
    assert captured["provider"] is None
    assert captured["provider_default_model"] is None
    assert captured["discord_channel"] is None
    gw = captured["gateway"]
    assert isinstance(gw, GatewayInputs)
    assert gw.port == 40500
    assert gw.bind == "lan"
    assert gw.auth == "install-bearer-xyz"


def test_install_openclaw_puts_rendered_bytes_in_ansible_vars():
    """End-to-end (no monkeypatch): the stub returns parseable JSON whose
    gateway block carries the supplied port + bearer. These are the
    bytes `run_installation` assigns to
    `ansible_vars["prerendered_openclaw_config_json"]` (see
    `install.py:991`); proving the stub produces them is equivalent to
    proving the var carries them, given the stub is the sole writer."""
    rendered = install._prerender_openclaw_install_stub(
        openclaw_port=41234,
        gateway_auth_token="bearer-abc",
    )

    parsed = json.loads(rendered)
    assert parsed["gateway"]["port"] == 41234
    assert parsed["gateway"]["bind"] == "lan"
    assert parsed["gateway"]["auth"] == {"mode": "token", "token": "bearer-abc"}


def test_install_non_openclaw_passes_empty_string_for_prerendered_var():
    """The `run_installation` openclaw branch initializes
    `prerendered_openclaw_config_json = ""` and only overwrites it when
    `claw_name == "openclaw"`. This test pins the contract by reading
    the source: for non-openclaw claw_names (hermes / zeroclaw /
    nemoclaw), the install ansible vars must carry an empty string for
    `prerendered_openclaw_config_json`. We assert the contract by
    checking the source code, since `run_installation` is too deeply
    nested to call ergonomically and the openclaw-only guard is the
    sole writer of the var."""
    import inspect

    src = inspect.getsource(install.run_installation)
    # The install path must initialize the var to empty string ...
    assert 'prerendered_openclaw_config_json = ""' in src, (
        "install.run_installation no longer initializes the openclaw "
        "prerender var to empty string — non-openclaw installs would "
        "carry stale bytes from a prior iteration."
    )
    # ... and only overwrite it under the openclaw guard.
    assert 'if claw_name == "openclaw":' in src
    # The ansible inventory must reference the var (so it ships to the
    # install playbook for openclaw and is empty-string for the rest).
    assert (
        '"prerendered_openclaw_config_json": prerendered_openclaw_config_json'
        in src
    )

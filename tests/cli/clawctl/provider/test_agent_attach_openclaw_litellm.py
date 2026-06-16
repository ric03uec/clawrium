"""Issue #723 — `litellm` provider type can attach to an openclaw agent.

Before #723 the renderer's per-agent-type allow-list rejected
`litellm` on openclaw, so `clawctl agent provider attach <openclaw>
<litellm-provider>` failed up-front in `build_render_inputs` with
`render_openclaw does not support provider type 'litellm'`. The fix
extends `_AGENT_TYPE_PROVIDER_SUPPORT['openclaw']` and writes a
`models.providers.<name>` block into `openclaw.json`. This test pins
the CLI-facing contract: attach succeeds, and the openclaw
single-provider invariant (#426) still rejects a second attachment.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.providers.storage import add_provider, set_provider_api_key

runner = CliRunner()


def _seed_litellm_provider(name: str = "lt") -> None:
    """Seed providers.json + secrets.json with a litellm provider.

    Bypasses `clawctl provider registry create --type litellm` so we
    don't try to probe a real LiteLLM proxy in a unit test.
    """
    add_provider(
        {
            "name": name,
            "type": "litellm",
            "endpoint": "http://192.168.1.17:4000",
            "default_model": "writer",
            "available_models": ["writer"],
        }
    )
    set_provider_api_key(name, "sk-master-1")


def _seed_anthropic_provider(name: str = "anth") -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            name,
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )


def test_attach_litellm_to_openclaw_succeeds(fleet_dir, stdin_not_tty) -> None:
    """#723: a litellm provider attached to an openclaw agent is accepted
    by the CLI and persisted in hosts.json."""
    _seed_litellm_provider("clawrium-gtm-litellm")
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "clawrium-gtm-litellm",
            "--agent",
            "wise-hypatia",
        ],
    )
    assert result.exit_code == 0, result.output
    # #723 ATX: pin the provider identity in the user-facing message,
    # not just the verb. A bare `'attached' in output` substring match
    # would pass even if the CLI silently attached the wrong provider.
    assert "attached" in result.output
    assert "clawrium-gtm-litellm" in result.output

    listed = runner.invoke(
        app,
        ["agent", "provider", "get", "--agent", "wise-hypatia", "-o", "json"],
    )
    assert listed.exit_code == 0
    data = json.loads(listed.output)
    assert any(p["name"] == "clawrium-gtm-litellm" for p in data)


def test_openclaw_single_provider_invariant_still_holds_for_litellm(
    fleet_dir, stdin_not_tty
) -> None:
    """#426 single-provider invariant survives the #723 allow-list change.

    Attaching a second provider — of any type — to an openclaw agent
    that already has a litellm primary must be rejected with the
    existing "already has provider" message pointing operators at
    `detach`.
    """
    _seed_litellm_provider("clawrium-gtm-litellm")
    _seed_anthropic_provider("anth")

    first = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "clawrium-gtm-litellm",
            "--agent",
            "wise-hypatia",
        ],
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        app,
        ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"],
    )
    assert second.exit_code != 0
    assert "already has provider" in second.output
    assert "detach" in second.output
    assert "clawrium-gtm-litellm" in second.output


def test_openclaw_litellm_passes_build_render_inputs(
    fleet_dir, stdin_not_tty
) -> None:
    """#723: `build_render_inputs` is the gate that previously blocked
    the wire. Pin that an openclaw agent attached to a litellm provider
    now assembles a valid RenderInputs bundle (provider.type == 'litellm',
    api_key + endpoint populated) — the upstream signal that the
    allow-list change works end-to-end through the assembly layer."""
    from clawrium.core.render import build_render_inputs

    _seed_litellm_provider("clawrium-gtm-litellm")
    runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "clawrium-gtm-litellm",
            "--agent",
            "wise-hypatia",
        ],
    )

    inputs = build_render_inputs("wise-hypatia")
    assert inputs.agent_type == "openclaw"
    assert inputs.provider.type == "litellm"
    assert inputs.provider.name == "clawrium-gtm-litellm"
    assert inputs.provider.endpoint == "http://192.168.1.17:4000"
    assert inputs.provider.api_key == "sk-master-1"
    assert inputs.provider.default_model == "writer"

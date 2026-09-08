"""Issue #976 — `litellm` provider type can attach to a zeroclaw agent.

Before #976 the renderer's per-agent-type allow-list rejected `litellm`
on zeroclaw, so `clawctl agent provider attach <zeroclaw> <litellm>`
failed up-front in `build_render_inputs` with `render_zeroclaw does not
support provider type 'litellm'`. The fix extends
`_AGENT_TYPE_PROVIDER_SUPPORT['zeroclaw']` + `_ZEROCLAW_PROVIDER_KINDS`
and adds a `litellm` branch to the config.toml template. This test
pins the CLI-facing contract: attach succeeds, and the zeroclaw
single-provider invariant (#426) still rejects a second attachment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.providers.storage import add_provider, set_provider_api_key

runner = CliRunner()


@pytest.fixture
def zeroclaw_fleet(fleet_dir: Path) -> Path:
    """Add a zeroclaw agent `clawrium-d01` to the shared fleet on wolf-i."""
    hosts_path = fleet_dir / "hosts.json"
    data = json.loads(hosts_path.read_text())
    data[0]["agents"]["clawrium-d01"] = {
        "type": "zeroclaw",
        "agent_name": "clawrium-d01",
        "version": "0.8.5",
        "installed_at": "2026-08-01T00:00:00+00:00",
        "status": "installed",
    }
    hosts_path.write_text(json.dumps(data, indent=2))
    return fleet_dir


def _seed_litellm_provider(name: str = "clawrium-gtm-litellm") -> None:
    """Seed providers.json + secrets.json with a litellm provider.

    Bypasses `clawctl provider registry create --type litellm` so we
    don't try to probe a real LiteLLM proxy in a unit test.
    """
    add_provider(
        {
            "name": name,
            "type": "litellm",
            "endpoint": "http://192.168.1.17:4000",
            "default_model": "Qwen3.8-27B-FP8",
            "available_models": ["Qwen3.8-27B-FP8"],
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


def test_attach_litellm_to_zeroclaw_succeeds(
    zeroclaw_fleet, stdin_not_tty
) -> None:
    """#976: a litellm provider attached to a zeroclaw agent is accepted
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
            "clawrium-d01",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "attached" in result.output
    assert "clawrium-gtm-litellm" in result.output

    listed = runner.invoke(
        app,
        ["agent", "provider", "get", "--agent", "clawrium-d01", "-o", "json"],
    )
    assert listed.exit_code == 0
    data = json.loads(listed.output)
    assert any(p["name"] == "clawrium-gtm-litellm" for p in data)


def test_zeroclaw_single_provider_invariant_still_holds_for_litellm(
    zeroclaw_fleet, stdin_not_tty
) -> None:
    """#426 single-provider invariant survives the #976 allow-list change.

    Attaching a second provider to a zeroclaw agent that already has a
    litellm primary must be rejected with the existing "already has
    provider" message pointing operators at `detach`.
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
            "clawrium-d01",
        ],
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        app,
        ["agent", "provider", "attach", "anth", "--agent", "clawrium-d01"],
    )
    # Pin the specific single-provider-rejection exit code (1) rather
    # than any non-zero — Typer emits exit 2 for usage errors and exit
    # 127 for command-not-found, and `!= 0` would false-pass either.
    assert second.exit_code == 1, (
        f"expected exit code 1 (single-provider rejection), got "
        f"{second.exit_code}. output:\n{second.output}"
    )
    assert "already has provider" in second.output
    assert "detach" in second.output
    assert "clawrium-gtm-litellm" in second.output


def test_zeroclaw_litellm_passes_build_render_inputs(
    zeroclaw_fleet, stdin_not_tty
) -> None:
    """#976: `build_render_inputs` is the gate that previously blocked
    the wire. Pin that a zeroclaw agent attached to a litellm provider
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
            "clawrium-d01",
        ],
    )

    inputs = build_render_inputs("clawrium-d01")
    assert inputs.agent_type == "zeroclaw"
    assert inputs.provider.type == "litellm"
    assert inputs.provider.name == "clawrium-gtm-litellm"
    assert inputs.provider.endpoint == "http://192.168.1.17:4000"
    assert inputs.provider.api_key == "sk-master-1"
    assert inputs.provider.default_model == "Qwen3.8-27B-FP8"

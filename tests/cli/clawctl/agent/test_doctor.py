"""Tests for `clawctl agent doctor` — F4 of parent #555.

The doctor command is pure-local (no SSH), so the only collaborators
to fake are `build_render_inputs` (which talks to the providers /
channels / integrations / secrets stores) and the per-type renderer
dispatch. Both are mocked so the tests run in isolation from a real
fleet.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.render import (
    AgentConfigError,
    ChannelInputs,
    IntegrationInputs,
    ProviderInputs,
    RenderInputs,
    RenderedFiles,
)


runner = CliRunner()


_OK_INPUTS = RenderInputs(
    agent_name="wise-hypatia",
    agent_type="openclaw",
    provider=ProviderInputs(
        name="anthropic-primary",
        type="anthropic",
        default_model="claude-opus",
        api_key="sk-xxx",
    ),
    channels=(
        ChannelInputs(
            name="discord-wise",
            type="discord",
            bot_token="bot-xxx",
        ),
    ),
    integrations=(
        IntegrationInputs(
            name="wise-github",
            type="github",
            credentials=(("GITHUB_TOKEN", "ghp_xxx"),),
        ),
    ),
)
_OK_FILES = RenderedFiles(
    files={
        ".openclaw/.env": "ANTHROPIC_API_KEY='sk-xxx'\nDISCORD_BOT_TOKEN='bot-xxx'\n",
    }
)


def test_doctor_unknown_agent(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "doctor", "ghost"])
    assert result.exit_code != 0
    assert "not found" in (result.output + (result.stderr or ""))


def test_doctor_ok_table(fleet_dir, monkeypatch) -> None:
    from clawrium.cli.clawctl.agent import doctor as doctor_mod

    monkeypatch.setattr(doctor_mod, "build_render_inputs", lambda name: _OK_INPUTS)
    monkeypatch.setattr(doctor_mod, "render_openclaw", lambda inputs: _OK_FILES)

    result = runner.invoke(app, ["agent", "doctor", "wise-hypatia"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Name:    wise-hypatia" in out
    assert "Status:  ok" in out
    assert "anthropic-primary" in out
    assert "discord-wise" in out
    assert "wise-github" in out
    assert ".openclaw/.env" in out
    # Secret values must never appear; only presence.
    assert "sk-xxx" not in out
    assert "bot-xxx" not in out
    assert "ghp_xxx" not in out
    assert "api_key:        present" in out


def test_doctor_ok_json(fleet_dir, monkeypatch) -> None:
    from clawrium.cli.clawctl.agent import doctor as doctor_mod

    monkeypatch.setattr(doctor_mod, "build_render_inputs", lambda name: _OK_INPUTS)
    monkeypatch.setattr(doctor_mod, "render_openclaw", lambda inputs: _OK_FILES)

    result = runner.invoke(app, ["agent", "doctor", "wise-hypatia", "-o", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list) and len(payload) == 1
    row = payload[0]
    assert row["name"] == "wise-hypatia"
    assert row["status"] == "ok"
    assert row["inputs"]["provider"]["api_key"] == "present"
    assert row["inputs"]["channels"][0]["name"] == "discord-wise"
    assert row["files"][0]["path"] == ".openclaw/.env"
    assert row["files"][0]["bytes"] > 0
    assert len(row["files"][0]["sha256_prefix"]) == 16


def test_doctor_broken_surfaces_error(fleet_dir, monkeypatch) -> None:
    from clawrium.cli.clawctl.agent import doctor as doctor_mod

    def _raise(name: str):
        raise AgentConfigError("provider 'foo' not registered in providers.json")

    monkeypatch.setattr(doctor_mod, "build_render_inputs", _raise)

    result = runner.invoke(app, ["agent", "doctor", "wise-hypatia"])
    # Non-zero exit so CI / shell pipelines can gate on doctor.
    assert result.exit_code != 0
    assert "Status:  broken" in result.output
    assert "provider 'foo'" in result.output


def test_doctor_broken_json_includes_error(fleet_dir, monkeypatch) -> None:
    from clawrium.cli.clawctl.agent import doctor as doctor_mod

    def _raise(name: str):
        raise AgentConfigError("channel 'discord-x' is missing BOT_TOKEN")

    monkeypatch.setattr(doctor_mod, "build_render_inputs", _raise)

    result = runner.invoke(app, ["agent", "doctor", "wise-hypatia", "-o", "json"])
    assert result.exit_code != 0
    # The JSON payload still prints to stdout before the non-zero exit.
    # Extract the first JSON-array prefix.
    body = result.output
    arr_end = body.rfind("]")
    payload = json.loads(body[: arr_end + 1])
    assert payload[0]["status"] == "broken"
    assert "BOT_TOKEN" in payload[0]["error"]

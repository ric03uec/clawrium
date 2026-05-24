"""Tests for `clawctl agent provider attach|detach|get`."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _create_provider(name: str = "anth"):
    return runner.invoke(
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


def test_attach_writes_into_agent_record(fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"],
    )
    assert result.exit_code == 0, result.output
    assert "attached" in result.output

    listed = runner.invoke(
        app, ["agent", "provider", "get", "--agent", "wise-hypatia", "-o", "json"]
    )
    assert listed.exit_code == 0
    data = json.loads(listed.output)
    assert any(p["name"] == "anth" for p in data)


def test_attach_unknown_provider_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "ghost", "--agent", "wise-hypatia"],
    )
    assert result.exit_code != 0
    assert "not found" in result.output


def test_detach_removes_from_agent_record(fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    runner.invoke(
        app, ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"]
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "anth", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0
    assert "detached" in result.output


def test_get_empty_lists_no_rows(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "provider", "get", "--agent", "wise-hypatia"])
    assert result.exit_code == 0


def test_attach_unknown_agent_fails(fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "anth", "--agent", "no-such-agent"],
    )
    assert result.exit_code != 0

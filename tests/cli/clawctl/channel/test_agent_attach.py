"""Tests for `clawctl agent channel attach|detach|get`."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _create_channel(name: str = "ch") -> None:
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            name,
            "--type",
            "discord",
            "--token",
            "t",
        ],
    )


def test_attach_writes_into_agent_record(fleet_dir, stdin_not_tty) -> None:
    _create_channel("ch")
    result = runner.invoke(
        app, ["agent", "channel", "attach", "ch", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0, result.output
    assert "attached" in result.output

    listed = runner.invoke(
        app, ["agent", "channel", "get", "--agent", "wise-hypatia", "-o", "json"]
    )
    assert listed.exit_code == 0
    data = json.loads(listed.output)
    assert any(c["name"] == "ch" for c in data)


def test_attach_unknown_channel_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app, ["agent", "channel", "attach", "ghost", "--agent", "wise-hypatia"]
    )
    assert result.exit_code != 0


def test_detach_removes_channel(fleet_dir, stdin_not_tty) -> None:
    _create_channel("ch")
    runner.invoke(app, ["agent", "channel", "attach", "ch", "--agent", "wise-hypatia"])
    result = runner.invoke(
        app, ["agent", "channel", "detach", "ch", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0


def test_get_empty_table(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "channel", "get", "--agent", "wise-hypatia"])
    assert result.exit_code == 0

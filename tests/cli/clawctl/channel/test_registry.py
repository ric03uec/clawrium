"""Tests for `clawctl channel registry` CRUD verbs (new Pattern A noun)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _channels_file(fleet_dir: Path) -> Path:
    return fleet_dir / "channels.json"


def test_create_discord_non_interactive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "my-discord",
            "--type",
            "discord",
            "--token",
            "bot-token",
            "--allowed-user",
            "123",
            "--allowed-channel",
            "456",
            "--require-mention",
        ],
    )
    assert result.exit_code == 0, result.output
    # New file is created at $XDG_CONFIG_HOME/clawrium/channels.json.
    assert _channels_file(fleet_dir).exists()
    payload = json.loads(_channels_file(fleet_dir).read_text())
    assert payload[0]["name"] == "my-discord"
    assert payload[0]["type"] == "discord"
    cfg = payload[0]["config"]
    assert cfg["allowed_users"] == ["123"]
    assert cfg["allowed_channels"] == ["456"]
    assert cfg["require_mention"] is True
    # Bot token is never written to channels.json in plaintext.
    assert "bot-token" not in _channels_file(fleet_dir).read_text()


def test_create_slack_with_stream_mode(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "my-slack",
            "--type",
            "slack",
            "--token",
            "xoxb-bot",
            "--app-token",
            "xapp-token",
            "--home-channel",
            "C12345",
            "--stream-mode",
            "replace",
            "--stream-delay",
            "100",
        ],
    )
    assert result.exit_code == 0, result.output


def test_create_token_stdin_reads_value(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "stdin-discord",
            "--type",
            "discord",
            "--token-stdin",
        ],
        input="piped-bot-token\n",
    )
    assert result.exit_code == 0, result.output


def test_create_requires_token(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "no-tok",
            "--type",
            "discord",
        ],
    )
    assert result.exit_code != 0
    assert "missing required flag --token" in result.output


def test_create_rejects_invalid_type(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "bad",
            "--type",
            "irc",
            "--token",
            "t",
        ],
    )
    assert result.exit_code != 0


def test_create_duplicate_fails(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "dup",
            "--type",
            "discord",
            "--token",
            "t",
        ],
    )
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "dup",
            "--type",
            "discord",
            "--token",
            "t",
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_create_app_token_rejected_on_discord(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "bad-d",
            "--type",
            "discord",
            "--token",
            "t",
            "--app-token",
            "x",
        ],
    )
    assert result.exit_code != 0


def test_get_lists_channels(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "c1",
            "--type",
            "discord",
            "--token",
            "t",
        ],
    )
    result = runner.invoke(app, ["channel", "registry", "get"])
    assert result.exit_code == 0
    assert "c1" in result.output
    assert "discord" in result.output


def test_describe_known(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "d1",
            "--type",
            "slack",
            "--token",
            "t",
            "--home-channel",
            "C42",
        ],
    )
    result = runner.invoke(app, ["channel", "registry", "describe", "d1"])
    assert result.exit_code == 0
    assert "Type:" in result.output
    assert "slack" in result.output
    assert "C42" in result.output


def test_edit_replaces_stream_mode(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "e1",
            "--type",
            "slack",
            "--token",
            "t",
            "--stream-mode",
            "replace",
        ],
    )
    result = runner.invoke(
        app,
        ["channel", "registry", "edit", "e1", "--stream-mode", "append"],
    )
    assert result.exit_code == 0
    desc = runner.invoke(app, ["channel", "registry", "describe", "e1", "-o", "json"])
    data = json.loads(desc.output)
    assert data[0]["stream_mode"] == "append"


def test_delete_requires_yes(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "dx",
            "--type",
            "discord",
            "--token",
            "t",
        ],
    )
    result = runner.invoke(app, ["channel", "registry", "delete", "dx"])
    assert result.exit_code != 0
    assert "--yes" in result.output


def test_delete_with_yes_succeeds(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "dy",
            "--type",
            "discord",
            "--token",
            "t",
        ],
    )
    result = runner.invoke(app, ["channel", "registry", "delete", "dy", "--yes"])
    assert result.exit_code == 0
    desc = runner.invoke(app, ["channel", "registry", "describe", "dy"])
    assert desc.exit_code != 0


def test_delete_oserror_surfaces_zombie_hint(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """ATX iter-2 W-NEW-3: when the atomic write fails after creds
    are cleared, the CLI surface must catch OSError and emit a clear
    error pointing the user at `--force`. A raw Python traceback is
    not acceptable."""
    from clawrium.core import channels as core_channels

    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "zb",
            "--type",
            "discord",
            "--token",
            "t",
        ],
    )

    def boom(channels, config_dir):
        raise OSError("disk full")

    monkeypatch.setattr(core_channels, "_save_channels_atomic", boom)

    result = runner.invoke(app, ["channel", "registry", "delete", "zb", "--yes"])
    assert result.exit_code != 0
    assert "zombie" in result.output
    assert "--force" in result.output

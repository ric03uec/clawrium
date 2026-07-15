"""Tests for `clawctl agent chat` (ATX iter-1 B8, issue #918)."""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_chat_unknown_agent_errors(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "chat", "no-such-agent"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_chat_once_forwards_flag_to_legacy(fleet_dir, monkeypatch) -> None:
    """Issue #918: `--once` must reach the delegated chat implementation
    verbatim so the single-shot path can consume it."""
    called: list[dict] = []

    def fake_chat(**kwargs):
        called.append(kwargs)

    monkeypatch.setattr("clawrium.cli.chat.chat", fake_chat)
    result = runner.invoke(app, ["agent", "chat", "wise-hypatia", "--once", "hi"])
    assert result.exit_code == 0
    assert len(called) == 1
    assert called[0]["agent_name"] == "wise-hypatia"
    assert called[0]["once"] == "hi"


def test_chat_without_once_invokes_backend(fleet_dir, monkeypatch) -> None:
    called: list[dict] = []

    def fake_chat(**kwargs):
        called.append(kwargs)

    monkeypatch.setattr("clawrium.cli.chat.chat", fake_chat)
    result = runner.invoke(app, ["agent", "chat", "wise-hypatia"])
    assert result.exit_code == 0
    assert len(called) == 1
    assert called[0]["agent_name"] == "wise-hypatia"
    assert called[0]["once"] is None

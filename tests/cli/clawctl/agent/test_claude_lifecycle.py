"""CLI contracts for the install-only Claude Code agent type (#996)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.agent_lifecycle import (
    incomplete_install_message,
    lifecycle_not_applicable_message,
)

runner = CliRunner()


def _add_claude_agent(fleet_dir) -> None:
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["claude-code"] = {
        "type": "claude",
        "agent_name": "claude-code",
        "version": "2.1.100",
        "status": "installed",
        "installed_at": "2026-10-03T00:00:00+00:00",
        "config": {},
    }
    hosts_path.write_text(json.dumps(hosts, indent=2))


def test_claude_is_visible_in_get_and_describe(fleet_dir) -> None:
    _add_claude_agent(fleet_dir)

    listed = runner.invoke(app, ["agent", "get", "-o", "name"])
    detail = runner.invoke(app, ["agent", "describe", "claude-code"])

    assert listed.exit_code == 0
    assert "agent/claude-code" in listed.output
    assert detail.exit_code == 0
    assert "claude" in detail.output.lower()


def test_claude_open_remains_manifest_capability_unavailable(fleet_dir) -> None:
    _add_claude_agent(fleet_dir)

    result = runner.invoke(app, ["agent", "open", "claude-code", "--print-url"])

    assert result.exit_code != 0
    assert "no web ui" in result.output.lower()


@pytest.mark.parametrize("verb", ["start", "stop", "restart", "logs"])
def test_claude_daemon_operations_are_not_applicable(
    fleet_dir, monkeypatch, verb: str
) -> None:
    _add_claude_agent(fleet_dir)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("daemon lifecycle must not be invoked for Claude Code")

    if verb == "start":
        monkeypatch.setattr("clawrium.cli.clawctl.agent.start.start_agent", _unexpected)
    elif verb == "stop":
        monkeypatch.setattr("clawrium.cli.clawctl.agent.stop.stop_agent", _unexpected)
    elif verb == "restart":
        monkeypatch.setattr(
            "clawrium.cli.clawctl.agent.restart.restart_agent", _unexpected
        )
    else:
        monkeypatch.setattr(
            "clawrium.core.lifecycle._run_lifecycle_playbook", _unexpected
        )

    result = runner.invoke(app, ["agent", verb, "claude-code"])

    assert result.exit_code != 0
    assert lifecycle_not_applicable_message("claude", verb) in result.output


def test_claude_sync_and_configure_are_clear_noops_without_renderer(
    fleet_dir, monkeypatch
) -> None:
    _add_claude_agent(fleet_dir)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("canonical renderer must not run for Claude Code")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", _unexpected
    )

    sync_result = runner.invoke(app, ["agent", "sync", "claude-code"])
    configure_result = runner.invoke(app, ["agent", "configure", "claude-code"])

    assert sync_result.exit_code == 0
    assert configure_result.exit_code == 0
    for result in (sync_result, configure_result):
        assert "installed CLI" in result.output
        assert "no daemon configuration is managed" in result.output


@pytest.mark.parametrize("verb", ["sync", "configure"])
def test_incomplete_claude_install_rejects_cli_reconcile(
    fleet_dir, monkeypatch, verb: str
) -> None:
    _add_claude_agent(fleet_dir)
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["claude-code"].update(
        {"status": "failed", "installed_at": None}
    )
    hosts_path.write_text(json.dumps(hosts, indent=2))

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("canonical sync must not run for an incomplete install")
        ),
    )
    result = runner.invoke(app, ["agent", verb, "claude-code"])

    assert result.exit_code != 0
    assert incomplete_install_message("claude", verb) in result.output

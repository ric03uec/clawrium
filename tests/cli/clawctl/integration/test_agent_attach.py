"""Tests for `clawctl agent integration attach|detach|get`."""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _create_integration(name: str = "gh") -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            name,
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )


def test_attach_writes_into_agent_record(fleet_dir, stdin_not_tty) -> None:
    _create_integration("gh")
    result = runner.invoke(
        app,
        ["agent", "integration", "attach", "gh", "--agent", "wise-hypatia"],
    )
    assert result.exit_code == 0, result.output


def test_detach_removes(fleet_dir, stdin_not_tty) -> None:
    _create_integration("gh")
    runner.invoke(
        app, ["agent", "integration", "attach", "gh", "--agent", "wise-hypatia"]
    )
    result = runner.invoke(
        app, ["agent", "integration", "detach", "gh", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0


def test_get_lists_attachments(fleet_dir, stdin_not_tty) -> None:
    _create_integration("gh")
    runner.invoke(
        app, ["agent", "integration", "attach", "gh", "--agent", "wise-hypatia"]
    )
    result = runner.invoke(
        app, ["agent", "integration", "get", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0
    assert "gh" in result.output


def test_attach_unknown_integration_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        ["agent", "integration", "attach", "ghost", "--agent", "wise-hypatia"],
    )
    assert result.exit_code != 0

"""Tests for the non-interactive contract on `clawctl agent`."""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_configure_stdin_closed_missing_stage_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "configure", "wise-hypatia"])
    assert result.exit_code != 0
    assert "Error: missing required flag --stage" in result.output


def test_configure_stdin_closed_providers_stage_requires_provider(
    fleet_dir, stdin_not_tty
) -> None:
    result = runner.invoke(
        app, ["agent", "configure", "wise-hypatia", "--stage", "providers"]
    )
    assert result.exit_code != 0
    assert "Error: missing required flag --provider" in result.output


def test_create_stdin_closed_missing_type_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "create", "x", "--host", "wolf-i", "--yes"])
    assert result.exit_code != 0
    assert "Error: missing required flag --type" in result.output


def test_create_stdin_closed_missing_host_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "create", "x", "--type", "openclaw", "--yes"])
    assert result.exit_code != 0
    assert "Error: missing required flag --host" in result.output


def test_create_rejects_shell_metachar_host(fleet_dir, stdin_not_tty) -> None:
    """ATX iter-3 S1: `--host` flows through `validate_hostname`."""
    result = runner.invoke(
        app,
        [
            "agent",
            "create",
            "x",
            "--type",
            "openclaw",
            "--host",
            "host;ls",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "invalid" in result.output


def test_create_rejects_oversized_label_host(fleet_dir, stdin_not_tty) -> None:
    """ATX iter-3 S1: hostname label > 63 chars rejected via `--host`."""
    bad_host = ("a" * 64) + ".com"
    result = runner.invoke(
        app,
        [
            "agent",
            "create",
            "x",
            "--type",
            "openclaw",
            "--host",
            bad_host,
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "invalid" in result.output


def test_delete_stdin_closed_without_yes_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "delete", "wise-hypatia"])
    assert result.exit_code != 0
    assert "--yes" in result.output


def test_exec_is_placeholder(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "exec", "wise-hypatia", "echo", "hi"])
    assert result.exit_code == 0
    assert "Not implemented: agent exec" in result.output


def test_registry_get_lists_supported_types(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "registry", "get"])
    assert result.exit_code == 0
    # The real clawrium platform registry ships at least one type.
    assert "NAME" in result.output


def test_registry_describe_unknown_type_errors(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "registry", "describe", "no-such-type"])
    assert result.exit_code != 0


def test_logs_placeholder_emits_event(fleet_dir) -> None:
    # ATX iter-2 W3: text-mode placeholder uses canonical
    # `Not implemented: agent logs` line. JSON mode tested separately
    # in test_logs_json_emits_json.
    result = runner.invoke(app, ["agent", "logs", "wise-hypatia", "--tail", "3"])
    assert result.exit_code == 0
    assert "Not implemented: agent logs" in result.output


def test_logs_json_emits_json(fleet_dir) -> None:
    import json

    result = runner.invoke(
        app, ["agent", "logs", "wise-hypatia", "--tail", "3", "-o", "json"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.output.strip())
    assert parsed["level"] == "info"
    assert "Not implemented: agent logs" in parsed["msg"]

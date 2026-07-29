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


def test_registry_get_lists_supported_types(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "registry", "get"])
    assert result.exit_code == 0
    # The real clawrium platform registry ships at least one type.
    assert "NAME" in result.output


def test_registry_describe_unknown_type_errors(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "registry", "describe", "no-such-type"])
    assert result.exit_code != 0


def _stamp_openclaw_sandbox(fleet_dir) -> None:
    import json

    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    config = hosts[0]["agents"]["openclaw"].setdefault("config", {})
    config["runtime"] = "nemoclaw"
    config["sandbox_name"] = "wise-hypatia"
    hosts_path.write_text(json.dumps(hosts, indent=2))


def test_logs_delegates_openclaw_to_nemoclaw(fleet_dir, monkeypatch) -> None:
    """ATX iter-1 W1: capture kwargs so we actually assert delegation
    parameters — the output-string check alone would pass even if the
    playbook was invoked with the wrong operation or sandbox_name."""
    _stamp_openclaw_sandbox(fleet_dir)
    from clawrium.core import lifecycle

    captured: dict = {}

    def _spy(**kwargs):
        captured.update(kwargs)
        return (True, None)

    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _spy)
    result = runner.invoke(app, ["agent", "logs", "wise-hypatia", "--tail", "3"])
    assert result.exit_code == 0
    assert "logs read from NemoClaw sandbox" in result.output
    # Pin delegation contract: operation + agent-type/name routed to
    # the openclaw playbook (which internally runs `nemoclaw logs
    # <sandbox>`). agent_name is the hosts.json record key that the
    # CLI resolves from the input alias.
    assert captured.get("operation") == "logs"
    assert captured.get("agent_type") == "openclaw"
    assert captured.get("agent_name") == "openclaw"
    assert captured.get("hostname"), "hostname must be threaded through"


def test_logs_json_emits_json(fleet_dir) -> None:
    import json

    result = runner.invoke(
        app, ["agent", "logs", "wise-hypatia", "--tail", "3", "-o", "json"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.output.strip())
    assert parsed["level"] == "info"
    assert "NemoClaw log streaming" in parsed["msg"]

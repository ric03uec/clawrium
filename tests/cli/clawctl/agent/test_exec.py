"""Tests for `clawctl agent exec`.

Mocks `core.agent_exec.run_agent_exec` to keep the suite hermetic.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import exec as exec_module
from clawrium.core.agent_exec import AgentExecError

runner = CliRunner()


@pytest.fixture
def exec_fleet(fleet_dir):
    """Augment the shared fleet with hermes + zeroclaw agents for B5 coverage."""
    import json

    hosts_path = fleet_dir / "hosts.json"
    data = json.loads(hosts_path.read_text())
    data[0]["agents"]["espresso"] = {
        "type": "hermes",
        "agent_name": "espresso",
        "version": "0.14.0",
        "installed_at": "2026-05-25T00:00:00+00:00",
        "status": "installed",
    }
    data[0]["agents"]["clawrium-d01"] = {
        "type": "zeroclaw",
        "agent_name": "clawrium-d01",
        "version": "0.7.5",
        "installed_at": "2026-05-25T00:00:00+00:00",
        "status": "installed",
    }
    hosts_path.write_text(json.dumps(data, indent=2))
    return fleet_dir


@pytest.fixture
def stub_exec(monkeypatch: pytest.MonkeyPatch):
    calls: dict = {}

    def fake(hostname, agent_name, claw_type, cmd_argv, timeout=120):
        calls.update(
            {
                "hostname": hostname,
                "agent_name": agent_name,
                "claw_type": claw_type,
                "cmd_argv": cmd_argv,
            }
        )
        return calls.get("_stdout", "ok\n"), calls.get("_stderr", ""), calls.get(
            "_rc", 0
        )

    monkeypatch.setattr(exec_module, "run_agent_exec", fake)
    return calls


def test_exec_success(fleet_dir, stdin_not_tty, stub_exec):
    result = runner.invoke(
        app, ["agent", "exec", "wise-hypatia", "--", "--version"]
    )
    assert result.exit_code == 0, result.output
    assert "ok" in result.output
    assert stub_exec["claw_type"] == "openclaw"
    assert stub_exec["cmd_argv"] == ["--version"]


def test_exec_nonzero_exit_propagation(fleet_dir, stdin_not_tty, stub_exec):
    stub_exec["_rc"] = 7
    stub_exec["_stderr"] = "boom\n"
    result = runner.invoke(
        app, ["agent", "exec", "wise-hypatia", "--", "bogus"]
    )
    assert result.exit_code == 7
    assert "boom" in result.output


def test_exec_unknown_agent(fleet_dir, stdin_not_tty, stub_exec):
    result = runner.invoke(
        app, ["agent", "exec", "does-not-exist", "--", "echo", "hi"]
    )
    assert result.exit_code != 0
    assert "not found" in result.output


def test_exec_unreachable_host(fleet_dir, stdin_not_tty, stub_exec):
    stub_exec["_rc"] = 255
    stub_exec["_stderr"] = "Host unreachable: ssh failed"
    result = runner.invoke(
        app, ["agent", "exec", "wise-hypatia", "--", "x"]
    )
    assert result.exit_code == 255
    assert "unreachable" in result.output.lower()


def test_exec_requires_command(fleet_dir, stdin_not_tty, stub_exec):
    result = runner.invoke(app, ["agent", "exec", "wise-hypatia"])
    assert result.exit_code != 0


def test_exec_help_documents_double_dash(fleet_dir):
    result = runner.invoke(app, ["agent", "exec", "--help"])
    assert result.exit_code == 0
    assert "--" in result.output


def test_exec_stdout_and_stderr_both_emitted(fleet_dir, stdin_not_tty, stub_exec):
    stub_exec["_stdout"] = "out line\n"
    stub_exec["_stderr"] = "err line\n"
    result = runner.invoke(
        app, ["agent", "exec", "wise-hypatia", "--", "x"]
    )
    assert result.exit_code == 0
    assert "out line" in result.output
    assert "err line" in result.output


def test_exec_works_without_dash_dash(fleet_dir, stdin_not_tty, stub_exec):
    """B4: `--version` (no `--`) must pass through, not raise Typer error."""
    result = runner.invoke(app, ["agent", "exec", "wise-hypatia", "--version"])
    assert result.exit_code == 0, result.output
    assert stub_exec["cmd_argv"] == ["--version"]


@pytest.mark.parametrize(
    "agent,expected_type",
    [
        ("wise-hypatia", "openclaw"),
        ("espresso", "hermes"),
        ("clawrium-d01", "zeroclaw"),
    ],
)
def test_exec_routes_by_claw_type(
    exec_fleet, stdin_not_tty, stub_exec, agent, expected_type
):
    """B5: hermes/zeroclaw must route through the dispatcher with correct type."""
    result = runner.invoke(app, ["agent", "exec", agent, "--", "--version"])
    assert result.exit_code == 0, result.output
    assert stub_exec["claw_type"] == expected_type


def test_exec_agent_exec_error_from_core(
    fleet_dir, stdin_not_tty, monkeypatch
):
    """B6: AgentExecError raised by core surfaces as exit 2 with the message."""
    def boom(**kw):
        raise AgentExecError("unsupported binary")

    monkeypatch.setattr(exec_module, "run_agent_exec", boom)
    result = runner.invoke(app, ["agent", "exec", "wise-hypatia", "--", "x"])
    assert result.exit_code == 2
    assert "unsupported binary" in result.output


def test_exec_strips_bidi_from_remote_stdout(
    fleet_dir, stdin_not_tty, stub_exec
):
    """B1: U+202E injected by a remote agent must not reach the terminal."""
    stub_exec["_stdout"] = "ok" + chr(0x202E) + "danger\n"
    result = runner.invoke(app, ["agent", "exec", "wise-hypatia", "--", "x"])
    assert result.exit_code == 0
    assert chr(0x202E) not in result.output
    # Whitespace (newline) preserved.
    assert "okdanger" in result.output


def test_exec_preserves_remote_newlines(fleet_dir, stdin_not_tty, stub_exec):
    """sanitize_passthrough must not strip \\n the way sanitize() does."""
    stub_exec["_stdout"] = "line1\nline2\nline3\n"
    result = runner.invoke(app, ["agent", "exec", "wise-hypatia", "--", "x"])
    assert result.exit_code == 0
    assert "line1\nline2\nline3" in result.output

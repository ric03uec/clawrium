"""Behavioral install-only Pi CLI contracts (#1032)."""

import json
import pytest
from typer.testing import CliRunner
from clawrium.cli import app
from clawrium.core.agent_lifecycle import lifecycle_not_applicable_message

runner = CliRunner()


def add_pi(fleet_dir):
    p = fleet_dir / "hosts.json"
    d = json.loads(p.read_text())
    d[0]["agents"]["pi-test"] = {
        "type": "pi",
        "agent_name": "pi-test",
        "version": "0.73.1",
        "status": "installed",
        "installed_at": "2026-10-06T00:00:00+00:00",
    }
    p.write_text(json.dumps(d))


@pytest.mark.parametrize("verb", ["start", "stop", "restart", "logs", "status"])
def test_pi_daemon_operations_do_not_reach_backend(fleet_dir, monkeypatch, verb):
    add_pi(fleet_dir)
    monkeypatch.setattr(
        "clawrium.core.lifecycle._run_lifecycle_playbook",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("backend called")),
    )
    result = runner.invoke(app, ["agent", verb, "pi-test"])
    if verb == "status":
        assert result.exit_code == 0
        assert "Pi is install-only" in result.output
        assert "no daemon status is available" in result.output
    else:
        assert result.exit_code != 0
        assert lifecycle_not_applicable_message("pi", verb) in result.output


@pytest.mark.parametrize("agent_type", ["pi", "openclaw"])
def test_start_preserves_gateway_dispatch_and_rejects_daemonless_pi(
    fleet_dir, monkeypatch, agent_type
):
    agents = json.loads((fleet_dir / "hosts.json").read_text())
    name = f"{agent_type}-dispatch"
    agents[0]["agents"][name] = {
        "type": agent_type,
        "agent_name": name,
        "version": "0.73.1",
        "status": "installed",
    }
    (fleet_dir / "hosts.json").write_text(json.dumps(agents))
    calls = []

    def fake_start(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    monkeypatch.setattr("clawrium.cli.clawctl.agent.start.start_agent", fake_start)
    result = runner.invoke(app, ["agent", "start", name])
    if agent_type == "pi":
        assert result.exit_code != 0
        assert calls == []
        assert "does not run a daemon" in result.output
    else:
        assert result.exit_code == 0, result.output
        assert calls and calls[0]["claw_name"] == "openclaw"
        assert calls[0]["agent_name"] == name


def test_pi_configure_help_discloses_unsupported_provider_configuration():
    result = runner.invoke(app, ["agent", "configure", "--help"])
    assert result.exit_code == 0
    assert "Pi provider configuration is unavailable" in result.output


def test_pi_exec_success_emits_native_output(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    calls = []

    def fake(**kw):
        calls.append(kw)
        return "0.73.1\n", "", 0

    monkeypatch.setattr("clawrium.cli.clawctl.agent.exec.run_agent_exec", fake)
    result = runner.invoke(app, ["agent", "exec", "pi-test", "--", "--version"])
    assert result.exit_code == 0
    assert result.output == "0.73.1\n"
    assert calls == [
        {
            "hostname": "10.0.0.1",
            "agent_name": "pi-test",
            "claw_type": "pi",
            "cmd_argv": ["--version"],
        }
    ]


def test_pi_exec_dispatch_and_nonzero(fleet_dir, monkeypatch):
    add_pi(fleet_dir)
    calls = []

    def fake(**kw):
        calls.append(kw)
        return "", "pi failed\n", 9

    monkeypatch.setattr("clawrium.cli.clawctl.agent.exec.run_agent_exec", fake)
    result = runner.invoke(app, ["agent", "exec", "pi-test", "--", "--version"])
    assert result.exit_code == 9 and "pi failed" in result.output
    assert calls == [
        {
            "hostname": "10.0.0.1",
            "agent_name": "pi-test",
            "claw_type": "pi",
            "cmd_argv": ["--version"],
        }
    ]

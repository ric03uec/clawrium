"""#1071 phase 2: web-UI tunnel gating regressions.

`clawctl agent open` and `clawctl agent port-forward` must refuse the
daemonless install-only runtimes (Claude Code, Codex, Pi) before
touching the resolver / tunnel manager, and must continue to run the
resolver for the daemon runtimes (OpenClaw, Hermes, ZeroClaw). This
file locks both halves in.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.web_ui import DAEMONLESS_AGENT_TYPES


runner = CliRunner()


def _seed_agent(fleet_dir, *, name: str, agent_type: str) -> None:
    path = fleet_dir / "hosts.json"
    data = json.loads(path.read_text())
    data[0]["agents"][name] = {
        "type": agent_type,
        "agent_name": name,
        "version": "0.73.1",
        "status": "installed",
        "installed_at": "2026-10-06T00:00:00+00:00",
    }
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("agent_type", sorted(DAEMONLESS_AGENT_TYPES))
def test_open_refuses_daemonless_agents(fleet_dir, monkeypatch, agent_type):
    """`agent open` must exit non-zero for Claude Code / Codex / Pi."""
    _seed_agent(fleet_dir, name=f"{agent_type}-inst", agent_type=agent_type)

    def _boom(*_args, **_kwargs):
        raise AssertionError("resolve_web_ui must not be called for daemonless agents")

    monkeypatch.setattr("clawrium.core.web_ui.resolve", _boom)
    result = runner.invoke(app, ["agent", "open", f"{agent_type}-inst", "--print-url"])
    assert result.exit_code != 0
    assert "daemonless install-only agent" in result.output
    assert "SSH to the agent host" in result.output


@pytest.mark.parametrize("agent_type", sorted(DAEMONLESS_AGENT_TYPES))
def test_port_forward_refuses_daemonless_agents(fleet_dir, monkeypatch, agent_type):
    """`agent port-forward` must exit non-zero for Claude Code / Codex / Pi."""
    _seed_agent(fleet_dir, name=f"{agent_type}-inst", agent_type=agent_type)

    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "tunnel manager must not be called for daemonless agents"
        )

    monkeypatch.setattr("clawrium.core.web_ui_tunnel.ensure", _boom)
    result = runner.invoke(
        app, ["agent", "port-forward", f"{agent_type}-inst", "22"]
    )
    assert result.exit_code != 0
    assert "daemonless install-only agent" in result.output
    assert "SSH to the agent host" in result.output


@pytest.mark.parametrize("agent_type", ["openclaw", "hermes", "zeroclaw"])
def test_open_hits_resolver_for_daemon_agents(fleet_dir, monkeypatch, agent_type):
    """`agent open` must still reach `resolve_web_ui` for daemon agents.

    A sentinel resolver proves gating does not apply to the daemon
    runtimes — the gating check short-circuits only for the three
    daemonless types.
    """
    _seed_agent(fleet_dir, name=f"{agent_type}-inst", agent_type=agent_type)

    resolve_calls: list[str] = []

    def _fake_resolve(name):
        resolve_calls.append(name)
        return None  # pretend the manifest has no features.web_ui

    monkeypatch.setattr("clawrium.cli.clawctl.agent.open.resolve_web_ui", _fake_resolve)
    result = runner.invoke(app, ["agent", "open", f"{agent_type}-inst", "--print-url"])
    # The resolver returned None, so the CLI emits the generic
    # "no web UI" message. What matters here is that we DID reach the
    # resolver — i.e., we were not short-circuited by the daemonless
    # gating check.
    assert resolve_calls == [f"{agent_type}-inst"]
    assert result.exit_code != 0
    assert "daemonless install-only agent" not in result.output


def test_daemonless_types_set_is_exactly_the_three():
    """Regression — the daemonless set must not drift without a code review."""
    assert DAEMONLESS_AGENT_TYPES == frozenset({"claude", "codex", "pi"})

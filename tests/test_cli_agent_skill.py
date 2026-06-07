"""Tests for the legacy `clm agent skill` CLI surface (#411).

The active surface is `clawctl agent skill`. These tests cover the
legacy entrypoint kept around for cli/main.py imports.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from clawrium.cli import agent_skill as cli_agent_skill
from clawrium.cli.agent_skill import agent_skill_app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    from clawrium.core import skills_state as state_mod

    monkeypatch.setattr(state_mod, "get_config_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def hermes_agent(monkeypatch):
    host = {"hostname": "h", "alias": "h", "user": "xclm"}
    monkeypatch.setattr(
        cli_agent_skill,
        "get_agent_by_name",
        lambda name: (host, "hermes", {"agent_name": name}),
    )
    return host


@pytest.fixture
def openclaw_agent(monkeypatch):
    host = {"hostname": "h", "alias": "h", "user": "xclm"}
    monkeypatch.setattr(
        cli_agent_skill,
        "get_agent_by_name",
        lambda name: (host, "openclaw", {"agent_name": name}),
    )
    return host


@pytest.fixture
def stub_apply(monkeypatch):
    """Patch apply_state to succeed without doing host I/O."""
    monkeypatch.setattr(
        cli_agent_skill,
        "apply_state",
        lambda agent: SimpleNamespace(
            agent_name=agent,
            agent_type="hermes",
            hostname="h",
            applied_skills=[],
            log_dir="/tmp/log",
        ),
    )


def test_list_empty(runner, cfg_dir, hermes_agent):
    result = runner.invoke(agent_skill_app, ["list", "agent-x"])
    assert result.exit_code == 0
    assert "No skills installed" in result.output


def test_install_supported_claw(runner, cfg_dir, hermes_agent, stub_apply):
    result = runner.invoke(agent_skill_app, ["install", "agent-x", "vetted/tdd"])
    assert result.exit_code == 0, result.output
    assert "Installed" in result.output


def test_install_unsupported_claw(runner, cfg_dir, openclaw_agent, stub_apply):
    result = runner.invoke(agent_skill_app, ["install", "agent-x", "vetted/tdd"])
    assert result.exit_code != 0
    assert "not yet supported" in result.output.lower()


def test_install_bare_ref_rejected(runner, cfg_dir, hermes_agent, stub_apply):
    result = runner.invoke(agent_skill_app, ["install", "agent-x", "tdd"])
    assert result.exit_code != 0
    assert "missing a source prefix" in result.output.lower()


def test_remove_idempotent(runner, cfg_dir, hermes_agent, stub_apply):
    result = runner.invoke(agent_skill_app, ["remove", "agent-x", "vetted/tdd"])
    assert result.exit_code == 0


def test_install_then_list(runner, cfg_dir, hermes_agent, stub_apply):
    runner.invoke(agent_skill_app, ["install", "agent-x", "vetted/tdd"])
    result = runner.invoke(agent_skill_app, ["list", "agent-x"])
    assert result.exit_code == 0
    assert "vetted/tdd" in result.output

"""Tests for the per-agent skills GUI routes (#411).

Smoke-level coverage of GET /api/agents/{key}/skills and
POST/DELETE /api/agents/{key}/skills/{source}/{name} against the new
unified vetted+local catalog and the SUPPORTED_CLAWS_BY_DEFAULT gate.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from clawrium.gui.routes import agents as agents_route
from clawrium.gui.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def hermes_agent(monkeypatch):
    host = {"hostname": "h", "alias": "h", "user": "xclm"}
    monkeypatch.setattr(
        agents_route,
        "_resolve_agent",
        lambda key: (host, "hermes", {"agent_name": key}),
    )
    return host


@pytest.fixture
def openclaw_agent(monkeypatch):
    host = {"hostname": "h", "alias": "h", "user": "xclm"}
    monkeypatch.setattr(
        agents_route,
        "_resolve_agent",
        lambda key: (host, "openclaw", {"agent_name": key}),
    )
    return host


@pytest.fixture
def stub_apply(monkeypatch):
    monkeypatch.setattr(
        agents_route,
        "apply_state",
        lambda agent: SimpleNamespace(
            agent_name=agent,
            agent_type="hermes",
            hostname="h",
            applied_skills=[],
            log_dir="/tmp/log",
        ),
    )


def test_list_404_for_unknown_agent(client, monkeypatch):
    monkeypatch.setattr(agents_route, "_resolve_agent", lambda key: None)
    r = client.get("/api/agents/missing/skills")
    assert r.status_code == 404


def test_list_returns_installed_available(client, hermes_agent):
    r = client.get("/api/agents/agent-x/skills")
    assert r.status_code == 200
    body = r.json()
    assert "installed" in body
    assert "available" in body


def test_install_422_on_bare_ref(client, hermes_agent, stub_apply):
    r = client.post("/api/agents/agent-x/skills/bareref/tdd")
    assert r.status_code == 422


def test_install_422_on_url(client, hermes_agent, stub_apply):
    r = client.post("/api/agents/agent-x/skills/https/example.com")
    assert r.status_code == 422


def test_install_supported_claw_200(client, hermes_agent, stub_apply):
    r = client.post("/api/agents/agent-x/skills/vetted/tdd")
    assert r.status_code in (200, 201), r.text


def test_remove_idempotent_200(client, hermes_agent, stub_apply):
    r = client.delete("/api/agents/agent-x/skills/vetted/tdd")
    assert r.status_code in (200, 204), r.text


def test_install_rolls_back_state_on_apply_failure(
    client, hermes_agent, tmp_path, monkeypatch
):
    """ATX #411 B3b: a failed apply must restore skills.json."""
    from clawrium.core import skills_state as state_mod
    from clawrium.core.skills_apply import SkillApplyError

    monkeypatch.setattr(state_mod, "get_config_dir", lambda: tmp_path)

    # Seed prior state: agent had vetted/blog-author installed.
    state_mod.write_state("agent-x", ["vetted/blog-author"])

    def boom(_agent):
        raise SkillApplyError("simulated host failure")

    monkeypatch.setattr("clawrium.gui.routes.agents.apply_state", boom)

    r = client.post("/api/agents/agent-x/skills/vetted/tdd")
    assert r.status_code == 502  # SkillApplyError → 502

    # State must equal the prior list — no half-applied mutation.
    assert state_mod.read_state("agent-x") == ["vetted/blog-author"]


def test_install_openclaw_returns_422_before_state_mutation(
    client, openclaw_agent, tmp_path, monkeypatch
):
    """ATX #411 B3a: ClawNotSupported pre-flight rejects before any
    state-file write."""
    from clawrium.core import skills_state as state_mod

    monkeypatch.setattr(state_mod, "get_config_dir", lambda: tmp_path)

    r = client.post("/api/agents/agent-x/skills/vetted/tdd")
    assert r.status_code == 422
    # State file must not exist or be empty.
    assert state_mod.read_state("agent-x") == []


def test_clawctl_skill_show_sanitizes_metadata(tmp_path, monkeypatch):
    """ATX #411 New-B1b: clawctl skill show must strip bidi from
    description + arbitrary metadata fields."""
    from typer.testing import CliRunner
    from clawrium.cli import app as clawctl_app
    from clawrium.core import skills as core_skills

    local_root = tmp_path / "local"
    local_root.mkdir()
    monkeypatch.setattr(core_skills, "_local_catalog_root", lambda: local_root)
    from clawrium.core import skills_local

    monkeypatch.setattr(skills_local, "_local_catalog_root", lambda: local_root)

    sk = local_root / "bidi2"
    sk.mkdir()
    # U+202E in description AND author field
    (sk / "SKILL.md").write_text(
        "---\nname: bidi2\n"
        "description: \"normal then ‮EVIL\"\n"
        "author: \"‮attacker\"\n"
        "version: \"‮9.9\"\n"
        "---\n\nclean body\n"
    )

    runner = CliRunner()
    result = runner.invoke(clawctl_app, ["skill", "show", "local/bidi2"])
    assert result.exit_code == 0, result.output
    assert "‮" not in result.output

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

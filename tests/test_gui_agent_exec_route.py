"""Tests for the GUI ``POST /api/agents/{agent_key}/exec`` route.

Regression guard: an earlier version of the handler treated
``_resolve_agent``'s ``tuple[host, claw_type, agent]`` return value as a
dict, so every "Run Command" click in the GUI raised ``TypeError`` and
came back as HTTP 500 / ``rc=-1`` regardless of agent type. These tests
pin the contract — tuple unpacking, the args passed to ``run_agent_exec``,
and the error-code mapping for each failure mode the handler distinguishes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawrium.gui.server import app


def _seed_hosts(config_dir: Path, agent_type: str) -> None:
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "box",
            "port": 22,
            "user": "xclm",
            "agents": {
                "demo": {
                    "type": agent_type,
                    "agent_name": "demo",
                    "name": "demo",
                    "config": {},
                }
            },
        }
    ]
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(json.dumps(hosts))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("agent_type", ["hermes", "zeroclaw", "openclaw"])
def test_exec_unpacks_resolve_agent_tuple(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    agent_type: str,
):
    """Handler must pass hostname/agent_name/claw_type — not raw tuple elements."""
    _seed_hosts(isolated_config, agent_type)

    called: dict[str, object] = {}

    def fake_run(hostname, agent_name, claw_type, cmd_argv, timeout):
        called["hostname"] = hostname
        called["agent_name"] = agent_name
        called["claw_type"] = claw_type
        called["cmd_argv"] = cmd_argv
        called["timeout"] = timeout
        return "ok\n", "", 0

    from clawrium.core import agent_exec as agent_exec_mod

    monkeypatch.setattr(agent_exec_mod, "run_agent_exec", fake_run)

    resp = client.post(
        "/api/agents/demo/exec",
        json={"command": ["--version"], "timeout": 30},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"stdout": "ok\n", "stderr": "", "return_code": 0}
    assert called == {
        "hostname": "192.168.1.100",
        "agent_name": "demo",
        "claw_type": agent_type,
        "cmd_argv": ["--version"],
        "timeout": 30,
    }


def test_exec_returns_404_when_agent_missing(
    isolated_config: Path, client: TestClient
):
    _seed_hosts(isolated_config, "hermes")
    resp = client.post(
        "/api/agents/nope/exec",
        json={"command": ["--version"]},
    )
    assert resp.status_code == 404
    assert "nope" in resp.json()["detail"]


def test_exec_returns_400_for_empty_command(
    isolated_config: Path, client: TestClient
):
    _seed_hosts(isolated_config, "hermes")
    resp = client.post("/api/agents/demo/exec", json={"command": []})
    assert resp.status_code == 400
    assert "command" in resp.json()["detail"].lower()


def test_exec_maps_agent_exec_error_to_400(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
):
    """Caller-recoverable input errors raised by core become 400, not 500."""
    _seed_hosts(isolated_config, "hermes")

    from clawrium.core import agent_exec as agent_exec_mod

    def raise_agent_exec_error(*args, **kwargs):
        raise agent_exec_mod.AgentExecError("invalid agent_name: 'bad'")

    monkeypatch.setattr(agent_exec_mod, "run_agent_exec", raise_agent_exec_error)

    resp = client.post(
        "/api/agents/demo/exec",
        json={"command": ["--version"]},
    )
    assert resp.status_code == 400
    assert "invalid agent_name" in resp.json()["detail"]


def test_exec_maps_unexpected_exception_to_500(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
):
    """Programmer bugs surface as 500 with a generic body — never leak internals."""
    _seed_hosts(isolated_config, "hermes")

    from clawrium.core import agent_exec as agent_exec_mod

    def boom(*args, **kwargs):
        raise RuntimeError("private path /home/x/.ssh/id_ed25519")

    monkeypatch.setattr(agent_exec_mod, "run_agent_exec", boom)

    resp = client.post(
        "/api/agents/demo/exec",
        json={"command": ["--version"]},
    )
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "private path" not in detail
    assert "server logs" in detail


def test_exec_propagates_nonzero_rc(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
):
    _seed_hosts(isolated_config, "hermes")

    from clawrium.core import agent_exec as agent_exec_mod

    monkeypatch.setattr(
        agent_exec_mod,
        "run_agent_exec",
        lambda *a, **kw: ("", "boom", 7),
    )

    resp = client.post(
        "/api/agents/demo/exec",
        json={"command": ["doomed"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"stdout": "", "stderr": "boom", "return_code": 7}


def test_exec_clamps_timeout(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
):
    """The handler clamps caller-supplied timeout into [5, 120]."""
    _seed_hosts(isolated_config, "hermes")

    captured: dict[str, int] = {}

    def fake_run(hostname, agent_name, claw_type, cmd_argv, timeout):
        captured["timeout"] = timeout
        return "", "", 0

    from clawrium.core import agent_exec as agent_exec_mod

    monkeypatch.setattr(agent_exec_mod, "run_agent_exec", fake_run)

    resp = client.post(
        "/api/agents/demo/exec",
        json={"command": ["--version"], "timeout": 9999},
    )
    assert resp.status_code == 200
    assert captured["timeout"] == 120

    resp = client.post(
        "/api/agents/demo/exec",
        json={"command": ["--version"], "timeout": 1},
    )
    assert resp.status_code == 200
    assert captured["timeout"] == 5

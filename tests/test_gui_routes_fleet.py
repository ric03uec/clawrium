"""Tests for the GUI /api/fleet/agents/{key}/web-ui endpoint and reaper.

Issue #478 phase 3. The endpoint should:
- 404 when the agent is unknown.
- Return ``available: false`` (with a reason) for agents whose manifest
  does not declare ``features.web_ui``.
- Establish a tunnel and return ``available: true`` for hermes agents
  on remote hosts.
- Skip the tunnel for loopback-bound hosts.

The reaper should close any tunnel whose last-access timestamp is older
than the configured threshold.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from clawrium.core.web_ui import ResolvedUI
from clawrium.gui.routes import fleet as fleet_mod
from clawrium.gui.server import app


@pytest.fixture(autouse=True)
def _reset_reaper_state():
    fleet_mod.WEB_UI_LAST_ACCESS.clear()
    yield
    fleet_mod.WEB_UI_LAST_ACCESS.clear()


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


def test_web_ui_404_for_unknown_agent(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    # We deliberately do NOT mount the lifespan reaper here; TestClient
    # default behavior is fine for the route-only assertions below.
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/nope/web-ui")
    assert resp.status_code == 404


def test_web_ui_returns_unavailable_for_non_hermes(isolated_config: Path):
    _seed_hosts(isolated_config, "openclaw")
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/demo/web-ui")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["local_url"] is None
    assert "openclaw" in (body["reason"] or "").lower()


def test_web_ui_returns_tunnel_url_for_remote_hermes(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="192.168.1.100",
        remote_port=9119,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=54321) as mock_ensure,
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/web-ui")
            # Assert inside the lifespan window — the shutdown handler
            # intentionally clears WEB_UI_LAST_ACCESS as part of draining.
            assert "demo" in fleet_mod.WEB_UI_LAST_ACCESS

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "available": True,
        "local_url": "http://127.0.0.1:54321/",
        "reason": None,
    }
    mock_ensure.assert_called_once_with("demo")


def test_web_ui_skips_tunnel_for_loopback_host(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="127.0.0.1",
        remote_port=9119,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch("clawrium.core.web_ui_tunnel.ensure") as mock_ensure,
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/web-ui")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["local_url"] == "http://127.0.0.1:9119/"
    mock_ensure.assert_not_called()


def test_web_ui_reports_tunnel_failure_as_unavailable(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="192.168.1.100",
        remote_port=9119,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    from clawrium.core.web_ui_tunnel import TunnelError

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch("clawrium.core.web_ui_tunnel.ensure", side_effect=TunnelError("ssh failed")),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/web-ui")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["local_url"] is None
    assert "ssh failed" in body["reason"]


def test_reaper_closes_idle_tunnels():
    """reap_idle_tunnels() must call web_ui_tunnel.close() for stale entries."""
    import time as time_module

    # One fresh, one stale.
    fleet_mod.WEB_UI_LAST_ACCESS["fresh"] = time_module.time()
    fleet_mod.WEB_UI_LAST_ACCESS["stale"] = time_module.time() - 3600

    closed: list[str] = []

    def _record_close(key: str) -> None:
        closed.append(key)

    with patch("clawrium.core.web_ui_tunnel.close", side_effect=_record_close):
        count = asyncio.run(fleet_mod.reap_idle_tunnels(threshold_seconds=1800.0))

    assert count == 1
    assert closed == ["stale"]
    assert "fresh" in fleet_mod.WEB_UI_LAST_ACCESS
    assert "stale" not in fleet_mod.WEB_UI_LAST_ACCESS


def test_reaper_noop_when_all_fresh():
    import time as time_module

    fleet_mod.WEB_UI_LAST_ACCESS["a"] = time_module.time()
    with patch("clawrium.core.web_ui_tunnel.close") as mock_close:
        count = asyncio.run(fleet_mod.reap_idle_tunnels(threshold_seconds=1800.0))
    assert count == 0
    mock_close.assert_not_called()

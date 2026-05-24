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


def _seed_hosts(
    config_dir: Path,
    agent_type: str,
    config: dict | None = None,
) -> None:
    """Seed `hosts.json` with one agent. `config` overrides the agent's
    `config` block — useful for tests that need a persisted gateway
    bearer or dashboard port.
    """
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
                    "config": config or {},
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
        patch(
            "clawrium.core.web_ui_tunnel.ensure", side_effect=TunnelError("ssh failed")
        ),
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


# ---------------------------------------------------------------------------
# POST /fleet/agents/{key}/pairing-code  (zeroclaw SPA pairing handshake)
# ---------------------------------------------------------------------------
#
# Contract (see `agent_pairing_code` in routes/fleet.py):
#   - 404 when the agent is unknown.
#   - 400 for agent types not in `_PAIRING_AGENT_TYPES` (today: anything
#     other than zeroclaw).
#   - 400 when the manifest does not declare features.web_ui.
#   - 409 when `hosts.json.agents.<name>.config.gateway.auth` is missing
#     or empty (lifecycle hasn't run yet).
#   - 409 when the daemon returns 401 (stale bearer).
#   - 503 when the daemon returns 503 (pairing disabled).
#   - 502 when the tunnel fails, the upstream call errors, or the daemon
#     returns an unexpected status / non-JSON / empty code.
#   - 504 on upstream timeout.
#   - 200 with {pairing_code: "..."} on success.


def _zeroclaw_config(bearer: str = "zc_test_bearer", port: int = 40123) -> dict:
    return {"gateway": {"auth": bearer, "port": port}}


def _zeroclaw_resolved(host: str = "192.168.1.100") -> ResolvedUI:
    return ResolvedUI(
        host=host,
        remote_port=40123,
        bind="wildcard",
        ssh_config={"user": "xclm"},
    )


def test_pairing_code_404_for_unknown_agent(isolated_config: Path):
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())
    with TestClient(app) as client:
        resp = client.post("/api/fleet/agents/nope/pairing-code")
    assert resp.status_code == 404


def test_pairing_code_400_for_non_pairing_agent_type(isolated_config: Path):
    """hermes uses features.web_ui but does not run the pairing handshake."""
    _seed_hosts(isolated_config, "hermes", {"dashboard": {"port": 45123}})
    with TestClient(app) as client:
        resp = client.post("/api/fleet/agents/demo/pairing-code")
    assert resp.status_code == 400
    assert "pairing handshake" in resp.json()["detail"].lower()


def test_pairing_code_400_when_manifest_lacks_web_ui(isolated_config: Path):
    """openclaw has no features.web_ui — resolver returns None."""
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())
    with patch("clawrium.core.web_ui.resolve", return_value=None):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")
    assert resp.status_code == 400
    assert "native web ui" in resp.json()["detail"].lower()


def test_pairing_code_409_when_bearer_missing(isolated_config: Path):
    """No persisted gateway.auth → 409 with `clm agent configure` guidance."""
    _seed_hosts(isolated_config, "zeroclaw", {"gateway": {"port": 40123}})
    with patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")
    assert resp.status_code == 409
    assert "clawctl agent configure" in resp.json()["detail"]


def test_pairing_code_409_when_bearer_blank(isolated_config: Path):
    _seed_hosts(isolated_config, "zeroclaw", {"gateway": {"auth": "   "}})
    with patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")
    assert resp.status_code == 409


def test_pairing_code_502_on_tunnel_failure(isolated_config: Path):
    from clawrium.core.web_ui_tunnel import TunnelError

    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())
    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch(
            "clawrium.core.web_ui_tunnel.ensure",
            side_effect=TunnelError("ssh refused"),
        ),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")
    assert resp.status_code == 502
    assert "ssh refused" in resp.json()["detail"]


def test_pairing_code_success(isolated_config: Path):
    """Happy path: tunnel up, daemon returns 200 with a code, route relays it."""
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config("zc_bearer"))

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"pairing_code": "508333", "message": "ok"}

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResp()

    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=39211),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")

    assert resp.status_code == 200
    assert resp.json() == {"pairing_code": "508333"}
    assert captured["url"] == "http://127.0.0.1:39211/api/pairing/initiate"
    assert captured["headers"] == {"Authorization": "Bearer zc_bearer"}


def test_pairing_code_409_on_daemon_401(isolated_config: Path):
    """Stale bearer in hosts.json → daemon 401 → 409 with re-pair guidance."""
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())

    class _FakeResp:
        status_code = 401

        def json(self):
            return {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None):
            return _FakeResp()

    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=39211),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")

    assert resp.status_code == 409
    assert "clawctl agent configure" in resp.json()["detail"]


def test_pairing_code_503_on_daemon_503(isolated_config: Path):
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())

    class _FakeResp:
        status_code = 503

        def json(self):
            return {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None):
            return _FakeResp()

    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=39211),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")

    assert resp.status_code == 503
    assert "clawctl agent restart" in resp.json()["detail"]


def test_pairing_code_502_on_unexpected_daemon_status(isolated_config: Path):
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())

    class _FakeResp:
        status_code = 418  # any non-200/401/503

        def json(self):
            return {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None):
            return _FakeResp()

    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=39211),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")

    assert resp.status_code == 502
    assert "418" in resp.json()["detail"]


def test_pairing_code_502_on_empty_code(isolated_config: Path):
    """Daemon returns 200 with a null/empty pairing_code — surface as 502."""
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"pairing_code": ""}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None):
            return _FakeResp()

    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=39211),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")

    assert resp.status_code == 502
    assert "empty pairing code" in resp.json()["detail"].lower()


def test_pairing_code_504_on_upstream_timeout(isolated_config: Path):
    import httpx

    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None):
            raise httpx.ReadTimeout("timed out")

    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=39211),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")

    assert resp.status_code == 504


def test_pairing_code_local_host_skips_tunnel(isolated_config: Path):
    """If the agent's host is loopback, we hit the daemon directly — no SSH."""
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config("zc_local"))

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"pairing_code": "111111"}

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None):
            captured["url"] = url
            return _FakeResp()

    resolved = ResolvedUI(
        host="127.0.0.1",
        remote_port=40123,
        bind="wildcard",
        ssh_config={"user": "xclm"},
    )

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch(
            "clawrium.core.web_ui_tunnel.ensure",
            side_effect=AssertionError("tunnel must not be ensured for local hosts"),
        ),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")

    assert resp.status_code == 200
    assert resp.json() == {"pairing_code": "111111"}
    # Hits the remote port directly, not the tunnel local port.
    assert captured["url"] == "http://127.0.0.1:40123/api/pairing/initiate"

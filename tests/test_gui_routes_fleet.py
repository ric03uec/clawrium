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

from clawrium.core.health import ClawStatus
from clawrium.core.lifecycle import LifecycleError
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


def test_web_ui_returns_unavailable_when_manifest_lacks_feature(
    isolated_config: Path,
):
    """When `features.web_ui` is absent, the endpoint returns
    `available: false` with the agent_type embedded in the reason.

    All three bundled agent types now declare `features.web_ui`, so this
    test patches the resolver to None to exercise the no-feature code
    path. The seeded agent is openclaw merely to keep the rest of the
    fixture stable.
    """
    _seed_hosts(isolated_config, "openclaw")
    with patch("clawrium.core.web_ui.resolve", return_value=None):
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


def test_web_ui_returns_tunnel_url_for_remote_openclaw(isolated_config: Path):
    """openclaw resolves with `bind='wildcard'` and a persisted gateway
    port; the route returns `available: true` with a local tunnel URL.

    Mirror of the hermes positive test above — anchors the openclaw
    parity work added with `features.web_ui` in the manifest.
    """
    _seed_hosts(isolated_config, "openclaw", {"gateway": {"port": 40456}})
    resolved = ResolvedUI(
        host="192.168.1.100",
        remote_port=40456,
        bind="wildcard",
        ssh_config={"user": "xclm"},
    )
    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=54322) as mock_ensure,
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/web-ui")
            assert "demo" in fleet_mod.WEB_UI_LAST_ACCESS

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "available": True,
        "local_url": "http://127.0.0.1:54322/",
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


def test_web_ui_returns_unavailable_on_unexpected_tunnel_exception(
    isolated_config: Path,
):
    """Non-TunnelError exception from ensure() → available:false with generic reason."""
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="192.168.1.100",
        remote_port=9119,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch(
            "clawrium.core.web_ui_tunnel.ensure",
            side_effect=RuntimeError("unexpected internal failure"),
        ),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/web-ui")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["local_url"] is None
    assert "Internal error" in body["reason"]
    assert "unexpected internal failure" not in body["reason"]


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


def test_reaper_skips_close_for_restamped_key():
    """Key re-stamped during a concurrent /web-ui call skips close() (TOCTOU guard).

    Two stale entries are in the snapshot. close("first") side-effects a re-stamp
    of "second" — simulating a /web-ui handler running between the snapshot pop and
    the per-key re-check. The reaper must close "first" (count==1) but skip "second".
    """
    import time as time_module

    fleet_mod.WEB_UI_LAST_ACCESS["first"] = time_module.time() - 3600
    fleet_mod.WEB_UI_LAST_ACCESS["second"] = time_module.time() - 3600

    def _close_first_restamp_second(key: str) -> None:
        if key == "first":
            fleet_mod.WEB_UI_LAST_ACCESS["second"] = time_module.time()

    with patch(
        "clawrium.core.web_ui_tunnel.close", side_effect=_close_first_restamp_second
    ) as mock_close:
        count = asyncio.run(fleet_mod.reap_idle_tunnels(threshold_seconds=1800.0))

    assert count == 1
    mock_close.assert_called_once_with("first")
    assert "second" in fleet_mod.WEB_UI_LAST_ACCESS


def test_reaper_continues_after_close_failure():
    """close() raising must not increment count; subsequent stale keys are still processed.

    Pop-before-close trade-off: keys are removed from WEB_UI_LAST_ACCESS in the
    initial snapshot (before close() is called) to avoid holding _LAST_ACCESS_LOCK
    across the blocking SSH teardown. This means a close() failure permanently
    removes tracking — the SSH process may still be alive but becomes un-reapable
    in future cycles. This is intentional: the alternative (re-inserting on failure)
    would require another lock acquire and make the reaper retry broken tunnels
    indefinitely.
    """
    import time as time_module

    fleet_mod.WEB_UI_LAST_ACCESS["bad"] = time_module.time() - 3600
    fleet_mod.WEB_UI_LAST_ACCESS["good"] = time_module.time() - 3600

    closed: list[str] = []

    def _failing_close(key: str) -> None:
        if key == "bad":
            raise OSError("ssh disconnect")
        closed.append(key)

    with patch("clawrium.core.web_ui_tunnel.close", side_effect=_failing_close):
        count = asyncio.run(fleet_mod.reap_idle_tunnels(threshold_seconds=1800.0))

    assert count == 1
    assert "good" in closed
    assert "bad" not in fleet_mod.WEB_UI_LAST_ACCESS
    assert "good" not in fleet_mod.WEB_UI_LAST_ACCESS


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


def test_pairing_code_400_for_openclaw_not_in_pairing_types(isolated_config: Path):
    """openclaw declares features.web_ui (so resolve() returns a valid
    ResolvedUI) but is intentionally NOT in `_PAIRING_AGENT_TYPES` —
    openclaw uses a gateway bearer token, not zeroclaw's pairing-code
    handshake. The earlier guard at fleet.py:402 fires first and returns
    400 with "pairing handshake" in the detail before the
    "no native web UI" branch is reached.
    """
    _seed_hosts(isolated_config, "openclaw", {"gateway": {"port": 40456}})
    with TestClient(app) as client:
        resp = client.post("/api/fleet/agents/demo/pairing-code")
    assert resp.status_code == 400
    assert "pairing handshake" in resp.json()["detail"].lower()


def test_pairing_code_400_when_resolver_returns_none(isolated_config: Path):
    """When resolve() returns None for a pairing-type agent, the manifest
    check fires (after the _PAIRING_AGENT_TYPES guard) and returns 400.

    Seeds zeroclaw (a pairing type) so the _PAIRING_AGENT_TYPES guard
    passes, then patches resolve to None to exercise the no-features.web_ui
    branch independently of any real manifest.
    """
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
    assert "clawctl agent configure" in resp.json()["detail"]


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
    assert "zc_test_bearer" not in resp.text


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
    assert captured["timeout"] == 10.0


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
    assert "zc_test_bearer" not in resp.text


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
    assert "zc_test_bearer" not in resp.text


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
    assert "zc_test_bearer" not in resp.text


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
    assert "zc_test_bearer" not in resp.text


def test_pairing_code_502_on_http_error(isolated_config: Path):
    """httpx.HTTPError (non-timeout, e.g. ConnectError) → 502."""
    import httpx

    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config("zc_bearer"))

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None):
            raise httpx.ConnectError("connection refused")

    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=39211),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")

    assert resp.status_code == 502
    assert "Could not reach the agent daemon" in resp.json()["detail"]
    assert "zc_bearer" not in resp.text


def test_pairing_code_502_on_non_json_response(isolated_config: Path):
    """resp.json() raising ValueError → 502 'non-JSON pairing response'."""
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config("zc_bearer"))

    class _FakeResp:
        status_code = 200

        def json(self):
            raise ValueError("not valid JSON")

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
    assert "non-JSON" in resp.json()["detail"]
    assert "zc_bearer" not in resp.text


def test_pairing_code_500_on_unexpected_tunnel_exception(isolated_config: Path):
    """Non-TunnelError from ensure() in pairing-code path → 500 with generic message."""
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config("zc_bearer"))
    with (
        patch("clawrium.core.web_ui.resolve", return_value=_zeroclaw_resolved()),
        patch(
            "clawrium.core.web_ui_tunnel.ensure",
            side_effect=RuntimeError("unexpected internal failure"),
        ),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/pairing-code")
    assert resp.status_code == 500
    assert "Internal error" in resp.json()["detail"]
    assert "unexpected internal failure" not in resp.json()["detail"]
    assert "zc_bearer" not in resp.text


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
    assert "zc_bearer" not in resp.text


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


# /api/fleet/agents/{key}/connection-token
# Reveals the long-lived gateway bearer for openclaw's Control UI login.
# Distinct from /pairing-code: no daemon round-trip, no mutation —
# returns the same install-time token already persisted in hosts.json.


def _openclaw_config(bearer: str = "oc_test_bearer", port: int = 40456) -> dict:
    return {"gateway": {"auth": bearer, "port": port}}


def _openclaw_resolved(host: str = "192.168.1.100") -> ResolvedUI:
    return ResolvedUI(
        host=host,
        remote_port=40456,
        bind="wildcard",
        ssh_config={"user": "xclm"},
    )


def test_connection_token_404_for_unknown_agent(isolated_config: Path):
    _seed_hosts(isolated_config, "openclaw", _openclaw_config())
    with TestClient(app) as client:
        resp = client.post("/api/fleet/agents/nope/connection-token")
    assert resp.status_code == 404


def test_connection_token_400_for_non_reveal_agent_type(isolated_config: Path):
    """hermes does not use a long-lived gateway token for browser auth."""
    _seed_hosts(isolated_config, "hermes", {"dashboard": {"port": 45123}})
    with TestClient(app) as client:
        resp = client.post("/api/fleet/agents/demo/connection-token")
    assert resp.status_code == 400
    assert "gateway token" in resp.json()["detail"].lower()


def test_connection_token_400_for_zeroclaw(isolated_config: Path):
    """zeroclaw is a pairing-code type, not a token-reveal type — the
    earlier guard fires before the manifest check.
    """
    _seed_hosts(isolated_config, "zeroclaw", _zeroclaw_config())
    with TestClient(app) as client:
        resp = client.post("/api/fleet/agents/demo/connection-token")
    assert resp.status_code == 400
    assert "gateway token" in resp.json()["detail"].lower()


def test_connection_token_400_when_resolver_returns_none(isolated_config: Path):
    """When resolve() returns None for an openclaw agent (no
    features.web_ui in the manifest), the route returns 400 after the
    type-allowlist guard passes.
    """
    _seed_hosts(isolated_config, "openclaw", _openclaw_config())
    with patch("clawrium.core.web_ui.resolve", return_value=None):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/connection-token")
    assert resp.status_code == 400
    assert "native web ui" in resp.json()["detail"].lower()


def test_connection_token_409_when_bearer_missing(isolated_config: Path):
    """openclaw without persisted gateway.auth → 409 + configure guidance."""
    _seed_hosts(isolated_config, "openclaw", {"gateway": {"port": 40456}})
    with patch("clawrium.core.web_ui.resolve", return_value=_openclaw_resolved()):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/connection-token")
    assert resp.status_code == 409
    assert "clawctl agent configure" in resp.json()["detail"]


def test_connection_token_409_when_bearer_blank(isolated_config: Path):
    _seed_hosts(isolated_config, "openclaw", {"gateway": {"auth": "   "}})
    with patch("clawrium.core.web_ui.resolve", return_value=_openclaw_resolved()):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/connection-token")
    assert resp.status_code == 409
    assert "clawctl agent configure" in resp.json()["detail"]


def test_connection_token_success(isolated_config: Path):
    """Happy path: returns the persisted gateway.auth verbatim."""
    _seed_hosts(isolated_config, "openclaw", _openclaw_config("oc_real_bearer"))
    with patch("clawrium.core.web_ui.resolve", return_value=_openclaw_resolved()):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/connection-token")
    assert resp.status_code == 200
    assert resp.json() == {"token": "oc_real_bearer"}


def test_connection_token_strips_trailing_whitespace(isolated_config: Path):
    """Hand-edited hosts.json with a trailing newline → returned stripped."""
    _seed_hosts(isolated_config, "openclaw", _openclaw_config("oc_bearer\n"))
    with patch("clawrium.core.web_ui.resolve", return_value=_openclaw_resolved()):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/connection-token")
    assert resp.status_code == 200
    assert resp.json() == {"token": "oc_bearer"}


def test_connection_token_prefers_secrets_store_over_legacy_hosts_json(
    isolated_config: Path,
):
    """W2 (ATX): the endpoint MUST go through `_resolve_openclaw_credentials`
    rather than reading `gateway.auth` directly. Otherwise a future rotation
    that lands only in the secrets store leaves the legacy hosts.json field
    stale and users paste a dead token into the Control UI.

    Verifies the wiring by patching the helper itself: if the endpoint
    bypassed it and read hosts.json directly, the assertion below would
    return the legacy value `"oc_legacy"` instead of `"oc_rotated"`.
    """
    _seed_hosts(isolated_config, "openclaw", _openclaw_config("oc_legacy"))
    with (
        patch("clawrium.core.web_ui.resolve", return_value=_openclaw_resolved()),
        patch(
            "clawrium.gui.routes.agents._resolve_openclaw_credentials",
            return_value=("oc_rotated", None),
        ),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/connection-token")
    assert resp.status_code == 200
    assert resp.json() == {"token": "oc_rotated"}


def test_connection_token_uses_instance_key_not_raw_agent_key(isolated_config: Path):
    """_resolve_openclaw_credentials must receive the host:type:name instance key,
    not the raw agent_key URL param. Passing agent_key directly means
    get_instance_secrets never matches and always falls back to hosts.json.
    """
    from clawrium.core.secrets import get_instance_key

    _seed_hosts(isolated_config, "openclaw", _openclaw_config("oc_bearer"))
    expected_key = get_instance_key("192.168.1.100", "openclaw", "demo")

    captured: dict = {}

    def _capture(instance_key, gateway):
        captured["instance_key"] = instance_key
        return ("oc_bearer", None)

    with (
        patch("clawrium.core.web_ui.resolve", return_value=_openclaw_resolved()),
        patch(
            "clawrium.gui.routes.agents._resolve_openclaw_credentials",
            side_effect=_capture,
        ),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/fleet/agents/demo/connection-token")

    assert resp.status_code == 200
    assert captured["instance_key"] == expected_key
    assert captured["instance_key"] != "demo"


def test_connection_token_get_does_not_leak_bearer(isolated_config: Path):
    """The endpoint is POST-only. The GUI server mounts the SPA on a
    catch-all GET, so a GET to this path falls through to index.html
    (not a 405). Guard against a future router refactor that
    accidentally adds a GET handler returning the bearer — the
    JSON-token shape MUST NOT appear in a GET response body.
    """
    _seed_hosts(
        isolated_config, "openclaw", _openclaw_config("oc_should_not_leak")
    )
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/demo/connection-token")
    # Either 405 (route refuses GET) or 200 (SPA fallback). The
    # invariant is that the bearer never appears in the GET body.
    assert "oc_should_not_leak" not in resp.text


# ---------------------------------------------------------------------------
# Helpers shared by B1–B6 tests
# ---------------------------------------------------------------------------

def _agent_vm(**overrides) -> dict:
    """Minimal AgentViewModel dict for mocking fleet data functions."""
    base: dict = {
        "agent_key": "demo",
        "agent_name": "demo",
        "agent_type": "hermes",
        "host": "192.168.1.100",
        "host_alias": "box",
        "host_os_family": "linux",
        "version": "2026.5.1",
        "status": ClawStatus.RUNNING,
        "model": "claude-sonnet",
        "uptime": "2h",
        "missing_secrets": [],
        "onboarding_step": None,
        "process_running": True,
        "health_error": None,
        "addresses": [],
        "provider": "anthropic",
        "provider_type": "anthropic",
        "cpu_count": 4,
        "memory_total_mb": 8192,
        "gateway_port": 45001,
        "gateway_url": "http://192.168.1.100:45001",
        "gateway_auth": "secret_bearer_must_not_leak",
        "device_id": None,
        "device_private_key": None,
    }
    base.update(overrides)
    return base


def _fleet_summary(**overrides) -> dict:
    base = {"total": 1, "running": 1, "provisioning": 0, "hosts": 1}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# B1 — GET /fleet (fleet_overview)
# ---------------------------------------------------------------------------


def test_fleet_overview_returns_agent_list(isolated_config: Path):
    vm = _agent_vm()
    with patch(
        "clawrium.gui.routes.fleet.get_fleet_data_local",
        return_value=([vm], _fleet_summary()),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total"] == 1
    assert data["summary"]["running"] == 1
    assert len(data["agents"]) == 1
    assert data["agents"][0]["agent_key"] == "demo"


def test_fleet_overview_host_filter_forwarded(isolated_config: Path):
    """host query param is forwarded to get_fleet_data_local."""
    with patch(
        "clawrium.gui.routes.fleet.get_fleet_data_local",
        return_value=([], _fleet_summary(total=0, running=0, hosts=0)),
    ) as mock_fn:
        with TestClient(app) as client:
            client.get("/api/fleet?host=box")
    mock_fn.assert_called_once_with("box")


def test_fleet_overview_excludes_gateway_auth(isolated_config: Path):
    """gateway_auth must never appear in the /fleet response body (W3)."""
    vm = _agent_vm()
    with patch(
        "clawrium.gui.routes.fleet.get_fleet_data_local",
        return_value=([vm], _fleet_summary()),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet")
    assert "secret_bearer_must_not_leak" not in resp.text
    assert "gateway_auth" not in resp.json()["agents"][0]


# ---------------------------------------------------------------------------
# B2 — GET /fleet/health (fleet_health)
# ---------------------------------------------------------------------------


def test_fleet_health_returns_health_data(isolated_config: Path):
    vm = _agent_vm()
    with patch(
        "clawrium.gui.routes.fleet.get_fleet_data",
        return_value=([vm], _fleet_summary()),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total"] == 1
    assert data["agents"][0]["agent_key"] == "demo"
    assert data["agents"][0]["process_running"] is True
    assert "gateway_auth" not in data["agents"][0]
    assert "secret_bearer_must_not_leak" not in resp.text


def test_fleet_health_sanitizes_path_in_health_error(isolated_config: Path):
    """_sanitize_health_error regex branch must run when health_error contains a path."""
    vm = _agent_vm(health_error="/home/user/.config/clawrium/secrets.json: permission denied")
    with patch(
        "clawrium.gui.routes.fleet.get_fleet_data",
        return_value=([vm], _fleet_summary()),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/health")
    assert resp.status_code == 200
    agent = resp.json()["agents"][0]
    assert agent["health_error"] == "<path>: permission denied"


def test_fleet_health_504_on_timeout(isolated_config: Path):
    with patch(
        "asyncio.wait_for", side_effect=asyncio.TimeoutError
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/health")
    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"]


def test_fleet_health_returns_200_under_concurrent_clients(isolated_config: Path):
    """Three concurrent clients all get 200 — smoke-tests basic concurrency."""
    from concurrent.futures import ThreadPoolExecutor as _TPE

    vm = _agent_vm()

    def _probe() -> int:
        with TestClient(app) as client:
            return client.get("/api/fleet/health").status_code

    with patch(
        "clawrium.gui.routes.fleet.get_fleet_data",
        return_value=([vm], _fleet_summary()),
    ):
        executor = _TPE(max_workers=3)
        try:
            futures = [executor.submit(_probe) for _ in range(3)]
            results = [f.result(timeout=15) for f in futures]
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    assert len(results) == 3, f"only {len(results)} threads completed"
    assert all(s == 200 for s in results), results


def test_fleet_health_host_filter_forwarded(isolated_config: Path):
    """?host= query param is forwarded to get_fleet_data on /fleet/health."""
    with patch(
        "clawrium.gui.routes.fleet.get_fleet_data",
        return_value=([], _fleet_summary(total=0, running=0, hosts=0)),
    ) as mock_fn:
        with TestClient(app) as client:
            resp = client.get("/api/fleet/health?host=box")
    assert resp.status_code == 200
    mock_fn.assert_called_once_with("box")


# ---------------------------------------------------------------------------
# B3 — GET /fleet/agents/{key} (agent_detail)
# ---------------------------------------------------------------------------


def test_agent_detail_404_for_unknown(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/nope")
    assert resp.status_code == 404


def test_agent_detail_success(isolated_config: Path):
    """The static endpoint serves identity from hosts.json. The sibling
    /health endpoint is the one that carries latest_supported_version
    (moved off the static path in #758)."""
    _seed_hosts(isolated_config, "hermes")
    vm = _agent_vm()
    captured: dict = {}

    def _capture_static(agent_key, hostname):
        captured["agent_key"] = agent_key
        captured["hostname"] = hostname
        return vm

    with patch(
        "clawrium.gui.routes.fleet.get_agent_static", side_effect=_capture_static
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_key"] == "demo"
    # latest_supported_version is no longer on the static endpoint.
    assert "latest_supported_version" not in data
    assert captured["hostname"] == "192.168.1.100"
    assert captured["agent_key"] == "demo"


def test_agent_health_returns_latest_supported_version(isolated_config: Path):
    """/health is the single source for latest_supported_version (#758)."""
    _seed_hosts(isolated_config, "hermes")
    vm = _agent_vm()
    with (
        patch("clawrium.gui.routes.fleet.get_agent_detail", return_value=vm),
        patch(
            "clawrium.core.registry.latest_supported_version",
            return_value="2026.6.0",
        ),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_key"] == "demo"
    assert data["latest_supported_version"] == "2026.6.0"


def test_agent_detail_404_when_get_agent_static_returns_none(isolated_config: Path):
    """Second 404 path: resolve_agent succeeds but get_agent_static returns None."""
    _seed_hosts(isolated_config, "hermes")
    with patch("clawrium.gui.routes.fleet.get_agent_static", return_value=None):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo")
    assert resp.status_code == 404


def test_agent_detail_404_when_host_mismatch(isolated_config: Path):
    """?host=wronghost for a known agent returns 404 (not 200 with wrong host data)."""
    _seed_hosts(isolated_config, "hermes")
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/demo?host=wronghost")
    assert resp.status_code == 404
    assert "demo" in resp.json()["detail"]
    assert "wronghost" in resp.json()["detail"]


def test_agent_health_hardware_null_coercion(isolated_config: Path):
    """Regression: hardware=null in hosts.json must not raise — `or {}` coerces it.

    Moved to /health in #758 since latest_supported_version now lives
    on the runtime endpoint.
    """
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "box",
            "port": 22,
            "user": "xclm",
            "hardware": None,
            "agents": {
                "demo": {
                    "type": "hermes",
                    "agent_name": "demo",
                    "name": "demo",
                    "config": {},
                }
            },
        }
    ]
    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(json.dumps(hosts))
    vm = _agent_vm()
    with patch("clawrium.gui.routes.fleet.get_agent_detail", return_value=vm):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/health")
    assert resp.status_code == 200
    # latest_supported_version raises on hardware={} with no arch; caught → None
    assert resp.json()["latest_supported_version"] is None


def test_agent_detail_excludes_gateway_auth(isolated_config: Path):
    """gateway_auth must never appear in the agent_detail response body (W3)."""
    _seed_hosts(isolated_config, "hermes")
    vm = _agent_vm()
    with patch("clawrium.gui.routes.fleet.get_agent_static", return_value=vm):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo")
    assert "secret_bearer_must_not_leak" not in resp.text
    assert "gateway_auth" not in resp.json()


def test_agent_detail_excludes_device_private_key(isolated_config: Path):
    """device_private_key is a secret too — _agent_to_dict's allow-list
    excludes it, but only the gateway_auth field had a regression test.
    (#758 ATX S1)."""
    _seed_hosts(isolated_config, "hermes")
    vm = _agent_vm(device_private_key="SENTINEL_PRIVKEY_NEVER_LEAK")
    with patch("clawrium.gui.routes.fleet.get_agent_static", return_value=vm):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo")
    assert resp.status_code == 200
    assert "SENTINEL_PRIVKEY_NEVER_LEAK" not in resp.text
    assert "device_private_key" not in resp.json()


# ---------------------------------------------------------------------------
# B4 — POST /agents/{key}/start
# ---------------------------------------------------------------------------


def test_start_agent_404_for_unknown(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with TestClient(app) as client:
        resp = client.post("/api/agents/nope/start")
    assert resp.status_code == 404


def test_start_agent_success(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.start_agent", return_value={"success": True}
    ) as mock_start:
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["operation"] == "start"
    assert data["agent"] == "demo"
    mock_start.assert_called_once_with("192.168.1.100", "hermes", agent_name="demo")


def test_start_agent_lifecycle_error_sanitized(isolated_config: Path):
    """LifecycleError detail must be path-sanitized before reaching the browser (W1)."""
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.start_agent",
        side_effect=LifecycleError("failed at /home/user/.config/clawrium/secrets.json"),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/start")
    assert resp.status_code == 500
    assert "/home/user/.config" not in resp.json()["detail"]
    assert "<path>" in resp.json()["detail"]


def test_start_agent_generic_exception_uses_safe_message(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.start_agent",
        side_effect=RuntimeError("internal detail /etc/secrets"),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/start")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Lifecycle operation failed. Check server logs."


# ---------------------------------------------------------------------------
# B5 — POST /agents/{key}/stop
# ---------------------------------------------------------------------------


def test_stop_agent_404_for_unknown(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with TestClient(app) as client:
        resp = client.post("/api/agents/nope/stop")
    assert resp.status_code == 404


def test_stop_agent_success(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.stop_agent", return_value={"success": True}
    ) as mock_stop:
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/stop")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["operation"] == "stop"
    mock_stop.assert_called_once_with("192.168.1.100", "hermes", agent_name="demo")


def test_stop_agent_lifecycle_error_sanitized(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.stop_agent",
        side_effect=LifecycleError("failed at /home/user/.config/clawrium/hosts.json"),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/stop")
    assert resp.status_code == 500
    assert "/home/user/.config" not in resp.json()["detail"]
    assert "<path>" in resp.json()["detail"]


def test_stop_agent_generic_exception_uses_safe_message(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.stop_agent",
        side_effect=RuntimeError("boom"),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/stop")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Lifecycle operation failed. Check server logs."


# ---------------------------------------------------------------------------
# B6 — POST /agents/{key}/restart
# ---------------------------------------------------------------------------


def test_restart_agent_404_for_unknown(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with TestClient(app) as client:
        resp = client.post("/api/agents/nope/restart")
    assert resp.status_code == 404


def test_restart_agent_success(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.restart_agent", return_value={"success": True}
    ) as mock_restart:
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/restart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["operation"] == "restart"
    mock_restart.assert_called_once_with("192.168.1.100", "hermes", agent_name="demo")


def test_restart_agent_lifecycle_error_sanitized(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.restart_agent",
        side_effect=LifecycleError("failed at /home/user/.config/clawrium/hosts.json"),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/restart")
    assert resp.status_code == 500
    assert "/home/user/.config" not in resp.json()["detail"]
    assert "<path>" in resp.json()["detail"]


def test_restart_agent_generic_exception_uses_safe_message(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    with patch(
        "clawrium.gui.routes.fleet.restart_agent",
        side_effect=RuntimeError("boom"),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/agents/demo/restart")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Lifecycle operation failed. Check server logs."


def test_fleet_endpoint_returns_tier1_model(isolated_config: Path):
    """End-to-end: `/api/fleet` JSON carries the tier-1 model (#790).

    A stale ``config.provider.default_model`` mirror in ``hosts.json``
    must NOT bleed into the serialized response — the live tier-1
    attachment + providers.json record is the source of truth. Keep
    this test forever; it is the user-visible gate for the original
    bug.
    """
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "wolf-i",
            "agents": {
                "clawrium-exec": {
                    "type": "openclaw",
                    "agent_name": "clawrium-exec",
                    "version": "1.0.0",
                    "providers": [{"name": "glm51"}],
                    "config": {
                        # Pre-#790 stale mirror — must be ignored.
                        "provider": {
                            "name": "openai-prod",
                            "type": "openai",
                            "default_model": "openai/gpt-4o",
                        },
                    },
                }
            },
        }
    ]
    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(json.dumps(hosts))
    (isolated_config / "providers.json").write_text(
        json.dumps(
            [
                {
                    "name": "glm51",
                    "type": "litellm",
                    "default_model": "z-ai/glm-5.1",
                }
            ]
        )
    )

    with TestClient(app) as client:
        resp = client.get("/api/fleet")
    assert resp.status_code == 200
    body = resp.json()
    agents = body["agents"]
    assert len(agents) == 1
    assert agents[0]["agent_key"] == "clawrium-exec"
    assert agents[0]["provider"] == "glm51"
    assert agents[0]["provider_type"] == "litellm"
    assert agents[0]["model"] == "z-ai/glm-5.1"
    # Explicit negative gates — keep the regression contract
    # self-documenting if the stale-mirror strings get renamed.
    assert agents[0]["model"] != "openai/gpt-4o"
    assert agents[0]["provider"] != "openai-prod"
    assert agents[0]["provider_type"] != "openai"


def test_fleet_endpoint_broken_attachment_fails_closed(isolated_config: Path):
    """Tier-1 attachment absent from providers.json → "broken" badge (#790).

    The "providers.json drifted from hosts.json" mode is the real-world
    drift this Phase 1 fix protects against. The serializer must surface
    "-" rather than silently falling back to any tier-2 mirror.
    """
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "wolf-i",
            "agents": {
                "clawrium-exec": {
                    "type": "openclaw",
                    "agent_name": "clawrium-exec",
                    "version": "1.0.0",
                    "providers": [{"name": "missing-prov"}],
                    "config": {
                        # Stale mirror present — must NOT be used as a fallback.
                        "provider": {
                            "name": "openai-prod",
                            "type": "openai",
                            "default_model": "openai/gpt-4o",
                        },
                    },
                }
            },
        }
    ]
    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(json.dumps(hosts))
    # No providers.json — get_provider returns None for any lookup.
    (isolated_config / "providers.json").write_text("[]")

    with TestClient(app) as client:
        resp = client.get("/api/fleet")
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["provider"] == "-"
    assert agents[0]["provider_type"] is None
    assert agents[0]["model"] == "-"
    assert agents[0]["model"] != "openai/gpt-4o"

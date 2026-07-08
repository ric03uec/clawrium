"""Tests for the static/health split on the agent-detail API (issue #758).

The static endpoint must:
  - return identity from hosts.json without invoking check_claw_health
  - succeed even when a remote probe would fail or hang

The /health endpoint must:
  - run check_claw_health and surface its result
  - include latest_supported_version (moved from the static endpoint)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from clawrium.core.health import ClawStatus, HealthResult
from clawrium.gui.server import app


def _seed_hosts(config_dir: Path) -> None:
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "box",
            "port": 22,
            "user": "xclm",
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 4,
                "memtotal_mb": 8192,
                "os": "ubuntu",
                "os_version": "24.04",
                "gpu": {"present": False},
            },
            "agents": {
                "demo": {
                    "type": "openclaw",
                    "agent_name": "demo",
                    "name": "demo",
                    "version": "2026.4.2",
                    "status": "installed",
                    "onboarding": {"state": "ready", "stages": {}},
                    "config": {
                        "provider": {"type": "anthropic", "name": "claude"},
                        "gateway": {"port": 40000, "url": "ws://x:40000"},
                    },
                }
            },
        }
    ]
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(json.dumps(hosts))


def test_static_endpoint_does_not_call_check_claw_health(isolated_config: Path):
    """The page-shell endpoint must never invoke the SSH probe."""
    _seed_hosts(isolated_config)
    with patch(
        "clawrium.cli.tui.data.check_claw_health",
        side_effect=AssertionError("probe must not run on static path"),
    ) as probe:
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo")
    assert resp.status_code == 200, resp.text
    probe.assert_not_called()
    body = resp.json()
    assert body["agent_name"] == "demo"
    assert body["agent_type"] == "openclaw"
    assert body["version"] == "2026.4.2"
    # latest_supported_version was moved to /health in #758.
    assert "latest_supported_version" not in body


def test_static_endpoint_returns_fast_when_probe_would_hang(isolated_config: Path):
    """A hanging probe must not bleed into the static-data response."""
    _seed_hosts(isolated_config)

    def _slow_probe(*_a, **_kw):
        time.sleep(5)
        raise RuntimeError("should not be reached — static path skips the probe")

    with patch("clawrium.cli.tui.data.check_claw_health", side_effect=_slow_probe):
        start = time.monotonic()
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo")
        elapsed = time.monotonic() - start
    assert resp.status_code == 200
    assert elapsed < 2.0, f"static endpoint blocked on probe ({elapsed:.2f}s)"


def test_health_endpoint_returns_runtime_fields(isolated_config: Path):
    _seed_hosts(isolated_config)
    fake_result = HealthResult(
        agent="demo",
        host="192.168.1.100",
        status=ClawStatus.RUNNING,
        user="xclm",
        error=None,
        missing_secrets=None,
        onboarding_step=None,
        process_running=True,
        onboarding_stages=None,
        cpu_count=4,
        memory_total_mb=8192,
    )
    with patch(
        "clawrium.cli.tui.data.check_claw_health", return_value=fake_result
    ) as probe:
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/health")
    assert resp.status_code == 200, resp.text
    probe.assert_called_once()
    body = resp.json()
    assert body["agent_key"] == "demo"
    assert body["status"] == "running"
    assert body["process_running"] is True
    assert body["cpu_count"] == 4
    assert body["memory_total_mb"] == 8192
    # latest_supported_version is bundled into the health response now.
    assert "latest_supported_version" in body


def test_health_endpoint_404_for_unknown_agent(isolated_config: Path):
    _seed_hosts(isolated_config)
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/nope/health")
    assert resp.status_code == 404


def test_health_endpoint_404_when_host_mismatch(isolated_config: Path):
    """?host=wronghost on /health must 404 — symmetric to the static route.

    Ensures the host-guard is in place; without this test a regression
    would let per-host runtime data leak across hosts (ATX W4).
    """
    _seed_hosts(isolated_config)
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/demo/health?host=wronghost")
    assert resp.status_code == 404
    assert "demo" in resp.json()["detail"]
    assert "wronghost" in resp.json()["detail"]


def test_health_endpoint_returns_degraded_on_probe_exception(isolated_config: Path):
    """A probe TimeoutError must surface as a 200 with health_error populated.

    The probe wrapper (`check_claw_health_safe`) catches exceptions and
    returns a degraded HealthResult; the endpoint must NOT 500 (ATX W5).
    """
    _seed_hosts(isolated_config)
    with patch(
        "clawrium.cli.tui.data.check_claw_health",
        side_effect=TimeoutError("ssh probe took too long"),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["health_error"] == "Health check failed — see server logs."
    assert "ssh probe timed out" not in body["health_error"]
    assert body["process_running"] is None
    assert body["cpu_count"] is None
    assert body["memory_total_mb"] is None


def test_health_endpoint_response_shape_pinned(isolated_config: Path):
    """The /health response shape is part of the contract with the GUI.

    A renamed or dropped field would silently degrade to `undefined` in
    React and break the UX without any backend test failing (ATX W6).
    """
    _seed_hosts(isolated_config)
    fake_result = HealthResult(
        agent="demo",
        host="192.168.1.100",
        status=ClawStatus.RUNNING,
        user="xclm",
        error=None,
        missing_secrets=None,
        onboarding_step=None,
        process_running=True,
        onboarding_stages=None,
        cpu_count=4,
        memory_total_mb=8192,
    )
    with patch(
        "clawrium.cli.tui.data.check_claw_health", return_value=fake_result
    ):
        with TestClient(app) as client:
            resp = client.get("/api/fleet/agents/demo/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "agent_key",
        "status",
        "process_running",
        "health_error",
        "cpu_count",
        "memory_total_mb",
        "missing_secrets",
        "onboarding_step",
        "latest_supported_version",
    }
    assert isinstance(body["agent_key"], str)
    assert isinstance(body["status"], str)
    assert body["health_error"] is None
    # uptime was intentionally dropped from /health (S5) — owned by
    # the static endpoint where it actually originates.
    assert "uptime" not in body

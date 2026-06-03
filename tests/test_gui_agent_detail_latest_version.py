"""Tests for `latest_supported_version` on the agent-detail API (issue #592)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from clawrium.gui.server import app


def _seed_hosts(
    config_dir: Path,
    *,
    agent_type: str,
    installed_version: str,
    architecture: str = "x86_64",
    os_: str = "ubuntu",
    os_version: str = "24.04",
) -> None:
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "box",
            "port": 22,
            "user": "xclm",
            "hardware": {
                "architecture": architecture,
                "processor_cores": 4,
                "memtotal_mb": 8192,
                "os": os_,
                "os_version": os_version,
                "gpu": {"present": False},
            },
            "agents": {
                "demo": {
                    "type": agent_type,
                    "agent_name": "demo",
                    "name": "demo",
                    "version": installed_version,
                    "status": "installed",
                    "onboarding": {"state": "ready", "stages": {}},
                    "config": {},
                }
            },
        }
    ]
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(json.dumps(hosts))


def test_agent_detail_includes_latest_supported_version(isolated_config: Path):
    _seed_hosts(isolated_config, agent_type="openclaw", installed_version="2026.4.2")
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/demo")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "latest_supported_version" in body
    assert body["latest_supported_version"] == "2026.5.28"


def test_agent_detail_latest_supported_version_is_none_for_unmatched_host(
    isolated_config: Path,
):
    """openclaw has no aarch64 platform entry — field must be None, not omitted."""
    _seed_hosts(
        isolated_config,
        agent_type="openclaw",
        installed_version="2026.4.2",
        architecture="aarch64",
    )
    with TestClient(app) as client:
        resp = client.get("/api/fleet/agents/demo")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "latest_supported_version" in body
    assert body["latest_supported_version"] is None

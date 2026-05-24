"""Shared fixtures for `tests/cli/agent/*`.

Mirrors `tests/cli/clawctl/conftest.py` so the R3-closure test can
exercise `clawctl agent configure` with the same isolated config dir.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def fleet_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "clawrium"
    config_dir.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    hosts: list[dict] = [
        {
            "hostname": "10.0.0.1",
            "key_id": "10.0.0.1",
            "port": 22,
            "user": "alice",
            "auth_method": "key",
            "alias": "wolf-i",
            "aliases": ["wolf-i"],
            "addresses": [
                {
                    "address": "10.0.0.1",
                    "is_primary": True,
                    "label": None,
                    "added_at": _utcnow(),
                }
            ],
            "metadata": {
                "added_at": _utcnow(),
                "last_seen": _utcnow(),
                "labels": {"env": "prod"},
            },
            "hardware": {"architecture": "x86_64", "processor_cores": 8},
            "agents": {
                "openclaw": {
                    "type": "openclaw",
                    "agent_name": "wise-hypatia",
                    "version": "0.4.2",
                    "installed_at": _utcnow(),
                    "status": "installed",
                    "onboarding": {"state": "ready", "stages": {}},
                    "config": {},
                }
            },
        }
    ]
    (config_dir / "hosts.json").write_text(json.dumps(hosts, indent=2))
    return config_dir


@pytest.fixture
def stdin_not_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    from clawrium.cli.clawctl import _common

    monkeypatch.setattr(_common, "stdin_is_tty", lambda *a, **k: False)

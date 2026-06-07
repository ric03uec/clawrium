"""Provider-CLI test fixtures.

Extends the clawctl `fleet_dir` fixture with a hermes agent so the
multi-provider attach tests (#612) have a real hermes target without
perturbing tests that count the default fleet (e.g.
`test_get_name_format` asserts an exact single-agent listing).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def hermes_fleet_dir(fleet_dir: Path) -> Path:
    """Augment the seeded hosts.json with a hermes agent (`sage-hermes`)."""
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["sage-hermes"] = {
        "type": "hermes",
        "agent_name": "sage-hermes",
        "version": "v2026.5.7",
        "installed_at": _utcnow(),
        "status": "installed",
        "onboarding": {
            "state": "ready",
            "stages": {
                "providers": {
                    "status": "complete",
                    "completed_at": _utcnow(),
                },
                "identity": {
                    "status": "complete",
                    "completed_at": _utcnow(),
                },
            },
        },
        "config": {},
    }
    hosts_path.write_text(json.dumps(hosts, indent=2))
    return fleet_dir

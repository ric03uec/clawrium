"""Test fixtures for clawctl host + agent CLI tests.

Builds a synthetic hosts.json in a tmp config dir and points
`XDG_CONFIG_HOME` at the tmp parent so `core/config.py:get_config_dir`
resolves to `<tmp>/clawrium/hosts.json`.
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
    """Point XDG_CONFIG_HOME at a tmp dir holding a seed hosts.json.

    `core/config.py:get_config_dir()` resolves to
    `$XDG_CONFIG_HOME/clawrium` when set. We build that subdir and
    seed `hosts.json` there.
    """
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
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 8,
                "memtotal_mb": 16000,
            },
            "agents": {
                "openclaw": {
                    "type": "openclaw",
                    "agent_name": "wise-hypatia",
                    "version": "0.4.2",
                    "installed_at": _utcnow(),
                    "status": "installed",
                    "onboarding": {
                        # Outer `state` is the state-machine pointer
                        # (core/onboarding.py:228). Per-stage records use
                        # `status` (core/onboarding.py:327, 451-457).
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
                            "channels": {"status": "skipped"},
                            "validate": {
                                "status": "complete",
                                "completed_at": _utcnow(),
                            },
                        },
                    },
                    "config": {
                        "providers": {"anthropic": {"model": "claude-opus"}},
                        "skills": ["clawrium/tdd"],
                    },
                },
            },
        },
        {
            "hostname": "10.0.0.2",
            "key_id": "10.0.0.2",
            "port": 22,
            "user": "bob",
            "auth_method": "key",
            "alias": "kevin",
            "aliases": ["kevin"],
            "addresses": [
                {
                    "address": "10.0.0.2",
                    "is_primary": True,
                    "label": None,
                    "added_at": _utcnow(),
                }
            ],
            "metadata": {
                "added_at": _utcnow(),
                "last_seen": None,
                "labels": {"env": "dev"},
            },
            "hardware": {
                "architecture": "armv7l",
                "processor_cores": 4,
                "memtotal_mb": 4000,
            },
            "agents": {},
        },
    ]

    (config_dir / "hosts.json").write_text(json.dumps(hosts, indent=2))
    return config_dir


@pytest.fixture
def stdin_not_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force `stdin_is_tty()` to report False for the duration of a test."""
    from clawrium.cli.clawctl import _common

    monkeypatch.setattr(_common, "stdin_is_tty", lambda *a, **k: False)


@pytest.fixture
def stdin_is_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force `stdin_is_tty()` to report True for the duration of a test."""
    from clawrium.cli.clawctl import _common

    monkeypatch.setattr(_common, "stdin_is_tty", lambda *a, **k: True)

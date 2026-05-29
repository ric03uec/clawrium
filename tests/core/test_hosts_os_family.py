"""Tests for `os_family` backfill in hosts.py (issue #469 step 1)."""

from __future__ import annotations

import json

from clawrium.core.hosts import _apply_legacy_defaults, load_hosts


def test_apply_legacy_defaults_fills_missing_os_family():
    record = {"hostname": "h", "key_id": "h"}
    out = _apply_legacy_defaults(record)
    assert out["os_family"] == "linux"


def test_apply_legacy_defaults_preserves_existing_os_family():
    record = {"hostname": "h", "key_id": "h", "os_family": "darwin"}
    out = _apply_legacy_defaults(record)
    assert out["os_family"] == "darwin"


def test_load_hosts_backfills_pre_469_records(tmp_path, monkeypatch):
    """A hosts.json written before #469 lacks `os_family` — load_hosts must
    transparently treat such records as Linux without raising.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hosts_path = config_dir / "hosts.json"
    hosts_path.write_text(
        json.dumps(
            [
                {
                    "hostname": "legacy-1",
                    "key_id": "legacy-1",
                    "user": "xclm",
                    "port": 22,
                    "addresses": [
                        {"address": "legacy-1", "is_primary": True, "label": None}
                    ],
                }
            ]
        )
    )
    monkeypatch.setattr("clawrium.core.hosts.get_config_dir", lambda: config_dir)

    hosts = load_hosts()
    assert len(hosts) == 1
    assert hosts[0]["os_family"] == "linux"


def test_load_hosts_preserves_darwin_records(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hosts_path = config_dir / "hosts.json"
    hosts_path.write_text(
        json.dumps(
            [
                {
                    "hostname": "mac-1",
                    "key_id": "mac-1",
                    "user": "xclm",
                    "port": 22,
                    "os_family": "darwin",
                    "addresses": [
                        {"address": "mac-1", "is_primary": True, "label": None}
                    ],
                }
            ]
        )
    )
    monkeypatch.setattr("clawrium.core.hosts.get_config_dir", lambda: config_dir)

    hosts = load_hosts()
    assert hosts[0]["os_family"] == "darwin"

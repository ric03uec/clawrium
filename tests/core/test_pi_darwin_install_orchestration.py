"""Mocked Darwin Pi installation dispatch through the production runner."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from clawrium.core.install import InstallationError, run_installation


def _result(status="successful"):
    result = MagicMock()
    result.status = status
    result.rc = 0 if status == "successful" else 1
    result.events = []
    return result


@pytest.fixture
def mac_host(isolated_config, monkeypatch):
    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "mac.example",
                    "alias": "mac",
                    "user": "piuser",
                    "port": 22,
                    "key_id": "mac-key",
                    "hardware": {
                        "architecture": "arm64",
                        "os": "macos",
                        "os_version": "14.0",
                        "memtotal_mb": 8192,
                    },
                    "os_family": "darwin",
                    "agents": {},
                }
            ]
        )
    )
    import clawrium.core.install as install

    monkeypatch.setattr(install, "get_host_private_key", lambda _: "test-key")
    return isolated_config


def test_pi_darwin_install_selects_macos_playbook_and_records_success(mac_host):
    with patch(
        "clawrium.core.install.ansible_runner.run", side_effect=[_result(), _result()]
    ) as run:
        result = run_installation("pi", "mac", name="pi-mac")
    assert result["success"]
    assert str(run.call_args_list[1].kwargs["playbook"]).endswith(
        "pi/playbooks/install_macos.yaml"
    )
    record = json.loads((mac_host / "hosts.json").read_text())[0]["agents"]["pi-mac"]
    assert record["status"] == "installed" and record["type"] == "pi"


def test_pi_darwin_install_failure_records_failed_state(mac_host):
    with patch(
        "clawrium.core.install.ansible_runner.run",
        side_effect=[_result(), _result("failed")],
    ):
        with pytest.raises(InstallationError):
            run_installation("pi", "mac", name="pi-mac")
    record = json.loads((mac_host / "hosts.json").read_text())[0]["agents"]["pi-mac"]
    assert record["status"] == "failed" and record["installed_at"] is None

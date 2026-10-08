"""Executed orchestration tests for the public Pi create/install path."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from clawrium.core.install import InstallationError, run_installation


@pytest.fixture
def pi_host(isolated_config, monkeypatch):
    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "pi-test-host",
                    "alias": "pi-test-host",
                    "port": 22,
                    "user": "xclm",
                    "key_id": "pi-test-host",
                    "hardware": {
                        "architecture": "x86_64",
                        "os": "ubuntu",
                        "os_version": "24.04",
                        "memtotal_mb": 8192,
                    },
                    "agents": {},
                }
            ]
        )
    )
    import clawrium.core.install as install

    monkeypatch.setattr(install, "get_host_private_key", lambda _: "test-key")
    return isolated_config


def _result(status="successful"):
    result = MagicMock()
    result.status, result.rc, result.events = (
        status,
        0 if status == "successful" else 1,
        [],
    )
    return result


def test_pi_install_success_records_agent_and_dispatches_pi_playbook(pi_host):
    with patch(
        "clawrium.core.install.ansible_runner.run", side_effect=[_result(), _result()]
    ) as run:
        result = run_installation("pi", "pi-test-host", name="pi-created")
    assert result["success"] is True
    calls = run.call_args_list
    assert len(calls) == 2
    assert str(calls[1].kwargs["playbook"]).endswith("pi/playbooks/install.yaml")
    assert "pi-created" in str(calls[1])
    agent = json.loads((pi_host / "hosts.json").read_text())[0]["agents"]["pi-created"]
    assert (
        agent["type"] == "pi"
        and agent["status"] == "installed"
        and agent["installed_at"]
    )


def test_pi_install_failure_persists_recoverable_failed_state(pi_host):
    with patch(
        "clawrium.core.install.ansible_runner.run",
        side_effect=[_result(), _result("failed")],
    ):
        with pytest.raises(InstallationError):
            run_installation("pi", "pi-test-host", name="pi-failed")
    agent = json.loads((pi_host / "hosts.json").read_text())[0]["agents"]["pi-failed"]
    assert agent["type"] == "pi" and agent["status"] == "failed"
    assert agent["installed_at"] is None and agent["error"]

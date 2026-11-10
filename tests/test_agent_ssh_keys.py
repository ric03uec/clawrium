"""Tests for shared system-level agent SSH identity provisioning."""

from __future__ import annotations

from importlib.resources import files
from types import SimpleNamespace

import pytest
import yaml


def _host() -> dict:
    return {
        "hostname": "host.example",
        "key_id": "stable-host-id",
        "user": "xclm",
        "os_family": "linux",
    }


def test_preflight_precedes_generation_and_provision(monkeypatch, isolated_config, tmp_path):
    from clawrium.core.agent_ssh_keys import ensure_agent_ssh_identity
    from clawrium.core.keys import generate_host_keypair

    generate_host_keypair("stable-host-id")
    calls: list[dict] = []

    def runner(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="successful")

    monkeypatch.setattr("clawrium.core.agent_ssh_keys.ansible_runner.run", runner)
    private, public = ensure_agent_ssh_identity(
        _host(), "agent-one", private_data_dir=tmp_path
    )

    assert private.exists() and public.exists()
    assert [call["extravars"]["agent_ssh_key_phase"] for call in calls] == [
        "preflight",
        "provision",
    ]
    assert calls[0]["extravars"]["controller_pair_exists"] is False
    assert calls[1]["extravars"]["controller_pair_exists"] is True
    assert "OPENSSH PRIVATE KEY" not in str(calls[1]["extravars"])


def test_provision_failure_keeps_controller_identity_for_safe_retry(
    monkeypatch, isolated_config, tmp_path
):
    from clawrium.core.agent_ssh_keys import AgentSSHIdentityError, ensure_agent_ssh_identity
    from clawrium.core.keys import generate_host_keypair

    generate_host_keypair("stable-host-id")
    statuses = iter(["successful", "failed"])
    monkeypatch.setattr(
        "clawrium.core.agent_ssh_keys.ansible_runner.run",
        lambda **_kwargs: SimpleNamespace(status=next(statuses)),
    )
    try:
        ensure_agent_ssh_identity(_host(), "agent-one", private_data_dir=tmp_path)
    except AgentSSHIdentityError:
        pass
    else:
        raise AssertionError("provision failure must be reported")

    from clawrium.core.keys import read_agent_public_key

    fingerprint = read_agent_public_key("stable-host-id", "agent-one")
    assert fingerprint
    monkeypatch.setattr(
        "clawrium.core.agent_ssh_keys.ansible_runner.run",
        lambda **_kwargs: SimpleNamespace(status="successful"),
    )
    ensure_agent_ssh_identity(_host(), "agent-one", private_data_dir=tmp_path)
    assert read_agent_public_key("stable-host-id", "agent-one") == fingerprint


def test_preflight_failure_never_generates_controller_key(monkeypatch, isolated_config, tmp_path):
    from clawrium.core.agent_ssh_keys import AgentSSHIdentityError, ensure_agent_ssh_identity
    from clawrium.core.keys import generate_host_keypair, get_agent_private_key

    generate_host_keypair("stable-host-id")
    monkeypatch.setattr(
        "clawrium.core.agent_ssh_keys.ansible_runner.run",
        lambda **_kwargs: SimpleNamespace(status="failed"),
    )

    try:
        ensure_agent_ssh_identity(_host(), "agent-one", private_data_dir=tmp_path)
    except AgentSSHIdentityError:
        pass
    else:
        raise AssertionError("unsafe remote state must fail")
    assert get_agent_private_key("stable-host-id", "agent-one") is None


@pytest.mark.parametrize("name", ("agent_ssh_keys.yaml", "agent_ssh_keys_macos.yaml"))
def test_key_playbook_allows_missing_identity_paths(name):
    """Absent remote key files are normal on first provisioning."""
    playbook = files("clawrium.platform.playbooks") / name
    tasks = yaml.safe_load(playbook.read_text())[0]["tasks"]
    guard = next(
        task
        for task in tasks
        if task["name"] == "Refuse unsafe or orphaned remote identity"
    )
    assert "selectattr('stat.islnk', 'defined')" in guard["when"]

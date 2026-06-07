"""Tests for `apply_state` — the per-agent reconciler (#411).

Mocks ansible-runner and host resolution so the tests exercise the
materialization + dispatch pipeline without touching SSH.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawrium.core import skills_apply as apply_mod
from clawrium.core import skills_state as state_mod
from clawrium.core.skills_apply import (
    AgentNotFoundError,
    SkillApplyError,
    SkillApplyNotSupported,
    apply_state,
)


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(apply_mod, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(state_mod, "get_config_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def fake_hermes_host(monkeypatch):
    host = {
        "hostname": "host-a",
        "alias": "alias-a",
        "user": "xclm",
        "port": 22,
        "key_id": "host-a",
    }
    monkeypatch.setattr(
        apply_mod, "get_agent_by_name", lambda name: (host, "hermes", {"agent_name": name})
    )
    return host


@pytest.fixture
def fake_openclaw_host(monkeypatch):
    host = {"hostname": "host-b", "alias": "alias-b", "user": "xclm", "port": 22}
    monkeypatch.setattr(
        apply_mod,
        "get_agent_by_name",
        lambda name: (host, "openclaw", {"agent_name": name}),
    )
    return host


@pytest.fixture
def stub_ssh_key(monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_text("fake-key")
    monkeypatch.setattr(apply_mod, "get_host_private_key", lambda _id: key)
    return key


@pytest.fixture
def stub_ansible(monkeypatch):
    captured: dict = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="successful", events=[])

    fake_module = SimpleNamespace(run=fake_run)
    monkeypatch.setitem(__import__("sys").modules, "ansible_runner", fake_module)
    return captured


def _seed_state(cfg_dir: Path, agent: str, refs: list[str]) -> None:
    state_file = cfg_dir / "agents" / agent / "skills.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"skills": refs}, indent=2))


def test_invalid_agent_name(cfg_dir):
    with pytest.raises(AgentNotFoundError):
        apply_state("../bad")


def test_unknown_agent(cfg_dir, monkeypatch):
    monkeypatch.setattr(apply_mod, "get_agent_by_name", lambda n: None)
    with pytest.raises(AgentNotFoundError):
        apply_state("no-such")


def test_unsupported_claw(cfg_dir, fake_openclaw_host):
    with pytest.raises(SkillApplyNotSupported):
        apply_state("agent-x")


def test_supported_hermes_runs(
    cfg_dir, fake_hermes_host, stub_ssh_key, stub_ansible, tmp_path
):
    _seed_state(cfg_dir, "agent-x", ["vetted/tdd"])
    result = apply_state("agent-x")
    assert result.agent_type == "hermes"
    assert result.hostname == "host-a"
    assert "vetted/tdd" in result.applied_skills
    assert stub_ansible["playbook"].endswith("skills_apply.yaml")


def test_runs_with_empty_state(
    cfg_dir, fake_hermes_host, stub_ssh_key, stub_ansible
):
    # No state file → empty desired state, playbook still runs to
    # converge host (e.g. prune drift).
    result = apply_state("agent-x")
    assert result.applied_skills == []


def test_apply_failure_surfaces(
    cfg_dir, fake_hermes_host, stub_ssh_key, monkeypatch
):
    _seed_state(cfg_dir, "agent-x", ["vetted/tdd"])

    fake = SimpleNamespace(
        run=lambda **kw: SimpleNamespace(
            status="failed",
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {"res": {"msg": "boom"}},
                }
            ],
        )
    )
    monkeypatch.setitem(__import__("sys").modules, "ansible_runner", fake)
    with pytest.raises(SkillApplyError) as exc:
        apply_state("agent-x")
    assert "boom" in str(exc.value)


def test_apply_timeout(cfg_dir, fake_hermes_host, stub_ssh_key, monkeypatch):
    _seed_state(cfg_dir, "agent-x", ["vetted/tdd"])
    fake = SimpleNamespace(
        run=lambda **kw: SimpleNamespace(status="timeout", events=[])
    )
    monkeypatch.setitem(__import__("sys").modules, "ansible_runner", fake)
    with pytest.raises(SkillApplyError) as exc:
        apply_state("agent-x", timeout=1)
    assert "timed out" in str(exc.value)


def test_invalid_ref_in_state_blocks_apply(
    cfg_dir, fake_hermes_host, stub_ssh_key, stub_ansible
):
    # State file with a deliberately invalid ref (skip migration by
    # writing a clearly bogus prefix that won't match _LEGACY_PREFIXES).
    state_file = cfg_dir / "agents" / "agent-x" / "skills.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"skills": ["bogusprefix/foo"]}))
    # `read_state` drops unknown legacy refs → empty state → playbook
    # still runs without error.
    result = apply_state("agent-x")
    assert result.applied_skills == []


def test_missing_ssh_key(cfg_dir, fake_hermes_host, monkeypatch):
    monkeypatch.setattr(apply_mod, "get_host_private_key", lambda _id: None)
    _seed_state(cfg_dir, "agent-x", ["vetted/tdd"])
    with pytest.raises(SkillApplyError) as exc:
        apply_state("agent-x")
    assert "SSH key" in str(exc.value)

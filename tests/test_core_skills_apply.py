"""Tests for `apply_state` — the per-agent reconciler.

Mocks ansible-runner and host resolution so the tests exercise the
materialization + dispatch pipeline without touching SSH or a real
inventory. Phase 2 only wires hermes; openclaw/zeroclaw should raise
`SkillApplyNotSupported`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from clawrium.core import skills_apply
from clawrium.core.skills import (
    IncompatibleSkillRegistry,
    NATIVE_REGISTRIES,
)
from clawrium.core.skills_apply import (
    AgentNotFoundError,
    SkillApplyError,
    SkillApplyNotSupported,
    apply_state,
    materialize_for_claw,
)
from clawrium.core.skills_state import write_state


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def _runner_result(status: str = "successful", events=None):
    """Build a stand-in for ansible_runner.run's return value."""
    result = MagicMock()
    result.status = status
    result.events = events or []
    return result


def _stub_host(hostname: str = "wolf-i", alias: str = "wolf-i") -> dict:
    return {
        "hostname": hostname,
        "alias": alias,
        "user": "wolf-i",
        "port": 22,
        "key_id": hostname,
    }


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_type: str = "hermes",
    host: dict | None = None,
    runner_result=None,
    ssh_key: Path | None = Path("/tmp/fake-key"),
):
    """Patch every external touchpoint used by apply_state.

    `ssh_key=None` simulates a missing host key (use to exercise the
    `SkillApplyError("SSH key…")` path).
    """
    host = host or _stub_host()
    runner_result = runner_result or _runner_result()

    monkeypatch.setattr(
        skills_apply,
        "get_agent_by_name",
        lambda name: (host, agent_type, {"agent_name": name}),
    )
    monkeypatch.setattr(
        skills_apply, "get_host_private_key", lambda _key_id: ssh_key
    )

    runner_mock = MagicMock()
    runner_mock.run.return_value = runner_result
    monkeypatch.setitem(sys.modules, "ansible_runner", runner_mock)
    return runner_mock


# ---------------------------- happy-path apply ------------------------------


def test_apply_state_hermes_empty_state_runs_playbook(monkeypatch):
    runner = _patch_runtime(monkeypatch)
    result = apply_state("tdd-hermes")
    assert result.agent_type == "hermes"
    assert result.applied_skills == []
    runner.run.assert_called_once()
    _, kwargs = runner.run.call_args
    extravars = kwargs["inventory"]["all"]["vars"]
    assert extravars["agent_name"] == "tdd-hermes"
    assert extravars["agent_type"] == "hermes"
    assert extravars["desired_skill_names"] == []


def test_apply_state_hermes_stages_and_applies_clawrium_tdd(monkeypatch, tmp_path):
    write_state("tdd-hermes", ["clawrium/tdd"])
    runner = _patch_runtime(monkeypatch)

    result = apply_state("tdd-hermes")

    assert result.applied_skills == ["clawrium/tdd"]
    _, kwargs = runner.run.call_args
    extravars = kwargs["inventory"]["all"]["vars"]
    assert extravars["desired_skill_names"] == ["tdd"]
    staging_dir = Path(extravars["staging_dir"])
    # apply_state cleans staging in `finally`; the dir should NOT exist
    # by the time the call returns.
    assert not staging_dir.exists()


def test_apply_state_stages_materialized_skill_md(monkeypatch, tmp_path):
    """Capture the staging dir mid-run and assert SKILL.md was written
    with the merged hermes-native frontmatter."""
    write_state("tdd-hermes", ["clawrium/tdd"])

    captured = {}

    def capture_and_succeed(**kwargs):
        staging = Path(kwargs["inventory"]["all"]["vars"]["staging_dir"])
        skill_md = staging / "tdd" / "SKILL.md"
        captured["text"] = skill_md.read_text()
        return _runner_result()

    runner = _patch_runtime(monkeypatch)
    runner.run.side_effect = capture_and_succeed

    apply_state("tdd-hermes")

    text = captured["text"]
    assert text.startswith("---\n")
    frontmatter_block, body = text.split("\n---\n", 1)
    frontmatter = yaml.safe_load(frontmatter_block[len("---\n"):])
    # The clawrium/* → hermes materializer must keep name/description
    # and lift the native.hermes.metadata.hermes.tags override into
    # the rendered frontmatter.
    assert frontmatter["name"] == "tdd"
    assert "description" in frontmatter
    assert frontmatter.get("metadata", {}).get("hermes", {}).get("tags") == [
        "tdd",
        "testing",
        "discipline",
        "clawrium",
    ]
    assert body.strip().startswith("# TDD")


# ---------------------------- error paths -----------------------------------


def test_apply_state_invalid_agent_name():
    with pytest.raises(AgentNotFoundError):
        apply_state("Invalid Name")


def test_apply_state_agent_not_found(monkeypatch):
    monkeypatch.setattr(skills_apply, "get_agent_by_name", lambda _name: None)
    with pytest.raises(AgentNotFoundError, match="not found"):
        apply_state("tdd-hermes")


def test_apply_state_ambiguous_agent_name(monkeypatch):
    def raise_value_error(_name):
        raise ValueError("Agent name 'tdd' is ambiguous across hosts: ...")

    monkeypatch.setattr(skills_apply, "get_agent_by_name", raise_value_error)
    with pytest.raises(AgentNotFoundError, match="ambiguous"):
        apply_state("tdd-hermes")


def test_apply_state_openclaw_not_supported(monkeypatch):
    _patch_runtime(monkeypatch, agent_type="openclaw")
    with pytest.raises(SkillApplyNotSupported, match="not implemented yet|openclaw"):
        apply_state("tdd-openclaw")


def test_apply_state_unknown_agent_type(monkeypatch):
    _patch_runtime(monkeypatch, agent_type="something-weird")
    with pytest.raises(SkillApplyNotSupported, match="unsupported claw type"):
        apply_state("tdd-weird")


def test_apply_state_missing_ssh_key(monkeypatch):
    write_state("tdd-hermes", ["clawrium/tdd"])
    _patch_runtime(monkeypatch, ssh_key=None)
    with pytest.raises(SkillApplyError, match="SSH key"):
        apply_state("tdd-hermes")


def test_apply_state_playbook_path_missing(monkeypatch):
    _patch_runtime(monkeypatch)
    # Force the playbook dispatch to point at a path that doesn't
    # exist on disk.
    monkeypatch.setattr(
        skills_apply, "_registry_playbook_dir", lambda _claw: Path("/nonexistent")
    )
    with pytest.raises(SkillApplyError, match="Playbook not found"):
        apply_state("tdd-hermes")


def test_apply_state_runner_timeout(monkeypatch):
    _patch_runtime(monkeypatch, runner_result=_runner_result(status="timeout"))
    with pytest.raises(SkillApplyError, match="timed out"):
        apply_state("tdd-hermes")


def test_apply_state_runner_failed(monkeypatch):
    events = [
        {
            "event": "runner_on_failed",
            "event_data": {"res": {"msg": "Permission denied"}},
        }
    ]
    _patch_runtime(
        monkeypatch,
        runner_result=_runner_result(status="failed", events=events),
    )
    with pytest.raises(SkillApplyError, match="Permission denied"):
        apply_state("tdd-hermes")


def test_apply_state_runner_unreachable(monkeypatch):
    events = [
        {
            "event": "runner_on_unreachable",
            "event_data": {"res": {"msg": "Connection refused"}},
        }
    ]
    _patch_runtime(
        monkeypatch,
        runner_result=_runner_result(status="failed", events=events),
    )
    with pytest.raises(SkillApplyError, match="host unreachable"):
        apply_state("tdd-hermes")


def test_apply_state_cleans_log_artifacts_on_success(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch)
    apply_state("tdd-hermes")
    # `inventory/` would contain the SSH key path + extravars; the
    # cleanup pass at the end of apply_state must remove it (matches
    # memory.py / lifecycle.py policy).
    logs_dir = tmp_path / "clawrium" / "logs"
    for log_dir in logs_dir.iterdir():
        for leaked in ("artifacts", "env", "inventory"):
            assert not (log_dir / leaked).exists(), (
                f"{log_dir / leaked} should have been cleaned"
            )


# ---------------------------- materialize_for_claw --------------------------


def test_materialize_for_claw_clawrium_to_hermes_merges_native_override():
    from clawrium.core.skills import load_skill, parse_skill_ref

    skill = load_skill(parse_skill_ref("clawrium/tdd"))
    frontmatter, body = materialize_for_claw(skill, "hermes")
    assert frontmatter["name"] == "tdd"
    assert "description" in frontmatter
    assert frontmatter["metadata"]["hermes"]["tags"] == [
        "tdd",
        "testing",
        "discipline",
        "clawrium",
    ]
    assert body.strip().startswith("# TDD")


def test_materialize_for_claw_unknown_claw_raises():
    from clawrium.core.skills import load_skill, parse_skill_ref

    skill = load_skill(parse_skill_ref("clawrium/tdd"))
    with pytest.raises(IncompatibleSkillRegistry):
        materialize_for_claw(skill, "not-a-claw")


# ---------------------------- compatibility check ---------------------------


def test_check_agent_compatibility_clawrium_default_true():
    from clawrium.core.skills import check_agent_compatibility, load_skill, parse_skill_ref

    skill = load_skill(parse_skill_ref("clawrium/tdd"))
    for claw in NATIVE_REGISTRIES:
        check_agent_compatibility(skill, claw)  # no raise


def test_check_agent_compatibility_clawrium_explicit_false_blocks(monkeypatch):
    from clawrium.core.skills import (
        Skill,
        SkillRef,
        check_agent_compatibility,
    )

    skill = Skill(
        ref=SkillRef("clawrium", "tdd"),
        path=Path("/dev/null"),
        metadata={
            "name": "tdd",
            "description": "fake",
            "compatibility": {"hermes": False, "openclaw": True, "zeroclaw": True},
        },
        body="",
    )
    with pytest.raises(IncompatibleSkillRegistry, match="not compatible"):
        check_agent_compatibility(skill, "hermes")


def test_check_agent_compatibility_native_must_match_agent_type():
    from clawrium.core.skills import (
        Skill,
        SkillRef,
        check_agent_compatibility,
    )

    skill = Skill(
        ref=SkillRef("hermes", "foo"),
        path=Path("/dev/null"),
        metadata={"name": "foo", "description": "fake"},
        body="",
    )
    check_agent_compatibility(skill, "hermes")
    with pytest.raises(IncompatibleSkillRegistry, match="hermes.*native"):
        check_agent_compatibility(skill, "openclaw")


def test_check_agent_compatibility_unknown_claw_fails_closed():
    from clawrium.core.skills import (
        Skill,
        SkillRef,
        check_agent_compatibility,
    )

    skill = Skill(
        ref=SkillRef("clawrium", "tdd"),
        path=Path("/dev/null"),
        metadata={"name": "tdd", "description": "fake"},
        body="",
    )
    with pytest.raises(IncompatibleSkillRegistry, match="Unknown agent type"):
        check_agent_compatibility(skill, "no-such-claw")


# ---------------------------- drift recovery --------------------------------


def test_apply_state_drift_recovery_reapplies_same_state(monkeypatch):
    """Re-running apply with the same state must invoke the playbook
    again. The playbook is responsible for restoring the file on the
    host if it was manually deleted — apply_state's job is just to
    invoke it idempotently."""
    write_state("tdd-hermes", ["clawrium/tdd"])
    runner = _patch_runtime(monkeypatch)

    apply_state("tdd-hermes")
    apply_state("tdd-hermes")

    assert runner.run.call_count == 2
    # Both invocations carry the same desired list.
    for call in runner.run.call_args_list:
        assert call.kwargs["inventory"]["all"]["vars"]["desired_skill_names"] == [
            "tdd"
        ]

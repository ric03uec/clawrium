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
    # Anchored to the parametrized claw type so a future reword that
    # drops `openclaw` from the message (or a third raise site added
    # elsewhere with the same generic phrase) would still surface as
    # a real test failure.
    with pytest.raises(
        SkillApplyNotSupported, match=r"not yet supported for openclaw"
    ):
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
    """The cleanup test only proves something if the directories
    actually exist at the moment cleanup runs — a MagicMock that
    never creates them makes the assertion vacuously pass. The
    side_effect below pre-creates `artifacts/`, `env/`, `inventory/`
    inside the runner's private_data_dir (with a real-looking
    inventory file mimicking what ansible-runner writes) so the
    cleanup pass has something to clean.
    """

    def create_artifacts_and_succeed(**kwargs):
        pd = Path(kwargs["private_data_dir"])
        for sub in ("artifacts", "env", "inventory"):
            (pd / sub).mkdir(parents=True, exist_ok=True)
            (pd / sub / "evidence.txt").write_text("would leak SSH key path")
        return _runner_result()

    runner = _patch_runtime(monkeypatch)
    runner.run.side_effect = create_artifacts_and_succeed

    apply_state("tdd-hermes")

    logs_dir = tmp_path / "clawrium" / "logs"
    log_dirs = list(logs_dir.iterdir())
    assert log_dirs, "expected at least one log dir on disk"
    for log_dir in log_dirs:
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


def test_check_agent_compatibility_empty_compat_map_defaults_true():
    """Per the docstring contract: a normalized clawrium skill with
    no `compatibility` keys for a given claw should default to
    *compatible*, not blocked. Catches the regression where the
    `.get(claw, default)` default was `False` instead of `True`.
    """
    from clawrium.core.skills import (
        Skill,
        SkillRef,
        check_agent_compatibility,
    )

    skill = Skill(
        ref=SkillRef("clawrium", "tdd"),
        path=Path("/dev/null"),
        metadata={"name": "tdd", "description": "fake", "compatibility": {}},
        body="",
    )
    for claw in NATIVE_REGISTRIES:
        check_agent_compatibility(skill, claw)  # no raise


def test_check_agent_compatibility_missing_key_defaults_true():
    """Same default-true contract when the entire `compatibility` key
    is absent from `_meta.yaml`. A skill that doesn't opt out should
    install on any claw."""
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
    for claw in NATIVE_REGISTRIES:
        check_agent_compatibility(skill, claw)  # no raise


def test_check_agent_compatibility_partial_map_only_blocks_explicit_false():
    """`{hermes: false}` blocks hermes only; openclaw/zeroclaw default-true."""
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
            "compatibility": {"hermes": False},
        },
        body="",
    )
    with pytest.raises(IncompatibleSkillRegistry, match="not compatible"):
        check_agent_compatibility(skill, "hermes")
    check_agent_compatibility(skill, "openclaw")  # default-true
    check_agent_compatibility(skill, "zeroclaw")  # default-true


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


def test_apply_state_openclaw_message_has_no_phase_jargon(monkeypatch):
    """`SkillApplyNotSupported` must not leak implementation-plan phase
    numbers into user-facing CLI output. The replacement message
    points the user at `clm agent ps` to find a supported agent."""
    _patch_runtime(monkeypatch, agent_type="openclaw")
    with pytest.raises(SkillApplyNotSupported) as excinfo:
        apply_state("tdd-openclaw")
    message = str(excinfo.value).lower()
    assert "phase" not in message
    assert "wires" not in message
    assert "clm agent ps" in str(excinfo.value)


def test_apply_state_runner_startup_failure_raises_skill_apply_error(monkeypatch):
    """Cover the previously-untested branch where `ansible_runner.run`
    itself raises during startup (e.g. missing executable, bad
    private_data_dir). The wrapper must translate the bare exception
    into a `SkillApplyError` instead of leaking the underlying class."""
    runner = _patch_runtime(monkeypatch)
    runner.run.side_effect = RuntimeError("ansible binary not found")
    with pytest.raises(SkillApplyError, match="ansible-runner failed to start"):
        apply_state("tdd-hermes")


def test_apply_state_failed_no_events_falls_back_to_status(monkeypatch):
    """`_extract_failure_message` must degrade to the status string
    when ansible-runner emits no `runner_on_*` events. Without this
    branch, an empty `events` list would surface as the literal word
    'unknown' — verify the wrapper handles the no-events case."""
    _patch_runtime(monkeypatch, runner_result=_runner_result(status="failed", events=[]))
    with pytest.raises(SkillApplyError, match="failed"):
        apply_state("tdd-hermes")


def test_apply_state_log_dir_sanitizes_host_alias(monkeypatch, tmp_path):
    """A tampered hosts.json with `alias: '../escape'` must not let
    the log dir traverse outside `${clawrium_config}/logs/`. The
    sanitizer replaces every non-allowlist char (including `/`) with
    `_`. Dots are kept (so timestamps remain readable), but since
    slashes are gone the `..` substring is just a filename token,
    not a path component."""
    _patch_runtime(
        monkeypatch,
        host={
            "hostname": "wolf-i",
            "alias": "../../escape",
            "user": "wolf-i",
            "port": 22,
            "key_id": "wolf-i",
        },
    )

    apply_state("tdd-hermes")

    logs_dir = (tmp_path / "clawrium" / "logs").resolve()
    log_dirs = list((tmp_path / "clawrium" / "logs").iterdir())
    assert log_dirs, "expected a log dir to be created"
    for log_dir in log_dirs:
        # The created path must be a direct child of logs_dir (a single
        # filesystem segment, no embedded slash).
        assert log_dir.parent.resolve() == logs_dir
        assert "/" not in log_dir.name
        # And the resolved path must stay rooted under logs_dir — this
        # is the safety property that matters; `..` as a substring of
        # a filename component is fine.
        assert str(log_dir.resolve()).startswith(str(logs_dir))


def test_apply_state_log_dir_strips_bidi_in_host_alias(monkeypatch, tmp_path):
    """A `hosts.json` `alias` containing U+202E (RTLO) must not let
    a spoofed log directory name reach the on-disk path. The
    `_sanitize_for_path` allowlist strips every non-`[a-zA-Z0-9._-]`
    char, which catches every bidi-format codepoint by construction —
    this test pins that behavior for the host-alias surface."""
    rtlo_alias = "wolf‮i"  # 'wolf' + RTLO + 'i'
    _patch_runtime(
        monkeypatch,
        host={
            "hostname": "wolf-i",
            "alias": rtlo_alias,
            "user": "wolf-i",
            "port": 22,
            "key_id": "wolf-i",
        },
    )

    apply_state("tdd-hermes")

    logs_dir = tmp_path / "clawrium" / "logs"
    log_dirs = list(logs_dir.iterdir())
    assert log_dirs, "expected a log dir to be created"
    for log_dir in log_dirs:
        assert "‮" not in log_dir.name, (
            f"RTLO leaked into log dir name: {log_dir.name!r}"
        )


def test_stage_skills_cleans_tempdir_on_partial_failure(monkeypatch, tmp_path):
    """If `_stage_skills` raises mid-loop (e.g. `write_text` fails on
    a disk-full simulator), the `mkdtemp` directory it just created
    must be removed before the exception propagates. Without this,
    `${clawrium_config}/staging/skills/` accumulates an orphan
    tempdir on every failure.
    """
    write_state("tdd-hermes", ["clawrium/tdd"])
    _patch_runtime(monkeypatch)

    def boom(_frontmatter, _body):
        # First skill raises; tempdir has already been created.
        raise OSError("simulated disk-full during render")

    monkeypatch.setattr(skills_apply, "_render_skill_md", boom)

    with pytest.raises(OSError, match="disk-full"):
        apply_state("tdd-hermes")

    staging_base = tmp_path / "clawrium" / "staging" / "skills"
    if staging_base.is_dir():
        leftovers = [p for p in staging_base.iterdir() if p.is_dir()]
        assert leftovers == [], (
            f"_stage_skills leaked tempdir on partial failure: {leftovers}"
        )


def test_apply_state_staging_cleaned_when_log_dir_creation_fails(monkeypatch, tmp_path):
    """If `_make_log_dir` raises after `_stage_skills` has created a
    tempdir, the staging dir must still be cleaned up. Without this
    ordering, control-machine `${clawrium_config}/staging/skills/`
    would accumulate orphan tempdirs on partial failures.
    """
    write_state("tdd-hermes", ["clawrium/tdd"])
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(
        skills_apply,
        "_make_log_dir",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        apply_state("tdd-hermes")

    staging_base = tmp_path / "clawrium" / "staging" / "skills"
    if staging_base.is_dir():
        leftovers = [p for p in staging_base.iterdir() if p.is_dir()]
        assert leftovers == [], (
            f"staging dir leaked on partial failure: {leftovers}"
        )


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

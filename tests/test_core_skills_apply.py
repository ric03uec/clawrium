"""Tests for `apply_state` — the per-agent reconciler.

Mocks ansible-runner and host resolution so the tests exercise the
materialization + dispatch pipeline without touching SSH or a real
inventory. All three native claws (hermes/openclaw/zeroclaw) are wired
as of Phase 3 (#382); unknown claw types still raise
`SkillApplyNotSupported`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import json

import pytest
import yaml

from clawrium.core import skills_apply
from clawrium.core.skills import (
    ExternalSourceBlocked,
    IncompatibleSkillRegistry,
    InvalidSkillRef,
    MissingRegistryPrefix,
    NATIVE_REGISTRIES,
)
from clawrium.core.skills_apply import (
    AgentNotFoundError,
    SkillApplyError,
    SkillApplyNotSupported,
    apply_state,
    materialize_for_claw,
)
from clawrium.core.skills_state import state_file_path, write_state


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


# ---------------------------- openclaw dispatch (Phase 3) -------------------


def test_apply_state_openclaw_empty_state_runs_playbook(monkeypatch):
    runner = _patch_runtime(monkeypatch, agent_type="openclaw")
    result = apply_state("tdd-openclaw")
    assert result.agent_type == "openclaw"
    assert result.applied_skills == []
    runner.run.assert_called_once()
    _, kwargs = runner.run.call_args
    extravars = kwargs["inventory"]["all"]["vars"]
    assert extravars["agent_type"] == "openclaw"
    assert extravars["desired_skill_names"] == []
    # The dispatched playbook path must end at the openclaw registry's
    # skills_apply.yaml — not hermes', not zeroclaw's.
    playbook_arg = kwargs["playbook"]
    assert "/openclaw/playbooks/skills_apply.yaml" in playbook_arg


def test_apply_state_openclaw_stages_and_applies_clawrium_tdd(monkeypatch):
    write_state("tdd-openclaw", ["clawrium/tdd"])
    runner = _patch_runtime(monkeypatch, agent_type="openclaw")

    result = apply_state("tdd-openclaw")

    assert result.applied_skills == ["clawrium/tdd"]
    _, kwargs = runner.run.call_args
    extravars = kwargs["inventory"]["all"]["vars"]
    assert extravars["agent_type"] == "openclaw"
    assert extravars["desired_skill_names"] == ["tdd"]
    staging_dir = Path(extravars["staging_dir"])
    # apply_state cleans staging in `finally`; the dir should NOT exist
    # by the time the call returns.
    assert not staging_dir.exists()


def test_apply_state_openclaw_materialized_skill_md_has_no_hermes_overrides(
    monkeypatch,
):
    """When materializing for openclaw, the per-claw override block under
    `native.hermes` in `_meta.yaml` must NOT bleed into the openclaw
    frontmatter — only `native.openclaw` (which is `{}` for clawrium/tdd)
    is lifted. This guards against the materializer applying the wrong
    claw's overrides."""
    write_state("tdd-openclaw", ["clawrium/tdd"])

    captured = {}

    def capture_and_succeed(**kwargs):
        staging = Path(kwargs["inventory"]["all"]["vars"]["staging_dir"])
        skill_md = staging / "tdd" / "SKILL.md"
        captured["text"] = skill_md.read_text()
        return _runner_result()

    runner = _patch_runtime(monkeypatch, agent_type="openclaw")
    runner.run.side_effect = capture_and_succeed

    apply_state("tdd-openclaw")

    text = captured["text"]
    frontmatter_block, _ = text.split("\n---\n", 1)
    frontmatter = yaml.safe_load(frontmatter_block[len("---\n"):])
    assert frontmatter["name"] == "tdd"
    # Hermes-specific tags must not be present in the openclaw rendering.
    assert "metadata" not in frontmatter or "hermes" not in (
        frontmatter.get("metadata") or {}
    )


# ---------------------------- zeroclaw dispatch (Phase 3) -------------------


def test_apply_state_zeroclaw_empty_state_runs_playbook(monkeypatch):
    runner = _patch_runtime(monkeypatch, agent_type="zeroclaw")
    result = apply_state("tdd-zeroclaw")
    assert result.agent_type == "zeroclaw"
    assert result.applied_skills == []
    runner.run.assert_called_once()
    _, kwargs = runner.run.call_args
    extravars = kwargs["inventory"]["all"]["vars"]
    assert extravars["agent_type"] == "zeroclaw"
    assert extravars["desired_skill_names"] == []
    playbook_arg = kwargs["playbook"]
    assert "/zeroclaw/playbooks/skills_apply.yaml" in playbook_arg


def test_apply_state_zeroclaw_stages_and_applies_clawrium_tdd(monkeypatch):
    write_state("tdd-zeroclaw", ["clawrium/tdd"])
    runner = _patch_runtime(monkeypatch, agent_type="zeroclaw")

    result = apply_state("tdd-zeroclaw")

    assert result.applied_skills == ["clawrium/tdd"]
    _, kwargs = runner.run.call_args
    extravars = kwargs["inventory"]["all"]["vars"]
    # Source-dirname == slug per Phase 0 contract — the playbook will
    # stage under `<remote-staging>/tdd/` and pass that path to
    # `zeroclaw skills install`.
    assert extravars["desired_skill_names"] == ["tdd"]


def test_apply_state_zeroclaw_dispatches_to_zeroclaw_playbook(monkeypatch):
    """Regression guard against a future refactor that accidentally
    points all three claws at the same playbook — we want the zeroclaw
    invocation routed to the zeroclaw `skills_apply.yaml` so the native
    `zeroclaw skills install` wrap (not raw file copy) runs."""
    runner = _patch_runtime(monkeypatch, agent_type="zeroclaw")
    apply_state("tdd-zeroclaw")
    _, kwargs = runner.run.call_args
    assert "/zeroclaw/" in kwargs["playbook"]
    assert "/hermes/" not in kwargs["playbook"]
    assert "/openclaw/" not in kwargs["playbook"]


def test_apply_state_drift_recovery_zeroclaw(monkeypatch):
    """Same drift-recovery contract as hermes: re-running install on a
    state that's already set must re-invoke the playbook so the
    playbook's idempotent install-if-missing branch runs."""
    write_state("tdd-zeroclaw", ["clawrium/tdd"])
    runner = _patch_runtime(monkeypatch, agent_type="zeroclaw")

    apply_state("tdd-zeroclaw")
    apply_state("tdd-zeroclaw")

    assert runner.run.call_count == 2
    for call in runner.run.call_args_list:
        assert call.kwargs["inventory"]["all"]["vars"]["desired_skill_names"] == [
            "tdd"
        ]


def test_apply_state_drift_recovery_openclaw(monkeypatch):
    """W8: parity gap fix — drift recovery must work on openclaw too,
    not just hermes/zeroclaw. The playbook is responsible for restoring
    SKILL.md if it was manually deleted on host; apply_state's job is
    just to invoke it idempotently on every install/remove call."""
    write_state("tdd-openclaw", ["clawrium/tdd"])
    runner = _patch_runtime(monkeypatch, agent_type="openclaw")

    apply_state("tdd-openclaw")
    apply_state("tdd-openclaw")

    assert runner.run.call_count == 2
    for call in runner.run.call_args_list:
        assert call.kwargs["inventory"]["all"]["vars"]["desired_skill_names"] == [
            "tdd"
        ]
        # Drift recovery means the SAME playbook is invoked again —
        # specifically the openclaw one, not a refactor that punts to
        # a different claw's apply.
        assert "/openclaw/" in call.kwargs["playbook"]


# ---------------------------- malicious-input rejection (ATX B3) ------------


def _write_raw_state(agent_name: str, skills: list[str]) -> None:
    """Bypass write_state's parse_skill_ref normalization to plant a
    hostile state file directly. Simulates a hand-edited
    `~/.config/clawrium/agents/<agent>/skills.json` carrying entries
    that should never have made it past `write_state`."""
    path = state_file_path(agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"skills": skills}))


@pytest.mark.parametrize(
    "malicious_ref,expected_error",
    [
        # Path traversal in name component
        ("clawrium/..", InvalidSkillRef),
        # Path traversal across separator
        ("../etc/passwd", (InvalidSkillRef, MissingRegistryPrefix)),
        # Path-segment-in-name
        ("clawrium/sub/dir", InvalidSkillRef),
        # Shell metacharacters in name
        ("clawrium/tdd;rm", InvalidSkillRef),
        ("clawrium/tdd|cat", InvalidSkillRef),
        ("clawrium/tdd&id", InvalidSkillRef),
        ("clawrium/tdd`id`", InvalidSkillRef),
        ("clawrium/tdd$(id)", InvalidSkillRef),
        # Backslash / Windows-style path
        ("clawrium\\tdd", (InvalidSkillRef, MissingRegistryPrefix)),
        # Null byte
        ("clawrium/tdd\x00", InvalidSkillRef),
        # Bidi-formatting codepoints — the slug regex bans these but
        # without a unit test, a future regex loosening could let them
        # through and reach RTLO-style output forgery in error messages
        # AND on-host CLI args (ATX #382 W14).
        ("clawrium/tdd‮", InvalidSkillRef),       # RIGHT-TO-LEFT OVERRIDE
        ("clawrium/​tdd", InvalidSkillRef),       # ZERO WIDTH SPACE
        ("clawrium/؜tdd", InvalidSkillRef),       # ARABIC LETTER MARK
        ("clawrium/tdd⁦inject", InvalidSkillRef), # LRI
        # External-source URL forms
        ("https://evil.example/skill", ExternalSourceBlocked),
        ("file:///etc/passwd", ExternalSourceBlocked),
        ("git+ssh://attacker.example/repo.git", ExternalSourceBlocked),
    ],
)
def test_apply_state_rejects_malicious_slugs_before_dispatch(
    monkeypatch, malicious_ref, expected_error
):
    """Defense-in-depth contract: hostile slugs in a hand-edited state
    file MUST be rejected by the Python validate-before-dispatch step
    in apply_state, not relied on the in-playbook regex re-check.
    `runner.run` must not be invoked — any exception thrown after the
    runner fires means the host already saw the bad input."""
    _write_raw_state("tdd-hermes", [malicious_ref])
    runner = _patch_runtime(monkeypatch)
    with pytest.raises(expected_error):
        apply_state("tdd-hermes")
    runner.run.assert_not_called()


def test_apply_state_rejects_malicious_slug_on_openclaw_before_dispatch(monkeypatch):
    """Same contract as the hermes parametrized case, but routed
    through the openclaw dispatch path so a future refactor that
    short-circuits openclaw's compatibility check can't quietly skip
    the slug rejection step."""
    _write_raw_state("tdd-openclaw", ["clawrium/../etc/passwd"])
    runner = _patch_runtime(monkeypatch, agent_type="openclaw")
    with pytest.raises(InvalidSkillRef):
        apply_state("tdd-openclaw")
    runner.run.assert_not_called()


def test_apply_state_rejects_malicious_slug_on_zeroclaw_before_dispatch(monkeypatch):
    """Zeroclaw arm of the B3 rejection contract. Zeroclaw is the most
    sensitive of the three because the slug is later passed to
    `zeroclaw skills install <path>` and `zeroclaw skills remove <slug>`
    on the host — any escape from the slug regex is reachable as a
    command argument."""
    _write_raw_state("tdd-zeroclaw", ["clawrium/tdd; rm -rf /"])
    runner = _patch_runtime(monkeypatch, agent_type="zeroclaw")
    with pytest.raises(InvalidSkillRef):
        apply_state("tdd-zeroclaw")
    runner.run.assert_not_called()


# ---------------------------- dispatch-table guard (ATX B4) -----------------


def test_apply_state_dispatch_table_miss_raises_not_supported(monkeypatch):
    """Defensive Guard 2 (`_APPLY_PLAYBOOK_BY_CLAW.get()` → None for a
    claw that's in `NATIVE_REGISTRIES` but missing from the dispatch
    table). This fires in the "future claw" scenario where a developer
    adds a claw to `NATIVE_REGISTRIES` but forgets to wire the playbook.
    Without this test, the message and code path are dead under
    normal config and would only surface as a confusing error after a
    real bug ships."""
    _patch_runtime(monkeypatch, agent_type="hermes")
    monkeypatch.setattr(skills_apply, "_APPLY_PLAYBOOK_BY_CLAW", {})
    with pytest.raises(SkillApplyNotSupported, match="has no playbook registered"):
        apply_state("tdd-hermes")


def test_dispatch_table_covers_every_native_registry():
    """Symmetry invariant: every claw in `NATIVE_REGISTRIES` MUST have
    an entry in `_APPLY_PLAYBOOK_BY_CLAW`. Catches the
    "added to NATIVE_REGISTRIES but forgot the playbook" mistake at
    development time instead of at the user's first
    `clm agent skill install <new-claw-agent> ...`."""
    missing = NATIVE_REGISTRIES - set(skills_apply._APPLY_PLAYBOOK_BY_CLAW)
    assert not missing, (
        f"NATIVE_REGISTRIES claws missing from _APPLY_PLAYBOOK_BY_CLAW: "
        f"{sorted(missing)}"
    )


def test_dispatch_table_entries_resolve_to_existing_playbooks():
    """W11: bind the Python dispatch table to the on-disk YAML files.
    A typo in a value (`skills_apply.yml` instead of `.yaml`, or a
    rename that misses the constant) is otherwise only caught when a
    real apply runs — which in CI never happens."""
    for claw, playbook_name in skills_apply._APPLY_PLAYBOOK_BY_CLAW.items():
        playbook = skills_apply._registry_playbook_dir(claw) / playbook_name
        assert playbook.is_file(), (
            f"_APPLY_PLAYBOOK_BY_CLAW[{claw!r}]={playbook_name!r} does not "
            f"resolve to an existing file at {playbook}"
        )

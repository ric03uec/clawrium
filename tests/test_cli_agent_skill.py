"""Tests for `clm agent skill list/install/remove`.

Exercise the CLI surface end-to-end against a mocked `apply_state` so we
verify the orchestration (state mutation order, error rendering, idempotent
re-runs) without depending on ansible / SSH.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli import agent_skill as cli_agent_skill
from clawrium.cli.agent_skill import agent_skill_app
from clawrium.core.skills import (
    IncompatibleSkillRegistry,
    SchemaValidationError,
    SkillNotFound,
)
from clawrium.core.skills_apply import (
    ApplyResult,
    SkillApplyError,
    SkillApplyNotSupported,
)
from clawrium.core.skills_state import read_state, state_file_path, write_state


runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def _stub_agent_resolution(
    monkeypatch: pytest.MonkeyPatch, agent_type: str = "hermes"
) -> None:
    """Pretend every agent name resolves to a `hermes` instance.

    Without this stub, the preflight `_resolve_agent_type` call (added
    in the rev2 fix for B1) would hit a real `hosts.json` read and the
    tests would fail before exercising the install/remove flow.
    """
    monkeypatch.setattr(
        cli_agent_skill,
        "get_agent_by_name",
        lambda name: (
            {"hostname": "wolf-i", "alias": "wolf-i"},
            agent_type,
            {"agent_name": name},
        ),
    )


def _stub_apply(monkeypatch, applied: list[str] | None = None) -> list[str]:
    """Replace `apply_state` with a recorder. Returns the list of agent
    names it was called with (so tests can assert it was actually invoked).
    Also stubs `get_agent_by_name` so the preflight path passes.
    """
    calls: list[str] = []

    def fake(agent_name: str, **_kwargs):
        calls.append(agent_name)
        return ApplyResult(
            agent_name=agent_name,
            agent_type="hermes",
            hostname="wolf-i",
            applied_skills=applied if applied is not None else read_state(agent_name),
            log_dir=Path("/tmp/fake-log"),
        )

    monkeypatch.setattr(cli_agent_skill, "apply_state", fake)
    _stub_agent_resolution(monkeypatch)
    return calls


# ------------------------------- list ---------------------------------------


def test_list_empty_state_shows_hint(monkeypatch):
    result = runner.invoke(agent_skill_app, ["list", "tdd-hermes"])
    assert result.exit_code == 0, result.output
    assert "No skills installed" in result.output


def test_list_renders_table_of_installed_skills():
    write_state("tdd-hermes", ["clawrium/tdd"])
    result = runner.invoke(agent_skill_app, ["list", "tdd-hermes"])
    assert result.exit_code == 0, result.output
    assert "clawrium/tdd" in result.output


def test_list_rejects_invalid_agent_name():
    result = runner.invoke(agent_skill_app, ["list", "Bad Name"])
    assert result.exit_code == 1
    # stderr is mixed with stdout under typer's default CliRunner; either
    # way the message should appear in `output`.
    assert "Invalid agent name" in result.output


# ------------------------------- install ------------------------------------


def test_install_happy_path_adds_to_state_and_applies(monkeypatch):
    calls = _stub_apply(monkeypatch)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 0, result.output
    assert calls == ["tdd-hermes"]
    assert read_state("tdd-hermes") == ["clawrium/tdd"]
    assert "Installed" in result.output


def test_install_already_present_still_reconciles(monkeypatch):
    write_state("tdd-hermes", ["clawrium/tdd"])
    calls = _stub_apply(monkeypatch)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 0, result.output
    # apply_state was still invoked (drift recovery contract).
    assert calls == ["tdd-hermes"]
    assert "already in desired state" in result.output


def test_install_rejects_bare_name(monkeypatch):
    _stub_apply(monkeypatch)
    result = runner.invoke(agent_skill_app, ["install", "tdd-hermes", "tdd"])
    assert result.exit_code == 1
    assert "missing a registry prefix" in result.output


def test_install_rejects_url(monkeypatch):
    _stub_apply(monkeypatch)
    result = runner.invoke(
        agent_skill_app,
        ["install", "tdd-hermes", "https://evil.example/skill.tgz"],
    )
    assert result.exit_code == 1
    assert "not allowed" in result.output


def test_install_renders_skill_not_found(monkeypatch):
    """Preflight `load_skill` raises before any state mutation when
    the ref points at a catalog entry that doesn't exist."""
    _stub_agent_resolution(monkeypatch)
    monkeypatch.setattr(
        cli_agent_skill,
        "load_skill",
        lambda ref: (_ for _ in ()).throw(
            SkillNotFound("Skill clawrium/missing not found.")
        ),
    )
    monkeypatch.setattr(cli_agent_skill, "apply_state", lambda *a, **kw: None)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "not found" in result.output
    # State must be untouched — preflight ran before add_skill.
    assert read_state("tdd-hermes") == []


def test_install_renders_incompatible_skill(monkeypatch):
    """Preflight `check_agent_compatibility` raises before state
    mutation when the resolved agent type doesn't match the skill."""
    _stub_agent_resolution(monkeypatch, agent_type="openclaw")
    monkeypatch.setattr(
        cli_agent_skill,
        "check_agent_compatibility",
        lambda _skill, _claw: (_ for _ in ()).throw(
            IncompatibleSkillRegistry(
                "Skill hermes/foo is a 'hermes'-native skill ..."
            )
        ),
    )
    monkeypatch.setattr(cli_agent_skill, "apply_state", lambda *a, **kw: None)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-openclaw", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "hermes" in result.output and "native" in result.output
    # State must be untouched — preflight caught the mismatch.
    assert read_state("tdd-openclaw") == []


def test_install_renders_apply_error(monkeypatch):
    _stub_agent_resolution(monkeypatch)

    def boom(name, **_kwargs):
        raise SkillApplyError(
            "Skills apply failed (status=failed): Permission denied "
            "(log: /tmp/log)."
        )

    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "Permission denied" in result.output


def test_bidi_chars_in_skill_error_are_stripped(monkeypatch):
    """B5 regression test (ATX #382 iter 2).

    `_exit_with_error` MUST pipe error text through
    `_sanitize_exception_text` before Rich-escaping, so a remote-supplied
    error body carrying bidi-override codepoints (e.g. RTLO at U+202E,
    ZWSP at U+200B, ALM at U+061C) can't reach the user's terminal and
    forge output. If a future refactor removes the sanitizer, this test
    fails.

    The non-bidi portion of the message ("Permission denied", "BUSY")
    must survive — sanitization is non-destructive for ordinary text.
    """
    # Mix every bidi class our regex covers: RTLO, ZWSP, ALM, LRI.
    poisoned = (
        "Skills apply failed: "
        "‮Permission​ denied "
        "(؜BUSY⁦hidden⁩ marker)"
    )

    def boom(name, **_kwargs):
        raise SkillApplyError(poisoned)

    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    # Every bidi codepoint must be absent from the rendered output.
    for codepoint in ("‮", "​", "؜", "⁦", "⁩"):
        assert codepoint not in result.output, (
            f"bidi codepoint U+{ord(codepoint):04X} survived sanitization"
        )
    # Non-bidi portion of the message survives — the sanitizer must
    # not be destructive to ordinary diagnostic text.
    assert "Permission" in result.output
    assert "denied" in result.output
    assert "BUSY" in result.output


def test_apply_error_bidi_stripped_does_not_destroy_ordinary_diagnostics(monkeypatch):
    """Companion to the B5 test — confirms the sanitizer leaves a
    real-world ansible-runner error message untouched. Hardens against
    a future "be more aggressive" patch to the sanitizer that would
    silently mask legitimate failures (and the user would just see
    "Error: " with no body)."""
    msg = (
        "Skills apply failed (status=failed): /home/agent/.openclaw/skills "
        "not writable by user-12345 (log: /var/log/clm-apply.log)."
    )

    def boom(name, **_kwargs):
        raise SkillApplyError(msg)

    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    # Every load-bearing token survives sanitization. Normalize Rich's
    # terminal-width line wrapping (newlines collapse to spaces) before
    # checking — multi-word tokens may split across rendered lines.
    flat = " ".join(result.output.split())
    for token in (
        "Skills apply failed",
        "/home/agent/.openclaw/skills",
        "not writable",
        "user-12345",
        "/var/log/clm-apply.log",
    ):
        assert token in flat, f"sanitizer stripped {token!r}"


def test_install_renders_apply_not_supported(monkeypatch):
    _stub_agent_resolution(monkeypatch, agent_type="openclaw")

    def boom(name, **_kwargs):
        raise SkillApplyNotSupported(
            "Skills install is not yet supported for openclaw agents. "
            "Run `clm agent ps` to find a compatible agent."
        )

    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-openclaw", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "not yet supported" in result.output
    # B6: no phase jargon in user-facing output.
    assert "phase" not in result.output.lower()


def test_install_renders_agent_not_found(monkeypatch):
    """Agent name doesn't resolve → preflight raises
    `AgentNotFoundError` before any state mutation."""
    monkeypatch.setattr(cli_agent_skill, "get_agent_by_name", lambda _n: None)
    monkeypatch.setattr(cli_agent_skill, "apply_state", lambda *a, **kw: None)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "not found" in result.output
    assert read_state("tdd-hermes") == []


def test_install_renders_ambiguous_agent_name(monkeypatch):
    """get_agent_by_name raising ValueError translates to
    AgentNotFoundError at the CLI surface."""
    def raise_ambiguous(_name):
        raise ValueError("Agent name 'tdd' is ambiguous across hosts: ...")

    monkeypatch.setattr(
        cli_agent_skill, "get_agent_by_name", raise_ambiguous
    )
    monkeypatch.setattr(cli_agent_skill, "apply_state", lambda *a, **kw: None)
    result = runner.invoke(agent_skill_app, ["install", "tdd", "clawrium/tdd"])
    assert result.exit_code == 1
    assert "ambiguous" in result.output


def test_install_renders_schema_validation_error(monkeypatch):
    """Preflight `validate_skill` raises before state mutation."""
    _stub_agent_resolution(monkeypatch)

    def boom(_skill):
        raise SchemaValidationError(
            "Skill clawrium/broken failed schema validation: ..."
        )

    monkeypatch.setattr(cli_agent_skill, "validate_skill", boom)
    monkeypatch.setattr(cli_agent_skill, "apply_state", lambda *a, **kw: None)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "schema validation" in result.output
    assert read_state("tdd-hermes") == []


# ------------------------------- remove -------------------------------------


def test_remove_happy_path(monkeypatch):
    write_state("tdd-hermes", ["clawrium/tdd"])
    calls = _stub_apply(monkeypatch, applied=[])
    result = runner.invoke(
        agent_skill_app, ["remove", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 0, result.output
    assert calls == ["tdd-hermes"]
    assert read_state("tdd-hermes") == []
    assert "Removed" in result.output


def test_remove_when_absent_still_reconciles(monkeypatch):
    calls = _stub_apply(monkeypatch, applied=[])
    result = runner.invoke(
        agent_skill_app, ["remove", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 0, result.output
    assert calls == ["tdd-hermes"]
    assert "was not in desired state" in result.output


def test_remove_rejects_bare_name(monkeypatch):
    _stub_apply(monkeypatch)
    result = runner.invoke(agent_skill_app, ["remove", "tdd-hermes", "tdd"])
    assert result.exit_code == 1
    assert "missing a registry prefix" in result.output


# --------------------- state file canonicalization ---------------------------


def test_state_file_canonicalized_after_install_remove_cycle(monkeypatch):
    _stub_apply(monkeypatch)

    runner.invoke(agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"])

    raw = json.loads(state_file_path("tdd-hermes").read_text())
    assert raw == {"skills": ["clawrium/tdd"]}

    runner.invoke(agent_skill_app, ["remove", "tdd-hermes", "clawrium/tdd"])
    raw = json.loads(state_file_path("tdd-hermes").read_text())
    assert raw == {"skills": []}


# --------------------- transactional install / remove -----------------------


def test_install_rolls_back_state_on_apply_failure(monkeypatch):
    """When `apply_state` raises after `add_skill` has mutated the
    state, the install path must restore the prior state so the
    file tracks what the host actually has.

    All preflight calls (`load_skill`, `validate_skill`,
    `check_agent_compatibility`) are stubbed so the assertion does
    not depend on the on-disk catalog (a missing `clawrium/tdd` would
    otherwise make the test pass vacuously: preflight would raise
    `SkillNotFound` before `add_skill` ever ran, and the final
    `assert read_state == []` would pass without exercising rollback).
    """
    _stub_agent_resolution(monkeypatch)
    monkeypatch.setattr(cli_agent_skill, "load_skill", lambda ref: object())
    monkeypatch.setattr(cli_agent_skill, "validate_skill", lambda _skill: None)
    monkeypatch.setattr(
        cli_agent_skill, "check_agent_compatibility",
        lambda _skill, _claw: None,
    )
    monkeypatch.setattr(
        cli_agent_skill,
        "apply_state",
        lambda *a, **kw: (_ for _ in ()).throw(
            SkillApplyError("ssh down (log: /tmp/...)")
        ),
    )

    # Sanity: assert mutation happened, then was rolled back, by
    # spying on read_state mid-flight via a recorder.
    assert read_state("tdd-hermes") == []
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "ssh down" in result.output
    # Rollback contract: state file shows the skill is NOT installed.
    assert read_state("tdd-hermes") == []


def test_install_rollback_path_actually_runs(monkeypatch):
    """Twin of `test_install_rolls_back_state_on_apply_failure` that
    *positively* asserts the rollback path executes by spying on
    `write_state`. Without this, a hypothetical refactor that simply
    skipped `add_skill` on failure would also pass the read-only
    assertion above."""
    _stub_agent_resolution(monkeypatch)
    monkeypatch.setattr(cli_agent_skill, "load_skill", lambda ref: object())
    monkeypatch.setattr(cli_agent_skill, "validate_skill", lambda _skill: None)
    monkeypatch.setattr(
        cli_agent_skill, "check_agent_compatibility",
        lambda _skill, _claw: None,
    )
    monkeypatch.setattr(
        cli_agent_skill,
        "apply_state",
        lambda *a, **kw: (_ for _ in ()).throw(SkillApplyError("ssh down")),
    )

    write_calls: list[tuple[str, list[str]]] = []
    real_write = cli_agent_skill.write_state

    def spying_write(agent_name, refs):
        write_calls.append((agent_name, [str(r) for r in refs]))
        return real_write(agent_name, refs)

    monkeypatch.setattr(cli_agent_skill, "write_state", spying_write)

    runner.invoke(agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"])

    # The rollback path explicitly calls `write_state(agent_name,
    # prior_state)` with the empty list. `add_skill` itself goes
    # through `skills_state.write_state` (its module-local
    # reference), bypassing this spy — so we expect exactly *one*
    # call here, the rollback. Asserting on the agent_name as well
    # would catch a hypothetical bug that rolled back the wrong
    # agent's state file.
    assert any(
        agent == "tdd-hermes" and refs == []
        for agent, refs in write_calls
    ), f"rollback write_state('tdd-hermes', []) never invoked: {write_calls}"


def test_remove_rolls_back_state_on_apply_failure(monkeypatch):
    """Symmetric: if `apply_state` raises after `remove_skill` drops
    the entry, restore the prior state so the user sees the file
    matches the host."""
    write_state("tdd-hermes", ["clawrium/tdd"])
    _stub_agent_resolution(monkeypatch)
    monkeypatch.setattr(
        cli_agent_skill,
        "apply_state",
        lambda *a, **kw: (_ for _ in ()).throw(
            SkillApplyError("ssh down (log: /tmp/...)")
        ),
    )
    result = runner.invoke(
        agent_skill_app, ["remove", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    # Rollback contract: the entry is still there.
    assert read_state("tdd-hermes") == ["clawrium/tdd"]


def test_install_preflight_failure_does_not_mutate_state(monkeypatch):
    """Bare-name validation lives upstream of `add_skill`; the state
    file must remain at its prior content."""
    _stub_apply(monkeypatch)
    write_state("tdd-hermes", ["clawrium/tdd"])
    result = runner.invoke(agent_skill_app, ["install", "tdd-hermes", "bare"])
    assert result.exit_code == 1
    # State unchanged.
    assert read_state("tdd-hermes") == ["clawrium/tdd"]


def test_install_rollback_failure_surfaces_warning_to_user(monkeypatch):
    """If `write_state` itself raises during the rollback (extremely
    rare — the file was just written successfully one statement
    earlier), the user must see a yellow warning telling them to
    verify with `clm agent skill list`. Silent rollback failure
    would leave the state file lying about the host."""
    _stub_agent_resolution(monkeypatch)
    monkeypatch.setattr(cli_agent_skill, "load_skill", lambda ref: object())
    monkeypatch.setattr(cli_agent_skill, "validate_skill", lambda _skill: None)
    monkeypatch.setattr(
        cli_agent_skill, "check_agent_compatibility",
        lambda _skill, _claw: None,
    )
    monkeypatch.setattr(
        cli_agent_skill,
        "apply_state",
        lambda *a, **kw: (_ for _ in ()).throw(SkillApplyError("ssh down")),
    )

    # Patch write_state on the *cli* module so the install's
    # `add_skill` and `read_state` use the real impls (which both
    # delegate through skills_state), but the *rollback's* explicit
    # `write_state` call from agent_skill resolves to the broken stub.
    def flaky_write(_agent_name, _refs):
        # `agent_skill.install` only calls `cli_agent_skill.write_state`
        # in the rollback path (add_skill goes straight to
        # `skills_state.write_state`, not the re-export on this
        # module). Patching here therefore triggers exactly on rollback.
        raise OSError("simulated rollback failure")

    monkeypatch.setattr(cli_agent_skill, "write_state", flaky_write)

    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )

    assert result.exit_code == 1
    assert "ssh down" in result.output
    assert "rollback failed" in result.output.lower()
    # Hint should point at the verification command.
    assert "clm agent skill list" in result.output


def test_remove_rollback_failure_surfaces_warning_to_user(monkeypatch):
    """Symmetric coverage for the remove path: a `write_state` failure
    during rollback after a failed `apply_state` must surface a yellow
    Warning + verification hint to stderr, not silently log."""
    write_state("tdd-hermes", ["clawrium/tdd"])
    _stub_agent_resolution(monkeypatch)
    monkeypatch.setattr(
        cli_agent_skill,
        "apply_state",
        lambda *a, **kw: (_ for _ in ()).throw(SkillApplyError("ssh down")),
    )

    def flaky_write(_agent_name, _refs):
        raise OSError("simulated rollback failure")

    monkeypatch.setattr(cli_agent_skill, "write_state", flaky_write)

    result = runner.invoke(
        agent_skill_app, ["remove", "tdd-hermes", "clawrium/tdd"]
    )

    assert result.exit_code == 1
    assert "ssh down" in result.output
    assert "rollback failed" in result.output.lower()
    assert "clm agent skill list" in result.output


def test_exit_with_error_sanitizes_bidi_in_message(monkeypatch):
    """A `SkillApplyError` whose message contains U+202E (RTLO) must
    render with the bidi-control codepoint stripped. The sanitizer
    used by `_exit_with_error` is the same one chat.py uses for the
    other CLI error paths."""
    rtlo_msg = "host ‮unreachable: msg"
    monkeypatch.setattr(
        cli_agent_skill,
        "apply_state",
        lambda *a, **kw: (_ for _ in ()).throw(SkillApplyError(rtlo_msg)),
    )
    _stub_agent_resolution(monkeypatch)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "‮" not in result.output

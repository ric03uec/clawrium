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
    AgentNotFoundError,
    ApplyResult,
    SkillApplyError,
    SkillApplyNotSupported,
)
from clawrium.core.skills_state import read_state, state_file_path, write_state


runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def _stub_apply(monkeypatch, applied: list[str] | None = None) -> list[str]:
    """Replace `apply_state` with a recorder. Returns the list of agent
    names it was called with (so tests can assert it was actually invoked).
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
    def boom(name, **_kwargs):
        raise SkillNotFound("Skill clawrium/missing not found.")

    _stub_apply(monkeypatch)
    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_install_renders_incompatible_skill(monkeypatch):
    def boom(name, **_kwargs):
        raise IncompatibleSkillRegistry(
            "Skill hermes/foo is a 'hermes'-native skill ..."
        )

    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-openclaw", "hermes/foo"]
    )
    assert result.exit_code == 1
    assert "hermes" in result.output and "native" in result.output


def test_install_renders_apply_error(monkeypatch):
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


def test_install_renders_apply_not_supported(monkeypatch):
    def boom(name, **_kwargs):
        raise SkillApplyNotSupported(
            "Skills apply for 'openclaw' is not implemented yet ..."
        )

    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-openclaw", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "not implemented yet" in result.output


def test_install_renders_agent_not_found(monkeypatch):
    def boom(name, **_kwargs):
        raise AgentNotFoundError("Agent 'tdd-hermes' not found.")

    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_install_renders_schema_validation_error(monkeypatch):
    def boom(name, **_kwargs):
        raise SchemaValidationError(
            "Skill clawrium/broken failed schema validation: ..."
        )

    monkeypatch.setattr(cli_agent_skill, "apply_state", boom)
    result = runner.invoke(
        agent_skill_app, ["install", "tdd-hermes", "clawrium/tdd"]
    )
    assert result.exit_code == 1
    assert "schema validation" in result.output


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

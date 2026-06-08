"""Tests for `clawctl agent skill` local skill lifecycle."""

from __future__ import annotations

import pathlib
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.skills_state import agent_skills_dir, read_state

runner = CliRunner()


def test_add_from_template_materializes_local_skill_without_sync(fleet_dir) -> None:
    result = runner.invoke(
        app,
        [
            "agent",
            "skill",
            "add",
            "wise-hypatia",
            "--from-template",
            "clawrium/tdd",
        ],
    )
    assert result.exit_code == 0, result.output
    assert read_state("wise-hypatia") == ["tdd"]
    skill_md = agent_skills_dir("wise-hypatia") / "tdd" / "SKILL.md"
    text = skill_md.read_text()
    assert "name: tdd" in text
    assert "description:" in text
    assert "x-clawrium-source: clawrium/tdd" in text
    assert "run `clawctl agent sync wise-hypatia`" in result.output


def test_add_rejects_duplicate_local_name(fleet_dir) -> None:
    first = runner.invoke(
        app,
        ["agent", "skill", "add", "wise-hypatia", "--from-template", "clawrium/tdd"],
    )
    assert first.exit_code == 0, first.output
    second = runner.invoke(
        app,
        ["agent", "skill", "add", "wise-hypatia", "--from-template", "clawrium/tdd"],
    )
    assert second.exit_code != 0
    assert "already exists" in second.output or "already in desired state" in second.output


def test_add_persist_mkdir_race(fleet_dir, tmp_path: Path, monkeypatch) -> None:
    """except FileExistsError branch in _persist_local_skill (TOCTOU race).

    The pre-check (target_dir.exists()) passes because the directory doesn't
    exist yet, but mkdir raises FileExistsError simulating a concurrent writer.
    The handler must still surface InvalidSkillRef as a CLI error.
    """
    source = tmp_path / "SKILL.md"
    source.write_text(
        "---\nname: race-local\ndescription: Race test\n---\n\n# Body\n"
    )

    _original_mkdir = pathlib.Path.mkdir

    def _mkdir_race(self, *args, **kwargs):
        if not kwargs.get("exist_ok", False):
            raise FileExistsError(f"[Errno 17] File exists: '{self}'")
        return _original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "mkdir", _mkdir_race)
    result = runner.invoke(app, ["agent", "skill", "add", "wise-hypatia", str(source)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_add_path_uses_native_skill_format(fleet_dir, tmp_path: Path) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text(
        "---\nname: custom-tdd\ndescription: Custom local skill\n---\n\n# Custom\n"
    )

    result = runner.invoke(app, ["agent", "skill", "add", "wise-hypatia", str(source)])
    assert result.exit_code == 0, result.output
    assert read_state("wise-hypatia") == ["custom-tdd"]
    assert (agent_skills_dir("wise-hypatia") / "custom-tdd" / "SKILL.md").read_text() == (
        "---\nname: custom-tdd\ndescription: Custom local skill\n---\n\n# Custom\n"
    )


def test_list_renders_bare_local_names(fleet_dir) -> None:
    runner.invoke(
        app,
        ["agent", "skill", "add", "wise-hypatia", "--from-template", "clawrium/tdd"],
    )
    result = runner.invoke(app, ["agent", "skill", "list", "wise-hypatia"])
    assert result.exit_code == 0, result.output
    assert "tdd" in result.output
    assert "clawrium/tdd" not in result.output


def test_list_supports_name_output(fleet_dir) -> None:
    runner.invoke(
        app,
        ["agent", "skill", "add", "wise-hypatia", "--from-template", "clawrium/tdd"],
    )
    result = runner.invoke(app, ["agent", "skill", "list", "wise-hypatia", "-o", "name"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "skill/tdd"


def test_add_rejects_path_and_template_together(fleet_dir, tmp_path: Path) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text("---\nname: custom-tdd\ndescription: Custom local skill\n---\n\n# Custom\n")
    result = runner.invoke(
        app,
        [
            "agent",
            "skill",
            "add",
            "wise-hypatia",
            str(source),
            "--from-template",
            "clawrium/tdd",
        ],
    )
    assert result.exit_code != 0
    assert "either PATH or --from-template" in result.output


def test_remove_deletes_state_and_local_dir(fleet_dir) -> None:
    runner.invoke(
        app,
        ["agent", "skill", "add", "wise-hypatia", "--from-template", "clawrium/tdd"],
    )
    result = runner.invoke(app, ["agent", "skill", "remove", "wise-hypatia", "tdd"])
    assert result.exit_code == 0, result.output
    assert read_state("wise-hypatia") == []
    assert not (agent_skills_dir("wise-hypatia") / "tdd").exists()


def test_removed_attach_verb_points_to_add(fleet_dir) -> None:
    result = runner.invoke(
        app,
        ["agent", "skill", "attach", "clawrium/tdd", "--agent", "wise-hypatia"],
    )
    assert result.exit_code != 0
    assert "was removed" in result.output
    assert "skill add" in result.output


def test_removed_detach_and_get_verbs_point_to_replacements(fleet_dir) -> None:
    detach = runner.invoke(
        app,
        ["agent", "skill", "detach", "clawrium/tdd", "--agent", "wise-hypatia"],
    )
    assert detach.exit_code != 0
    assert "skill remove" in detach.output

    get = runner.invoke(app, ["agent", "skill", "get", "--agent", "wise-hypatia"])
    assert get.exit_code != 0
    assert "skill list" in get.output


def test_edit_restores_invalid_changes(fleet_dir, monkeypatch) -> None:
    runner.invoke(
        app,
        ["agent", "skill", "add", "wise-hypatia", "--from-template", "clawrium/tdd"],
    )
    skill_md = agent_skills_dir("wise-hypatia") / "tdd" / "SKILL.md"
    before = skill_md.read_text()

    from clawrium.cli.clawctl.agent import skill as skill_cli

    def corrupt(path: Path, editor: str | None) -> int:
        path.write_text("---\nname: tdd\n---\n\nmissing description\n")
        return 0

    monkeypatch.setattr(skill_cli, "_run_editor", corrupt)
    result = runner.invoke(app, ["agent", "skill", "edit", "wise-hypatia", "tdd"])
    assert result.exit_code != 0
    assert skill_md.read_text() == before

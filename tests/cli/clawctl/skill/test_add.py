"""Tests for `clawctl skill add` user overlay writes."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.skills import _overlay_root

runner = CliRunner()


def test_skill_add_writes_native_overlay_and_registry_get_sees_it(
    fleet_dir, tmp_path: Path
) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text("---\nname: local-hermes\ndescription: Local Hermes skill\n---\n\n# Body\n")

    result = runner.invoke(app, ["skill", "add", str(source), "--registry", "hermes"])
    assert result.exit_code == 0, result.output
    assert (_overlay_root() / "hermes" / "local-hermes" / "SKILL.md").is_file()

    listing = runner.invoke(app, ["skill", "registry", "get", "-o", "name"])
    assert listing.exit_code == 0, listing.output
    assert "skill/hermes/local-hermes" in listing.output


def test_skill_add_rejects_overlay_collision(fleet_dir, tmp_path: Path) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text("---\nname: local-hermes\ndescription: Local Hermes skill\n---\n\n# Body\n")
    first = runner.invoke(app, ["skill", "add", str(source), "--registry", "hermes"])
    assert first.exit_code == 0, first.output

    second = runner.invoke(app, ["skill", "add", str(source), "--registry", "hermes"])
    assert second.exit_code != 0
    assert "already exists" in second.output

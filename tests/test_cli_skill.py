"""Tests for the legacy `clm skill` CLI surface (#411)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clawrium.cli.main import app


@pytest.fixture
def runner():
    return CliRunner()


def test_skill_list_includes_vetted_tdd(runner):
    result = runner.invoke(app, ["skill", "list"])
    assert result.exit_code == 0, result.output
    assert "vetted/tdd" in result.output


def test_skill_list_source_filter_vetted(runner):
    result = runner.invoke(app, ["skill", "list", "--source", "vetted"])
    assert result.exit_code == 0
    assert "vetted/tdd" in result.output


def test_skill_list_unknown_source_rejected(runner):
    result = runner.invoke(app, ["skill", "list", "--source", "bogus"])
    assert result.exit_code != 0


def test_skill_show_vetted_tdd(runner):
    result = runner.invoke(app, ["skill", "show", "vetted/tdd"])
    assert result.exit_code == 0
    assert "vetted/tdd" in result.output


def test_skill_show_bare_name_hint(runner):
    result = runner.invoke(app, ["skill", "show", "tdd"])
    assert result.exit_code != 0
    assert "source prefix" in result.output.lower()


def test_skill_show_not_found(runner):
    result = runner.invoke(app, ["skill", "show", "vetted/no-such"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_skill_show_unknown_source(runner):
    result = runner.invoke(app, ["skill", "show", "clawrium/tdd"])
    assert result.exit_code != 0


def test_skill_show_sanitizes_bidi_in_body(runner, tmp_path, monkeypatch):
    """Legacy `clm skill show` must strip U+202E from rendered body.

    ATX #411 New-B1a: catalog bodies are author-supplied; bidi
    codepoints in SKILL.md must never reach the terminal.
    """
    from clawrium.core import skills as core_skills

    local_root = tmp_path / "local"
    local_root.mkdir()
    monkeypatch.setattr(core_skills, "_local_catalog_root", lambda: local_root)
    from clawrium.core import skills_local
    monkeypatch.setattr(skills_local, "_local_catalog_root", lambda: local_root)

    sk = local_root / "bidi"
    sk.mkdir()
    # U+202E (right-to-left override) embedded in body
    body = "# Heading\n\nNormal then ‮REVERSED tail.\n"
    (sk / "SKILL.md").write_text(
        f"---\nname: bidi\ndescription: ok desc\n---\n\n{body}"
    )

    result = runner.invoke(app, ["skill", "show", "local/bidi"])
    assert result.exit_code == 0, result.output
    assert "‮" not in result.output

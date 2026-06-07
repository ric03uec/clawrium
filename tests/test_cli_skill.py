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

"""Tests for `clawctl skill registry` read-only catalog access (#411)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_get_lists_skills(fleet_dir) -> None:
    result = runner.invoke(app, ["skill", "registry", "get"])
    assert result.exit_code == 0, result.output
    assert "NAME" in result.output
    assert "SOURCE" in result.output


def test_get_with_source_selector(fleet_dir) -> None:
    result = runner.invoke(
        app, ["skill", "registry", "get", "-l", "source=vetted"]
    )
    assert result.exit_code == 0, result.output
    body_lines = result.output.strip().splitlines()[1:]
    for line in body_lines:
        if line:
            assert line.startswith("vetted/"), line


def test_get_with_unknown_source_filter(fleet_dir) -> None:
    result = runner.invoke(
        app, ["skill", "registry", "get", "-l", "source=no-such-source"]
    )
    assert result.exit_code != 0


def test_get_json_emits_array(fleet_dir) -> None:
    result = runner.invoke(app, ["skill", "registry", "get", "-o", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)


def test_describe_known(fleet_dir) -> None:
    result = runner.invoke(app, ["skill", "registry", "describe", "vetted/tdd"])
    assert result.exit_code == 0, result.output


def test_describe_bare_name_rejected(fleet_dir) -> None:
    result = runner.invoke(app, ["skill", "registry", "describe", "tdd"])
    assert result.exit_code != 0

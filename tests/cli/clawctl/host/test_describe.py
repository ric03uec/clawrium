"""Tests for `clawctl host describe <name>`."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_describe_text_format(fleet_dir) -> None:
    result = runner.invoke(app, ["host", "describe", "wolf-i"])
    assert result.exit_code == 0
    assert "Name:" in result.output
    assert "wolf-i" in result.output
    assert "Kind:" in result.output
    assert "Address:" in result.output
    assert "Description:" in result.output
    assert "Description: -" in result.output


def test_describe_json_format(fleet_dir) -> None:
    result = runner.invoke(app, ["host", "describe", "wolf-i", "-o", "json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "wolf-i"
    assert "description" in parsed[0]


def test_describe_unknown_host_errors(fleet_dir) -> None:
    result = runner.invoke(app, ["host", "describe", "nonexistent"])
    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "not found" in result.output


def test_describe_agents_section_when_present(fleet_dir) -> None:
    result = runner.invoke(app, ["host", "describe", "wolf-i"])
    assert result.exit_code == 0
    assert "Agents" in result.output
    assert "wise-hypatia" in result.output

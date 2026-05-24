"""Tests for `clawctl mcp registry` placeholder behaviour."""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_mcp_registry_get_is_placeholder() -> None:
    result = runner.invoke(app, ["mcp", "registry", "get"])
    assert result.exit_code == 0
    assert "Not implemented: mcp registry get" in result.output


def test_mcp_registry_describe_is_placeholder() -> None:
    result = runner.invoke(app, ["mcp", "registry", "describe", "foo"])
    assert result.exit_code == 0
    assert "Not implemented: mcp registry describe" in result.output

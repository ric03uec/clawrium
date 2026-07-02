"""Tests for `clawctl mcp registry` placeholder behaviour.

#834 (B10): the mcp stubs now exit 1 (not 0) with a redirect hint that
points operators at `clawctl integration registry create` — the current
path for MCP-backed integrations (Slack today; more via #499 follow-up).
The exit-code flip means `clawctl mcp registry get && next_cmd` fails
loudly instead of silently chaining past an unimplemented verb.
"""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_mcp_registry_get_is_placeholder() -> None:
    result = runner.invoke(app, ["mcp", "registry", "get"])
    assert result.exit_code == 1
    assert "Not implemented: mcp registry get" in result.output
    assert "clawctl integration registry create" in result.output
    assert "#499" in result.output


def test_mcp_registry_describe_is_placeholder() -> None:
    result = runner.invoke(app, ["mcp", "registry", "describe", "foo"])
    assert result.exit_code == 1
    assert "Not implemented: mcp registry describe" in result.output
    assert "clawctl integration registry create" in result.output
    assert "#499" in result.output

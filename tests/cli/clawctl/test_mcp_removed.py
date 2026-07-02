"""Tests that `clawctl mcp` is no longer a registered command group.

The `mcp` placeholder group was removed in #838 as part of the #499
Slack-integration chain. MCP-backed integrations now live under
`clawctl integration registry create --type slack-user|slack-cookie`;
generic MCP-server support is tracked as the successor issue.

Removing the group means Typer treats `mcp` as an unknown command and
exits 2 (not the placeholder's exit 1). That's the intended breaking
behavior — silent chaining past a stub is impossible when the stub is
gone.
"""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _assert_no_placeholder_leakage(output: str) -> None:
    """Guard against a partial revert re-registering the stub at exit 2.

    The pre-#838 stub emitted `Not implemented: mcp registry <verb>`
    plus a `#499` redirect hint. Both strings MUST be absent so the
    "group removed" invariant is not silently downgraded to "stub
    exiting 2".
    """
    assert "Not implemented" not in output
    assert "#499" not in output


def test_mcp_top_level_is_unknown_command() -> None:
    result = runner.invoke(app, ["mcp"])
    assert result.exit_code == 2
    assert "No such command 'mcp'" in result.output
    _assert_no_placeholder_leakage(result.output)


def test_mcp_registry_get_is_unknown_command() -> None:
    result = runner.invoke(app, ["mcp", "registry", "get"])
    assert result.exit_code == 2
    assert "No such command 'mcp'" in result.output
    _assert_no_placeholder_leakage(result.output)


def test_mcp_registry_describe_is_unknown_command() -> None:
    result = runner.invoke(app, ["mcp", "registry", "describe", "foo"])
    assert result.exit_code == 2
    assert "No such command 'mcp'" in result.output
    _assert_no_placeholder_leakage(result.output)

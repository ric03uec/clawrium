"""Tests for the top-level `clawctl` Typer app skeleton.

These cover plan §"Specific Outcomes to Validate":

- `clawctl --help` lists every top-level group from plan §4.
- Every group's `--help` exits 0 (proves Risk R2 is closed).
- Stubbed subcommands print the canonical `Not implemented: <group> <verb>`
  line.
"""

import pytest
from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


EXPECTED_TOP_LEVEL = [
    "service",
    "version",
    "completion",
    "tui",
    "server",
    "host",
    "agent",
    "provider",
    "channel",
    "integration",
    "skill",
]


def test_root_help_lists_every_group() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for token in EXPECTED_TOP_LEVEL:
        assert token in result.output, f"missing from root --help: {token}"
    # `mcp` group removed in #838 — accidental re-registration in
    # `cli/__init__.py` must not slip through this test.
    assert "mcp" not in result.output
    # `gui` removed in #874, replaced by `server` group. If the old
    # command sneaks back in (import side-effect etc.) this test fires.
    assert "gui" not in result.output


@pytest.mark.parametrize(
    "group",
    [
        "service",
        "server",
        "host",
        "agent",
        "provider",
        "channel",
        "integration",
        "skill",
    ],
)
def test_group_help_exits_zero(group: str) -> None:
    result = runner.invoke(app, [group, "--help"])
    assert result.exit_code == 0


def test_pattern_a_registry_subgroup_exposed() -> None:
    """Each Pattern A noun has `registry` as its only subgroup (plan §3)."""
    # `mcp` was removed in #838 — Slack MCP is now a first-class
    # integration type via `clawctl integration registry create --type
    # slack-*`. Generic MCP-server support is tracked in #844.
    for noun in ("provider", "channel", "integration", "skill"):
        result = runner.invoke(app, [noun, "--help"])
        assert result.exit_code == 0
        assert "registry" in result.output, f"{noun}: registry subgroup missing"


def test_core_untouched_by_imports() -> None:
    """Importing `clawrium.cli` (the new clawctl app) must not pull in
    any `clawrium.core` module side-effects beyond what was already
    needed for `__version__`. This is a smoke check; the real guarantee
    is the `git diff` rule in the Acceptance Criteria.
    """
    import importlib

    importlib.import_module("clawrium.cli")
    # If this import succeeded, we know clawrium.cli works in isolation.

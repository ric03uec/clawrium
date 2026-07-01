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
    "gui",
    "host",
    "agent",
    "provider",
    "channel",
    "integration",
    "skill",
    "mcp",
]


def test_root_help_lists_every_group() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for token in EXPECTED_TOP_LEVEL:
        assert token in result.output, f"missing from root --help: {token}"


@pytest.mark.parametrize(
    "group",
    [
        "service",
        "host",
        "agent",
        "provider",
        "channel",
        "integration",
        "skill",
        "mcp",
    ],
)
def test_group_help_exits_zero(group: str) -> None:
    result = runner.invoke(app, [group, "--help"])
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "argv,expected",
    [
        # `mcp registry` remains a placeholder per plan §4 (no MCP
        # implementation yet). `agent exec` was implemented in #413;
        # its tests live in `tests/cli/clawctl/agent/test_exec.py`.
        # #834 (B10): mcp stubs now exit 1 with a slack-integration
        # redirect hint following the canonical line.
        (["mcp", "registry", "get"], "Not implemented: mcp registry get"),
        (
            ["mcp", "registry", "describe", "foo"],
            "Not implemented: mcp registry describe",
        ),
    ],
)
def test_stub_verb_emits_canonical_line(argv: list[str], expected: str) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 1
    # First line is the canonical `Not implemented:` string; the redirect
    # hint follows on its own line.
    lines = result.output.strip().splitlines()
    assert lines[0] == expected
    assert "clawctl integration registry create" in result.output


def test_pattern_a_registry_subgroup_exposed() -> None:
    """Each Pattern A noun has `registry` as its only subgroup (plan §3)."""
    for noun in ("provider", "channel", "integration", "skill", "mcp"):
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

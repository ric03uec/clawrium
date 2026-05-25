"""Regression guard for issue #524.

`clawctl --help` (and every sub-command's `--help` at every depth) must
render as flat plain text — no Rich rounded-box panels — so the help
surface matches `kubectl`, `docker`, and `git`.

Mechanism: every `typer.Typer(...)` instance in `src/clawrium/cli/`
carries `rich_markup_mode=None`. If a future Typer constructor lands
without that flag (or if a typer upgrade reinterprets it), help output
silently regrows box-drawing characters. The parametrised tests below
assert their absence across a representative sample of root, group, and
nested-subgroup `--help` invocations on both `clawctl` and the legacy
`clm` CLI.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clawrium.cli import app as clawctl_app
from clawrium.cli.main import app as clm_app

_BOX_CHARS = "╭╮╰╯│─"

_CLAWCTL_PATHS: list[list[str]] = [
    [],
    ["--help"],
    ["agent", "--help"],
    ["agent", "configure", "--help"],
    ["agent", "skill", "--help"],
    ["agent", "secret", "--help"],
    ["agent", "memory", "--help"],
    ["agent", "provider", "--help"],
    ["agent", "channel", "--help"],
    ["agent", "integration", "--help"],
    ["agent", "registry", "--help"],
    ["host", "--help"],
    ["host", "create", "--help"],
    ["host", "registry", "--help"],
    ["host", "address", "--help"],
    ["skill", "--help"],
    ["skill", "registry", "--help"],
    ["service", "--help"],
    ["provider", "--help"],
    ["provider", "registry", "--help"],
    ["channel", "--help"],
    ["channel", "registry", "--help"],
    ["integration", "--help"],
    ["integration", "registry", "--help"],
    ["mcp", "--help"],
    ["mcp", "registry", "--help"],
]

_CLM_PATHS: list[list[str]] = [
    [],
    ["--help"],
    ["agent", "--help"],
    ["agent", "install", "--help"],
    ["host", "--help"],
    ["host", "address", "--help"],
    ["provider", "--help"],
    ["integration", "--help"],
    ["skill", "--help"],
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _assert_flat(label: str, args: list[str], result) -> None:
    # Guard against vacuous passes — an import failure or crash produces
    # an empty output that trivially contains no box chars. Exit 0 is the
    # `--help` success path; exit 2 is Click's "no command given" path
    # which renders the help surface for no_args_is_help apps.
    assert result.exit_code in (0, 2), (
        f"{label} {' '.join(args)} failed unexpectedly "
        f"(exit {result.exit_code}, exception={result.exception!r}):\n"
        f"{result.output}"
    )
    assert result.output, f"{label} {' '.join(args)} produced no output"
    leaked = [c for c in _BOX_CHARS if c in result.output]
    assert not leaked, (
        f"{label} {' '.join(args)} leaked Rich panel chars {leaked!r}:\n"
        f"{result.output}"
    )


@pytest.mark.parametrize("args", _CLAWCTL_PATHS, ids=lambda a: " ".join(a) or "<root>")
def test_clawctl_help_is_flat(runner: CliRunner, args: list[str]) -> None:
    _assert_flat("clawctl", args, runner.invoke(clawctl_app, args))


@pytest.mark.parametrize("args", _CLM_PATHS, ids=lambda a: " ".join(a) or "<root>")
def test_clm_help_is_flat(runner: CliRunner, args: list[str]) -> None:
    _assert_flat("clm", args, runner.invoke(clm_app, args))

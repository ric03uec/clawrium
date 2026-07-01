"""`clawctl mcp` — Pattern A attachable (PLACEHOLDER).

Per plan §4, the entire `mcp` group is a placeholder pending a
dedicated MCP design. Bundle 4 (#509) keeps it as a placeholder and
ensures `describe <name>` accepts (and ignores) its positional
argument so the surface aligns with the other Pattern A registries.

#834 (B10): the two stubs now exit 1 (not 0) so that
`clawctl mcp registry get && next_cmd` fails loudly. The redirect
hint points operators at `clawctl integration registry create` — the
current path for MCP-backed integrations (Slack today; more via #499
follow-up).
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl._stub import echo_not_implemented

__all__ = ["mcp_app"]


mcp_app = typer.Typer(
    name="mcp",
    help="MCP servers (Pattern A attachable; placeholder).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)

mcp_registry_app = typer.Typer(
    name="registry",
    help="Read-only entrypoint for the MCP registry (placeholder).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


_GROUP = "mcp registry"
_REDIRECT_HINT = (
    "use `clawctl integration registry create --type slack-user` — see #499"
)


@mcp_registry_app.command("get", help="List registered MCP servers.")
def get() -> None:
    """List MCP servers (placeholder — exits 1 with slack redirect)."""
    echo_not_implemented(_GROUP, "get", hint=_REDIRECT_HINT, exit_code=1)


@mcp_registry_app.command("describe", help="Describe an MCP server.")
def describe(
    name: str = typer.Argument(..., help="MCP server name."),
) -> None:
    """Describe an MCP server (placeholder — exits 1 with slack redirect)."""
    # `name` is accepted to keep the verb grammar aligned with the
    # other Pattern A registries; bundle 4 ships no implementation.
    del name
    echo_not_implemented(_GROUP, "describe", hint=_REDIRECT_HINT, exit_code=1)


mcp_app.add_typer(mcp_registry_app, name="registry")

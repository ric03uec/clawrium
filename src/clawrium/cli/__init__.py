"""`clawctl` — the kubectl-style CLI for Clawrium.

This module exports `app`, the top-level Typer entrypoint wired to the
`clawctl` script in `pyproject.toml`. The legacy `clm` entry point
(`cli/main.py`) was removed in #707; remaining parallel modules under
`src/clawrium/cli/` (chat.py, agent.py, host.py, integration.py,
provider.py, skill.py, …) are hybrid — still imported by clawctl /
TUI code paths — and tracked for removal in #707.
"""

import typer

from clawrium import __git_sha__, __version__
from clawrium.cli.clawctl.agent import agent_app
from clawrium.cli.clawctl.audit import audit_app
from clawrium.cli.clawctl.channel import channel_app
from clawrium.cli.clawctl.host import host_app
from clawrium.cli.clawctl.integration import integration_app
from clawrium.cli.clawctl.mcp import mcp_app
from clawrium.cli.clawctl.provider import provider_app
from clawrium.cli.clawctl.skill import skill_app
from clawrium.cli.meta import completion_cmd, version_cmd
from clawrium.cli.service import service_app

__all__ = ["app"]


app = typer.Typer(
    name="clawctl",
    help=(
        "clawctl — manage your AI assistant fleet, kubectl-style.\n\n"
        "Run 'clawctl <group> --help' for group-specific options."
    ),
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show clawctl version and exit.",
        is_eager=True,
    ),
) -> None:
    """clawctl root callback — handles `--version` and falls through to subcommands."""
    if version:
        typer.echo(f"clawctl {__version__} (git: {__git_sha__})")
        raise typer.Exit(code=0)
    # Otherwise Typer dispatches to the chosen subcommand. When no
    # subcommand is given Typer prints help (no_args_is_help=True).


# Meta verbs: `version` and `completion`.
app.command(name="version", help="Show clawctl version and exit.")(version_cmd)
app.command(name="completion", help="Emit a shell-completion script.")(completion_cmd)


# `tui` and `gui` are rebrand wrappers — they delegate to the same
# implementations the legacy `clm` CLI used. No behavioural change.
@app.command(name="tui", help="Launch the interactive TUI dashboard.")
def tui_cmd() -> None:
    """Launch the Clawrium TUI dashboard."""
    try:
        from clawrium.cli.tui import launch_tui
    except ImportError:
        typer.echo(
            "Error: TUI requires textual. Reinstall with: "
            "uv tool install --force clawrium",
            err=True,
        )
        raise typer.Exit(code=1)
    launch_tui()


@app.command(name="gui", help="Launch the local web GUI dashboard.")
def gui_cmd(
    port: int = typer.Option(
        36000,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Local TCP port to bind (1-65535).",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Skip auto-opening the browser. Useful for headless/SSH sessions.",
    ),
) -> None:
    """Launch the local web GUI dashboard (binds to 127.0.0.1 only)."""
    from clawrium.cli.gui import gui as _gui_impl

    _gui_impl(port=port, no_open=no_open)


# Group registrations. Order here drives `--help` listing.
app.add_typer(service_app, name="service")
app.add_typer(host_app, name="host")
app.add_typer(agent_app, name="agent")
app.add_typer(provider_app, name="provider")
app.add_typer(channel_app, name="channel")
app.add_typer(integration_app, name="integration")
app.add_typer(skill_app, name="skill")
app.add_typer(mcp_app, name="mcp")
app.add_typer(audit_app, name="audit")

# Declarative fleet management verbs: apply / diff / delete -f
from clawrium.cli.clawctl.apply import apply as _apply_cmd  # noqa: E402
from clawrium.cli.clawctl.diff import diff as _diff_cmd  # noqa: E402
from clawrium.cli.clawctl.delete_file import delete_file as _delete_file_cmd  # noqa: E402

app.command(name="apply", help="Apply a fleet manifest (declarative reconciliation).")(
    _apply_cmd
)
app.command(name="diff", help="Preview changes a fleet manifest would make.")(_diff_cmd)
app.command(name="delete", help="Delete resources declared in a fleet manifest.")(
    _delete_file_cmd
)

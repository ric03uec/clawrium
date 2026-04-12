"""Main CLI entry point for Clawrium.

Clawrium is an assistant-first CLI. Use 'clm agent' for agent management.

Quick start:
    clm init                    # Initialize Clawrium
    clm agent registry list     # Browse available agents
    clm agent install           # Install an agent
    clm agent ps                # View agent status
    clm ps                      # Quick fleet overview
"""

from typing import Optional

import typer
from rich.console import Console

from clawrium.cli.init import init as init_command
from clawrium.cli.agent import agent_app
from clawrium.cli.chat import chat as chat_command
from clawrium.cli.host import host_app
from clawrium.cli.provider import provider_app
from clawrium.cli.status import status as status_command

__all__ = ["app"]

console = Console()

app = typer.Typer(
    name="clm",
    help="Clawrium - Manage your AI assistant fleet. Use 'clm agent' for agent management.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Clawrium CLI main entry point."""
    # If no command was provided, show help (handled by no_args_is_help)
    if ctx.invoked_subcommand is None:
        pass


@app.command()
def init() -> None:
    """Initialize Clawrium and check dependencies."""
    init_command()


@app.command()
def ps(
    host: Optional[str] = typer.Option(
        None, "--host", "-H", help="Filter to specific host"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed onboarding stages"
    ),
) -> None:
    """Quick fleet overview - show agents and hosts status."""
    status_command(host=host, verbose=verbose)


@app.command()
def chat(
    agent_name: str = typer.Argument(..., help="Installed agent name to chat with"),
    session: str = typer.Option(
        "main",
        "--session",
        "-s",
        help="Gateway session key (for example: main, direct:<channel>, or thread-specific key)",
    ),
    timeout: float = typer.Option(
        120.0,
        "--timeout",
        min=1.0,
        help="Seconds to wait for each assistant response before failing.",
    ),
    idle_timeout: float = typer.Option(
        300.0,
        "--idle-timeout",
        min=0.0,
        help="Seconds to wait for user input before auto-exit (0 disables).",
    ),
) -> None:
    """Start interactive chat with an installed agent (use `clm ps` to find names)."""
    chat_command(
        agent_name=agent_name,
        session=session,
        timeout=timeout,
        idle_timeout=idle_timeout,
    )


@app.command()
def snapshot() -> None:
    """Backup full system state.

    [Not yet implemented]
    """
    console.print("[yellow]Not implemented:[/yellow] snapshot")
    console.print(
        "This command will backup your fleet configuration in a future release."
    )
    raise typer.Exit(code=0)


@app.command()
def tui() -> None:
    """Launch the interactive TUI dashboard."""
    try:
        from clawrium.cli.tui import launch_tui

        launch_tui()
    except ImportError:
        console.print(
            "[red]Error:[/red] TUI requires textual. Install with: pip install clawrium"
        )
        raise typer.Exit(code=1)


# Register agent subcommands (primary interface)
app.add_typer(agent_app, name="agent")

# Register host subcommands (secondary/infrastructure)
app.add_typer(host_app, name="host")

# Register provider subcommands (inference provider management)
app.add_typer(provider_app, name="provider")


if __name__ == "__main__":
    app()

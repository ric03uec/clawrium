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
from clawrium.cli.host import host_app
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
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Filter to specific host"),
) -> None:
    """Quick fleet overview - show agents and hosts status."""
    status_command(host=host)


@app.command()
def snapshot() -> None:
    """Backup full system state.

    [Not yet implemented]
    """
    console.print("[yellow]Not implemented:[/yellow] snapshot")
    console.print("This command will backup your fleet configuration in a future release.")
    raise typer.Exit(code=0)


# Register agent subcommands (primary interface)
app.add_typer(agent_app, name="agent")

# Register host subcommands (secondary/infrastructure)
app.add_typer(host_app, name="host")


if __name__ == "__main__":
    app()

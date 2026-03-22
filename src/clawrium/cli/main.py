"""Main CLI entry point for Clawrium."""

from typing import Optional

import typer

from clawrium.cli.init import init as init_command
from clawrium.cli.host import host_app
from clawrium.cli.install import install as install_command
from clawrium.cli.registry import registry_app
from clawrium.cli.secret import secret_app
from clawrium.cli.status import status as status_command

__all__ = ["app"]

app = typer.Typer(
    name="clm",
    help="Clawrium - Manage your AI assistant fleet",
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
def install(
    claw: Optional[str] = typer.Option(None, "--claw", "-c", help="Claw type to install"),
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Target host"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Install a claw on a host."""
    install_command(claw=claw, host=host, yes=yes)


@app.command()
def status(
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Filter to specific host"),
) -> None:
    """Show fleet status across all hosts."""
    status_command(host=host)


# Register host subcommands
app.add_typer(host_app, name="host")

# Register registry subcommands
app.add_typer(registry_app, name="registry")

# Register secret subcommands
app.add_typer(secret_app, name="secret")


if __name__ == "__main__":
    app()

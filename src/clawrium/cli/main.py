"""Main CLI entry point for Clawrium."""

import typer

from clawrium.cli.init import init as init_command
from clawrium.cli.host import host_app
from clawrium.cli.registry import registry_app

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


# Register host subcommands
app.add_typer(host_app, name="host")

# Register registry subcommands
app.add_typer(registry_app, name="registry")


if __name__ == "__main__":
    app()

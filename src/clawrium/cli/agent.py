"""Agent management commands for Clawrium.

This is the primary interface for managing AI assistants (claws).
"""

from typing import Optional

import typer
from rich.console import Console

from clawrium.cli.install import install as install_command
from clawrium.cli.status import status as status_command

__all__ = ["agent_app"]

console = Console()

agent_app = typer.Typer(
    name="agent",
    help="Manage AI assistants (claws) in your fleet",
    no_args_is_help=True,
)


@agent_app.command()
def install(
    claw: Optional[str] = typer.Option(None, "--claw", "-c", help="Claw type to install"),
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Target host"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Install a claw on a host."""
    install_command(claw=claw, host=host, yes=yes)


@agent_app.command()
def ps(
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Filter to specific host"),
) -> None:
    """Show status of agents across hosts."""
    status_command(host=host)


@agent_app.command()
def configure(
    claw_name: str = typer.Argument(..., help="Claw name to configure"),
) -> None:
    """Configure agent settings.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] configure '{claw_name}'")
    console.print("This command will allow configuring agent settings in a future release.")
    raise typer.Exit(code=0)


@agent_app.command()
def remove(
    claw_name: str = typer.Argument(..., help="Claw name to remove"),
) -> None:
    """Remove an agent from a host.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] remove '{claw_name}'")
    console.print("This command will allow removing agents in a future release.")
    raise typer.Exit(code=0)


@agent_app.command()
def start(
    claw_name: str = typer.Argument(..., help="Claw name to start"),
) -> None:
    """Start an agent.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] start '{claw_name}'")
    console.print("This command will allow starting agents in a future release.")
    raise typer.Exit(code=0)


@agent_app.command()
def stop(
    claw_name: str = typer.Argument(..., help="Claw name to stop"),
) -> None:
    """Stop an agent.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] stop '{claw_name}'")
    console.print("This command will allow stopping agents in a future release.")
    raise typer.Exit(code=0)


@agent_app.command()
def logs(
    claw_name: str = typer.Argument(..., help="Claw name to view logs for"),
) -> None:
    """View agent logs.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] logs '{claw_name}'")
    console.print("This command will allow viewing agent logs in a future release.")
    raise typer.Exit(code=0)


# Nested secret subcommand group
secret_app = typer.Typer(
    name="secret",
    help="Manage secrets for agent instances",
    no_args_is_help=True,
)


@secret_app.command(name="set")
def secret_set(
    claw_name: str = typer.Argument(..., help="Claw name (e.g., opc-work)"),
    key: str = typer.Argument(..., help="Secret key name (e.g., OPENAI_API_KEY)"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Description of the secret"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip overwrite confirmation"),
) -> None:
    """Set a secret value for an agent instance."""
    from clawrium.cli.secret import set_cmd
    set_cmd(claw_name=claw_name, key=key, description=description, yes=yes)


@secret_app.command(name="list")
def secret_list(
    claw_name: str = typer.Argument(..., help="Claw name (e.g., zc-kevin)"),
) -> None:
    """List secrets for an agent instance."""
    from clawrium.cli.secret import list_cmd
    list_cmd(claw_name=claw_name)


@secret_app.command(name="remove")
def secret_remove(
    claw_name: str = typer.Argument(..., help="Claw name"),
    key: str = typer.Argument(..., help="Secret key to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove a secret from an agent instance."""
    from clawrium.cli.secret import remove_cmd
    remove_cmd(claw_name=claw_name, key=key, force=force)


@secret_app.command(name="import")
def secret_import(
    source_claw: str = typer.Argument(..., help="Source claw to import secrets from"),
    target_claw: str = typer.Argument(..., help="Target claw to import secrets to"),
) -> None:
    """Import secrets from another claw instance.

    [Not yet implemented]
    """
    console.print(f"[yellow]Not implemented:[/yellow] import secrets from '{source_claw}' to '{target_claw}'")
    console.print("This command will allow importing secrets between claws in a future release.")
    raise typer.Exit(code=0)


# Register secret subcommand
agent_app.add_typer(secret_app, name="secret")


# Nested registry subcommand group
registry_app = typer.Typer(
    name="registry",
    help="Browse available agent types",
    no_args_is_help=True,
)


@registry_app.command(name="list")
def registry_list() -> None:
    """List available agent types in the registry."""
    from clawrium.cli.registry import list_registry
    list_registry()


@registry_app.command(name="show")
def registry_show(
    claw_name: str = typer.Argument(..., help="Name of the claw to show"),
) -> None:
    """Show detailed information about an agent type."""
    from clawrium.cli.registry import show
    show(claw_name=claw_name)


# Register registry subcommand
agent_app.add_typer(registry_app, name="registry")

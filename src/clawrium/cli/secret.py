"""Secret management commands for Clawrium."""

import getpass
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from clawrium.core.secrets import (
    load_secrets,
    SecretsFileCorruptedError,
    InvalidSecretKeyError,
    get_installed_claw,
    get_instance_key,
    get_instance_secrets,
    set_instance_secret,
    remove_instance_secret,
    AgentNotFoundError,
)
from clawrium.core.registry import (
    get_required_secrets,
)

__all__ = ["secret_app"]

console = Console()

secret_app = typer.Typer(
    name="secret",
    help="Manage secrets for agents",
    no_args_is_help=True,
)


@secret_app.command(name="set")
def set_cmd(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    key: str = typer.Argument(..., help="Secret key name (e.g., OPENAI_API_KEY)"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Description of the secret"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip overwrite confirmation"),
) -> None:
    """Set a secret value for an agent.

    Prompts for the value using masked input (not visible on screen).
    """
    # Validate agent type exists
    try:
        hostname, claw_type, name = get_installed_claw(claw_name)
    except AgentNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    instance_key = get_instance_key(hostname, claw_type, name)

    # Check if secret already exists for this instance
    try:
        instance_secrets = get_instance_secrets(instance_key)
    except SecretsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    existing = instance_secrets.get(key)
    if existing and not yes:
        console.print(
            f"[yellow]Secret '{key}' already exists for '{claw_name}'[/yellow]"
        )
        console.print(f"  Description: {existing.get('description') or '-'}")
        console.print(f"  Last updated: {existing.get('updated_at', 'Unknown')}")
        if not typer.confirm("Overwrite this secret?"):
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    # Prompt for value with masked input
    try:
        value = getpass.getpass(prompt=f"Enter value for {key}: ")
    except (KeyboardInterrupt, EOFError):
        console.print("\nCancelled.")
        raise typer.Exit(code=1)

    if not value:
        console.print("[red]Error:[/red] Secret value cannot be empty")
        raise typer.Exit(code=1)

    # Set the secret for this instance
    try:
        is_new = set_instance_secret(instance_key, key, value, description or "")
    except InvalidSecretKeyError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            "[dim]Hint: Keys must be uppercase letters, digits, and underscores (e.g., OPENAI_API_KEY)[/dim]"
        )
        raise typer.Exit(code=1)

    if is_new:
        console.print(f"[green]Secret '{key}' created for '{claw_name}'.[/green]")
    else:
        console.print(f"[green]Secret '{key}' updated for '{claw_name}'.[/green]")


@secret_app.command(name="list")
def list_cmd(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
) -> None:
    """List secrets for an agent.

    Shows secret keys and metadata. Values are never displayed.
    Also shows missing required secrets.
    """
    # Validate agent type exists
    try:
        hostname, claw_type, name = get_installed_claw(claw_name)
    except AgentNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    instance_key = get_instance_key(hostname, claw_type, name)

    try:
        secrets = load_secrets()
    except SecretsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Get secrets for this instance
    instance_secrets = secrets.get(instance_key, {})

    # Build gateway config based on agent type
    required_secrets = get_required_secrets(claw_type)
    required_keys = {s["key"] for s in required_secrets}
    stored_keys = set(instance_secrets.keys())
    missing_keys = required_keys - stored_keys

    # Display agent header
    console.print(f"\n[bold]Agent:[/bold] {name} ({hostname})")

    # Display stored secrets if any
    if instance_secrets:
        table = Table(show_header=True, box=None)
        table.add_column("Key", style="cyan")
        table.add_column("Description")
        table.add_column("Updated", style="dim")

        for key in sorted(instance_secrets.keys()):
            entry = instance_secrets[key]
            # Format updated_at as date only for readability
            updated = entry.get("updated_at", "")
            if updated:
                updated = updated.split("T")[0]  # Extract date portion
            table.add_row(
                key,
                entry.get("description") or "-",
                updated,
            )

        console.print(table)
    else:
        console.print("  No secrets set")

    # Display missing required secrets
    if missing_keys:
        console.print("  [yellow]Missing:[/yellow]", end="")
        for secret_def in required_secrets:
            if secret_def["key"] in missing_keys:
                desc = secret_def.get("description", "")
                console.print(f" {secret_def['key']}", end="")
                if desc:
                    console.print(f" ({desc})", end="")
        console.print()  # New line


@secret_app.command(name="remove")
def remove_cmd(
    claw_name: str = typer.Argument(..., help="Agent name"),
    key: str = typer.Argument(..., help="Secret key to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove a secret from an agent.

    Prompts for confirmation unless --force is specified.
    """
    # Validate agent type exists
    try:
        hostname, claw_type, name = get_installed_claw(claw_name)
    except AgentNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    instance_key = get_instance_key(hostname, claw_type, name)

    # Check if secret exists for this instance
    try:
        instance_secrets = get_instance_secrets(instance_key)
    except SecretsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    if key not in instance_secrets:
        console.print(f"[red]Error:[/red] Secret '{key}' not found for '{claw_name}'")
        raise typer.Exit(code=1)

    # Confirmation
    if not force:
        confirmed = typer.confirm(
            f"Remove secret '{key}' from '{claw_name}'? This cannot be undone."
        )
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    success = remove_instance_secret(instance_key, key)
    if success:
        console.print(f"[green]Secret '{key}' removed from '{claw_name}'.[/green]")
    else:
        console.print("[red]Error:[/red] Failed to remove secret")
        raise typer.Exit(code=1)

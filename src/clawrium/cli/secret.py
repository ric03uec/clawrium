"""Secret management commands for Clawrium."""

import getpass
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from clawrium.core.secrets import (
    get_secret,
    set_secret,
    remove_secret,
    load_secrets,
    SecretsFileCorruptedError,
    InvalidSecretKeyError,
    get_installed_claw,
    get_instance_key,
    get_instance_secrets,
    set_instance_secret,
    remove_instance_secret,
    list_instances_with_secrets,
    ClawNotFoundError,
)
from clawrium.core.registry import (
    get_required_secrets,
    list_claws,
)

__all__ = ["secret_app"]

console = Console()

secret_app = typer.Typer(
    name="secret",
    help="Manage secrets for claw instances",
    no_args_is_help=True,
)


@secret_app.command(name="set")
def set_cmd(
    claw_name: str = typer.Argument(..., help="Claw name (e.g., opc-work)"),
    key: str = typer.Argument(..., help="Secret key name (e.g., OPENAI_API_KEY)"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Description of the secret"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip overwrite confirmation"),
) -> None:
    """Set a secret value for a claw instance.

    Prompts for the value using masked input (not visible on screen).
    """
    # Validate claw exists
    try:
        hostname, claw_type, name = get_installed_claw(claw_name)
    except ClawNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    instance_key = get_instance_key(hostname, claw_type, name)

    # Check if secret already exists for this instance
    instance_secrets = get_instance_secrets(instance_key)
    existing = instance_secrets.get(key)
    if existing and not yes:
        console.print(f"[yellow]Secret '{key}' already exists for '{claw_name}'[/yellow]")
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
        console.print("[dim]Hint: Keys must be uppercase letters, digits, and underscores (e.g., OPENAI_API_KEY)[/dim]")
        raise typer.Exit(code=1)

    if is_new:
        console.print(f"[green]Secret '{key}' created for '{claw_name}'.[/green]")
    else:
        console.print(f"[green]Secret '{key}' updated for '{claw_name}'.[/green]")


@secret_app.command(name="list")
def list_cmd() -> None:
    """List all stored secrets.

    Shows secret keys and metadata. Values are never displayed.
    Also shows missing required secrets per claw type.
    """
    try:
        secrets = load_secrets()
    except SecretsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Display stored secrets (legacy __global__ namespace)
    global_secrets = secrets.get("__global__", {})
    if global_secrets:
        table = Table(title="Stored Secrets")
        table.add_column("Key", style="cyan")
        table.add_column("Description")
        table.add_column("Updated", style="dim")

        for key in sorted(global_secrets.keys()):
            entry = global_secrets[key]
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
        console.print("No secrets stored. Use 'clm secret set KEY' to add a secret.")

    # Check for missing required secrets per claw (per D-08)
    stored_keys = set(global_secrets.keys())
    missing_by_claw: dict[str, list[dict]] = {}

    for claw_name in list_claws():
        required = get_required_secrets(claw_name)
        missing = [s for s in required if s["key"] not in stored_keys]
        if missing:
            missing_by_claw[claw_name] = missing

    if missing_by_claw:
        console.print("")  # Blank line separator
        console.print("[yellow]Missing Required Secrets[/yellow]")

        for claw_name, missing_secrets in sorted(missing_by_claw.items()):
            console.print(f"\n  [cyan]{claw_name}[/cyan]")
            for s in missing_secrets:
                console.print(f"    - {s['key']}: {s.get('description', '')}")


@secret_app.command(name="remove")
def remove_cmd(
    key: str = typer.Argument(..., help="Secret key to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove a secret.

    Prompts for confirmation unless --force is specified.
    """
    # Check if secret exists
    existing = get_secret(key)
    if not existing:
        console.print(f"[red]Error:[/red] Secret '{key}' not found")
        raise typer.Exit(code=1)

    # Confirmation (per D-12, matching host remove pattern)
    if not force:
        confirmed = typer.confirm(f"Remove secret '{key}'? This cannot be undone.")
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    success = remove_secret(key)
    if success:
        console.print(f"[green]Secret '{key}' removed.[/green]")
    else:
        console.print("[red]Error:[/red] Failed to remove secret")
        raise typer.Exit(code=1)

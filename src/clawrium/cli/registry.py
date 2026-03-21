"""Registry commands for browsing available claws."""

import typer
from rich.console import Console
from rich.table import Table

from clawrium.core.registry import (
    list_claws,
    get_claw_info,
    load_manifest,
    ManifestNotFoundError,
)

__all__ = ["registry_app"]

console = Console()

registry_app = typer.Typer(
    name="registry",
    help="Browse available claw types",
    no_args_is_help=True,
)


@registry_app.command(name="list")
def list_registry() -> None:
    """List available claw types in the registry."""
    claws = list_claws()

    if not claws:
        console.print("No claws available in registry.")
        return

    table = Table(title="Available Claws")
    table.add_column("Name", style="cyan")
    table.add_column("Latest Version", style="green")
    table.add_column("Description")

    for claw_name in claws:
        try:
            info = get_claw_info(claw_name)
            table.add_row(
                info["name"],
                info["latest_version"],
                info["description"],
            )
        except ManifestNotFoundError:
            table.add_row(claw_name, "?", "Error loading manifest")

    console.print(table)


@registry_app.command()
def show(
    claw_name: str = typer.Argument(..., help="Name of the claw to show"),
) -> None:
    """Show detailed information about a claw type."""
    try:
        manifest = load_manifest(claw_name)
    except ManifestNotFoundError:
        console.print(f"[red]Error:[/red] Claw '{claw_name}' not found in registry")
        raise typer.Exit(code=1)

    # Header info
    console.print(f"\n[bold cyan]{manifest['name']}[/bold cyan]")
    console.print(f"{manifest['description']}\n")

    # Supported platforms table
    table = Table(title="Supported Platforms")
    table.add_column("Version", style="green")
    table.add_column("OS")
    table.add_column("Architecture")
    table.add_column("Min Memory")
    table.add_column("GPU Required")

    for entry in manifest["entries"]:
        reqs = entry["requirements"]
        table.add_row(
            entry["version"],
            f"{entry['os']} {entry['os_version']}",
            entry["arch"],
            f"{reqs['min_memory_mb']}MB",
            "Yes" if reqs["gpu_required"] else "No",
        )

    console.print(table)

    # Dependencies section (if any entry has dependencies)
    all_deps = set()
    for entry in manifest["entries"]:
        for dep, version in entry["requirements"].get("dependencies", {}).items():
            all_deps.add(f"{dep} {version}")

    if all_deps:
        console.print("\n[bold]Dependencies:[/bold]")
        for dep in sorted(all_deps):
            console.print(f"  - {dep}")

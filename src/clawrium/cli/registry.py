"""Registry commands for browsing available agent types."""

import logging

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from clawrium.core.registry import (
    list_claws,
    get_claw_info,
    load_manifest,
    ManifestNotFoundError,
    ManifestParseError,
    InvalidAgentTypeError,
)

__all__ = ["registry_app"]

logger = logging.getLogger(__name__)
console = Console()

registry_app = typer.Typer(
    name="registry",
    help="Browse available agent types",
    no_args_is_help=True,
    rich_markup_mode=None,
)


@registry_app.command(name="list")
def list_registry() -> None:
    """List available agent types in the registry."""
    claws = list_claws()
    corrupted_count = 0

    if not claws:
        console.print("No agent types available in registry.")
        return

    table = Table(title="Available Agent Types")
    table.add_column("Name", style="cyan")
    table.add_column("Latest Version", style="green")
    table.add_column("Description")

    for claw_name in claws:
        try:
            info = get_claw_info(claw_name)
            table.add_row(
                escape(info["agent_type"]),
                escape(info["latest_version"]),
                escape(info["description"]),
            )
        except ManifestNotFoundError:
            table.add_row(escape(claw_name), "?", "Manifest not found")
        except ManifestParseError as error:
            logger.debug(
                "Manifest parse failure while listing agent type '%s'",
                claw_name,
                exc_info=error,
            )
            corrupted_count += 1
            table.add_row(escape(claw_name), "?", escape("Corrupted manifest"))

    console.print(table)
    if corrupted_count:
        console.print(
            "\n[yellow]Warning:[/yellow] Some registry manifests are corrupted. "
            "Reinstall Clawrium to restore bundled manifests: "
            "https://github.com/ric03uec/clawrium#installation"
        )


@registry_app.command()
def show(
    agent_type: str = typer.Argument(
        ..., help="Name of the agent type to show (e.g., zeroclaw)"
    ),
) -> None:
    """Show detailed information about an agent type."""
    try:
        manifest = load_manifest(agent_type)
    except ManifestNotFoundError:
        console.print(
            f"[red]Error:[/red] Agent type '{escape(agent_type)}' not found in registry. "
            "Run 'clm agent registry list' to view available agent types."
        )
        raise typer.Exit(code=1)
    except ManifestParseError as e:
        logger.debug("Registry manifest parse failure for '%s'", agent_type, exc_info=e)
        console.print(
            f"[red]Error:[/red] Registry manifest is corrupted: {escape(str(e))}. "
            "Reinstall Clawrium to restore bundled manifests: "
            "https://github.com/ric03uec/clawrium#installation"
        )
        raise typer.Exit(code=1)
    except InvalidAgentTypeError as e:
        console.print(
            f"[red]Error:[/red] {escape(str(e))}. "
            "Run 'clm agent registry list' to see valid agent type names."
        )
        raise typer.Exit(code=1)

    # Header info (escape manifest fields to prevent markup injection)
    console.print(f"\n[bold cyan]{escape(manifest['agent']['type'])}[/bold cyan]")
    console.print(f"{escape(manifest['agent'].get('description', ''))}\n")

    # Supported platforms table
    table = Table(title="Supported Platforms")
    table.add_column("Version", style="green")
    table.add_column("OS")
    table.add_column("Architecture")
    table.add_column("Min Memory")
    table.add_column("GPU Required")

    for entry in manifest["platforms"]:
        reqs = entry["requirements"]
        table.add_row(
            entry["version"],
            f"{entry['os']} {entry['os_version']}",
            entry["arch"],
            f"{reqs['min_memory_mb']}MB",
            "Yes" if reqs["gpu_required"] else "No",
        )

    console.print(table)

    required_secrets = manifest.get("secrets", {}).get("required", [])
    optional_secrets = manifest.get("secrets", {}).get("optional", [])

    if required_secrets:
        required_table = Table(title="Required Secrets")
        required_table.add_column("Key", style="yellow")
        required_table.add_column("Description")
        for secret in required_secrets:
            required_table.add_row(
                escape(secret["key"]),
                escape(secret["description"]),
            )
        console.print(required_table)

    if optional_secrets:
        optional_table = Table(title="Optional Secrets")
        optional_table.add_column("Key", style="yellow")
        optional_table.add_column("Description")
        for secret in optional_secrets:
            optional_table.add_row(
                escape(secret["key"]),
                escape(secret["description"]),
            )
        console.print(optional_table)

    # Dependencies section (if any entry has dependencies)
    all_deps = set()
    for entry in manifest["platforms"]:
        for dep, version in entry["requirements"].get("dependencies", {}).items():
            all_deps.add(f"{dep} {version}")

    if all_deps:
        console.print("\n[bold]Dependencies:[/bold]")
        for dep in sorted(all_deps):
            console.print(f"  - {dep}")

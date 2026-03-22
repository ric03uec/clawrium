"""Fleet status command for viewing claw instances across hosts."""

from collections import defaultdict
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from clawrium.core.hosts import load_hosts, HostsFileCorruptedError
from clawrium.core.health import check_claw_health, ClawStatus

__all__ = ["status"]

console = Console()


def status(
    host: Optional[str] = typer.Option(
        None, "--host", "-H", help="Filter to specific host (hostname or alias)"
    ),
) -> None:
    """Show fleet status across all hosts.

    Displays claw instances grouped by claw type (per D-12) with live
    health check (per D-13). Shows name, version, host, status (per D-14).
    """
    # Load all hosts
    try:
        hosts = load_hosts()
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not hosts:
        console.print("No hosts registered. Run 'clm host add' to add a host.")
        return

    # Filter to specific host if requested
    if host:
        hosts = [h for h in hosts if h.get("hostname") == host or h.get("alias") == host]
        if not hosts:
            console.print(f"[red]Error:[/red] Host '{escape(host)}' not found")
            raise typer.Exit(code=1)

    # Collect all claws across hosts, grouped by claw type
    # Structure: {claw_name: [(host_record, claw_record), ...]}
    claws_by_type: dict[str, list[tuple[dict, dict]]] = defaultdict(list)

    for h in hosts:
        for claw_name, claw_record in h.get("claws", {}).items():
            claws_by_type[claw_name].append((h, claw_record))

    if not claws_by_type:
        console.print("No claws installed on any host.")
        console.print("Run 'clm install' to install a claw.")
        return

    # Perform live health checks with progress spinner
    health_results: dict[tuple[str, str], ClawStatus] = {}  # (claw, hostname) -> status

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Checking fleet health...", total=None)

        for claw_name, instances in claws_by_type.items():
            for h, claw_record in instances:
                progress.update(task, description=f"Checking {claw_name} on {h.get('alias') or h['hostname']}...")
                result = check_claw_health(claw_name, h)
                health_results[(claw_name, h["hostname"])] = result["status"]

    console.print()  # Blank line after progress

    # Display claw-centric view (per D-12)
    for claw_name in sorted(claws_by_type.keys()):
        instances = claws_by_type[claw_name]

        table = Table(title=f"[bold cyan]{escape(claw_name)}[/bold cyan]")
        table.add_column("Host", style="white")
        table.add_column("Version", style="green")
        table.add_column("User", style="dim")
        table.add_column("Status")
        table.add_column("Installed", style="dim")

        for h, claw_record in instances:
            display_host = h.get("alias") or h["hostname"]
            version = claw_record.get("version", "?")
            user = claw_record.get("user", "-")
            installed_at = claw_record.get("installed_at", "-")
            if installed_at and installed_at != "-":
                # Format as date only for readability
                installed_at = installed_at.split("T")[0]

            # Get live status with color coding
            live_status = health_results.get((claw_name, h["hostname"]), ClawStatus.UNKNOWN)

            if live_status == ClawStatus.RUNNING:
                status_display = "[green]running[/green]"
            elif live_status == ClawStatus.STOPPED:
                status_display = "[red]stopped[/red]"
            elif live_status == ClawStatus.NOT_INSTALLED:
                status_display = "[yellow]not installed[/yellow]"
            else:
                status_display = "[yellow]unknown[/yellow]"

            # Also show install state if failed
            install_status = claw_record.get("status", "")
            if install_status == "failed":
                status_display = "[red]install failed[/red]"
            elif install_status == "installing":
                status_display = "[yellow]installing...[/yellow]"

            table.add_row(
                escape(display_host),
                version,
                escape(user) if user else "-",
                status_display,
                installed_at,
            )

        console.print(table)
        console.print()  # Space between claw types

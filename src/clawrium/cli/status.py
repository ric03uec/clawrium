"""Fleet status command for viewing claw instances across hosts."""

from collections import defaultdict
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from clawrium.core.hosts import load_hosts, HostsFileCorruptedError
from clawrium.core.health import (
    check_claw_health,
    ClawStatus,
    HealthResult,
)

__all__ = ["status"]

console = Console()


def display_verbose_onboarding(
    claw_name: str, host_alias: str, result: HealthResult
) -> None:
    """Display detailed onboarding stage breakdown.

    Args:
        claw_name: Name of the claw
        host_alias: Host alias or hostname
        result: Health result containing onboarding stages
    """
    console.print(
        f"\n[bold]{escape(claw_name)}[/bold] on [cyan]{escape(host_alias)}[/cyan]:"
    )

    stages = result.get("onboarding_stages")
    if not stages or not isinstance(stages, dict):
        console.print("  [dim]No onboarding data available[/dim]")
        return

    for stage_name, stage_data in stages.items():
        status = stage_data.get("status", "pending")
        completed_at = stage_data.get("completed_at")

        if status == "complete":
            icon = "✓"
            color = "green"
            detail = f"({escape(completed_at[:10])})" if completed_at else ""
        elif status == "skipped":
            icon = "○"
            color = "dim"
            detail = "(skipped)"
        else:
            icon = "○"
            color = "yellow"
            detail = "pending"

        escaped_name = escape(stage_name)
        console.print(f"  [{color}]{icon} {escaped_name:<10}[/{color}] - {detail}")


def status(
    host: Optional[str] = typer.Option(
        None, "--host", "-H", help="Filter to specific host (hostname or alias)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed onboarding stages"
    ),
) -> None:
    """Show fleet status across all hosts.

    Displays claw instances grouped by claw type (per D-12) with live
    health check (per D-13). Shows name, version, host, status (per D-14).

    Use --verbose to see detailed onboarding stage breakdown.
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
        hosts = [
            h for h in hosts if h.get("hostname") == host or h.get("alias") == host
        ]
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
    health_results: dict[
        tuple[str, str], HealthResult
    ] = {}  # (claw, hostname) -> result

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Checking fleet health...", total=None)

            for claw_name, instances in claws_by_type.items():
                for h, claw_record in instances:
                    progress.update(
                        task,
                        description=f"Checking {escape(claw_name)} on {escape(h.get('alias') or h['hostname'])}...",
                    )
                    result = check_claw_health(claw_name, h)
                    health_results[(claw_name, h["hostname"])] = result
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        raise typer.Exit(code=1)

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

        verbose_rows: list[tuple[str, str, HealthResult]] = []

        for h, claw_record in instances:
            display_host = h.get("alias") or h["hostname"]
            version = claw_record.get("version", "?")
            user = claw_record.get("user", "-")
            installed_at = claw_record.get("installed_at", "-")
            if installed_at and installed_at != "-":
                # Format as date only for readability
                installed_at = installed_at.split("T")[0]

            # Get live status with color coding
            result = health_results.get((claw_name, h["hostname"]))
            if result:
                live_status = result["status"]
                missing_secrets = result.get("missing_secrets", [])
            else:
                live_status = ClawStatus.UNKNOWN
                missing_secrets = []

            if live_status == ClawStatus.RUNNING:
                status_display = "[green]running[/green]"
            elif live_status == ClawStatus.DEGRADED:
                # Show degraded with missing secret keys
                if missing_secrets:
                    # B7: Escape secret keys to prevent Rich markup injection
                    escaped_keys = [escape(k) for k in missing_secrets[:3]]
                    missing_str = ", ".join(escaped_keys)
                    if len(missing_secrets) > 3:
                        missing_str += f" +{len(missing_secrets) - 3} more"
                    status_display = (
                        f"[yellow]degraded (missing: {missing_str})[/yellow]"
                    )
                else:
                    status_display = "[yellow]degraded[/yellow]"
            elif live_status == ClawStatus.STOPPED:
                # Deprecated: check_claw_health() no longer returns STOPPED for stopped processes
                # Kept for backward compatibility with any external callers
                status_display = "[red]stopped[/red]"
            elif live_status == ClawStatus.NOT_INSTALLED:
                status_display = "[yellow]not installed[/yellow]"
            elif live_status == ClawStatus.PENDING_ONBOARD:
                status_display = "[yellow]pending onboard[/yellow]"
            elif live_status == ClawStatus.ONBOARDING:
                stages = result.get("onboarding_stages")
                if stages and isinstance(stages, dict):
                    completed = sum(
                        1
                        for s in stages.values()
                        if isinstance(s, dict)
                        and s.get("status") in ("complete", "skipped")
                    )
                    total = len(stages)
                else:
                    completed, total = 0, 4
                status_display = f"[cyan]onboarding ({completed}/{total})[/cyan]"
            elif live_status == ClawStatus.READY:
                status_display = "[blue]ready (stopped)[/blue]"
            else:
                error_detail = result.get("error") if result else None
                if error_detail and isinstance(error_detail, str):
                    status_display = (
                        f"[yellow]unknown ({escape(error_detail[:40])})[/yellow]"
                    )
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

            if verbose and result and result.get("process_running") is False:
                verbose_rows.append((claw_name, display_host, result))

        console.print(table)
        console.print()

        for vname, vhost, vresult in verbose_rows:
            display_verbose_onboarding(vname, vhost, vresult)

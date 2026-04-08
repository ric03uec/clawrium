"""Install command for deploying claws to hosts."""

from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from clawrium.core.hosts import load_hosts, get_host, HostsFileCorruptedError
from clawrium.core.install import run_installation, InstallationError
from clawrium.core.registry import (
    list_claws,
    get_claw_info,
    check_compatibility,
    ManifestNotFoundError,
)

__all__ = ["install"]

console = Console()


def _select_claw() -> str:
    """Prompt user to select a claw from registry."""
    claws = list_claws()
    if not claws:
        console.print("[red]Error:[/red] No claws available in registry")
        raise typer.Exit(code=1)

    console.print("\n[bold]Available claws:[/bold]")
    for i, claw in enumerate(claws, 1):
        try:
            info = get_claw_info(claw)
            console.print(
                f"  {i}. {escape(claw)} (v{info['latest_version']}) - {escape(info['description'])}"
            )
        except ManifestNotFoundError:
            console.print(f"  {i}. {escape(claw)} (manifest error)")

    console.print()
    choice = typer.prompt("Select claw", type=int)
    if choice < 1 or choice > len(claws):
        console.print("[red]Invalid selection[/red]")
        raise typer.Exit(code=1)

    return claws[choice - 1]


def _select_host() -> str:
    """Prompt user to select a host from registered hosts."""
    try:
        hosts = load_hosts()
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not hosts:
        console.print(
            "[red]Error:[/red] No hosts registered. Run 'clm host add' first."
        )
        raise typer.Exit(code=1)

    console.print("\n[bold]Available hosts:[/bold]")
    for i, host in enumerate(hosts, 1):
        name = host.get("alias") or host["hostname"]
        hw = host.get("hardware", {})
        arch = hw.get("architecture", "?")
        mem_gb = (
            round(hw.get("memtotal_mb", 0) / 1024, 1) if hw.get("memtotal_mb") else "?"
        )
        console.print(f"  {i}. {escape(name)} ({arch}, {mem_gb}GB)")

    console.print()
    choice = typer.prompt("Select host", type=int)
    if choice < 1 or choice > len(hosts):
        console.print("[red]Invalid selection[/red]")
        raise typer.Exit(code=1)

    # Return hostname for lookup
    selected = hosts[choice - 1]
    return selected.get("alias") or selected["hostname"]


def install(
    claw: Optional[str] = typer.Option(
        None, "--claw", "-c", help="Claw type to install (e.g., openclaw)"
    ),
    host: Optional[str] = typer.Option(
        None, "--host", "-H", help="Target host (hostname or alias)"
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Friendly name for the claw instance (max 32 chars, alphanumeric/hyphens/underscores). "
        "Names are unique per host and immutable after installation.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Install a claw on a host.

    Without flags, prompts for claw and host selection interactively.
    With --claw and --host flags, runs directly (per D-01 hybrid invocation).
    """
    # Step 1: Get claw (prompt if not provided per D-01)
    selected_claw = claw or _select_claw()

    # Step 2: Validate claw exists
    try:
        get_claw_info(selected_claw)  # Validates claw exists
    except ManifestNotFoundError:
        console.print(
            f"[red]Error:[/red] Claw '{escape(selected_claw)}' not found in registry"
        )
        raise typer.Exit(code=1)

    # Step 3: Get host (prompt if not provided per D-01)
    selected_host = host or _select_host()

    # Step 4: Load host and check compatibility
    try:
        host_record = get_host(selected_host)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not host_record:
        console.print(f"[red]Error:[/red] Host '{escape(selected_host)}' not found")
        raise typer.Exit(code=1)

    hardware = host_record.get("hardware", {})
    compat = check_compatibility(selected_claw, hardware)

    if not compat["compatible"]:
        console.print(f"[red]Error:[/red] Host is incompatible with {selected_claw}:")
        for reason in compat["reasons"]:
            console.print(f"  - {reason}")
        raise typer.Exit(code=1)

    matched_version = compat["matched_entry"]["version"]
    display_host = host_record.get("alias") or host_record["hostname"]

    # Step 5: Show confirmation summary (per D-03)
    summary = Panel(
        f"[bold]Claw:[/bold] {selected_claw}\n"
        f"[bold]Version:[/bold] {matched_version}\n"
        f"[bold]Host:[/bold] {display_host}\n"
        f"[bold]Architecture:[/bold] {hardware.get('architecture', 'unknown')}\n"
        f"[bold]Memory:[/bold] {round(hardware.get('memtotal_mb', 0) / 1024, 1)}GB",
        title="Installation Summary",
        border_style="cyan",
    )
    console.print(summary)

    if not yes and not typer.confirm("\nProceed with installation?", default=False):
        console.print("Installation cancelled.")
        raise typer.Exit(code=0)

    # Step 6: Run installation with progress spinner (per D-02)
    console.print()  # Blank line before progress

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Starting installation...", total=None)

            def update_progress(stage: str, message: str) -> None:
                progress.update(task, description=f"[{stage}] {message}")

            result = run_installation(
                claw_name=selected_claw,
                hostname=selected_host,
                name=name,
                on_event=update_progress,
            )

        # Success
        console.print(
            f"[green]Success![/green] {selected_claw} v{result['version']} installed as '{name}' on {display_host}"
            if name
            else f"[green]Success![/green] {selected_claw} v{result['version']} installed on {display_host}"
        )

    except InstallationError as e:
        # Error display per D-10
        console.print(f"[red]Installation failed:[/red] {e}")
        raise typer.Exit(code=1)

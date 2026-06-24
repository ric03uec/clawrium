"""Install command for deploying agents to hosts."""

from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from clawrium.core.hosts import load_hosts, get_host, HostsFileCorruptedError
from clawrium.core.install import (
    run_installation,
    InstallationError,
    IncompleteInstallationError,
)
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
        console.print("[red]Error:[/red] No agent types available in registry")
        raise typer.Exit(code=1)

    console.print("\n[bold]Available agent types:[/bold]")
    for i, claw in enumerate(claws, 1):
        try:
            info = get_claw_info(claw)
            console.print(
                f"  {i}. {escape(claw)} (v{info['latest_version']}) - {escape(info['description'])}"
            )
        except ManifestNotFoundError:
            console.print(f"  {i}. {escape(claw)} (manifest error)")

    console.print()
    choice = typer.prompt("Select agent type", type=int)
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


def _handle_incomplete_installation(
    error: IncompleteInstallationError,
) -> tuple[bool, bool]:
    """Prompt user to handle incomplete installation.

    Returns:
        Tuple of (cleanup_failed, resume) flags for run_installation()
    """
    details = error.details
    status = details.get("status", "unknown")
    agent_name = details.get("agent_name") or error.claw_name
    error_msg = details.get("error")

    console.print()
    console.print(
        f"[yellow]Found incomplete installation for {error.claw_name} "
        f"(name: {agent_name})[/yellow]"
    )
    console.print(f"[yellow]Status: {status}[/yellow]")
    if error_msg:
        console.print(f"[yellow]Error: {error_msg}[/yellow]")
    console.print()

    console.print("[bold]Options:[/bold]")
    console.print("  1. Resume installation (continue from current state)")
    console.print("  2. Clean up and retry (remove failed agent, start fresh)")
    console.print("  3. Abort (cancel operation)")
    console.print()

    choice = typer.prompt("Choose option [1/2/3]", type=int)

    if choice == 1:
        # Resume
        return (False, True)
    elif choice == 2:
        # Clean up and retry
        return (True, False)
    elif choice == 3:
        # Abort
        console.print("Installation cancelled.")
        raise typer.Exit(code=0)
    else:
        console.print("[red]Invalid selection[/red]")
        raise typer.Exit(code=1)


def _run_installation_with_progress(
    selected_claw: str,
    selected_host: str,
    name: str | None,
    cleanup_failed: bool,
    resume: bool,
    force: bool = False,
) -> dict:
    """Run installation with progress spinner.

    Returns:
        InstallResult dict
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting installation...", total=None)

        def update_progress(stage: str, message: str) -> None:
            # Surface warnings immediately outside progress context
            if stage == "warn":
                console.print(f"[yellow]Warning:[/yellow] {message}")
            else:
                progress.update(task, description=f"[{stage}] {message}")

        result = run_installation(
            claw_name=selected_claw,
            hostname=selected_host,
            name=name,
            on_event=update_progress,
            cleanup_failed=cleanup_failed,
            resume=resume,
            force=force,
        )

    return result


def install(
    claw: Optional[str] = typer.Option(
        None, "--type", "-t", help="Agent type to install (e.g., openclaw)"
    ),
    host: Optional[str] = typer.Option(
        None, "--host", "-H", help="Target host (hostname or alias)"
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Agent name for the instance (max 32 chars, alphanumeric/hyphens/underscores). "
        "Names are unique per host and immutable after installation.",
    ),
    cleanup_failed: bool = typer.Option(
        False,
        "--cleanup-failed",
        help="Remove incomplete or failed installation of this agent type before retrying",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help=(
            "Force reinstall, even if same version installed. "
            "WARNING: rotates gateway tokens and device credentials."
        ),
    ),
) -> None:
    """Install an agent on a host.

    Without flags, prompts for claw and host selection interactively.
    With --type and --host flags, runs directly (per D-01 hybrid invocation).
    """
    # Step 1: Get agent type (prompt if not provided per D-01)
    selected_claw = claw or _select_claw()

    # Step 2: Validate agent type exists
    try:
        get_claw_info(selected_claw)  # Validates claw exists
    except ManifestNotFoundError:
        console.print(
            f"[red]Error:[/red] Agent type '{escape(selected_claw)}' not found in registry"
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

    if compat["matched_entry"] is None:
        console.print(
            f"[red]Error:[/red] Cannot determine compatible version for "
            f"'{selected_claw}': host hardware information is not available.\n"
            f"Run 'clawctl host create' with SSH access first to gather "
            f"hardware facts, then retry the install."
        )
        raise typer.Exit(code=1)

    matched_version = compat["matched_entry"]["version"]
    display_host = host_record.get("alias") or host_record["hostname"]

    # Step 4b: --force triggers gateway-token + device-credential rotation, which
    # silently breaks every existing integration that pinned the old credentials.
    # Require explicit confirmation (bypassable with --yes for automation).
    if force and not yes:
        console.print(
            "[yellow]Warning:[/yellow] --force will rotate gateway tokens and "
            "device credentials. Existing integrations will break until "
            "reconfigured."
        )
        if not typer.confirm("Confirm force reinstall?", default=False):
            console.print("Installation cancelled.")
            raise typer.Exit(code=0)

    # Step 5: Show confirmation summary (per D-03)
    summary = Panel(
        f"[bold]Agent Type:[/bold] {selected_claw}\n"
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

    resume = False

    try:
        result = _run_installation_with_progress(
            selected_claw, selected_host, name, cleanup_failed, resume, force
        )

        # Success
        if result.get("skipped"):
            console.print(
                f"[green]Success![/green] {selected_claw} v{result['version']} already installed on {display_host} (skipped)"
            )
        else:
            console.print(
                f"[green]Success![/green] {selected_claw} v{result['version']} installed as '{name}' on {display_host}"
                if name
                else f"[green]Success![/green] {selected_claw} v{result['version']} installed on {display_host}"
            )

    except IncompleteInstallationError as e:
        if cleanup_failed:
            agent_name = e.details.get("agent_name") or e.claw_name
            console.print(
                f"[yellow]Removing incomplete installation of {selected_claw} "
                f"({agent_name}) from {display_host} and retrying...[/yellow]"
            )
            try:
                result = _run_installation_with_progress(
                    selected_claw, selected_host, None, True, False, force
                )
                if result.get("skipped"):
                    console.print(
                        f"[green]Success![/green] {selected_claw} v{result['version']} already installed on {display_host} (skipped)"
                    )
                else:
                    console.print(
                        f"[green]Success![/green] {selected_claw} v{result['version']} installed on {display_host}"
                    )
            except InstallationError as retry_error:
                console.print(f"[red]Installation failed:[/red] {retry_error}")
                raise typer.Exit(code=1)
        else:
            # Handle incomplete installation with interactive prompt
            cleanup_failed, resume = _handle_incomplete_installation(e)
            # Retry installation with user's choice
            try:
                result = _run_installation_with_progress(
                    selected_claw, selected_host, name, cleanup_failed, resume, force
                )

                # Success
                if result.get("skipped"):
                    console.print(
                        f"[green]Success![/green] {selected_claw} v{result['version']} already installed on {display_host} (skipped)"
                    )
                else:
                    console.print(
                        f"[green]Success![/green] {selected_claw} v{result['version']} installed as '{name}' on {display_host}"
                        if name
                        else f"[green]Success![/green] {selected_claw} v{result['version']} installed on {display_host}"
                    )

            except InstallationError as retry_error:
                console.print(f"[red]Installation failed:[/red] {retry_error}")
                raise typer.Exit(code=1)

    except InstallationError as e:
        # Error display per D-10
        console.print(f"[red]Installation failed:[/red] {e}")
        raise typer.Exit(code=1)

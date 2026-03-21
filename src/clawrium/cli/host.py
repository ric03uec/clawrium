"""Host management commands for Clawrium."""

from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from clawrium.core.hosts import add_host, get_host, load_hosts, remove_host, save_hosts
from clawrium.core.ssh_connection import get_ssh_config, test_ssh_connection
from clawrium.core.hardware import gather_hardware

__all__ = ["host_app"]

console = Console()

host_app = typer.Typer(
    name="host",
    help="Manage hosts in your fleet",
    no_args_is_help=True,
)


@host_app.command()
def add(
    hostname: str = typer.Argument(..., help="Host IP address or hostname"),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="SSH port (default: 22)"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="SSH user (default: xclm)"),
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="Friendly name for this host"),
    key_path: Optional[str] = typer.Option(None, "--key", "-k", help="Path to SSH private key"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
) -> None:
    """Add a new host to the fleet.

    Tests SSH connection before saving. Detects hardware capabilities
    automatically after successful connection.
    """
    # Check for duplicate
    existing = get_host(hostname)
    if existing:
        console.print(f"[red]Error:[/red] Host '{hostname}' already exists")
        raise typer.Exit(code=1)

    if alias:
        existing_alias = get_host(alias)
        if existing_alias:
            console.print(f"[red]Error:[/red] Alias '{alias}' already in use")
            raise typer.Exit(code=1)

    # Load SSH config and merge with provided values (per D-09)
    ssh_config = get_ssh_config(hostname)

    # CLI flags override SSH config (per D-07 hybrid input)
    # Use 'is not None' to allow explicit --port 0 or --user ''
    final_port = port if port is not None else int(ssh_config.get('port', 22))
    final_user = user if user is not None else ssh_config.get('user', 'xclm')  # Default per D-11
    final_key = key_path or (ssh_config.get('identityfile', [None])[0] if 'identityfile' in ssh_config else None)

    console.print(f"Testing connection to {hostname}:{final_port} as {final_user}...")

    # Test connection (per D-10)
    success, message = test_ssh_connection(
        hostname=hostname,
        port=final_port,
        user=final_user,
        key_filename=final_key
    )

    if not success:
        console.print(f"[red]Connection failed:[/red] {message}")
        raise typer.Exit(code=1)

    console.print(f"[green]Connection successful![/green]")

    # Detect hardware (per D-06)
    console.print("Detecting hardware capabilities...")
    try:
        hardware = gather_hardware(
            hostname=hostname,
            user=final_user,
            port=final_port,
            ssh_key=final_key
        )
        console.print(f"[green]Hardware detected:[/green] {hardware['architecture']}, "
                     f"{hardware['processor_cores']} cores, "
                     f"{hardware['memtotal_mb']}MB RAM")
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Could not detect hardware: {e}")
        hardware = {}

    # Build host record (per D-04)
    now = datetime.now(timezone.utc).isoformat()
    host = {
        "hostname": hostname,
        "port": final_port,
        "user": final_user,
        "auth_method": "key",
        "alias": alias,
        "key_path": final_key,
        "hardware": hardware,
        "metadata": {
            "added_at": now,
            "last_seen": now,
            "tags": [t.strip() for t in tags.split(",")] if tags else []
        }
    }

    add_host(host)
    console.print(f"[green]Host '{alias or hostname}' added successfully![/green]")


@host_app.command(name="list")
def list_hosts() -> None:
    """List all registered hosts."""
    hosts = load_hosts()

    if not hosts:
        console.print("No hosts registered. Use 'clm host add' to add a host.")
        return

    table = Table(title="Registered Hosts")

    table.add_column("Alias", style="cyan")
    table.add_column("Host", style="white")
    table.add_column("Architecture", style="yellow")
    table.add_column("Cores", justify="right")
    table.add_column("Memory (GB)", justify="right")
    table.add_column("Tags", style="dim")

    for host in hosts:
        hw = host.get('hardware', {})
        meta = host.get('metadata', {})

        # Format memory as GB with 1 decimal
        mem_gb = round(hw.get('memtotal_mb', 0) / 1024, 1) if hw.get('memtotal_mb') else '-'

        table.add_row(
            host.get('alias') or '-',
            host['hostname'],
            hw.get('architecture', '?'),
            str(hw.get('processor_cores', '?')),
            str(mem_gb),
            ', '.join(meta.get('tags', [])) or '-'
        )

    console.print(table)


@host_app.command()
def remove(
    hostname: str = typer.Argument(..., help="Host hostname or alias to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove a host from the fleet.

    Prompts for confirmation unless --force is specified.
    """
    # Find host by hostname or alias
    host = get_host(hostname)
    if not host:
        console.print(f"[red]Error:[/red] Host '{hostname}' not found")
        raise typer.Exit(code=1)

    display_name = host.get('alias') or host['hostname']

    # Confirmation (per D-18)
    if not force:
        confirmed = typer.confirm(f"Remove host '{display_name}'? This cannot be undone.")
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)  # Clean exit on user cancel, not error

    # Remove by actual hostname
    success = remove_host(host['hostname'])
    if success:
        console.print(f"[green]Host '{display_name}' removed successfully.[/green]")
    else:
        console.print(f"[red]Error:[/red] Failed to remove host")
        raise typer.Exit(code=1)


@host_app.command()
def status(
    hostname: str = typer.Argument(..., help="Host hostname or alias to check"),
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Re-detect hardware capabilities"),
) -> None:
    """Check status of a host.

    Shows connection status, hostname verification, and last seen time.
    Use --refresh to update hardware information.
    """
    # Find host
    host = get_host(hostname)
    if not host:
        console.print(f"[red]Error:[/red] Host '{hostname}' not found")
        raise typer.Exit(code=1)

    display_name = host.get('alias') or host['hostname']
    console.print(f"Checking status of '{display_name}'...")

    # Test connection
    success, message = test_ssh_connection(
        hostname=host['hostname'],
        port=host.get('port', 22),
        user=host.get('user', 'xclm'),
        key_filename=host.get('key_path')
    )

    # Display status table
    table = Table(title=f"Host Status: {display_name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    if success:
        table.add_row("Connection", "[green]Connected[/green]")
    else:
        table.add_row("Connection", f"[red]Disconnected[/red] ({message})")

    table.add_row("Hostname", host['hostname'])
    table.add_row("Port", str(host.get('port', 22)))
    table.add_row("User", host.get('user', 'xclm'))

    meta = host.get('metadata', {})
    table.add_row("Added", meta.get('added_at', 'Unknown'))
    table.add_row("Last Seen", meta.get('last_seen', 'Unknown'))
    table.add_row("Tags", ', '.join(meta.get('tags', [])) or '-')

    hw = host.get('hardware', {})
    if hw:
        table.add_row("Architecture", hw.get('architecture', '?'))
        table.add_row("CPU Cores", str(hw.get('processor_cores', '?')))
        table.add_row("Memory", f"{round(hw.get('memtotal_mb', 0) / 1024, 1)} GB")
        gpu = hw.get('gpu', {})
        if gpu.get('present'):
            table.add_row("GPU", f"{gpu.get('vendor', 'unknown').upper()}")
        else:
            table.add_row("GPU", "None detected")

    console.print(table)

    # Refresh hardware if requested (per D-06)
    if refresh and success:
        console.print("\nRefreshing hardware information...")
        try:
            new_hardware = gather_hardware(
                hostname=host['hostname'],
                user=host.get('user', 'xclm'),
                port=host.get('port', 22),
                ssh_key=host.get('key_path')
            )

            # Update host record
            hosts = load_hosts()
            for h in hosts:
                if h.get('hostname') == host['hostname']:
                    h['hardware'] = new_hardware
                    h['metadata']['last_seen'] = datetime.now(timezone.utc).isoformat()
                    break

            save_hosts(hosts)

            console.print(f"[green]Hardware information updated.[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Could not refresh hardware: {e}")
    elif refresh and not success:
        console.print("[yellow]Cannot refresh hardware: host is not connected[/yellow]")

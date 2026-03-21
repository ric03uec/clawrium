"""Host management commands for Clawrium."""

import getpass
import os
from datetime import datetime, timezone
from typing import Optional

import paramiko
import typer
from rich.console import Console
from rich.table import Table

from clawrium.core.hosts import add_host, get_host, load_hosts, remove_host, save_hosts, HostsFileCorruptedError
from clawrium.core.keys import (
    generate_host_keypair,
    get_host_private_key,
    get_host_public_key,
    read_public_key,
    delete_host_keys,
)
from clawrium.core.ssh_connection import (
    get_ssh_config,
    test_ssh_connection,
    accept_host_key,
    HostKeyVerificationRequired,
)
from clawrium.core.hardware import gather_hardware

__all__ = ["host_app"]

console = Console()

host_app = typer.Typer(
    name="host",
    help="Manage hosts in your fleet",
    no_args_is_help=True,
)


@host_app.command()
def init(
    hostname: str = typer.Argument(..., help="Host IP or hostname to initialize"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="SSH user for initial connection (default: current user)"),
) -> None:
    """Initialize a host for Clawrium management.

    Generates a per-host SSH keypair and attempts to configure the xclm
    management user on the remote host. If SSH access fails, displays
    manual setup commands.
    """
    # Step 1: Generate keypair if not exists
    private_key = get_host_private_key(hostname)
    if private_key:
        console.print(f"Using existing keypair for '{hostname}'")
    else:
        console.print(f"Generating SSH keypair for '{hostname}'...")
        private_key_path, public_key_path = generate_host_keypair(hostname)
        console.print(f"[green]Keypair created:[/green] {public_key_path}")
        private_key = private_key_path

    # Read the public key for display/setup
    public_key_content = read_public_key(hostname)

    # Step 2: Determine connection user
    connection_user = user or getpass.getuser()

    # Step 3: Try to connect to host
    console.print(f"\nAttempting connection to {hostname} as {connection_user}...")

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    auto_setup_success = False
    try:
        # Try to connect with current user's default keys
        client.connect(
            hostname=hostname,
            username=connection_user,
            timeout=10
        )

        transport = client.get_transport()
        if transport and transport.is_active():
            console.print("[green]Connection successful![/green]")
            console.print("Setting up xclm management user...")

            # Execute setup commands
            setup_commands = [
                "sudo useradd -m -s /bin/bash xclm 2>/dev/null || true",
                'echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm',
                "sudo chmod 440 /etc/sudoers.d/xclm",
                "sudo mkdir -p /home/xclm/.ssh",
                "sudo chmod 700 /home/xclm/.ssh",
                f'echo "{public_key_content}" | sudo tee /home/xclm/.ssh/authorized_keys',
                "sudo chmod 600 /home/xclm/.ssh/authorized_keys",
                "sudo chown -R xclm:xclm /home/xclm/.ssh",
            ]

            for cmd in setup_commands:
                stdin, stdout, stderr = client.exec_command(cmd)
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0 and "useradd" not in cmd:
                    error = stderr.read().decode().strip()
                    console.print(f"[yellow]Warning:[/yellow] Command failed: {cmd}")
                    if error:
                        console.print(f"  {error}")

            # Verify xclm connection works
            console.print("\nVerifying xclm access...")
            success, message = test_ssh_connection(
                hostname=hostname,
                port=22,
                user="xclm",
                key_filename=str(private_key)
            )

            if success:
                console.print("[green]xclm user configured successfully![/green]")
                console.print(f"\nNext step: [cyan]clm host add {hostname}[/cyan]")
                auto_setup_success = True
            else:
                console.print(f"[yellow]Warning:[/yellow] xclm verification failed: {message}")
                console.print("You may need to complete setup manually.")

    except HostKeyVerificationRequired as e:
        console.print(f"\n[yellow]Unknown host key for {e.hostname}[/yellow]")
        console.print(f"  Key type: {e.key_type}")
        console.print(f"  Fingerprint: {e.fingerprint}")

        if typer.confirm("\nAccept this host key and retry?"):
            accept_host_key(hostname, 22, expected_fingerprint=e.fingerprint)
            console.print("Host key saved. Please run 'clm host init' again.")
        else:
            console.print("Connection cancelled.")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[yellow]Could not connect:[/yellow] {e}")
    finally:
        client.close()

    # Step 4: If auto-setup failed, show manual commands
    if not auto_setup_success:
        console.print("\n[yellow]Manual setup required.[/yellow]")
        console.print("\nRun these commands on the target host:\n")
        console.print("[dim]# Create xclm user[/dim]")
        console.print("sudo useradd -m -s /bin/bash xclm")
        console.print("")
        console.print("[dim]# Grant passwordless sudo[/dim]")
        console.print('echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm')
        console.print("sudo chmod 440 /etc/sudoers.d/xclm")
        console.print("")
        console.print("[dim]# Setup SSH access[/dim]")
        console.print("sudo mkdir -p /home/xclm/.ssh")
        console.print("sudo chmod 700 /home/xclm/.ssh")
        console.print(f'echo "{public_key_content}" | sudo tee /home/xclm/.ssh/authorized_keys')
        console.print("sudo chmod 600 /home/xclm/.ssh/authorized_keys")
        console.print("sudo chown -R xclm:xclm /home/xclm/.ssh")
        console.print("")
        console.print(f"Then run: [cyan]clm host add {hostname}[/cyan]")


@host_app.command()
def add(
    hostname: str = typer.Argument(..., help="Host IP address or hostname"),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="SSH port (default: 22)"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="SSH user (default: xclm)"),
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="Friendly name for this host"),
    key_path: Optional[str] = typer.Option(None, "--key", "-k", help="Path to SSH private key (used for this connection only; add to ~/.ssh/config for persistence)"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
) -> None:
    """Add a new host to the fleet.

    Tests SSH connection before saving. Detects hardware capabilities
    automatically after successful connection.
    """
    # Check for duplicate
    try:
        existing = get_host(hostname)
        if existing:
            console.print(f"[red]Error:[/red] Host '{hostname}' already exists")
            raise typer.Exit(code=1)

        if alias:
            existing_alias = get_host(alias)
            if existing_alias:
                console.print(f"[red]Error:[/red] Alias '{alias}' already in use")
                raise typer.Exit(code=1)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Load SSH config and merge with provided values (per D-09)
    ssh_config = get_ssh_config(hostname)

    # CLI flags override SSH config (per D-07 hybrid input)
    # Use 'is not None' to allow explicit --port 0 or --user ''
    final_hostname = ssh_config.get('hostname', hostname)  # Resolve HostName from SSH config
    final_port = port if port is not None else int(ssh_config.get('port', 22))
    final_user = user if user is not None else ssh_config.get('user', 'xclm')  # Default per D-11
    final_key = key_path if key_path is not None else (ssh_config.get('identityfile', [None])[0] if 'identityfile' in ssh_config else None)

    console.print(f"Testing connection to {final_hostname}:{final_port} as {final_user}...")

    # Test connection (per D-10)
    try:
        result = test_ssh_connection(
            hostname=final_hostname,
            port=final_port,
            user=final_user,
            key_filename=final_key
        )
        success, message = result
    except HostKeyVerificationRequired as e:
        # TOFU: Show fingerprint and ask user to verify
        console.print(f"\n[yellow]Unknown host key for {e.hostname}[/yellow]")
        console.print(f"  Key type: {e.key_type}")
        console.print(f"  Fingerprint: {e.fingerprint}")
        console.print("\n[yellow]Warning:[/yellow] Verify this fingerprint matches the host's actual key.")
        console.print("If this is your first connection to this host, this is expected.")

        if not typer.confirm("\nAccept this host key and continue?"):
            console.print("Connection cancelled.")
            raise typer.Exit(code=1)

        # Accept the host key with fingerprint verification
        if not accept_host_key(final_hostname, final_port, expected_fingerprint=e.fingerprint):
            console.print("[red]Error:[/red] Failed to save host key (fingerprint may have changed)")
            raise typer.Exit(code=1)

        # Retry connection
        result = test_ssh_connection(
            hostname=final_hostname,
            port=final_port,
            user=final_user,
            key_filename=final_key
        )
        success, message = result

    if not success:
        console.print(f"[red]Connection failed:[/red] {message}")
        raise typer.Exit(code=1)

    console.print("[green]Connection successful![/green]")

    # Detect hardware (per D-06)
    console.print("Detecting hardware capabilities...")
    try:
        hardware = gather_hardware(
            hostname=final_hostname,
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
    # Store resolved hostname for portability; keep original input as ssh_config_host
    # for SSH config lookup. Do not store key_path for security - look up from SSH config.
    now = datetime.now(timezone.utc).isoformat()

    # Determine display alias
    display_alias = alias or (hostname if hostname != final_hostname else None)

    host = {
        "hostname": final_hostname,  # Resolved hostname for direct connections
        "port": final_port,
        "user": final_user,
        "auth_method": "key",
        "hardware": hardware,
        "metadata": {
            "added_at": now,
            "last_seen": now,
            "tags": [t.strip() for t in tags.split(",")] if tags else []
        }
    }
    # Only add optional fields if they have values (avoid null pollution)
    if hostname != final_hostname:
        host["ssh_config_host"] = hostname
    if display_alias:
        host["alias"] = display_alias

    add_host(host)
    console.print(f"[green]Host '{display_alias or hostname}' added successfully![/green]")

    # Warn if --key was used but no SSH config entry exists for future lookups
    if key_path and 'identityfile' not in ssh_config:
        console.print(f"[yellow]Note:[/yellow] Key path '{key_path}' was used for this connection but is not stored.")
        console.print(f"  Add to ~/.ssh/config for persistence: IdentityFile {key_path}")


@host_app.command(name="list")
def list_hosts() -> None:
    """List all registered hosts."""
    try:
        hosts = load_hosts()
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

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
    try:
        host = get_host(hostname)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

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
    try:
        host = get_host(hostname)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not host:
        console.print(f"[red]Error:[/red] Host '{hostname}' not found")
        raise typer.Exit(code=1)

    display_name = host.get('alias') or host['hostname']
    console.print(f"Checking status of '{display_name}'...")

    # Get SSH config for key lookup (key_path not stored for security)
    ssh_config_host = host.get('ssh_config_host') or host['hostname']
    ssh_config = get_ssh_config(ssh_config_host)
    ssh_key = ssh_config.get('identityfile', [None])[0] if 'identityfile' in ssh_config else None

    # Test connection
    try:
        result = test_ssh_connection(
            hostname=host['hostname'],
            port=host.get('port', 22),
            user=host.get('user', 'xclm'),
            key_filename=ssh_key
        )
        success, message = result
    except HostKeyVerificationRequired as e:
        success = False
        message = "Host key verification required"
        console.print(f"[yellow]Note:[/yellow] Run 'clm host remove {hostname} && clm host add {host['hostname']}' to re-verify the host key.")

    # Refresh hardware BEFORE building table if requested (per D-06)
    hw = host.get('hardware', {})
    if refresh and success:
        console.print("Refreshing hardware information...")
        try:
            hw = gather_hardware(
                hostname=host['hostname'],
                user=host.get('user', 'xclm'),
                port=host.get('port', 22),
                ssh_key=ssh_key
            )

            # Update host record - separate error handling
            try:
                hosts = load_hosts()
                for h in hosts:
                    if h.get('hostname') == host['hostname']:
                        h['hardware'] = hw
                        h['metadata']['last_seen'] = datetime.now(timezone.utc).isoformat()
                        break
                save_hosts(hosts)
                console.print("[green]Hardware information updated.[/green]\n")
            except Exception as e:
                console.print(f"[red]Error saving host data:[/red] {e}")
                raise typer.Exit(code=1)
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Could not refresh hardware: {e}\n")
    elif refresh and not success:
        console.print("[yellow]Cannot refresh hardware: host is not connected[/yellow]\n")

    # Display status table
    table = Table(title=f"Host Status: {display_name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    if success:
        table.add_row("Connection", "[green]Connected[/green]")
    else:
        table.add_row("Connection", f"[red]Disconnected[/red] ({message})")

    table.add_row("Hostname", host['hostname'])
    if host.get('ssh_config_host'):
        table.add_row("SSH Config", host['ssh_config_host'])
    table.add_row("Port", str(host.get('port', 22)))
    table.add_row("User", host.get('user', 'xclm'))

    meta = host.get('metadata', {})
    table.add_row("Added", meta.get('added_at', 'Unknown'))
    table.add_row("Last Seen", meta.get('last_seen', 'Unknown'))
    table.add_row("Tags", ', '.join(meta.get('tags', [])) or '-')

    if hw:
        table.add_row("Architecture", hw.get('architecture', '?'))
        table.add_row("CPU Cores", str(hw.get('processor_cores', '?')))
        table.add_row("Memory", f"{round(hw.get('memtotal_mb', 0) / 1024, 1)} GB")
        gpu = hw.get('gpu', {})
        if gpu.get('present'):
            table.add_row("GPU", gpu.get('vendor') or 'Unknown')
        else:
            table.add_row("GPU", "None detected")

    console.print(table)

    # Exit 1 if host is disconnected (for scripting)
    if not success:
        raise typer.Exit(code=1)

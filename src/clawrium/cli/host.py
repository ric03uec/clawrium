"""Host management commands for Clawrium."""

import getpass
import shlex
from datetime import datetime, timezone
from typing import Optional

import paramiko
import typer
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.table import Table

from clawrium.core.hosts import (
    add_host,
    alias_exists,
    get_host,
    get_host_by_key_id,
    load_hosts,
    remove_host,
    update_host,
    add_address_to_host,
    remove_address_from_host,
    set_primary_address,
    get_host_addresses,
    HostsFileCorruptedError,
    DuplicateHostError,
    AddressError,
)
from clawrium.core.keys import (
    generate_host_keypair,
    get_host_private_key,
    read_public_key,
    delete_host_keys,
    InvalidKeyIdError,
)
from clawrium.core.ssh_connection import (
    get_ssh_config,
    test_ssh_connection,
    accept_host_key,
    HostKeyVerificationRequired,
)
from clawrium.core.hardware import gather_hardware
from clawrium.core.reset import enumerate_targets, execute_reset

__all__ = ["host_app"]

console = Console()

host_app = typer.Typer(
    name="host",
    help="Manage hosts in your fleet (infrastructure management)",
    no_args_is_help=True,
)

address_app = typer.Typer(
    name="address",
    help="Manage multiple addresses for a host",
    no_args_is_help=True,
)
host_app.add_typer(address_app, name="address")


@host_app.command()
def init(
    hostname: str = typer.Argument(..., help="Host IP or hostname to initialize"),
    user: Optional[str] = typer.Option(
        None,
        "--user",
        "-u",
        help="SSH user for initial connection (default: current user)",
    ),
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
    # Use RejectPolicy - we'll handle unknown hosts via HostKeyVerificationRequired
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    auto_setup_success = False
    try:
        # Try to connect with current user's default keys
        client.connect(hostname=hostname, username=connection_user, timeout=10)

        transport = client.get_transport()
        if transport and transport.is_active():
            console.print("[green]Connection successful![/green]")
            console.print("Setting up xclm management user...")

            # Execute setup commands (no shell injection - public key written via stdin)
            setup_commands = [
                ("sudo useradd -m -s /bin/bash xclm 2>/dev/null || true", None),
                (
                    'echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm',
                    None,
                ),
                ("sudo chmod 440 /etc/sudoers.d/xclm", None),
                ("sudo mkdir -p /home/xclm/.ssh", None),
                ("sudo chmod 700 /home/xclm/.ssh", None),
                (
                    "sudo tee /home/xclm/.ssh/authorized_keys",
                    public_key_content,
                ),  # Write via stdin
                ("sudo chmod 600 /home/xclm/.ssh/authorized_keys", None),
                ("sudo chown -R xclm:xclm /home/xclm/.ssh", None),
            ]

            for cmd, stdin_data in setup_commands:
                stdin, stdout, stderr = client.exec_command(cmd)
                if stdin_data:
                    stdin.write(stdin_data + "\n")
                    stdin.channel.shutdown_write()
                # Drain both stdout and stderr before checking exit status to prevent buffer hangs (W4 fix)
                stdout.read()
                stderr_output = stderr.read().decode().strip()
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0 and "useradd" not in cmd:
                    console.print(
                        f"[yellow]Warning:[/yellow] Setup step failed (exit {exit_status})"
                    )
                    if stderr_output:
                        # Escape stderr to prevent Rich markup injection (W2 fix)
                        console.print(f"  {rich_escape(stderr_output)}")

            # Verify xclm connection works
            console.print("\nVerifying xclm access...")
            success, message = test_ssh_connection(
                hostname=hostname, port=22, user="xclm", key_filename=str(private_key)
            )

            if success:
                console.print("[green]xclm user configured successfully![/green]")
                console.print(
                    f"\nNext step: [cyan]clawctl host create {hostname}[/cyan]"
                )
                auto_setup_success = True
            else:
                console.print(
                    f"[yellow]Warning:[/yellow] xclm verification failed: {message}"
                )
                console.print("You may need to complete setup manually.")

    except HostKeyVerificationRequired as e:
        console.print(f"\n[yellow]Unknown host key for {e.hostname}[/yellow]")
        console.print(f"  Key type: {e.key_type}")
        console.print(f"  Fingerprint: {e.fingerprint}")
        console.print(
            "\n[yellow]Warning:[/yellow] Verify this fingerprint matches the host's actual key."
        )

        if typer.confirm("\nAccept this host key and retry?"):
            accept_host_key(hostname, 22, expected_fingerprint=e.fingerprint)
            console.print(
                "Host key saved. Please run 'clawctl host create --bootstrap' again."
            )
        else:
            console.print("Connection cancelled.")
        raise typer.Exit(code=1)
    except paramiko.SSHException as e:
        # Handle unknown host key from RejectPolicy
        if "not found in known_hosts" in str(e) or "Server" in str(e):
            console.print(f"\n[yellow]Unknown host key for {hostname}[/yellow]")
            console.print(
                "Run 'ssh-keyscan' or connect manually first to add the host key."
            )
        else:
            console.print(f"[yellow]SSH error:[/yellow] {e}")
    except paramiko.AuthenticationException as e:
        console.print(f"[yellow]Authentication failed:[/yellow] {e}")
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
        console.print(
            'echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm'
        )
        console.print("sudo chmod 440 /etc/sudoers.d/xclm")
        console.print("")
        console.print("[dim]# Setup SSH access[/dim]")
        console.print("sudo mkdir -p /home/xclm/.ssh")
        console.print("sudo chmod 700 /home/xclm/.ssh")
        # Shell-escape public key to prevent injection and escape Rich markup
        # Use soft_wrap=False to keep command on one line for easy copy-paste
        escaped_key = shlex.quote(public_key_content) if public_key_content else "''"
        console.print(
            f"echo {rich_escape(escaped_key)} | sudo tee /home/xclm/.ssh/authorized_keys",
            soft_wrap=False,
        )
        console.print("sudo chmod 600 /home/xclm/.ssh/authorized_keys")
        console.print("sudo chown -R xclm:xclm /home/xclm/.ssh")
        console.print("")
        console.print(f"Then run: [cyan]clawctl host create {hostname}[/cyan]")
        # Exit non-zero so scripts can detect failure (B2 fix)
        raise typer.Exit(code=1)


@host_app.command()
def add(
    hostname: str = typer.Argument(..., help="Host IP address or hostname"),
    port: Optional[int] = typer.Option(
        None, "--port", "-p", help="SSH port (default: 22)"
    ),
    user: Optional[str] = typer.Option(
        None, "--user", "-u", help="SSH user (default: xclm)"
    ),
    alias: Optional[str] = typer.Option(
        None, "--alias", "-a", help="Friendly name for this host"
    ),
    tags: Optional[str] = typer.Option(
        None, "--tags", "-t", help="Comma-separated tags"
    ),
) -> None:
    """Add a new host to the fleet.

    Requires keypair to exist (run 'clawctl host create --bootstrap' first).
    Tests SSH connection before saving. Detects hardware capabilities
    automatically after successful connection.
    """
    # Determine key_id: Try hostname first, fall back to alias
    # This ensures `clawctl host create --bootstrap 192.168.1.10` + `clawctl host create 192.168.1.10 --alias mybox` works
    from clawrium.core.keys import validate_key_id

    # Try hostname first (most common case: init and add use same identifier)
    host_key = get_host_private_key(hostname)
    key_lookup_id = hostname

    # Fall back to alias if hostname key doesn't exist and alias is provided
    if not host_key and alias:
        host_key = get_host_private_key(alias)
        key_lookup_id = alias

    # Validate the resolved key_id to prevent path traversal
    try:
        validate_key_id(key_lookup_id)
    except InvalidKeyIdError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Check for per-host keypair (enforces init-first workflow)
    if not host_key:
        console.print(f"[red]Error:[/red] No keypair found for '{hostname}'")
        if alias:
            console.print(f"  Also checked alias '{alias}'")
        console.print(
            f"Run 'clawctl host create --bootstrap {hostname}' first to generate keys"
        )
        raise typer.Exit(code=1)

    # Check for duplicate hostname, alias, or key_id
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

        # Check key_id uniqueness to prevent cross-host key collision
        existing_key_id = get_host_by_key_id(key_lookup_id)
        if existing_key_id:
            console.print(
                f"[red]Error:[/red] key_id '{key_lookup_id}' already in use by host '{existing_key_id.get('hostname')}'"
            )
            raise typer.Exit(code=1)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Load SSH config for hostname resolution
    ssh_config = get_ssh_config(hostname)

    # CLI flags override defaults
    final_hostname = ssh_config.get(
        "hostname", hostname
    )  # Resolve HostName from SSH config
    final_port = port if port is not None else int(ssh_config.get("port", 22))
    final_user = user if user is not None else "xclm"  # Always default to xclm
    final_key = str(host_key)  # Use per-host key

    console.print(
        f"Testing connection to {final_hostname}:{final_port} as {final_user}..."
    )

    # Test connection (per D-10)
    try:
        result = test_ssh_connection(
            hostname=final_hostname,
            port=final_port,
            user=final_user,
            key_filename=final_key,
        )
        success, message = result
    except HostKeyVerificationRequired as e:
        # TOFU: Show fingerprint and ask user to verify
        console.print(f"\n[yellow]Unknown host key for {e.hostname}[/yellow]")
        console.print(f"  Key type: {e.key_type}")
        console.print(f"  Fingerprint: {e.fingerprint}")
        console.print(
            "\n[yellow]Warning:[/yellow] Verify this fingerprint matches the host's actual key."
        )
        console.print(
            "If this is your first connection to this host, this is expected."
        )

        if not typer.confirm("\nAccept this host key and continue?"):
            console.print("Connection cancelled.")
            raise typer.Exit(code=1)

        # Accept the host key with fingerprint verification
        if not accept_host_key(
            final_hostname, final_port, expected_fingerprint=e.fingerprint
        ):
            console.print(
                "[red]Error:[/red] Failed to save host key (fingerprint may have changed)"
            )
            raise typer.Exit(code=1)

        # Retry connection
        result = test_ssh_connection(
            hostname=final_hostname,
            port=final_port,
            user=final_user,
            key_filename=final_key,
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
            hostname=final_hostname, user=final_user, port=final_port, ssh_key=final_key
        )
        console.print(
            f"[green]Hardware detected:[/green] {hardware['architecture']}, "
            f"{hardware['processor_cores']} cores, "
            f"{hardware['memtotal_mb']}MB RAM"
        )
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
        "key_id": key_lookup_id,  # Key storage identifier (alias, hostname, or generated name)
        "port": final_port,
        "user": final_user,
        "auth_method": "key",
        "hardware": hardware,
        "metadata": {
            "added_at": now,
            "last_seen": now,
            "tags": [t.strip() for t in tags.split(",")] if tags else [],
        },
    }
    # Only add optional fields if they have values (avoid null pollution)
    if hostname != final_hostname:
        host["ssh_config_host"] = hostname
    if display_alias:
        host["alias"] = display_alias

    # B3: Handle DuplicateHostError from race condition
    try:
        add_host(host)
    except DuplicateHostError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    console.print(
        f"[green]Host '{display_alias or hostname}' added successfully![/green]"
    )


@host_app.command(name="list")
def list_hosts() -> None:
    """List all registered hosts."""
    try:
        hosts = load_hosts()
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not hosts:
        console.print("No hosts registered. Use 'clawctl host create' to add a host.")
        return

    table = Table(title="Registered Hosts")

    table.add_column("Alias", style="cyan")
    table.add_column("Host", style="white")
    table.add_column("Architecture", style="yellow")
    table.add_column("Cores", justify="right")
    table.add_column("Memory (GB)", justify="right")
    table.add_column("Tags", style="dim")

    for host in hosts:
        hw = host.get("hardware", {})
        meta = host.get("metadata", {})

        # Format memory as GB with 1 decimal
        mem_gb = (
            round(hw.get("memtotal_mb", 0) / 1024, 1) if hw.get("memtotal_mb") else "-"
        )

        # Show [+N] indicator for additional addresses
        addresses = host.get("addresses", [])
        additional_count = len(addresses) - 1 if len(addresses) > 1 else 0
        hostname_display = host["hostname"]
        if additional_count > 0:
            hostname_display = f"{hostname_display} [+{additional_count}]"

        table.add_row(
            host.get("alias") or "-",
            hostname_display,
            hw.get("architecture", "?"),
            str(hw.get("processor_cores", "?")),
            str(mem_gb),
            ", ".join(meta.get("tags", [])) or "-",
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

    display_name = host.get("alias") or host["hostname"]

    # Confirmation (per D-18)
    if not force:
        confirmed = typer.confirm(
            f"Remove host '{display_name}'? This cannot be undone."
        )
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)  # Clean exit on user cancel, not error

    # Remove by actual hostname
    success = remove_host(host["hostname"])
    if success:
        # Also delete per-host keys using key_id
        key_id = host.get("key_id") or host["hostname"]  # Fallback for old records
        keys_deleted = delete_host_keys(key_id)
        console.print(f"[green]Host '{display_name}' removed successfully.[/green]")
        if keys_deleted:
            console.print(f"[dim]Keypair for '{key_id}' deleted.[/dim]")
    else:
        console.print("[red]Error:[/red] Failed to remove host")
        raise typer.Exit(code=1)


@host_app.command(name="alias")
def alias_cmd(
    host: str = typer.Argument(..., help="Host hostname or alias"),
    set_alias: str = typer.Option(..., "--set", "-s", help="New alias for the host"),
) -> None:
    """Update the alias for a host.

    Target can be specified by hostname or current alias.
    """
    # Find host by hostname or alias
    try:
        host_record = get_host(host)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not host_record:
        console.print(f"[red]Error:[/red] Host '{host}' not found")
        raise typer.Exit(code=1)

    hostname = host_record["hostname"]
    old_alias = host_record.get("alias")

    # Validate new alias doesn't conflict
    exists, conflicting_host = alias_exists(set_alias, exclude_hostname=hostname)
    if exists:
        # Determine if conflict is with hostname or alias
        if conflicting_host == set_alias:
            console.print(
                f"[red]Error:[/red] Alias '{set_alias}' conflicts with existing hostname"
            )
        else:
            console.print(
                f"[red]Error:[/red] Alias '{set_alias}' already in use by host '{conflicting_host}'"
            )
        raise typer.Exit(code=1)

    # Update alias atomically
    def apply_alias_update(h: dict) -> dict:
        h["alias"] = set_alias
        return h

    if update_host(hostname, apply_alias_update):
        old_display = old_alias or hostname
        console.print(f"Host alias updated: {old_display} -> {set_alias}")
    else:
        console.print("[red]Error:[/red] Failed to update host alias")
        raise typer.Exit(code=1)


@host_app.command()
def tag(
    host: str = typer.Argument(..., help="Host hostname or alias"),
    add: Optional[list[str]] = typer.Option(None, "--add", help="Add tag(s)"),
    remove: Optional[list[str]] = typer.Option(None, "--remove", help="Remove tag(s)"),
    set_tags: Optional[str] = typer.Option(
        None, "--set", help="Replace all tags (comma-separated)"
    ),
) -> None:
    """Manage tags for a host.

    Add, remove, or replace tags. Use --set "" to clear all tags.
    """
    # Validate mutually exclusive options
    if set_tags is not None and (add or remove):
        console.print(
            "[red]Error:[/red] --set cannot be combined with --add or --remove"
        )
        raise typer.Exit(code=1)

    # Require at least one operation
    if set_tags is None and not add and not remove:
        console.print("[red]Error:[/red] Specify --add, --remove, or --set")
        raise typer.Exit(code=1)

    # Find host by hostname or alias
    try:
        host_record = get_host(host)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not host_record:
        console.print(f"[red]Error:[/red] Host '{host}' not found")
        raise typer.Exit(code=1)

    hostname = host_record["hostname"]
    display_name = host_record.get("alias") or hostname

    # Build updater function based on operation
    def apply_tag_update(h: dict) -> dict:
        if "metadata" not in h:
            h["metadata"] = {}
        current_tags = list(h["metadata"].get("tags", []))

        if set_tags is not None:
            # Replace all tags
            if set_tags == "":
                new_tags = []
            else:
                new_tags = [t.strip() for t in set_tags.split(",") if t.strip()]
        else:
            # Add tags (deduplicate)
            if add:
                for t in add:
                    tag_clean = t.strip()
                    if tag_clean and tag_clean not in current_tags:
                        current_tags.append(tag_clean)
            # Remove tags
            if remove:
                for t in remove:
                    tag_clean = t.strip()
                    if tag_clean in current_tags:
                        current_tags.remove(tag_clean)
            new_tags = current_tags

        h["metadata"]["tags"] = new_tags
        return h

    if update_host(hostname, apply_tag_update):
        # Reload to show final state
        updated_host = get_host(hostname)
        final_tags = (
            updated_host.get("metadata", {}).get("tags", []) if updated_host else []
        )

        if final_tags:
            console.print(f"Tags updated for '{display_name}': {', '.join(final_tags)}")
        else:
            console.print(f"Tags cleared for '{display_name}'")
    else:
        console.print("[red]Error:[/red] Failed to update host tags")
        raise typer.Exit(code=1)


@host_app.command()
def update(
    host: str = typer.Argument(..., help="Host hostname or alias"),
    alias: Optional[str] = typer.Option(
        None, "--alias", "-a", help="Update host alias"
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Set host description (pass empty string to clear)",
    ),
    add_tag: Optional[list[str]] = typer.Option(
        None, "--add-tag", help="Add tag(s) (repeatable)"
    ),
    remove_tag: Optional[list[str]] = typer.Option(
        None, "--remove-tag", help="Remove tag(s) (repeatable)"
    ),
    set_tags: Optional[str] = typer.Option(
        None, "--tags", help="Replace all tags (comma-separated; '' to clear)"
    ),
) -> None:
    """Update host metadata fields (alias, description, tags).

    Combine multiple fields in one call. Use --tags to replace all tags,
    or --add-tag/--remove-tag to modify incrementally.
    """
    # Require at least one field to update
    if (
        alias is None
        and description is None
        and not add_tag
        and not remove_tag
        and set_tags is None
    ):
        console.print(
            "[red]Error:[/red] Specify at least one field to update "
            "(--alias, --description, --add-tag, --remove-tag, or --tags)"
        )
        raise typer.Exit(code=1)

    # --tags is mutually exclusive with --add-tag/--remove-tag
    if set_tags is not None and (add_tag or remove_tag):
        console.print(
            "[red]Error:[/red] --tags cannot be combined with --add-tag or --remove-tag"
        )
        raise typer.Exit(code=1)

    # Validate alias is non-empty whitespace
    if alias is not None and not alias.strip():
        console.print("[red]Error:[/red] --alias cannot be empty")
        raise typer.Exit(code=1)

    # Find host by hostname or alias
    try:
        host_record = get_host(host)
    except HostsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not host_record:
        console.print(f"[red]Error:[/red] Host '{host}' not found")
        raise typer.Exit(code=1)

    hostname = host_record["hostname"]

    # Validate alias uniqueness (if changing)
    if alias is not None:
        new_alias = alias.strip()
        if new_alias != host_record.get("alias"):
            exists, conflicting_host = alias_exists(
                new_alias, exclude_hostname=hostname
            )
            if exists:
                if conflicting_host == new_alias:
                    console.print(
                        f"[red]Error:[/red] Alias '{new_alias}' conflicts with existing hostname"
                    )
                else:
                    console.print(
                        f"[red]Error:[/red] Alias '{new_alias}' already in use by host '{conflicting_host}'"
                    )
                raise typer.Exit(code=1)

    changes: list[str] = []

    def apply_update(h: dict) -> dict:
        if "metadata" not in h:
            h["metadata"] = {}

        if alias is not None:
            new_alias = alias.strip()
            old_alias = h.get("alias")
            if new_alias != old_alias:
                h["alias"] = new_alias
                changes.append(f"alias: {old_alias or '-'} -> {new_alias}")

        if description is not None:
            old_desc = h["metadata"].get("description")
            if description == "":
                if "description" in h["metadata"]:
                    del h["metadata"]["description"]
                    changes.append("description: cleared")
            else:
                new_desc = description.strip()
                if new_desc != old_desc:
                    h["metadata"]["description"] = new_desc
                    changes.append("description updated")

        # Tag operations
        current_tags = list(h["metadata"].get("tags", []))
        if set_tags is not None:
            new_tags = (
                [t.strip() for t in set_tags.split(",") if t.strip()]
                if set_tags
                else []
            )
            if new_tags != current_tags:
                h["metadata"]["tags"] = new_tags
                changes.append(
                    f"tags: {', '.join(new_tags) if new_tags else '(cleared)'}"
                )
        elif add_tag or remove_tag:
            if add_tag:
                for t in add_tag:
                    tag_clean = t.strip()
                    if tag_clean and tag_clean not in current_tags:
                        current_tags.append(tag_clean)
            if remove_tag:
                for t in remove_tag:
                    tag_clean = t.strip()
                    if tag_clean in current_tags:
                        current_tags.remove(tag_clean)
            h["metadata"]["tags"] = current_tags
            changes.append(
                f"tags: {', '.join(current_tags) if current_tags else '(cleared)'}"
            )

        return h

    if not update_host(hostname, apply_update):
        console.print("[red]Error:[/red] Failed to update host")
        raise typer.Exit(code=1)

    display_name = (
        alias.strip() if alias is not None else (host_record.get("alias") or hostname)
    )

    if not changes:
        console.print(f"No changes for '{display_name}'.")
        return

    console.print(f"[green]Host '{display_name}' updated:[/green]")
    for change in changes:
        console.print(f"  - {change}")


@host_app.command()
def ps(
    hostname: str = typer.Argument(..., help="Host hostname or alias to check"),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Re-detect hardware capabilities"
    ),
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

    display_name = host.get("alias") or host["hostname"]
    console.print(f"Checking status of '{display_name}'...")

    # Get per-host key using key_id
    key_id = host.get("key_id") or host["hostname"]  # Fallback for old records
    host_key = get_host_private_key(key_id)
    if host_key is None:
        console.print(f"[red]Error:[/red] No keypair found for '{key_id}'")
        console.print(
            f"Run 'clawctl host create --bootstrap {key_id}' to regenerate keys"
        )
        raise typer.Exit(code=1)
    ssh_key = str(host_key)

    # Test connection
    try:
        result = test_ssh_connection(
            hostname=host["hostname"],
            port=host.get("port", 22),
            user=host.get("user", "xclm"),
            key_filename=ssh_key,
        )
        success, message = result
    except HostKeyVerificationRequired:
        success = False
        message = "Host key verification required"
        console.print(
            f"[yellow]Note:[/yellow] Run 'clawctl host delete {hostname} && clawctl host create {host['hostname']}' to re-verify the host key."
        )

    # Refresh hardware BEFORE building table if requested (per D-06)
    hw = host.get("hardware", {})
    if refresh and success:
        console.print("Refreshing hardware information...")
        try:
            hw = gather_hardware(
                hostname=host["hostname"],
                user=host.get("user", "xclm"),
                port=host.get("port", 22),
                ssh_key=ssh_key,
            )

            # Update host record atomically to prevent TOCTOU races (B3 fix)
            def apply_hardware_update(h: dict) -> dict:
                h["hardware"] = hw
                h["metadata"]["last_seen"] = datetime.now(timezone.utc).isoformat()
                return h

            try:
                if update_host(host["hostname"], apply_hardware_update):
                    console.print("[green]Hardware information updated.[/green]\n")
                else:
                    console.print(
                        "[yellow]Warning:[/yellow] Host not found during update\n"
                    )
            except Exception as e:
                console.print(f"[red]Error saving host data:[/red] {e}")
                raise typer.Exit(code=1)
        except typer.Exit:
            raise
        except Exception as e:
            console.print(
                f"[yellow]Warning:[/yellow] Could not refresh hardware: {e}\n"
            )
    elif refresh and not success:
        console.print(
            "[yellow]Cannot refresh hardware: host is not connected[/yellow]\n"
        )

    # Display status table
    table = Table(title=f"Host Status: {display_name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    if success:
        table.add_row("Connection", "[green]Connected[/green]")
    else:
        table.add_row("Connection", f"[red]Disconnected[/red] ({message})")

    table.add_row("Hostname", host["hostname"])
    if host.get("ssh_config_host"):
        table.add_row("SSH Config", host["ssh_config_host"])
    table.add_row("Port", str(host.get("port", 22)))
    table.add_row("User", host.get("user", "xclm"))

    meta = host.get("metadata", {})
    table.add_row("Added", meta.get("added_at", "Unknown"))
    table.add_row("Last Seen", meta.get("last_seen", "Unknown"))
    table.add_row("Tags", ", ".join(meta.get("tags", [])) or "-")
    if meta.get("description"):
        table.add_row("Description", meta["description"])

    if hw:
        table.add_row("Architecture", hw.get("architecture", "?"))
        table.add_row("CPU Cores", str(hw.get("processor_cores", "?")))
        table.add_row("Memory", f"{round(hw.get('memtotal_mb', 0) / 1024, 1)} GB")
        gpu = hw.get("gpu", {})
        if gpu.get("present"):
            table.add_row("GPU", gpu.get("vendor") or "Unknown")
        else:
            table.add_row("GPU", "None detected")

    console.print(table)

    # Display addresses if multiple exist
    addresses = host.get("addresses", [])
    if len(addresses) > 1:
        console.print("\n[bold]Addresses:[/bold]")
        for addr in addresses:
            primary_marker = "* " if addr.get("is_primary") else "  "
            label_str = f" ({rich_escape(addr['label'])})" if addr.get("label") else ""
            console.print(
                f"  {primary_marker}{rich_escape(addr['address'])}{label_str}"
            )

    # Exit 1 if host is disconnected (for scripting)
    if not success:
        raise typer.Exit(code=1)


@host_app.command()
def reset(
    hostname: str = typer.Argument(..., help="Host hostname or alias to reset"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be removed without executing"
    ),
    untrack: bool = typer.Option(
        False, "--untrack", help="Also remove host from Clawrium tracking after reset"
    ),
) -> None:
    """Reset a host, removing all claws and users.

    This command will:
    - Stop and remove all *claw* services
    - Remove all users with uid >= 1000 (except xclm)
    - Clean clawrium configuration paths

    Use --dry-run to preview changes without executing.
    Use --yes to skip the confirmation prompt.
    Use --untrack to also remove the host from tracking.
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

    display_name = host.get("alias") or host["hostname"]
    console.print(f"Scanning '{display_name}' for targets...")

    # Enumerate targets
    try:
        targets = enumerate_targets(hostname)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] Failed to enumerate targets: {e}")
        raise typer.Exit(code=1)

    # Display targets
    # W1: Use rich_escape for user-controlled strings from remote host
    if targets.users:
        console.print(f"\n[bold]Users to remove ({len(targets.users)}):[/bold]")
        for user in targets.users:
            console.print(f"  - {rich_escape(user)}")

    if targets.services:
        console.print(f"\n[bold]Services to remove ({len(targets.services)}):[/bold]")
        for service in targets.services:
            console.print(f"  - {rich_escape(service)}")

    if targets.paths:
        console.print(f"\n[bold]Paths to clean ({len(targets.paths)}):[/bold]")
        for path in targets.paths:
            console.print(f"  - {rich_escape(path)}")

    total_items = len(targets.users) + len(targets.services) + len(targets.paths)
    if total_items == 0:
        console.print("\n[yellow]No targets found to remove.[/yellow]")
        return

    # Dry run exits here
    if dry_run:
        console.print("\n[yellow]Dry run - no changes made[/yellow]")
        return

    # Confirm unless --yes
    if not yes:
        console.print(
            f"\n[bold red]WARNING:[/bold red] This will permanently remove {total_items} items from '{display_name}'."
        )
        confirmed = typer.confirm("Continue?")
        if not confirmed:
            console.print("Aborted.")
            raise typer.Exit(code=0)  # Clean exit on user cancel, not error

    # Execute reset
    console.print(f"\nResetting '{display_name}'...")
    result = execute_reset(hostname, targets)

    if result.success:
        console.print("[green]Reset complete![/green]")
        console.print(f"  Users removed: {result.removed['users']}")
        console.print(f"  Services removed: {result.removed['services']}")
        console.print(f"  Paths cleaned: {result.removed['paths']}")

        # Clear agents from host record and set last_reset timestamp
        def clear_agents(h: dict) -> dict:
            from datetime import datetime, timezone

            h["agents"] = {}
            if "metadata" not in h:
                h["metadata"] = {}
            h["metadata"]["last_reset"] = datetime.now(timezone.utc).isoformat()
            return h

        # W4: Check return value of update_host
        if not update_host(hostname, clear_agents):
            console.print(
                "[yellow]Warning:[/yellow] Could not update host record (host may have been removed)"
            )

        # Optionally untrack
        if untrack:
            console.print(f"\nUntracking '{display_name}'...")
            if remove_host(hostname):
                console.print("[green]Host removed from tracking.[/green]")
            else:
                console.print(
                    "[yellow]Warning:[/yellow] Could not remove host from tracking"
                )
    else:
        console.print("[red]Reset failed![/red]")
        for error in result.errors:
            console.print(f"  - {error}")
        raise typer.Exit(code=1)


# Address management commands


@address_app.command(name="add")
def address_add(
    host: str = typer.Argument(..., help="Host hostname or alias"),
    address: str = typer.Argument(
        ..., help="Address as IPv4, IPv6, or hostname (e.g., 192.168.1.1, myhost.local)"
    ),
    label: Optional[str] = typer.Option(
        None, "--label", "-l", help="Label for the address (e.g., lan, vpn, external)"
    ),
) -> None:
    """Add an address to a host.

    The first address added to a host is automatically the primary.
    Additional addresses can be used to reach the host from different
    network contexts.
    """
    try:
        add_address_to_host(host, address, label)
        label_str = f" ({label})" if label else ""
        console.print(
            f"[green]Address '{rich_escape(address)}'{label_str} added to host '{rich_escape(host)}'[/green]"
        )
    except AddressError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)


@address_app.command(name="remove")
def address_remove(
    host: str = typer.Argument(..., help="Host hostname or alias"),
    address: str = typer.Argument(
        ..., help="Address to remove (use 'clawctl host address get' to see addresses)"
    ),
) -> None:
    """Remove an address from a host.

    Cannot remove the primary address. Use 'set-primary' to switch
    to a different address first.
    """
    try:
        remove_address_from_host(host, address)
        console.print(
            f"[green]Address '{rich_escape(address)}' removed from host '{rich_escape(host)}'[/green]"
        )
    except AddressError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        console.print(
            f"[dim]Use 'clawctl host address get {rich_escape(host)}' to see available addresses.[/dim]"
        )
        raise typer.Exit(code=1)


@address_app.command(name="list")
def address_list(
    host: str = typer.Argument(..., help="Host hostname or alias"),
) -> None:
    """List all addresses for a host.

    Shows the primary address (used for all downstream commands) and
    any secondary addresses for different network contexts.
    """
    try:
        addresses = get_host_addresses(host)
    except AddressError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)

    if not addresses:
        console.print(f"No addresses configured for host '{rich_escape(host)}'")
        return

    table = Table(title=f"Addresses for {rich_escape(host)}")
    table.add_column("Address", style="white")
    table.add_column("Primary", style="cyan")
    table.add_column("Label", style="dim")
    table.add_column("Added", style="dim")

    for addr in addresses:
        # Format timestamp for display
        added_at = addr.get("added_at", "")
        if added_at:
            try:
                # Parse ISO format and display nicely
                dt = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
                added_display = dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                added_display = added_at
        else:
            added_display = "-"

        table.add_row(
            rich_escape(addr.get("address", "?")),
            "*" if addr.get("is_primary") else "",
            rich_escape(addr.get("label") or "-"),
            added_display,
        )

    console.print(table)


@address_app.command(name="set-primary")
def address_set_primary(
    host: str = typer.Argument(..., help="Host hostname or alias"),
    address: str = typer.Argument(..., help="Address to make primary"),
) -> None:
    """Set a different address as the primary for a host.

    The primary address is used for all downstream commands (agent
    install, configure, status checks, etc.). Changing the primary
    updates the host's hostname field.
    """
    try:
        set_primary_address(host, address)
        console.print(
            f"[green]Primary address for '{rich_escape(host)}' set to '{rich_escape(address)}'[/green]"
        )
    except AddressError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        console.print(
            f"[dim]Use 'clawctl host address get {rich_escape(host)}' to see available addresses.[/dim]"
        )
        raise typer.Exit(code=1)

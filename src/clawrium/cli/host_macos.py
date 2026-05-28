"""macOS host bootstrap.

Counterpart to `cli/host.py:init` for macOS targets. Creates the `xclm`
management user using Darwin-native tooling (dscl + dseditgroup + sudoers.d),
drops the per-host SSH public key into `/Users/xclm/.ssh/authorized_keys`,
and adds xclm to `com.apple.access_ssh` so sshd will accept its connections.

The `com.apple.access_ssh` group membership is the **non-obvious** Mac-only
step: without it, sshd silently closes the connection with no useful log
entry. Easy to misdiagnose as a key/firewall problem.

Idempotency: every step is safe to re-run.

- `dscl . -create /Users/xclm` is a no-op once the user exists.
- `tee /etc/sudoers.d/xclm` overwrites with the same content.
- `dseditgroup -o edit -a xclm` is a no-op if xclm is already in the group.

This module is invoked via `cli/clawctl/host/create.py:_run_bootstrap`
when the remote `uname -s` returns `Darwin`. See `cli/host_bootstrap.py`.
"""

from __future__ import annotations

import getpass
import shlex
from typing import Optional

import paramiko
import typer
from rich.console import Console
from rich.markup import escape as rich_escape

from clawrium.core.keys import (
    generate_host_keypair,
    get_host_private_key,
    read_public_key,
)
from clawrium.core.ssh_connection import test_ssh_connection

__all__ = ["init_macos"]

console = Console()

# Free UID floor for the xclm management user. macOS reserves 500–599 for
# Apple system accounts. Picking >=600 avoids collisions with any future
# Apple-introduced system user.
_XCLM_UID_MIN = 600


def init_macos(hostname: str, user: Optional[str] = None) -> None:
    """Bootstrap the xclm management user on a macOS host.

    Mirrors `cli/host.py:init` (Linux). Differences:
      - User creation uses dscl instead of useradd.
      - HOME is `/Users/xclm` (not `/home/xclm`).
      - PrimaryGroupID = 20 (staff), the default for human users on macOS.
      - xclm is added to `com.apple.access_ssh` (sshd ACL group).
    """
    # Step 1: keypair (shared identity store with the Linux path)
    private_key = get_host_private_key(hostname)
    if private_key:
        console.print(f"Using existing keypair for '{hostname}'")
    else:
        console.print(f"Generating SSH keypair for '{hostname}'...")
        private_key_path, public_key_path = generate_host_keypair(hostname)
        console.print(f"[green]Keypair created:[/green] {public_key_path}")
        private_key = private_key_path

    public_key_content = read_public_key(hostname)
    if not public_key_content:
        console.print(f"[red]Could not read public key for {hostname}[/red]")
        raise typer.Exit(code=1)

    connection_user = user or getpass.getuser()
    # `connection_user` originates from the CLI flag (user-controlled);
    # `hostname` likewise. Escape both so rich does not parse stray
    # `[brackets]` as markup tags. Mirrors cli/host.py pattern.
    console.print(
        f"\nConnecting to {rich_escape(hostname)} as "
        f"{rich_escape(connection_user)}..."
    )

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    auto_setup_success = False
    try:
        client.connect(hostname=hostname, username=connection_user, timeout=10)
        transport = client.get_transport()
        if not (transport and transport.is_active()):
            console.print("[yellow]Could not establish active SSH transport[/yellow]")
            raise typer.Exit(code=1)

        console.print("[green]Connection successful![/green]")
        console.print("Setting up xclm management user (Darwin)...")

        # If xclm already exists from a prior run, reuse its UID so the
        # idempotent re-run doesn't drift the UID upward on every call.
        existing_uid = _existing_user_uid(client, "xclm")
        if existing_uid is not None:
            uid = existing_uid
            console.print(f"  xclm uid: {uid} (existing)")
        else:
            uid = _pick_free_uid(client, _XCLM_UID_MIN)
            console.print(f"  xclm uid: {uid}")

        # Pre-escape the public key for the shell echo. Falls through one
        # quoting layer (sudo tee) cleanly.
        quoted_key = shlex.quote(public_key_content)

        commands = [
            # Idempotent dscl: -create on an existing record overwrites,
            # which we want (e.g. UserShell drift).
            ("sudo dscl . -create /Users/xclm", None),
            ("sudo dscl . -create /Users/xclm UserShell /bin/bash", None),
            ('sudo dscl . -create /Users/xclm RealName "Clawrium Mgmt"', None),
            (f"sudo dscl . -create /Users/xclm UniqueID {uid}", None),
            ("sudo dscl . -create /Users/xclm PrimaryGroupID 20", None),
            (
                "sudo dscl . -create /Users/xclm NFSHomeDirectory /Users/xclm",
                None,
            ),
            ("sudo mkdir -p /Users/xclm", None),
            ("sudo chown xclm:staff /Users/xclm", None),
            # Passwordless sudo. sudoers.d is honored on macOS.
            (
                'echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm',
                None,
            ),
            ("sudo chmod 440 /etc/sudoers.d/xclm", None),
            # SSH key drop. Use sudo tee with stdin to avoid embedding the
            # raw key into the shell command line.
            ("sudo mkdir -p /Users/xclm/.ssh", None),
            ("sudo chmod 700 /Users/xclm/.ssh", None),
            (
                "sudo tee /Users/xclm/.ssh/authorized_keys",
                public_key_content,
            ),
            ("sudo chmod 600 /Users/xclm/.ssh/authorized_keys", None),
            ("sudo chown -R xclm:staff /Users/xclm/.ssh", None),
            # The critical mac-only step: without this, sshd silently
            # closes connections from xclm with no log entry.
            (
                "sudo dseditgroup -o edit -a xclm -t user com.apple.access_ssh",
                None,
            ),
        ]
        _ = quoted_key  # used in fallback manual steps below

        for cmd, stdin_data in commands:
            stdin, stdout, stderr = client.exec_command(cmd)
            if stdin_data:
                stdin.write(stdin_data + "\n")
                stdin.channel.shutdown_write()
            stdout.read()
            stderr_output = stderr.read().decode().strip()
            exit_status = stdout.channel.recv_exit_status()
            # dseditgroup returns non-zero if user already in group;
            # tolerate that one. dscl -create is idempotent and returns 0.
            tolerate = "dseditgroup" in cmd and (
                "already a member" in stderr_output.lower()
                or "is already" in stderr_output.lower()
            )
            if exit_status != 0 and not tolerate:
                console.print(
                    f"[yellow]Warning:[/yellow] step failed (exit {exit_status}): "
                    f"{rich_escape(cmd)}"
                )
                if stderr_output:
                    console.print(f"  {rich_escape(stderr_output)}")

        console.print("\nVerifying xclm access...")
        success, message = test_ssh_connection(
            hostname=hostname,
            port=22,
            user="xclm",
            key_filename=str(private_key),
        )
        if success:
            console.print("[green]xclm user configured successfully![/green]")
            console.print(f"\nNext step: [cyan]clawctl host create {hostname}[/cyan]")
            auto_setup_success = True
        else:
            # `message` originates from test_ssh_connection (paramiko
            # error strings) — may contain remote-controlled content.
            console.print(
                f"[yellow]Warning:[/yellow] xclm verification failed: "
                f"{rich_escape(str(message))}"
            )

    except paramiko.AuthenticationException as e:
        console.print(
            f"[yellow]Authentication failed:[/yellow] {rich_escape(str(e))}"
        )
    except paramiko.SSHException as e:
        console.print(f"[yellow]SSH error:[/yellow] {rich_escape(str(e))}")
    except Exception as e:
        console.print(f"[yellow]Could not connect:[/yellow] {rich_escape(str(e))}")
    finally:
        client.close()

    if not auto_setup_success:
        console.print("\n[yellow]Manual setup required.[/yellow]")
        console.print("\nRun these commands on the target Mac:\n")
        console.print("[dim]# Create xclm user via dscl[/dim]")
        console.print("sudo dscl . -create /Users/xclm")
        console.print("sudo dscl . -create /Users/xclm UserShell /bin/bash")
        console.print('sudo dscl . -create /Users/xclm RealName "Clawrium Mgmt"')
        console.print(f"sudo dscl . -create /Users/xclm UniqueID {_XCLM_UID_MIN}")
        console.print("sudo dscl . -create /Users/xclm PrimaryGroupID 20")
        console.print(
            "sudo dscl . -create /Users/xclm NFSHomeDirectory /Users/xclm"
        )
        console.print("sudo mkdir -p /Users/xclm && sudo chown xclm:staff /Users/xclm")
        console.print("")
        console.print("[dim]# Grant passwordless sudo[/dim]")
        console.print(
            'echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm'
        )
        console.print("sudo chmod 440 /etc/sudoers.d/xclm")
        console.print("")
        console.print("[dim]# SSH access[/dim]")
        console.print("sudo mkdir -p /Users/xclm/.ssh && sudo chmod 700 /Users/xclm/.ssh")
        escaped_key = (
            shlex.quote(public_key_content) if public_key_content else "''"
        )
        console.print(
            f"echo {rich_escape(escaped_key)} | sudo tee /Users/xclm/.ssh/authorized_keys",
            soft_wrap=False,
        )
        console.print("sudo chmod 600 /Users/xclm/.ssh/authorized_keys")
        console.print("sudo chown -R xclm:staff /Users/xclm/.ssh")
        console.print("")
        console.print("[dim]# Critical mac-only step: SSH ACL group[/dim]")
        console.print(
            "sudo dseditgroup -o edit -a xclm -t user com.apple.access_ssh"
        )
        console.print("")
        console.print(f"Then run: [cyan]clawctl host create {hostname}[/cyan]")
        raise typer.Exit(code=1)


def _existing_user_uid(client: paramiko.SSHClient, username: str) -> int | None:
    """Return the UID of `username` on the remote host, or None if missing.

    Uses `dscl . -read /Users/<name> UniqueID`. The command returns non-zero
    if the user is missing; treat that as "not found" and any parse failure
    as "unknown" (which the caller treats as missing).
    """
    _, stdout, stderr = client.exec_command(
        f"dscl . -read /Users/{shlex.quote(username)} UniqueID"
    )
    raw = stdout.read().decode()
    stderr.read()
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        return None
    # Output is like: "UniqueID: 600"
    for line in raw.splitlines():
        if line.startswith("UniqueID:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _pick_free_uid(client: paramiko.SSHClient, floor: int) -> int:
    """Return the lowest unused UID >= floor on the remote macOS host.

    `dscl . -list /Users UniqueID` emits one row per user with the UID as
    the second whitespace-separated token. Parse defensively — older
    macOS versions occasionally emit a comment line; ignore non-integers.
    """
    _, stdout, _ = client.exec_command("dscl . -list /Users UniqueID")
    raw = stdout.read().decode()
    used: set[int] = set()
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            used.add(int(parts[1]))
        except ValueError:
            continue
    candidate = floor
    while candidate in used:
        candidate += 1
    return candidate

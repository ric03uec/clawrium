"""`clawctl host create <hostname>` — register a host record.

On first run for a given hostname:
  1. Generate a per-host ed25519 keypair (if one does not already exist).
  2. Verify SSH access as `xclm` using that key.
  3. On failure: print the manual setup commands (Linux + macOS, pubkey
     inlined) and exit non-zero so the user can run them on the host
     and re-invoke this command.
  4. On success: persist the host record to `hosts.json`.

Re-running after manual setup is idempotent — the keypair is reused,
the SSH check succeeds, and the record write is a no-op when the
existing record already matches.

Auto-bootstrap (`--bootstrap`) was removed in #547. The previous
implementation assumed passwordless sudo as the bootstrap user, but
the paramiko exec channel has no PTY/askpass, so every `sudo` step
silently failed on hosts that actually needed bootstrapping.
"""

from __future__ import annotations

import shlex
from datetime import datetime, timezone
from typing import Optional

import paramiko
import typer
from rich.console import Console
from rich.markup import escape as rich_escape

from clawrium.cli.clawctl._common import (
    require_flag,
    validate_alias,
    validate_hostname,
)
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.hosts import (
    DuplicateHostError,
    HostsFileCorruptedError,
    add_host,
    get_host,
    update_host,
)
from clawrium.core.keys import (
    generate_host_keypair,
    get_host_private_key,
    read_public_key,
)
from clawrium.core.ssh_connection import (
    HostKeyVerificationRequired,
    test_ssh_connection,
)

console = Console()


def create(
    hostname: str = typer.Argument(..., help="Hostname or IP of the new host."),
    user: Optional[str] = typer.Option(
        None,
        "--user",
        "-u",
        help="Management user on the host (must be 'xclm').",
    ),
    port: int = typer.Option(22, "--port", "-p", min=1, max=65535, help="SSH port."),
    alias: Optional[str] = typer.Option(
        None, "--alias", "-a", help="Display alias for the host."
    ),
) -> None:
    """Register a host after verifying SSH access to the xclm management user."""
    validate_hostname(hostname)
    if alias is not None:
        validate_alias(alias)
    require_flag(user, flag="--user")
    if user != "xclm":
        emit_error(
            f"--user must be 'xclm' (got {user!r})",
            hint=(
                "clawrium manages hosts as the dedicated 'xclm' user; "
                "see docs/host-preparation.md to create it"
            ),
        )

    try:
        existing = get_host(hostname) or (get_host(alias) if alias else None)
    except HostsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/hosts.json")

    if existing:
        if existing.get("hostname") == hostname and existing.get("user") == user:
            stream_action(
                resource=f"host/{alias or hostname}",
                message=f"already exists on {hostname}",
            )
            return
        # Re-record path (issue #448): the alias resolves to an existing
        # host whose `hostname` is being updated (IP → DNS, renumber,
        # Tailscale migration). Preserve `key_id` so every per-agent
        # secret stored under `<key_id>:<type>:<name>` stays reachable;
        # mutate only the network coordinates. Reject re-records that
        # also try to change `user`, since that's an identity change
        # and not the case #448 is solving.
        existing_alias = existing.get("alias")
        if alias and existing_alias == alias:
            if existing.get("user") != user:
                emit_error(
                    f"host alias {alias!r} already registered with a "
                    f"different user ({existing.get('user')!r}); refusing "
                    "to mutate identity on re-record",
                    hint="clawctl host delete first if you really want to "
                    "rotate the management user",
                )
            old_hostname = existing.get("hostname")
            preserved_key_id = existing.get("key_id") or old_hostname
            private_key = _ensure_host_keypair(preserved_key_id)
            verified, os_family = _verify_xclm_access(hostname, port, private_key)
            if not verified:
                _print_manual_setup(hostname)
                raise typer.Exit(code=1)

            now = datetime.now(timezone.utc).isoformat()

            def _rewrite(host: dict) -> dict:
                host["hostname"] = hostname
                host["port"] = port
                host["os_family"] = os_family
                host["key_id"] = preserved_key_id
                addresses = host.get("addresses") or []
                # De-primary existing entries and append the new dial
                # target as primary. Duplicate-by-`address` is collapsed
                # so re-recording the same value doesn't grow the list.
                rebuilt = []
                seen = False
                for entry in addresses:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("address") == hostname:
                        seen = True
                        entry["is_primary"] = True
                        entry["added_at"] = entry.get("added_at") or now
                    else:
                        entry["is_primary"] = False
                    rebuilt.append(entry)
                if not seen:
                    rebuilt.append(
                        {
                            "address": hostname,
                            "is_primary": True,
                            "label": None,
                            "added_at": now,
                        }
                    )
                host["addresses"] = rebuilt
                metadata = host.get("metadata") or {}
                metadata["last_seen"] = None
                host["metadata"] = metadata
                return host

            # `update_host` looks up by the *current* hostname value in
            # hosts.json; pass the old one, not the new one.
            updated = update_host(old_hostname, _rewrite)
            if not updated:
                emit_error(
                    f"failed to rewrite host record for alias {alias!r}",
                    hint="check ~/.config/clawrium/hosts.json",
                )
            stream_action(
                resource=f"host/{alias}",
                message=(
                    f"hostname {old_hostname} → {hostname} "
                    f"(key_id preserved: {preserved_key_id})"
                ),
            )
            return
        emit_error(
            f"host {hostname!r} already registered with different settings",
            hint="clawctl host edit to modify, or clawctl host delete first",
        )

    private_key = _ensure_host_keypair(hostname)
    verified, os_family = _verify_xclm_access(hostname, port, private_key)
    if not verified:
        _print_manual_setup(hostname)
        raise typer.Exit(code=1)

    now = datetime.now(timezone.utc).isoformat()
    record: dict = {
        "hostname": hostname,
        "key_id": hostname,
        "port": port,
        "user": user,
        "auth_method": "key",
        "os_family": os_family,
        "hardware": {},
        "metadata": {"added_at": now, "last_seen": None, "labels": {}},
        "addresses": [
            {
                "address": hostname,
                "is_primary": True,
                "label": None,
                "added_at": now,
            }
        ],
        "agents": {},
    }
    if alias:
        record["alias"] = alias

    try:
        add_host(record)
    except DuplicateHostError as exc:
        emit_error(str(exc), hint="clawctl host delete to remove first")
    except HostsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/hosts.json")

    display = alias or hostname
    stream_action(resource=f"host/{display}", message=f"created on {hostname}:{port}")


def _ensure_host_keypair(hostname: str) -> str:
    """Return the path to the host's private key, generating it if missing."""
    existing = get_host_private_key(hostname)
    if existing:
        return str(existing)
    console.print(
        f"Generating SSH keypair for [cyan]{rich_escape(hostname)}[/cyan]..."
    )
    private_key_path, public_key_path = generate_host_keypair(hostname)
    console.print(f"[green]Keypair created:[/green] {rich_escape(str(public_key_path))}")
    return str(private_key_path)


def _verify_xclm_access(
    hostname: str, port: int, private_key: str
) -> tuple[bool, str]:
    """Verify SSH as xclm and detect the host's OS family.

    Returns (verified, os_family). On failure the caller should treat
    `os_family` as undefined — it is only meaningful when verified is True.
    The returned value is one of `linux` or `darwin`; anything else from
    `uname -s` (BSDs, exotic platforms) is reported with a clear message
    and treated as unsupported.
    """
    try:
        success, message = test_ssh_connection(
            hostname=hostname, port=port, user="xclm", key_filename=private_key
        )
    except HostKeyVerificationRequired as exc:
        console.print(
            f"[yellow]Host key prompt required for "
            f"{rich_escape(exc.hostname)}[/yellow] "
            f"(fingerprint {rich_escape(exc.fingerprint)})."
        )
        console.print(
            "Run [cyan]ssh -p "
            f"{port} xclm@{rich_escape(hostname)}[/cyan] once to record the host key, "
            "then re-run this command."
        )
        return False, ""
    if not success:
        console.print(
            f"[yellow]xclm SSH verification failed:[/yellow] {rich_escape(message)}"
        )
        return False, ""

    os_family = _detect_os_family(hostname, port, private_key)
    if os_family is None:
        return False, ""
    return True, os_family


def _detect_os_family(hostname: str, port: int, private_key: str) -> str | None:
    """Run `uname -s` as xclm and map the result to a supported family.

    Persisting this here (rather than inferring later) keeps the macOS
    lifecycle dispatcher in #469 working — every reader of `os_family`
    treats a missing value as `linux`, so a fresh Mac registered without
    this step would silently take the Linux path.
    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    try:
        client.connect(
            hostname=hostname,
            port=port,
            username="xclm",
            key_filename=private_key,
            timeout=10,
        )
        _, stdout, _ = client.exec_command("uname -s", timeout=10)
        raw = stdout.read().decode().strip()
    except Exception as exc:
        console.print(
            f"[yellow]OS detection failed:[/yellow] {rich_escape(str(exc))}"
        )
        return None
    finally:
        client.close()

    if raw == "Linux":
        return "linux"
    if raw == "Darwin":
        return "darwin"
    console.print(
        f"[yellow]Unsupported remote OS:[/yellow] uname -s returned "
        f"{rich_escape(raw)!r}. Clawrium supports Linux and macOS targets."
    )
    return None


def _print_manual_setup(hostname: str) -> None:
    """Print Linux + macOS manual setup blocks with the public key inlined."""
    pubkey = read_public_key(hostname)
    if not pubkey:
        console.print(
            f"[red]Could not read public key for "
            f"{rich_escape(hostname)}.[/red] Re-run after deleting "
            f"~/.config/clawrium/keys/{rich_escape(hostname)}/ to regenerate."
        )
        return
    # shlex.quote handles quotes, backticks, $(), and other shell
    # metacharacters in the pubkey (the comment portion is operator-
    # controlled when keys are imported, so harden the printed echo).
    quoted_pubkey = shlex.quote(pubkey.strip())

    console.print(
        "\n[bold]Manual setup required.[/bold] "
        "Log into the host with a sudo-capable user and run the block that "
        "matches its OS:\n"
    )

    console.print("[bold cyan]## Linux[/bold cyan]")
    console.print("[dim]# Create xclm user[/dim]")
    console.print("sudo useradd -m -s /bin/bash xclm")
    console.print("[dim]# Passwordless sudo[/dim]")
    console.print(
        'echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm'
    )
    console.print("sudo chmod 440 /etc/sudoers.d/xclm")
    console.print("[dim]# Authorized key[/dim]")
    console.print("sudo mkdir -p /home/xclm/.ssh && sudo chmod 700 /home/xclm/.ssh")
    console.print(
        f"echo {rich_escape(quoted_pubkey)} | sudo tee /home/xclm/.ssh/authorized_keys",
        soft_wrap=False,
    )
    console.print("sudo chmod 600 /home/xclm/.ssh/authorized_keys")
    console.print("sudo chown -R xclm:xclm /home/xclm/.ssh\n")

    console.print(
        "[bold cyan]## macOS — preflight (run LOCALLY on the Mac)[/bold cyan]"
    )
    console.print(
        "[dim]# sshd is off by default on a fresh macOS install. "
        "Run this on the Mac itself BEFORE attempting the SSH commands below.[/dim]"
    )
    console.print("sudo systemsetup -setremotelogin on")
    console.print(
        "[dim]# If that fails with a Full Disk Access error (macOS 13+), "
        "enable it via System Settings → General → Sharing → Remote Login.[/dim]\n"
    )

    console.print(
        "[bold cyan]## macOS — SSH in as your sudo user, then paste:[/bold cyan]"
    )
    console.print("[dim]# Create xclm user via dscl[/dim]")
    console.print("sudo dscl . -create /Users/xclm")
    console.print("sudo dscl . -create /Users/xclm UserShell /bin/bash")
    console.print('sudo dscl . -create /Users/xclm RealName "Clawrium Mgmt"')
    console.print("sudo dscl . -create /Users/xclm UniqueID 600")
    console.print("sudo dscl . -create /Users/xclm PrimaryGroupID 20")
    console.print("sudo dscl . -create /Users/xclm NFSHomeDirectory /Users/xclm")
    console.print("sudo mkdir -p /Users/xclm && sudo chown xclm:staff /Users/xclm")
    console.print("[dim]# Passwordless sudo[/dim]")
    console.print(
        'echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm'
    )
    console.print("sudo chmod 440 /etc/sudoers.d/xclm")
    console.print("[dim]# Authorized key[/dim]")
    console.print(
        "sudo mkdir -p /Users/xclm/.ssh && sudo chmod 700 /Users/xclm/.ssh"
    )
    console.print(
        f"echo {rich_escape(quoted_pubkey)} | sudo tee /Users/xclm/.ssh/authorized_keys",
        soft_wrap=False,
    )
    console.print("sudo chmod 600 /Users/xclm/.ssh/authorized_keys")
    console.print("sudo chown -R xclm:staff /Users/xclm/.ssh")
    console.print(
        "[dim]# Critical Mac-only step: SSH ACL group "
        "(without this, sshd silently rejects xclm)[/dim]"
    )
    console.print(
        "sudo dseditgroup -o edit -a xclm -t user com.apple.access_ssh\n"
    )

    console.print(
        f"Then re-run: [cyan]clawctl host create {rich_escape(hostname)} "
        "--user xclm[/cyan]"
    )

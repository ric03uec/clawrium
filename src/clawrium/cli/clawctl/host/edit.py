"""`clawctl host edit <hostname>` — modify host record in place.

For this bundle, edit accepts flag-driven updates (`--user`, `--port`,
`--alias`). Opening `$EDITOR` on the YAML record is deferred to bundle
4 (it's the same `$EDITOR` flow as `clawctl agent edit` and the two
should share infrastructure).
"""

from __future__ import annotations

from typing import Optional

import typer

from clawrium.cli.clawctl._common import validate_alias
from clawrium.cli.clawctl.host._shared import display_name, hostname_key, safe_get_host
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.hosts import AddressError, _validate_address, alias_exists, load_hosts, update_host


def edit(
    hostname: str = typer.Argument(..., help="Host name or alias to edit."),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="New SSH user."),
    port: Optional[int] = typer.Option(
        None, "--port", "-p", min=1, max=65535, help="New SSH port."
    ),
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="New alias."),
    hostname_new: Optional[str] = typer.Option(
        None,
        "--hostname",
        help="New IP address or hostname (e.g. after DHCP renewal). key_id is preserved.",
    ),
) -> None:
    """Edit a host record in place (flag-driven)."""
    host = safe_get_host(hostname)
    canonical = hostname_key(host)
    old_name = display_name(host)

    if user is None and port is None and alias is None and hostname_new is None:
        emit_error(
            "no edits requested",
            hint="pass at least one of --user, --port, --alias, --hostname",
        )

    if alias is not None:
        validate_alias(alias)
        exists, conflict = alias_exists(alias, exclude_hostname=canonical)
        if exists:
            emit_error(
                f"alias {alias!r} already in use by {conflict!r}",
                hint="choose a different alias or remove the conflict first",
            )

    if hostname_new is not None:
        new_ip = hostname_new.strip()
        if not new_ip:
            emit_error("--hostname cannot be empty")
        try:
            _validate_address(new_ip)
        except AddressError as exc:
            emit_error(str(exc))
        if new_ip != canonical:
            conflicting = [
                h
                for h in load_hosts()
                if h["hostname"] == new_ip
                and h.get("key_id") != host.get("key_id")
            ]
            if conflicting:
                emit_error(
                    f"hostname {new_ip!r} already in use",
                    hint="choose a different address or remove the conflicting host first",
                )

    def apply(h: dict) -> dict:
        if user is not None:
            h["user"] = user
        if port is not None:
            h["port"] = port
        if alias is not None:
            h["alias"] = alias
        if hostname_new is not None:
            new_ip = hostname_new.strip()
            if new_ip and new_ip != h["hostname"]:
                h["hostname"] = new_ip
                for addr in h.get("addresses", []):
                    if addr.get("is_primary"):
                        addr["address"] = new_ip
                        break
        return h

    if not update_host(canonical, apply):
        emit_error(f"failed to update host {old_name!r}")
    new_name = alias if alias is not None else old_name
    stream_action(resource=f"host/{new_name}", message="updated")
    if hostname_new is not None and hostname_new.strip() != canonical:
        key_id = host.get("key_id", canonical)
        stream_action(
            resource=f"host/{new_name}",
            message=(
                f"SSH key (key_id: {key_id}) unchanged"
                " — confirm authorized_keys on the new address"
            ),
        )

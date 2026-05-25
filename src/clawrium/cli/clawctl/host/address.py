"""`clawctl host address <hostname> {add|delete|get|set-primary}`.

Nested verb group; each sub-verb wraps a `core/hosts.py` address API.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.host._shared import display_name, hostname_key, safe_get_host
from clawrium.cli.output import emit_error, render_table, stream_action
from clawrium.core.hosts import (
    AddressError,
    add_address_to_host,
    get_host_addresses,
    remove_address_from_host,
    set_primary_address,
)

__all__ = ["address_app"]


address_app = typer.Typer(
    name="address",
    help="Manage host addresses (multi-value).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


@address_app.command("add")
def add(
    hostname: str = typer.Argument(..., help="Host name or alias."),
    address: str = typer.Argument(..., help="Address to add (IP or FQDN)."),
    label: str = typer.Option("", "--label", help="Optional label for the address."),
) -> None:
    """Add an address to a host."""
    host = safe_get_host(hostname)
    canonical = hostname_key(host)
    name = display_name(host)
    try:
        add_address_to_host(canonical, address, label or None)
    except AddressError as exc:
        emit_error(str(exc))
    stream_action(resource=f"host/{name}", message=f"added address {address}")


@address_app.command("delete")
def delete(
    hostname: str = typer.Argument(..., help="Host name or alias."),
    address: str = typer.Argument(..., help="Address to remove."),
) -> None:
    """Remove an address from a host."""
    host = safe_get_host(hostname)
    canonical = hostname_key(host)
    name = display_name(host)
    try:
        remove_address_from_host(canonical, address)
    except AddressError as exc:
        emit_error(str(exc))
    stream_action(resource=f"host/{name}", message=f"removed address {address}")


@address_app.command("get")
def get(
    hostname: str = typer.Argument(..., help="Host name or alias."),
) -> None:
    """List addresses for a host."""
    host = safe_get_host(hostname)
    canonical = hostname_key(host)
    addrs = get_host_addresses(canonical)
    headers = ["ADDRESS", "PRIMARY", "LABEL", "ADDED"]
    body = [
        [
            str(a.get("address", "")),
            "yes" if a.get("is_primary") else "no",
            str(a.get("label") or "-"),
            str(a.get("added_at") or "-"),
        ]
        for a in addrs
    ]
    typer.echo(render_table(headers, body), nl=False)


@address_app.command("set-primary")
def set_primary(
    hostname: str = typer.Argument(..., help="Host name or alias."),
    address: str = typer.Argument(..., help="Address to mark as primary."),
) -> None:
    """Mark one of a host's addresses as the primary."""
    host = safe_get_host(hostname)
    canonical = hostname_key(host)
    name = display_name(host)
    try:
        set_primary_address(canonical, address)
    except AddressError as exc:
        emit_error(str(exc))
    stream_action(resource=f"host/{name}", message=f"primary address set to {address}")

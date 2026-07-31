"""Shared host helpers: lookup + row serialization.

Centralizes the host-record → output-row transformation so `get`,
`describe`, and `-o yaml|json|name` produce identical shapes.
"""

from __future__ import annotations

from typing import Optional

from clawrium.cli.clawctl._common import now_seconds_since
from clawrium.cli.output import emit_error
from clawrium.core.hosts import (
    HostsFileCorruptedError,
    get_host,
    load_hosts,
)


def safe_load_hosts() -> list[dict]:
    try:
        return load_hosts()
    except HostsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/hosts.json")


def safe_get_host(identifier: str) -> dict:
    try:
        host = get_host(identifier)
    except HostsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/hosts.json")
    if not host:
        emit_error(
            f"host {identifier!r} not found",
            hint="clawctl host get",
        )
    return host  # type: ignore[return-value]


def primary_address(host: dict) -> str:
    """Return the primary address for a host (fallback to hostname)."""
    for addr in host.get("addresses", []) or []:
        if addr.get("is_primary"):
            return str(addr.get("address") or host.get("hostname", ""))
    return str(host.get("hostname", ""))


def derive_status(host: dict) -> str:
    """Coarse host status derived from `metadata.last_seen` presence.

    Plan §6.13 status vocabulary doesn't define a "host-level" enum;
    we use `ready` if `last_seen` is set (host has been contacted),
    else `pending`. Reset clears it back to `pending`.
    """
    if host.get("metadata", {}).get("last_seen"):
        return "ready"
    return "pending"


def matches_label_selector(host: dict, selector: dict[str, str]) -> bool:
    """Return True if `host` matches every KEY=VALUE in `selector`.

    Host labels live under `metadata.labels` going forward (plan §4
    moved `tag` → `label`). For backwards-compat we also accept the
    legacy `metadata.tags` list-form where VALUE must be empty.
    """
    if not selector:
        return True
    labels = host.get("metadata", {}).get("labels", {}) or {}
    legacy_tags = host.get("metadata", {}).get("tags", []) or []
    for key, want in selector.items():
        if key in labels:
            if labels[key] != want:
                return False
            continue
        if want == "" and key in legacy_tags:
            continue
        return False
    return True


def host_to_row(host: dict) -> dict:
    """Render a host as a serializable row (snake_case keys, plan §6.5)."""
    meta = host.get("metadata", {}) or {}
    return {
        "kind": "host",
        "name": host.get("alias") or host.get("hostname", ""),
        "hostname": host.get("hostname", ""),
        "address": primary_address(host),
        "user": host.get("user", ""),
        "port": host.get("port"),
        "status": derive_status(host),
        "age_seconds": now_seconds_since(meta.get("added_at")),
        "added_at": meta.get("added_at"),
        "last_seen": meta.get("last_seen"),
        "labels": meta.get("labels", {}) or {},
        "aliases": host.get("aliases")
        or ([host["alias"]] if host.get("alias") else []),
        "addresses": host.get("addresses", []) or [],
        "description": host.get("description", ""),
    }


def display_name(host: dict) -> str:
    return host.get("alias") or host.get("hostname", "")


def hostname_key(host: dict) -> str:
    """Return the canonical hostname used by `core/hosts.py` updaters."""
    return host["hostname"]


def selector_option_help() -> str:
    return "Label selector (KEY=VALUE). Repeatable."


def maybe_alias(host: Optional[dict]) -> str:
    if not host:
        return ""
    return display_name(host)

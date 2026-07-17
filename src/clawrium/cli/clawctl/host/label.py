"""`clawctl host label <hostname> KEY=VALUE [KEY=VALUE ...] [KEY- ...]`.

Replaces legacy `clawctl host tag`. Stores labels under `metadata.labels`
(dict) going forward. Legacy `metadata.tags` (list) is migrated lazily
when labels are touched on a record.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl._common import parse_kv_pairs
from clawrium.cli.clawctl.host._shared import display_name, hostname_key, safe_get_host
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.hosts import update_host


def label(
    hostname: str = typer.Argument(..., help="Host name or alias."),
    pairs: list[str] = typer.Argument(
        ..., help="Label pairs: KEY=VALUE to set, KEY- to delete."
    ),
) -> None:
    """Set or delete labels on a host."""
    host = safe_get_host(hostname)
    canonical = hostname_key(host)
    name = display_name(host)

    set_map, delete_keys = parse_kv_pairs(pairs)

    def apply(h: dict) -> dict:
        meta = h.setdefault("metadata", {})
        labels = meta.setdefault("labels", {})
        # Migrate legacy tags (list) into labels (dict) lazily — once a
        # label op is invoked, we adopt the new shape.
        legacy_tags = meta.get("tags")
        if isinstance(legacy_tags, list) and not labels:
            for tag in legacy_tags:
                labels[str(tag)] = ""
        for key, value in set_map.items():
            labels[key] = value
        for key in delete_keys:
            labels.pop(key, None)
        return h

    if not update_host(canonical, apply):
        emit_error(f"failed to update labels for {name!r}")
    stream_action(resource=f"host/{name}", message="labels updated")

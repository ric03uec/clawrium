"""`clawctl agent get` — list agents across the fleet.

Plan §6.2 default columns: NAME TYPE HOST PROVIDER STATUS AGE
Plan §6.3 wide columns: + ADDRESS PORT VERSION INSTALLED
"""

from __future__ import annotations

from typing import Optional

import typer

from clawrium.cli.clawctl._common import OutputFormat, parse_kv_labels
from clawrium.cli.clawctl.agent._shared import agent_to_row
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    format_age,
    format_status,
    render_table,
)
from clawrium.core.hosts import HostsFileCorruptedError, load_hosts


def get(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    selectors: Optional[list[str]] = typer.Option(
        None,
        "-l",
        "--selector",
        help="Label selector (KEY=VALUE) on host labels. Repeatable.",
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip the header row."),
) -> None:
    """List installed agents (filterable by host labels)."""
    selector = parse_kv_labels(selectors)
    try:
        hosts = load_hosts()
    except HostsFileCorruptedError as exc:
        from clawrium.cli.output import emit_error

        emit_error(str(exc), hint="check ~/.config/clawrium/hosts.json")

    rows: list[dict] = []
    for host in hosts:
        if selector and not _host_matches(host, selector):
            continue
        for agent_key, claw_record in (host.get("agents") or {}).items():
            rows.append(agent_to_row(host, agent_key, claw_record))

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return
    if output is OutputFormat.name:
        typer.echo(dump_name(rows), nl=False)
        return

    if output is OutputFormat.wide:
        headers = [
            "NAME",
            "TYPE",
            "HOST",
            "ADDRESS",
            "PROVIDER",
            "STATUS",
            "AGE",
            "PORT",
            "VERSION",
            "RUNTIME",
            "INSTALLED",
        ]
        body = [
            [
                str(r["name"]),
                str(r["type"]),
                str(r["host"]),
                str(r["address"]),
                str(r["provider"] or "-"),
                format_status(str(r["status"])),
                format_age(int(r["age_seconds"])),
                str(r["port"] or "-"),
                str(r["version"] or "-"),
                str(r.get("runtime") or "-"),
                str(r["installed_at"] or "-"),
            ]
            for r in rows
        ]
    else:
        # Phase 3 of #11 (issue #945): RUNTIME column at the end of the
        # default view — every openclaw row shows `nemoclaw@<version>`.
        # Non-openclaw agents render "-" so the shape stays uniform.
        headers = [
            "NAME",
            "TYPE",
            "HOST",
            "PROVIDER",
            "STATUS",
            "AGE",
            "RUNTIME",
        ]
        body = [
            [
                str(r["name"]),
                str(r["type"]),
                str(r["host"]),
                str(r["provider"] or "-"),
                format_status(str(r["status"])),
                format_age(int(r["age_seconds"])),
                str(r.get("runtime") or "-"),
            ]
            for r in rows
        ]

    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


def _host_matches(host: dict, selector: dict[str, str]) -> bool:
    from clawrium.cli.clawctl.host._shared import matches_label_selector

    return matches_label_selector(host, selector)

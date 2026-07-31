"""`clawctl host describe <hostname>` — single-host detail view.

Plan §6.7 layout for the human-readable form; `-o yaml|json` returns
the structured row (same shape as `get -o yaml|json` for a single
record).
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl.host._shared import host_to_row, safe_get_host
from clawrium.cli.output import dump_json, dump_yaml, format_age, format_status
from clawrium.cli.output._sanitize import sanitize


def _s(value: object) -> str:
    """Per-field sanitize (ATX iter-1 B1).

    Applied at every f-string interpolation site so a host alias / agent
    name carrying U+202E from hosts.json cannot reverse the terminal.
    Crucially, sanitize collapses control chars including `\\n`, so we
    MUST call it per cell, not on the joined block.
    """
    return sanitize(str(value))


def describe(
    hostname: str = typer.Argument(..., help="Host name or alias."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (yaml/json or text)."
    ),
) -> None:
    """Describe a single host."""
    host = safe_get_host(hostname)
    row = host_to_row(host)

    if output is OutputFormat.json:
        typer.echo(dump_json([row]), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml([row]), nl=False)
        return

    lines: list[str] = []
    lines.append(f"Name:       {_s(row['name'])}")
    lines.append("Kind:       host")
    lines.append(f"Address:    {_s(row['address'])}")
    lines.append(f"User:       {_s(row['user'] or '-')}")
    lines.append(f"Port:       {_s(row['port'] or '-')}")
    lines.append(f"Description: {_s(row['description'] or '-')}")
    lines.append(f"Status:     {format_status(_s(row['status']))}")
    lines.append(f"Age:        {format_age(int(row['age_seconds']))}")
    lines.append(f"Added:      {_s(row['added_at'] or '-')}")
    lines.append(f"Last seen:  {_s(row['last_seen'] or '-')}")

    aliases = row["aliases"]
    if aliases:
        lines.append("")
        lines.append(f"Aliases ({len(aliases)}):")
        for alias in aliases:
            lines.append(f"  {_s(alias)}")

    addresses = row["addresses"]
    if addresses:
        lines.append("")
        lines.append(f"Addresses ({len(addresses)}):")
        for addr in addresses:
            mark = "*" if addr.get("is_primary") else " "
            label = addr.get("label") or ""
            label_part = f"  ({_s(label)})" if label else ""
            lines.append(f"  {mark} {_s(addr.get('address'))}{label_part}")

    labels = row["labels"]
    if labels:
        lines.append("")
        lines.append(f"Labels ({len(labels)}):")
        for key in sorted(labels):
            lines.append(f"  {_s(key)}={_s(labels[key])}")

    agents = host.get("agents", {}) or {}
    if agents:
        lines.append("")
        lines.append(f"Agents ({len(agents)}):")
        for key, record in agents.items():
            agent_type = record.get("type") or key
            agent_name = record.get("agent_name") or key
            status = record.get("status", "unknown")
            lines.append(f"  {_s(agent_name)}  ({_s(agent_type)})  {_s(status)}")

    typer.echo("\n".join(lines))

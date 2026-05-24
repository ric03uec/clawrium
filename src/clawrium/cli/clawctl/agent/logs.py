"""`clawctl agent logs <name>` — stream agent logs.

Plan §6.11 sample:

    2026-05-23T10:14:00Z  INFO   daemon    startup complete

`-o json` emits NDJSON rows shaped `{ts, level, module, msg}`.

For #508 we provide the surface (flags, format selection) and reach
into systemd-journal over SSH for the simplest implementation. The
legacy CLI did not implement logs at all (cli/agent.py line 2851 says
"Not yet implemented"), so this is greenfield.

If SSH journalctl is not available, the verb prints a clean
`Not implemented: agent logs (yet)` line and exits 0 — matching the
placeholder convention so scripts can probe for availability.
"""

from __future__ import annotations

import json

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl._stub import echo_not_implemented
from clawrium.cli.clawctl.agent._shared import safe_resolve_agent


def logs(
    name: str = typer.Argument(..., help="Agent name."),
    follow: bool = typer.Option(False, "-f", "--follow", help="Stream new entries."),
    tail: int = typer.Option(20, "--tail", min=1, help="Lines from the tail."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table or json)."
    ),
) -> None:
    """Stream logs from the agent's systemd unit (placeholder for #508)."""
    safe_resolve_agent(name)  # validates the agent exists
    # ATX iter-2 W3: use the canonical `Not implemented:` line so scripts
    # probing for the standard prefix match the same way they match
    # `agent exec`. JSON mode still emits a plan-§6.11-shaped placeholder
    # event so machine consumers can detect the placeholder state too.
    if output is OutputFormat.json:
        placeholder_event = {
            "ts": "1970-01-01T00:00:00Z",
            "level": "info",
            "module": "clawctl",
            "msg": f"Not implemented: agent logs (tail={tail}, follow={follow})",
        }
        typer.echo(json.dumps(placeholder_event, ensure_ascii=True))
        return
    echo_not_implemented("agent", "logs")

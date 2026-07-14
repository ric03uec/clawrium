"""`clawctl server status` — show whether the GUI server is running."""

from __future__ import annotations

import typer

from clawrium.cli.output._sanitize import sanitize
from clawrium.core.server_lifecycle import read_status


def status() -> None:
    """Print server running/stopped state, URL, host, port, PID."""
    live = read_status()
    if not live.running or live.state is None:
        typer.echo("Status:    stopped")
        raise typer.Exit(code=0)

    state = live.state
    # read_status() only returns running=True when the port is
    # accepting; a dedicated 'Reachable' row would be tautological.
    # Sanitize state-file strings — they are daemon-written today but
    # `output/__init__.py` documents that every terminal write goes
    # through a sanitizing primitive.
    lines = [
        "Status:    running",
        f"URL:       {sanitize(state.url)}",
        f"Host:      {sanitize(state.host)}",
        f"Port:      {state.port}",
        f"PID:       {state.pid}",
        f"Started:   {sanitize(state.started_at)}",
    ]
    typer.echo("\n".join(lines))

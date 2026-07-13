"""`clawctl server` — GUI server lifecycle.

Verbs: `start`, `stop`, `status`, `run`. See .itx/874/00_PLAN.md for
the design rationale (fixed port 36000, detached POSIX spawn,
loopback-only bind, no auto-start).
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.server.run import run
from clawrium.cli.clawctl.server.start import start
from clawrium.cli.clawctl.server.status import status
from clawrium.cli.clawctl.server.stop import stop

__all__ = ["server_app"]


server_app = typer.Typer(
    name="server",
    help="Manage the local GUI server (loopback-only, port 36000).",
    no_args_is_help=True,
    rich_markup_mode=None,
)

server_app.command(name="start", help="Start the GUI server in the background.")(start)
server_app.command(name="stop", help="Stop the running GUI server.")(stop)
server_app.command(name="status", help="Show whether the GUI server is running.")(status)
server_app.command(name="run", help="Run the GUI server in the foreground (systemd/Docker).")(run)

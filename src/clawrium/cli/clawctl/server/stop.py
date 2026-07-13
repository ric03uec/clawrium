"""`clawctl server stop` — stop the running GUI server."""

from __future__ import annotations

import typer

from clawrium.cli.output.errors import emit_error
from clawrium.core.server_lifecycle import ServerNotRunningError, stop_running


def stop() -> None:
    """Stop the running GUI server; no-op with clear message if not running."""
    try:
        state = stop_running()
    except ServerNotRunningError:
        typer.echo("Server is not running")
        raise typer.Exit(code=0)
    except (PermissionError, OSError) as exc:
        # Recorded PID may belong to a process owned by another user
        # (e.g. root-started daemon, non-root stop). Surface a clean
        # error instead of a raw traceback. emit_error is NoReturn
        # today; the explicit Exit is belt-and-suspenders so a future
        # signature change cannot fall through to the success line
        # with `state` unbound.
        emit_error(f"stop failed: {exc}")
        raise typer.Exit(code=1)

    typer.echo(f"Server stopped (pid {state.pid}, {state.url})")

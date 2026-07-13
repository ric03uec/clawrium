"""`clawctl server start` — start the GUI server in the background."""

from __future__ import annotations

import typer

from clawrium.cli.output.errors import emit_error
from clawrium.core.server_lifecycle import (
    PortInUseError,
    ServerAlreadyRunningError,
    ServerStartupError,
    start_detached,
)


def start() -> None:
    """Start the GUI server detached from the current shell.

    Idempotent: a second call while the server is running prints the
    live URL and exits 0. If :36000 is held by a foreign process the
    command fails with exit 1 and does not touch state.
    """
    try:
        state = start_detached()
    except ServerAlreadyRunningError as exc:
        typer.echo(f"Server already running at {exc.state.url}")
        raise typer.Exit(code=0)
    except PortInUseError as exc:
        emit_error(
            f"port already in use: {exc}",
            hint="Stop the process holding TCP :36000 and try again.",
        )
        raise typer.Exit(code=1)
    except ServerStartupError as exc:
        emit_error(f"server failed to start: {exc}")
        raise typer.Exit(code=1)
    except RuntimeError as exc:
        # Platform gate (Linux-only in PR 1).
        emit_error(str(exc))
        raise typer.Exit(code=1)

    typer.echo(f"Server started at {state.url} (pid {state.pid})")

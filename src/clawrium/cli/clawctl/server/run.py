"""`clawctl server run` — run the GUI server in the foreground.

Intended for systemd/Docker/`--foreground` use. Does not write the
state file; the process manager owns lifecycle.
"""

from __future__ import annotations

import typer

from clawrium.cli.output._sanitize import sanitize
from clawrium.cli.output.errors import emit_error
from clawrium.core.server_lifecycle import (
    GUI_HOST,
    GUI_PORT,
    ServerPlatformError,
    _assert_supported_platform,
)


def run() -> None:
    """Run uvicorn on 127.0.0.1:36000 in the foreground (blocking)."""
    try:
        _assert_supported_platform()
    except ServerPlatformError as exc:
        emit_error(str(exc))
        raise typer.Exit(code=1)
    try:
        import uvicorn
    except ImportError:
        # emit_error is NoReturn today; the explicit Exit is
        # belt-and-suspenders defense so a future signature change
        # cannot fall through to `uvicorn.run(...)` with `uvicorn`
        # unbound.
        emit_error(
            "GUI dependencies missing",
            hint="Reinstall with: uv tool install --force clawrium",
        )
        raise typer.Exit(code=1)

    url = f"http://{GUI_HOST}:{GUI_PORT}"
    typer.echo(f"Serving GUI at {sanitize(url)} — press Ctrl+C to stop")
    uvicorn.run(
        "clawrium.gui.server:app",
        host=GUI_HOST,
        port=GUI_PORT,
        log_level="info",
    )

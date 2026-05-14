"""GUI command - Launch the local web dashboard."""

import threading

import typer
from rich.console import Console

console = Console()

GUI_HOST = "127.0.0.1"
_BROWSER_OPEN_DELAY_SECONDS = 1.0


def gui(port: int = 36000, no_open: bool = False) -> None:
    """Launch the local web GUI dashboard.

    Called as plain Python from cli/main.py; defaults and validation are
    declared there. Binds uvicorn to 127.0.0.1 only.
    """
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Error:[/red] GUI requires extra dependencies. "
            "Reinstall with: uv tool install --force 'clawrium[gui]'"
        )
        raise typer.Exit(code=1)

    url = f"http://{GUI_HOST}:{port}"
    console.print(
        f"[bold]Clawrium GUI[/bold] starting on [cyan]{url}[/cyan] — "
        "press Ctrl+C to stop"
    )

    open_timer: threading.Timer | None = None
    if not no_open:
        import webbrowser

        # uvicorn.run() blocks until shutdown, so the browser open has to be
        # scheduled. Opening synchronously before bind always races the
        # listener; a short Timer lets uvicorn bind first, and any first-hit
        # connection-refused retries cleanly. We hold a reference so that we
        # can cancel it if uvicorn fails to bind (port-in-use) and never
        # actually starts serving.
        open_timer = threading.Timer(
            _BROWSER_OPEN_DELAY_SECONDS, webbrowser.open, args=[url]
        )
        open_timer.daemon = True
        open_timer.start()

    try:
        uvicorn.run(
            "clawrium.gui.server:app",
            host=GUI_HOST,
            port=port,
            log_level="info",
        )
    except BaseException:
        if open_timer is not None:
            open_timer.cancel()
        raise

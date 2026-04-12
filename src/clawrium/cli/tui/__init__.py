"""Clawrium TUI - Interactive terminal dashboard for fleet management."""

from clawrium.cli.tui.app import ClawriumApp

__all__ = ["launch_tui"]


def launch_tui() -> None:
    """Launch the Clawrium TUI application."""
    app = ClawriumApp()
    app.run()

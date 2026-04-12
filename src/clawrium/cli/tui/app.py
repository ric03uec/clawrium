"""Main TUI application class."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from clawrium.cli.tui.screens.fleet import FleetScreen

__all__ = ["ClawriumApp"]


class ClawriumApp(App):
    """Clawrium fleet management dashboard."""

    TITLE = "Clawrium"
    SUB_TITLE = "Fleet Dashboard"

    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question", "show_help", "Help", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield FleetScreen()
        yield Footer()

    def on_screen_resume(self, event) -> None:
        if isinstance(event.screen, FleetScreen):
            self.sub_title = "Fleet Dashboard"

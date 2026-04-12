"""Main TUI application class."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual import work
from textual.widgets import DataTable, Footer, Header, Label

from clawrium.cli.tui.widgets.agent_table import AgentTable
from clawrium.cli.tui.widgets.metrics_bar import MetricsBar

__all__ = ["ClawriumApp"]


class ClawriumApp(App):
    """Clawrium fleet management dashboard."""

    TITLE = "Clawrium"
    SUB_TITLE = "Fleet Dashboard"

    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("d", "view_detail", "Details", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label("FLEET OVERVIEW", id="fleet-label")
        yield MetricsBar(id="fleet-metrics")
        yield AgentTable(id="fleet-table")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_fleet()

    def refresh_fleet(self) -> None:
        fleet_worker = getattr(self, "_fleet_worker", None)
        if fleet_worker is not None and not fleet_worker.is_finished:
            fleet_worker.cancel()
        self._fleet_worker = self._load_data_async()

    @work(thread=True)
    def _load_data_async(self) -> None:
        from textual.worker import get_current_worker
        from clawrium.cli.tui.data import get_fleet_data

        worker = get_current_worker()
        try:
            agents, summary = get_fleet_data()
        except Exception as e:
            if worker.is_cancelled:
                return
            self.call_from_thread(
                self.notify,
                f"Failed to load fleet data: {e}",
                severity="error",
            )
            return
        if worker.is_cancelled:
            return
        self.call_from_thread(self._update_ui, agents, summary)

    def _update_ui(self, agents, summary) -> None:
        metrics = self.query_one("#fleet-metrics", MetricsBar)
        metrics.update_summary(summary)
        table = self.query_one("#fleet-table", AgentTable)
        table.load_agents(agents)
        self.sub_title = (
            f"Fleet Dashboard — {summary['total']} agents, {summary['running']} running"
        )

    def action_view_detail(self) -> None:
        table = self.query_one("#fleet-table", AgentTable)
        agent = table.get_selected_agent()
        if not agent:
            self.notify("No agent selected", severity="warning")
            return

        from clawrium.cli.tui.screens.detail import DetailScreen

        if any(isinstance(screen, DetailScreen) for screen in self.screen_stack):
            return

        self.push_screen(DetailScreen(agent=agent))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "fleet-table":
            self.action_view_detail()

    def action_refresh(self) -> None:
        self.refresh_fleet()

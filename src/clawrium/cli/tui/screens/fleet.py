"""Fleet overview screen - main dashboard showing all agents."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual import work
from textual.screen import Screen
from textual.widgets import DataTable, Label
from textual.worker import get_current_worker

from clawrium.cli.tui.data import get_fleet_data
from clawrium.cli.tui.widgets.agent_table import AgentTable
from clawrium.cli.tui.widgets.metrics_bar import MetricsBar


class FleetScreen(Screen):
    BINDINGS = [
        Binding("d", "view_detail", "Details", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._filter_text: str = ""

    def compose(self) -> ComposeResult:
        yield Label("FLEET OVERVIEW", id="fleet-label")
        yield MetricsBar(id="fleet-metrics")
        yield AgentTable(id="fleet-table")

    def on_mount(self) -> None:
        self._load_data_async()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#fleet-table", AgentTable)
        agent = table.get_selected_agent()
        if agent:
            from clawrium.cli.tui.screens.detail import DetailScreen

            self.app.push_screen(DetailScreen(agent=agent))

    @work(thread=True)
    def _load_data_async(self) -> None:
        worker = get_current_worker()
        agents, summary = get_fleet_data(host_filter=self._filter_text or None)
        if worker.is_cancelled:
            return
        self.app.call_from_thread(self._update_ui, agents, summary)

    def _update_ui(self, agents, summary) -> None:
        metrics = self.query_one("#fleet-metrics", MetricsBar)
        metrics.update_summary(summary)
        table = self.query_one("#fleet-table", AgentTable)
        table.load_agents(agents)
        self.app.sub_title = (
            f"Fleet Dashboard — {summary['total']} agents, {summary['running']} running"
        )

    def action_view_detail(self) -> None:
        table = self.query_one("#fleet-table", AgentTable)
        agent = table.get_selected_agent()
        if agent:
            from clawrium.cli.tui.screens.detail import DetailScreen

            self.app.push_screen(DetailScreen(agent=agent))

    def action_refresh(self) -> None:
        self._load_data_async()

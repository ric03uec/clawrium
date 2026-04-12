"""Agent detail screen - shows detailed information for a single agent."""

from __future__ import annotations

from rich.markup import escape

from textual.app import ComposeResult
from textual.binding import Binding
from textual import work
from textual.screen import Screen
from textual.widgets import Label, Static
from textual.worker import get_current_worker

from clawrium.cli.tui.data import AgentViewModel, get_agent_detail
from clawrium.cli.tui.widgets.detail_cards import DetailCards


class ConfirmModal(Screen):
    BINDINGS = [
        Binding("y", "confirm", "Yes", show=True),
        Binding("n", "cancel", "No", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        yield Label(self._message)
        yield Static("[dim]Press 'y' to confirm, 'n' or 'esc' to cancel[/dim]")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class DetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("s", "stop_agent", "Stop", show=True),
        Binding("r", "restart_agent", "Restart", show=True),
    ]

    def __init__(self, agent: AgentViewModel, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent = agent

    def compose(self) -> ComposeResult:
        yield Label(
            f"AGENT DETAIL — {escape(self._agent['agent_name'])}",
            id="detail-label",
        )
        yield DetailCards(agent=self._agent, id="detail-cards")
        yield Static(
            "[dim]Press 's' to stop, 'r' to restart, 'esc' to go back[/dim]",
            id="detail-hint",
        )

    def on_mount(self) -> None:
        self.app.sub_title = (
            f"{escape(self._agent['agent_name'])} · "
            f"{escape(self._agent['agent_type'])} · "
            f"{escape(self._agent['host_alias'])}"
        )

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_stop_agent(self) -> None:
        agent_key = escape(self._agent["agent_key"])
        host = escape(self._agent["host"])
        self.app.push_screen(
            ConfirmModal(f"Stop {agent_key} on {host}?"),
            callback=lambda confirmed: self._do_stop(confirmed) if confirmed else None,
        )

    def action_restart_agent(self) -> None:
        agent_key = escape(self._agent["agent_key"])
        host = escape(self._agent["host"])
        self.app.push_screen(
            ConfirmModal(f"Restart {agent_key} on {host}?"),
            callback=lambda confirmed: (
                self._do_restart(confirmed) if confirmed else None
            ),
        )

    @work(thread=True)
    def _do_stop(self, confirmed: bool) -> None:
        if not confirmed:
            return
        from clawrium.core.lifecycle import stop_agent

        agent_key = self._agent["agent_key"]
        host = self._agent["host"]
        agent_type = self._agent["agent_type"]
        try:
            result = stop_agent(host, agent_type, agent_name=agent_key)
            if result["success"]:
                self.app.call_from_thread(
                    self.notify,
                    f"Stopped {agent_key} on {host}",
                    severity="information",
                )
            else:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to stop: {result.get('error', 'unknown')}",
                    severity="error",
                )
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Error: {e}", severity="error")
        self.app.call_from_thread(self._refresh_async)

    @work(thread=True)
    def _do_restart(self, confirmed: bool) -> None:
        if not confirmed:
            return
        from clawrium.core.lifecycle import restart_agent

        agent_key = self._agent["agent_key"]
        host = self._agent["host"]
        agent_type = self._agent["agent_type"]
        try:
            result = restart_agent(host, agent_type, agent_name=agent_key)
            if result["success"]:
                self.app.call_from_thread(
                    self.notify,
                    f"Restarted {agent_key} on {host}",
                    severity="information",
                )
            else:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to restart: {result.get('error', 'unknown')}",
                    severity="error",
                )
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Error: {e}", severity="error")
        self.app.call_from_thread(self._refresh_async)

    @work(thread=True)
    def _refresh_async(self) -> None:
        worker = get_current_worker()
        updated = get_agent_detail(self._agent["agent_key"], self._agent["host"])
        if worker.is_cancelled:
            return
        if updated:
            self._agent = updated
            self.app.call_from_thread(self._update_cards, updated)

    def _update_cards(self, updated: AgentViewModel) -> None:
        self._agent = updated
        cards = self.query_one("#detail-cards", DetailCards)
        cards.update_agent(updated)

"""Agent detail screen - shows detailed information for a single agent."""

from __future__ import annotations

from rich.markup import escape

from textual.app import ComposeResult
from textual.binding import Binding
from textual import work
from textual.screen import ModalScreen, Screen
from textual.widgets import Label, Static
from textual.worker import get_current_worker

from clawrium.cli.tui.data import AgentViewModel, get_agent_detail
from clawrium.cli.tui.widgets.detail_cards import DetailCards
from clawrium.core.health import ClawStatus
from clawrium.core.lifecycle import restart_agent, stop_agent


class ConfirmModal(ModalScreen[bool]):
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
        self.dismiss()

    def on_unmount(self) -> None:
        self.app.sub_title = "Fleet Dashboard"

    def action_stop_agent(self) -> None:
        if self._agent["status"] not in (ClawStatus.RUNNING, ClawStatus.DEGRADED):
            self.notify("Agent is not running", severity="warning")
            return
        agent_key = escape(self._agent["agent_key"])
        host = escape(self._agent["host"])
        self.app.push_screen(
            ConfirmModal(f"Stop {agent_key} on {host}?"),
            callback=self._on_stop_confirmed,
        )

    def action_restart_agent(self) -> None:
        if self._agent["status"] not in (ClawStatus.RUNNING, ClawStatus.DEGRADED):
            self.notify("Agent is not restartable in current state", severity="warning")
            return
        agent_key = escape(self._agent["agent_key"])
        host = escape(self._agent["host"])
        self.app.push_screen(
            ConfirmModal(f"Restart {agent_key} on {host}?"),
            callback=self._on_restart_confirmed,
        )

    def _on_stop_confirmed(self, confirmed: bool) -> None:
        if confirmed:
            self._do_stop()

    def _on_restart_confirmed(self, confirmed: bool) -> None:
        if confirmed:
            self._do_restart()

    @work(thread=True)
    def _do_stop(self) -> None:
        worker = get_current_worker()
        agent_key = self._agent["agent_key"]
        host = self._agent["host"]
        current = get_agent_detail(agent_key, host)
        if not current:
            self.app.call_from_thread(self._on_agent_removed)
            return
        if current["status"] not in (ClawStatus.RUNNING, ClawStatus.DEGRADED):
            self.app.call_from_thread(
                self.notify, "Agent is no longer running", severity="warning"
            )
            if not worker.is_cancelled:
                self._refresh_async()
            return
        agent_type = current["agent_type"]
        try:
            result = stop_agent(host, agent_type, agent_name=agent_key)
            if worker.is_cancelled:
                return
            if result["success"]:
                self.app.call_from_thread(
                    self.notify,
                    f"Stopped {escape(agent_key)} on {escape(host)}",
                    severity="information",
                )
            else:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to stop: {escape(str(result.get('error', 'unknown')))}",
                    severity="error",
                )
        except Exception as e:
            if worker.is_cancelled:
                return
            self.app.call_from_thread(
                self.notify, f"Error: {escape(str(e))}", severity="error"
            )
        if not worker.is_cancelled:
            self._refresh_async()

    @work(thread=True)
    def _do_restart(self) -> None:
        worker = get_current_worker()
        agent_key = self._agent["agent_key"]
        host = self._agent["host"]
        current = get_agent_detail(agent_key, host)
        if not current:
            self.app.call_from_thread(self._on_agent_removed)
            return
        if current["status"] not in (ClawStatus.RUNNING, ClawStatus.DEGRADED):
            self.app.call_from_thread(
                self.notify,
                "Agent is no longer restartable",
                severity="warning",
            )
            if not worker.is_cancelled:
                self._refresh_async()
            return
        agent_type = current["agent_type"]
        try:
            result = restart_agent(host, agent_type, agent_name=agent_key)
            if worker.is_cancelled:
                return
            if result["success"]:
                self.app.call_from_thread(
                    self.notify,
                    f"Restarted {escape(agent_key)} on {escape(host)}",
                    severity="information",
                )
            else:
                self.app.call_from_thread(
                    self.notify,
                    f"Failed to restart: {escape(str(result.get('error', 'unknown')))}",
                    severity="error",
                )
        except Exception as e:
            if worker.is_cancelled:
                return
            self.app.call_from_thread(
                self.notify, f"Error: {escape(str(e))}", severity="error"
            )
        if not worker.is_cancelled:
            self._refresh_async()

    def _refresh_async(self) -> None:
        updated = get_agent_detail(self._agent["agent_key"], self._agent["host"])
        if updated:
            self.app.call_from_thread(self._update_cards, updated)
        else:
            self.app.call_from_thread(self._on_agent_removed)

    def _update_cards(self, updated: AgentViewModel) -> None:
        if not self.is_attached:
            return
        self._agent = updated
        cards = self.query_one("#detail-cards", DetailCards)
        cards.update_agent(updated)
        self.app.refresh_fleet()

    def _on_agent_removed(self) -> None:
        if not self.is_attached:
            return
        self.notify("Agent no longer exists, returning to fleet", severity="warning")
        self.dismiss()

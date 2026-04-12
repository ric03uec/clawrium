"""Agent detail screen - shows detailed information for a single agent."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Label, Static

from clawrium.cli.tui.data import AgentViewModel, get_agent_detail
from clawrium.cli.tui.widgets.detail_cards import DetailCards


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
            f"AGENT DETAIL — {self._agent['agent_name']}",
            id="detail-label",
        )
        yield DetailCards(agent=self._agent, id="detail-cards")
        yield Static(
            "[dim]Press 's' to stop, 'r' to restart, 'esc' to go back[/dim]",
            id="detail-hint",
        )

    def on_mount(self) -> None:
        self.app.sub_title = f"{self._agent['agent_name']} · {self._agent['agent_type']} · {self._agent['host_alias']}"

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_stop_agent(self) -> None:
        from clawrium.core.lifecycle import stop_agent

        agent_key = self._agent["agent_key"]
        host = self._agent["host"]
        agent_type = self._agent["agent_type"]
        try:
            result = stop_agent(host, agent_type, agent_name=agent_key)
            if result["success"]:
                self.notify(f"Stopped {agent_key} on {host}", severity="information")
            else:
                self.notify(
                    f"Failed to stop: {result.get('error', 'unknown')}",
                    severity="error",
                )
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
        self._refresh()

    def action_restart_agent(self) -> None:
        from clawrium.core.lifecycle import restart_agent

        agent_key = self._agent["agent_key"]
        host = self._agent["host"]
        agent_type = self._agent["agent_type"]
        try:
            result = restart_agent(host, agent_type, agent_name=agent_key)
            if result["success"]:
                self.notify(f"Restarted {agent_key} on {host}", severity="information")
            else:
                self.notify(
                    f"Failed to restart: {result.get('error', 'unknown')}",
                    severity="error",
                )
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
        self._refresh()

    def _refresh(self) -> None:
        updated = get_agent_detail(self._agent["agent_key"], self._agent["host"])
        if updated:
            self._agent = updated
            cards = self.query_one("#detail-cards", DetailCards)
            cards.update_agent(updated)

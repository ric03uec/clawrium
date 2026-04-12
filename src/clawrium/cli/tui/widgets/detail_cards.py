"""Agent detail cards widget."""

from __future__ import annotations

from rich.markup import escape

from textual.app import ComposeResult
from textual.containers import Grid
from textual.widget import Widget
from textual.widgets import Label, Static

from clawrium.cli.tui.data import AgentViewModel
from clawrium.core.health import ClawStatus


class DetailCard(Widget):
    DEFAULT_CSS = """
    DetailCard {
        background: $surface;
        border: round $primary-darken-2;
        padding: 1 2;
        height: auto;
    }
    DetailCard .card-title {
        text-style: bold;
        color: $text-disabled;
        margin: 0 0 1 0;
    }
    DetailCard .card-row {
        height: 1;
    }
    """

    def __init__(self, title: str, rows: list[tuple[str, str]], **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._rows = rows

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="card-title")
        for key, value in self._rows:
            yield Static(f"[dim]{key}[/dim]  {escape(str(value))}", classes="card-row")


class DetailCards(Grid):
    DEFAULT_CSS = """
    DetailCards {
        grid-size: 2;
        grid-gutter: 1 2;
        padding: 0 2;
        height: auto;
    }
    """

    def __init__(self, agent: AgentViewModel | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent = agent

    def compose(self) -> ComposeResult:
        if self._agent is None:
            return
        yield from self._build_cards(self._agent)

    def _build_cards(self, agent: AgentViewModel) -> list[DetailCard]:
        status = agent["status"]
        status_text = {
            ClawStatus.RUNNING: "running",
            ClawStatus.DEGRADED: "degraded",
            ClawStatus.STOPPED: "stopped",
            ClawStatus.NOT_INSTALLED: "not installed",
            ClawStatus.PENDING_ONBOARD: "pending onboard",
            ClawStatus.ONBOARDING: "onboarding",
            ClawStatus.READY: "ready",
            ClawStatus.UNKNOWN: "unknown",
        }.get(status, "unknown")

        identity_rows = [
            ("role", agent["agent_name"]),
            ("type", agent["agent_type"]),
            ("version", agent["version"]),
            (
                "host",
                f"{agent['host_alias']} ({agent['host']})"
                if agent["host_alias"] != agent["host"]
                else agent["host"],
            ),
            ("status", status_text),
            ("uptime", agent["uptime"]),
        ]

        model_cost_rows = [
            ("model", agent["model"]),
            ("tokens / 24h", "N/A"),
            ("tokens / 7d", "N/A"),
            ("est. cost / 24h", "N/A"),
            ("est. cost / 7d", "N/A"),
        ]

        secrets_status = "configured"
        if agent.get("missing_secrets"):
            secrets_status = f"missing: {len(agent['missing_secrets'])} key(s)"

        config_rows = [
            ("provider", "N/A"),
            ("gateway port", "N/A"),
            ("secrets", secrets_status),
        ]

        health_rows = [
            ("cpu", "N/A"),
            ("memory", "N/A"),
            ("errors / 24h", "N/A"),
        ]

        if agent.get("health_error"):
            identity_rows.append(("error", agent["health_error"][:50]))

        return [
            DetailCard("IDENTITY", identity_rows),
            DetailCard("MODEL & COST", model_cost_rows),
            DetailCard("CONFIGURATION", config_rows),
            DetailCard("HEALTH", health_rows),
        ]

    def update_agent(self, agent: AgentViewModel) -> None:
        self._agent = agent
        self.remove_children()
        for card in self._build_cards(agent):
            self.mount(card)

"""Agent table widget for fleet overview."""

from __future__ import annotations

import logging

from rich.markup import escape
from textual.widgets import DataTable

from clawrium.cli.tui.data import AgentViewModel
from clawrium.core.health import ClawStatus

COLUMNS = ("", "Agent", "Type", "Model", "Host", "Uptime", "Status")
logger = logging.getLogger(__name__)


def status_color(status: ClawStatus) -> str:
    color_map = {
        ClawStatus.RUNNING: "text-success",
        ClawStatus.DEGRADED: "warning",
        ClawStatus.STOPPED: "error",
        ClawStatus.NOT_INSTALLED: "warning",
        ClawStatus.PENDING_ONBOARD: "warning",
        ClawStatus.ONBOARDING: "cyan",
        ClawStatus.READY: "cyan",
        ClawStatus.UNKNOWN: "warning",
    }
    return color_map.get(status, "text")


def status_dot(status: ClawStatus) -> str:
    dot_map = {
        ClawStatus.RUNNING: "[text-success]●[/text-success]",
        ClawStatus.DEGRADED: "[warning]●[/warning]",
        ClawStatus.STOPPED: "[error]●[/error]",
        ClawStatus.NOT_INSTALLED: "[warning]○[/warning]",
        ClawStatus.PENDING_ONBOARD: "[warning]○[/warning]",
        ClawStatus.ONBOARDING: "[cyan]○[/cyan]",
        ClawStatus.READY: "[cyan]○[/cyan]",
        ClawStatus.UNKNOWN: "[warning]○[/warning]",
    }
    return dot_map.get(status, "[warning]○[/warning]")


def status_label(status: ClawStatus, error: str | None = None) -> str:
    label_map = {
        ClawStatus.RUNNING: "running",
        ClawStatus.DEGRADED: "degraded",
        ClawStatus.STOPPED: "stopped",
        ClawStatus.NOT_INSTALLED: "not installed",
        ClawStatus.PENDING_ONBOARD: "pending onboard",
        ClawStatus.ONBOARDING: "onboarding",
        ClawStatus.READY: "ready",
        ClawStatus.UNKNOWN: "unknown",
    }
    label = label_map.get(status, "unknown")
    if error and status == ClawStatus.UNKNOWN:
        display_error = error[:30] if len(error) > 30 else error
        display_error = escape(display_error)
        label = f"unknown ({display_error})"
    return label


class AgentTable(DataTable):
    DEFAULT_CSS = """
    AgentTable {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agents: list[AgentViewModel] = []

    def on_mount(self) -> None:
        for col in COLUMNS:
            self.add_column(col, key=col.lower().replace(" ", "_") if col else "dot")
        self.cursor_type = "row"
        self.zebra_stripes = True

    def load_agents(self, agents: list[AgentViewModel]) -> None:
        self._agents = agents
        self.clear()
        for agent in agents:
            status = agent["status"]
            label = status_label(status, agent.get("health_error"))
            self.add_row(
                status_dot(status),
                escape(agent["agent_name"]),
                escape(agent["agent_type"]),
                escape(agent["model"]),
                escape(agent["host_alias"]),
                escape(agent["uptime"]),
                f"[{status_color(status)}]{escape(label)}[/{status_color(status)}]",
                key=agent["agent_key"] + "@" + agent["host"],
            )

    def get_selected_agent(self) -> AgentViewModel | None:
        try:
            from textual.coordinate import Coordinate

            cell_key = self.coordinate_to_cell_key(Coordinate(self.cursor_row, 0))
            row_key = cell_key[0]
            key_str = str(row_key.value)
            for agent in self._agents:
                agent_key = agent["agent_key"] + "@" + agent["host"]
                if agent_key == key_str:
                    return agent
        except Exception as e:
            logger.debug("Failed to resolve selected agent: %s", e)
        return None

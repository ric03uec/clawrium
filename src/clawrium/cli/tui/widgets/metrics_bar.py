"""Summary metrics bar widget for fleet overview."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label

from clawrium.cli.tui.data import FleetSummary


class MetricCard(Widget):
    DEFAULT_CSS = """
    MetricCard {
        width: 1fr;
        height: auto;
        padding: 0 1;
        background: $surface;
        border: round $primary-darken-2;
    }
    MetricCard Label.metric-value {
        text-style: bold;
        width: 100%;
    }
    MetricCard Label.metric-label {
        color: $text-disabled;
        width: 100%;
    }
    """

    def __init__(
        self, value: str, label: str, value_color: str = "text", **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self._value = value
        self._label = label
        self._value_color = value_color
        self._label_id = label.replace(" ", "-").replace("/", "-")

    def compose(self) -> ComposeResult:
        yield Label(
            self._value, classes="metric-value", id=f"metric-val-{self._label_id}"
        )
        yield Label(self._label, classes="metric-label")

    def update_value(self, value: str) -> None:
        val_label = self.query_one(f"#metric-val-{self._label_id}", Label)
        val_label.update(value)


class MetricsBar(Widget):
    DEFAULT_CSS = """
    MetricsBar {
        height: auto;
        padding: 0 1;
        layout: horizontal;
    }
    """

    def __init__(self, summary: FleetSummary | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._summary = summary or FleetSummary(
            total=0, running=0, provisioning=0, hosts=0
        )

    def compose(self) -> ComposeResult:
        yield MetricCard(str(self._summary["total"]), "total agents", "text")
        yield MetricCard(str(self._summary["running"]), "running", "text-success")
        yield MetricCard(str(self._summary["provisioning"]), "provisioning", "warning")
        yield MetricCard(str(self._summary["hosts"]), "hosts", "text")

    def update_summary(self, summary: FleetSummary) -> None:
        self._summary = summary
        cards = list(self.query(MetricCard))
        values = [
            (str(summary["total"]), "text"),
            (str(summary["running"]), "text-success"),
            (str(summary["provisioning"]), "warning"),
            (str(summary["hosts"]), "text"),
        ]
        for card, (val, _) in zip(cards, values):
            card.update_value(val)

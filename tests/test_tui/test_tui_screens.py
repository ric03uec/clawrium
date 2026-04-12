"""Tests for TUI screen components."""

from clawrium.cli.tui.data import AgentViewModel, FleetSummary
from clawrium.cli.tui.widgets.agent_table import (
    status_color,
    status_dot,
    status_label,
)
from clawrium.cli.tui.widgets.metrics_bar import MetricsBar, MetricCard
from clawrium.cli.tui.widgets.detail_cards import DetailCards
from clawrium.core.health import ClawStatus


class TestStatusColor:
    def test_running(self):
        assert status_color(ClawStatus.RUNNING) == "text-success"

    def test_degraded(self):
        assert status_color(ClawStatus.DEGRADED) == "warning"

    def test_stopped(self):
        assert status_color(ClawStatus.STOPPED) == "error"

    def test_unknown(self):
        assert status_color(ClawStatus.UNKNOWN) == "warning"


class TestStatusDot:
    def test_running_is_filled(self):
        result = status_dot(ClawStatus.RUNNING)
        assert "●" in result

    def test_stopped_is_filled(self):
        result = status_dot(ClawStatus.STOPPED)
        assert "●" in result

    def test_not_installed_is_hollow(self):
        result = status_dot(ClawStatus.NOT_INSTALLED)
        assert "○" in result

    def test_pending_onboard_is_hollow(self):
        result = status_dot(ClawStatus.PENDING_ONBOARD)
        assert "○" in result


class TestStatusLabel:
    def test_running(self):
        assert status_label(ClawStatus.RUNNING) == "running"

    def test_degraded(self):
        assert status_label(ClawStatus.DEGRADED) == "degraded"

    def test_unknown_with_error(self):
        result = status_label(ClawStatus.UNKNOWN, error="SSH timed out")
        assert "SSH timed out" in result

    def test_unknown_without_error(self):
        assert status_label(ClawStatus.UNKNOWN) == "unknown"

    def test_onboarding(self):
        assert status_label(ClawStatus.ONBOARDING) == "onboarding"

    def test_error_truncated(self):
        long_error = "x" * 50
        result = status_label(ClawStatus.UNKNOWN, error=long_error)
        assert len(result) < len(long_error) + 20


class TestMetricCard:
    def test_default_values(self):
        card = MetricCard("5", "agents")
        assert card._value == "5"
        assert card._label == "agents"


class TestMetricsBar:
    def test_default_summary(self):
        bar = MetricsBar()
        assert bar._summary["total"] == 0

    def test_custom_summary(self):
        summary = FleetSummary(total=10, running=8, provisioning=2, hosts=3)
        bar = MetricsBar(summary=summary)
        assert bar._summary["total"] == 10


class TestDetailCards:
    def test_none_agent(self):
        cards = DetailCards(agent=None)
        assert cards._agent is None

    def test_with_agent(self):
        agent = AgentViewModel(
            agent_key="openclaw",
            agent_name="opc-test",
            agent_type="openclaw",
            host="192.168.1.100",
            host_alias="testhost",
            version="1.0.0",
            status=ClawStatus.RUNNING,
            model="gpt-4o",
            uptime="2d 5h",
            missing_secrets=None,
            onboarding_step=None,
            process_running=True,
            health_error=None,
        )
        cards = DetailCards(agent=agent)
        assert cards._agent is not None
        built = cards._build_cards(agent)
        assert len(built) == 4
        assert built[0]._title == "IDENTITY"
        assert built[1]._title == "MODEL & COST"
        assert built[2]._title == "CONFIGURATION"
        assert built[3]._title == "HEALTH"

    def test_missing_secrets_shown(self):
        agent = AgentViewModel(
            agent_key="openclaw",
            agent_name="opc-test",
            agent_type="openclaw",
            host="192.168.1.100",
            host_alias="testhost",
            version="1.0.0",
            status=ClawStatus.DEGRADED,
            model="gpt-4o",
            uptime="-",
            missing_secrets=["API_KEY", "SECRET_TOKEN"],
            onboarding_step=None,
            process_running=True,
            health_error=None,
        )
        cards = DetailCards(agent=agent)
        built = cards._build_cards(agent)
        config_card = built[2]
        secrets_rows = [r for r in config_card._rows if r[0] == "secrets"]
        assert len(secrets_rows) == 1
        assert "missing" in secrets_rows[0][1]
        assert "2 key" in secrets_rows[0][1]

    def test_secrets_not_rendered_as_raw_values(self):
        agent = AgentViewModel(
            agent_key="openclaw",
            agent_name="opc-test",
            agent_type="openclaw",
            host="192.168.1.100",
            host_alias="testhost",
            version="1.0.0",
            status=ClawStatus.RUNNING,
            model="gpt-4o",
            uptime="-",
            missing_secrets=None,
            onboarding_step=None,
            process_running=True,
            health_error=None,
        )
        cards = DetailCards(agent=agent)
        built = cards._build_cards(agent)
        config_card = built[2]
        secrets_row = [r for r in config_card._rows if r[0] == "secrets"]
        assert len(secrets_row) == 1
        assert "sk-" not in secrets_row[0][1]

    def test_rich_markup_escaped_in_error(self):
        agent = AgentViewModel(
            agent_key="openclaw",
            agent_name="opc-test",
            agent_type="openclaw",
            host="192.168.1.100",
            host_alias="testhost",
            version="1.0.0",
            status=ClawStatus.UNKNOWN,
            model="gpt-4o",
            uptime="-",
            missing_secrets=None,
            onboarding_step=None,
            process_running=False,
            health_error="Host [red]unreachable[/red]",
        )
        cards = DetailCards(agent=agent)
        built = cards._build_cards(agent)
        identity = built[0]
        error_rows = [r for r in identity._rows if r[0] == "error"]
        assert len(error_rows) == 1

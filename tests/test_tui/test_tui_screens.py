"""Tests for TUI screen components."""

import asyncio
from unittest.mock import patch

from clawrium.cli.tui.app import ClawriumApp
from clawrium.cli.tui.data import AgentViewModel, FleetSummary
from clawrium.cli.tui.widgets.agent_table import (
    status_color,
    status_dot,
    status_label,
)
from clawrium.cli.tui.widgets.metrics_bar import MetricsBar, MetricCard
from clawrium.cli.tui.widgets.detail_cards import DetailCards
from clawrium.cli.tui.screens.detail import DetailScreen, ConfirmModal
from clawrium.core.health import ClawStatus
from textual.widgets import Static


SAMPLE_AGENT = AgentViewModel(
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


class TestStatusColor:
    def test_running(self):
        assert status_color(ClawStatus.RUNNING) == "text-success"

    def test_degraded(self):
        assert status_color(ClawStatus.DEGRADED) == "warning"

    def test_stopped(self):
        assert status_color(ClawStatus.STOPPED) == "error"

    def test_unknown(self):
        assert status_color(ClawStatus.UNKNOWN) == "warning"

    def test_not_installed(self):
        assert status_color(ClawStatus.NOT_INSTALLED) == "warning"

    def test_onboarding(self):
        assert status_color(ClawStatus.ONBOARDING) == "cyan"

    def test_ready(self):
        assert status_color(ClawStatus.READY) == "cyan"

    def test_pending_onboard(self):
        assert status_color(ClawStatus.PENDING_ONBOARD) == "warning"


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
        cards = DetailCards(agent=SAMPLE_AGENT)
        assert cards._agent is not None
        built = cards._build_cards(SAMPLE_AGENT)
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
        cards = DetailCards(agent=SAMPLE_AGENT)
        built = cards._build_cards(SAMPLE_AGENT)
        config_card = built[2]
        secrets_row = [r for r in config_card._rows if r[0] == "secrets"]
        assert len(secrets_row) == 1
        assert "sk-" not in secrets_row[0][1]

    def test_health_error_stored_with_raw_markup(self):
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
        assert "[red]" in error_rows[0][1]

        rendered_items = list(identity.compose())
        static_values = [
            str(item.renderable) for item in rendered_items if isinstance(item, Static)
        ]
        assert any("\\[" in value for value in static_values)


class TestConfirmModal:
    def test_y_dismisses_true(self):
        async def _test():
            results = []
            modal = ConfirmModal("Test?")
            modal.dismiss = lambda v: results.append(v)
            modal.action_confirm()
            assert results == [True]

        asyncio.run(_test())

    def test_n_dismisses_false(self):
        async def _test():
            modal = ConfirmModal("Test?")
            results = []
            modal.dismiss = lambda v: results.append(v)
            modal.action_cancel()
            assert results == [False]

        asyncio.run(_test())

    def test_escape_dismisses_false(self):
        modal = ConfirmModal("Test?")
        results = []
        modal.dismiss = lambda v: results.append(v)
        modal.action_cancel()
        assert results == [False]


class TestDetailScreenCallbacks:
    def test_stop_confirmed_calls_stop_agent(self):
        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.stop_agent",
                    return_value={"success": True},
                ) as mock_stop,
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=SAMPLE_AGENT,
                ),
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    await pilot.press("s")
                    await pilot.pause()
                    await pilot.press("y")
                    # First wait drains _do_stop worker; second drains chained _refresh_async.
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    mock_stop.assert_called_once()

        asyncio.run(_test())

    def test_restart_confirmed_calls_restart_agent(self):
        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.restart_agent",
                    return_value={"success": True},
                ) as mock_restart,
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=SAMPLE_AGENT,
                ),
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    await pilot.press("r")
                    await pilot.pause()
                    await pilot.press("y")
                    # First wait drains _do_restart worker; second drains chained _refresh_async.
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    mock_restart.assert_called_once()

        asyncio.run(_test())

    def test_refresh_removed_agent_dismisses_detail(self):
        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=None,
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.stop_agent",
                    return_value={"success": True},
                ),
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    assert len(app.screen_stack) == 2
                    await pilot.press("s")
                    await pilot.pause()
                    await pilot.press("y")
                    await app.workers.wait_for_complete()
                    assert len(app.screen_stack) == 1

        asyncio.run(_test())

    def test_stop_confirmed_agent_removed_dismisses_screen(self):
        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=None,
                ),
                patch("clawrium.cli.tui.screens.detail.stop_agent") as mock_stop,
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    await pilot.press("s")
                    await pilot.pause()
                    await pilot.press("y")
                    await app.workers.wait_for_complete()
                    mock_stop.assert_not_called()
                    assert len(app.screen_stack) == 1

        asyncio.run(_test())

    def test_stop_confirmed_stale_status_aborts_stop(self):
        stale_agent = AgentViewModel(**{**SAMPLE_AGENT, "status": ClawStatus.STOPPED})

        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=stale_agent,
                ),
                patch("clawrium.cli.tui.screens.detail.stop_agent") as mock_stop,
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    detail = app.screen
                    calls = []

                    def _notify(message, *, severity="information", **kwargs):
                        calls.append((message, severity))

                    detail.notify = _notify
                    await pilot.press("s")
                    await pilot.pause()
                    await pilot.press("y")
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    mock_stop.assert_not_called()
                    assert any(severity == "warning" for _, severity in calls)

        asyncio.run(_test())

    def test_restart_confirmed_stale_status_aborts_restart(self):
        stale_agent = AgentViewModel(**{**SAMPLE_AGENT, "status": ClawStatus.STOPPED})

        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=stale_agent,
                ),
                patch("clawrium.cli.tui.screens.detail.restart_agent") as mock_restart,
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    detail = app.screen
                    calls = []

                    def _notify(message, *, severity="information", **kwargs):
                        calls.append((message, severity))

                    detail.notify = _notify
                    await pilot.press("r")
                    await pilot.pause()
                    await pilot.press("y")
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    mock_restart.assert_not_called()
                    assert any(severity == "warning" for _, severity in calls)

        asyncio.run(_test())

    def test_stop_failure_notifies_error(self):
        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=SAMPLE_AGENT,
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.stop_agent",
                    return_value={"success": False, "error": "playbook failed"},
                ),
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    detail = app.screen
                    calls = []

                    def _notify(message, *, severity="information", **kwargs):
                        calls.append((message, severity))

                    detail.notify = _notify
                    await pilot.press("s")
                    await pilot.pause()
                    await pilot.press("y")
                    # First wait drains _do_stop worker; second drains chained _refresh_async.
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    assert any(severity == "error" for _, severity in calls)

        asyncio.run(_test())

    def test_stop_exception_notifies_error(self):
        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=SAMPLE_AGENT,
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.stop_agent",
                    side_effect=RuntimeError("boom"),
                ),
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    detail = app.screen
                    calls = []

                    def _notify(message, *, severity="information", **kwargs):
                        calls.append((message, severity))

                    detail.notify = _notify
                    await pilot.press("s")
                    await pilot.pause()
                    await pilot.press("y")
                    # First wait drains _do_stop worker; second drains chained _refresh_async.
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    assert any(severity == "error" for _, severity in calls)

        asyncio.run(_test())

    def test_stop_agent_not_running_shows_warning(self):
        stopped_agent = AgentViewModel(**{**SAMPLE_AGENT, "status": ClawStatus.STOPPED})

        async def _test():
            with patch(
                "clawrium.cli.tui.data.get_fleet_data",
                return_value=(
                    [stopped_agent],
                    FleetSummary(total=1, running=0, provisioning=0, hosts=1),
                ),
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=stopped_agent))
                    await pilot.pause()
                    detail = app.screen
                    calls = []

                    def _notify(message, *, severity="information", **kwargs):
                        calls.append((message, severity))

                    detail.notify = _notify
                    await pilot.press("s")
                    await pilot.pause()
                    assert len(app.screen_stack) == 2
                    assert any(severity == "warning" for _, severity in calls)

        asyncio.run(_test())

    def test_stop_agent_degraded_status_proceeds(self):
        degraded_agent = AgentViewModel(
            **{**SAMPLE_AGENT, "status": ClawStatus.DEGRADED}
        )

        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [degraded_agent],
                        FleetSummary(total=1, running=0, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=degraded_agent,
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.stop_agent",
                    return_value={"success": True},
                ) as mock_stop,
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=degraded_agent))
                    await pilot.pause()
                    await pilot.press("s")
                    await pilot.pause()
                    assert len(app.screen_stack) == 3
                    assert isinstance(app.screen, ConfirmModal)
                    await pilot.press("y")
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    mock_stop.assert_called_once()

        asyncio.run(_test())

    def test_restart_failure_notifies_error(self):
        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=SAMPLE_AGENT,
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.restart_agent",
                    return_value={"success": False, "error": "restart failed"},
                ),
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    detail = app.screen
                    calls = []

                    def _notify(message, *, severity="information", **kwargs):
                        calls.append((message, severity))

                    detail.notify = _notify
                    await pilot.press("r")
                    await pilot.pause()
                    await pilot.press("y")
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    assert any(severity == "error" for _, severity in calls)

        asyncio.run(_test())

    def test_restart_exception_notifies_error(self):
        async def _test():
            with (
                patch(
                    "clawrium.cli.tui.data.get_fleet_data",
                    return_value=(
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.get_agent_detail",
                    return_value=SAMPLE_AGENT,
                ),
                patch(
                    "clawrium.cli.tui.screens.detail.restart_agent",
                    side_effect=RuntimeError("boom"),
                ),
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(DetailScreen(agent=SAMPLE_AGENT))
                    await pilot.pause()
                    detail = app.screen
                    calls = []

                    def _notify(message, *, severity="information", **kwargs):
                        calls.append((message, severity))

                    detail.notify = _notify
                    await pilot.press("r")
                    await pilot.pause()
                    await pilot.press("y")
                    await app.workers.wait_for_complete()
                    await app.workers.wait_for_complete()
                    assert any(severity == "error" for _, severity in calls)

        asyncio.run(_test())

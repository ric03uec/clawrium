"""Tests for TUI app structure and launch."""

import asyncio
from unittest.mock import patch

from clawrium.cli.tui import launch_tui
from clawrium.cli.tui.app import ClawriumApp
from clawrium.cli.tui.data import AgentViewModel, FleetSummary
from clawrium.cli.tui.widgets.agent_table import AgentTable
from clawrium.cli.tui.widgets.metrics_bar import MetricsBar
from clawrium.cli.tui.screens.detail import DetailScreen
from clawrium.core.health import ClawStatus


MOCK_FLEET_EMPTY = ([], FleetSummary(total=0, running=0, provisioning=0, hosts=0))

SAMPLE_AGENT = AgentViewModel(
    agent_key="test-claw",
    agent_name="test-claw",
    agent_type="openclaw",
    host="192.168.1.100",
    host_alias="testhost",
    version="1.0",
    status=ClawStatus.RUNNING,
    model="gpt-4o",
    uptime="1h",
    missing_secrets=None,
    onboarding_step=None,
    process_running=True,
    health_error=None,
)

MOCK_FLEET_WITH_AGENT = (
    [SAMPLE_AGENT],
    FleetSummary(total=1, running=1, provisioning=0, hosts=1),
)


class TestClawriumApp:
    def test_app_title(self):
        app = ClawriumApp()
        assert app.TITLE == "Clawrium"

    def test_bindings_include_quit(self):
        app = ClawriumApp()
        binding_keys = [b.key for b in app.BINDINGS]
        assert "q" in binding_keys

    def test_bindings_include_detail_and_refresh(self):
        app = ClawriumApp()
        binding_keys = [b.key for b in app.BINDINGS]
        assert "d" in binding_keys
        assert "r" in binding_keys


class TestClawriumAppCompose:
    def test_compose_contains_fleet_widgets(self):
        async def _test():
            with patch(
                "clawrium.cli.tui.data.get_fleet_data", return_value=MOCK_FLEET_EMPTY
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    assert app.query_one("#fleet-label") is not None
                    assert app.query_one("#fleet-metrics", MetricsBar) is not None
                    assert app.query_one("#fleet-table", AgentTable) is not None

        asyncio.run(_test())

    def test_compose_contains_header_and_footer(self):
        async def _test():
            with patch(
                "clawrium.cli.tui.data.get_fleet_data", return_value=MOCK_FLEET_EMPTY
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    from textual.widgets import Header, Footer

                    assert app.query_one(Header) is not None
                    assert app.query_one(Footer) is not None

        asyncio.run(_test())


class TestClawriumAppNavigation:
    def test_non_fleet_row_selected_does_not_navigate(self):
        class _Table:
            id = "other-table"

        class _Event:
            data_table = _Table()

        app = ClawriumApp()
        called = {"value": False}

        def _mark_called() -> None:
            called["value"] = True

        app.action_view_detail = _mark_called
        app.on_data_table_row_selected(_Event())
        assert called["value"] is False

    def test_row_selected_pushes_detail_screen(self):
        async def _test():
            with patch(
                "clawrium.cli.tui.data.get_fleet_data",
                return_value=MOCK_FLEET_WITH_AGENT,
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    table = app.query_one("#fleet-table", AgentTable)
                    table.load_agents([SAMPLE_AGENT])
                    await pilot.pause()

                    await pilot.press("enter")
                    await pilot.pause()

                    from clawrium.cli.tui.screens.detail import DetailScreen

                    assert len(app.screen_stack) == 2
                    assert isinstance(app.screen, DetailScreen)

        asyncio.run(_test())

    def test_d_key_pushes_detail_screen(self):
        async def _test():
            with patch(
                "clawrium.cli.tui.data.get_fleet_data",
                return_value=MOCK_FLEET_WITH_AGENT,
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    table = app.query_one("#fleet-table", AgentTable)
                    table.load_agents([SAMPLE_AGENT])
                    await pilot.pause()

                    await pilot.press("d")
                    await pilot.pause()

                    from clawrium.cli.tui.screens.detail import DetailScreen

                    assert isinstance(app.screen, DetailScreen)

        asyncio.run(_test())

    def test_esc_returns_to_fleet(self):
        async def _test():
            with patch(
                "clawrium.cli.tui.data.get_fleet_data",
                return_value=MOCK_FLEET_WITH_AGENT,
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    table = app.query_one("#fleet-table", AgentTable)
                    table.load_agents([SAMPLE_AGENT])
                    await pilot.pause()

                    await pilot.press("enter")
                    await pilot.pause()

                    await pilot.press("escape")
                    await pilot.pause()

                    assert len(app.screen_stack) == 1
                    assert not isinstance(app.screen, DetailScreen)

        asyncio.run(_test())


class TestLaunchTui:
    def test_launch_creates_app_and_runs(self):
        with patch.object(ClawriumApp, "run") as mock_run:
            launch_tui()
            mock_run.assert_called_once()


class TestFleetRefresh:
    def test_refresh_fleet_updates_widgets(self):
        refreshed_agent = AgentViewModel(
            agent_key="test-claw",
            agent_name="test-claw",
            agent_type="openclaw",
            host="192.168.1.100",
            host_alias="testhost",
            version="1.0",
            status=ClawStatus.RUNNING,
            model="gpt-4.1",
            uptime="2h",
            missing_secrets=None,
            onboarding_step=None,
            process_running=True,
            health_error=None,
        )

        async def _test():
            with patch(
                "clawrium.cli.tui.data.get_fleet_data",
                side_effect=[
                    MOCK_FLEET_EMPTY,
                    (
                        [refreshed_agent],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                ],
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    app.refresh_fleet()
                    await app.workers.wait_for_complete()

                    table = app.query_one("#fleet-table", AgentTable)
                    assert table.row_count == 1

                    metrics = app.query_one("#fleet-metrics", MetricsBar)
                    assert metrics._summary["total"] == 1
                    assert app.sub_title == "Fleet Dashboard — 1 agents, 1 running"

        asyncio.run(_test())

    def test_refresh_fleet_worker_exception_does_not_blank_screen(self):
        async def _test():
            with patch(
                "clawrium.cli.tui.data.get_fleet_data",
                side_effect=[
                    (
                        [SAMPLE_AGENT],
                        FleetSummary(total=1, running=1, provisioning=0, hosts=1),
                    ),
                    RuntimeError("boom"),
                ],
            ):
                app = ClawriumApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                    table = app.query_one("#fleet-table", AgentTable)
                    assert table.row_count == 1

                    app.refresh_fleet()
                    await pilot.pause()

                    table_after = app.query_one("#fleet-table", AgentTable)
                    assert table_after.row_count == 1

        asyncio.run(_test())

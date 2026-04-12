"""Tests for TUI app structure and launch."""

from unittest.mock import patch


from clawrium.cli.tui import launch_tui
from clawrium.cli.tui.app import ClawriumApp


class TestClawriumApp:
    def test_app_title(self):
        app = ClawriumApp()
        assert app.TITLE == "Clawrium"

    def test_bindings_include_quit(self):
        app = ClawriumApp()
        binding_keys = [b.key for b in app.BINDINGS]
        assert "q" in binding_keys


class TestLaunchTui:
    def test_launch_creates_app_and_runs(self):
        with patch.object(ClawriumApp, "run") as mock_run:
            launch_tui()
            mock_run.assert_called_once()

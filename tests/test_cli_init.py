"""Tests for clm init command."""

from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli.main import app

runner = CliRunner()


class TestCliInit:
    """Tests for the init command."""

    def test_no_args_shows_help(self) -> None:
        """Running clm with no args should show help."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Usage:" in result.output or "usage:" in result.output.lower()

    def test_init_creates_config_dir(self, isolated_config: Path) -> None:
        """clm init should create the config directory."""
        assert not isolated_config.exists()

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert isolated_config.exists()
        assert isolated_config.is_dir()

    def test_init_outputs_config_path(self, isolated_config: Path) -> None:
        """clm init should output the config directory path."""
        result = runner.invoke(app, ["init"])

        assert str(isolated_config) in result.output

    def test_init_shows_success_message(self, isolated_config: Path) -> None:
        """clm init should show a success message."""
        result = runner.invoke(app, ["init"])

        assert "initialized" in result.output.lower() or "created" in result.output.lower()

    def test_init_idempotent(self, isolated_config: Path) -> None:
        """clm init should work even if directory exists."""
        # First run
        runner.invoke(app, ["init"])
        assert isolated_config.exists()

        # Second run should not fail
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0

"""Tests for registry CLI commands."""

from typer.testing import CliRunner
from clawrium.cli.main import app
from clawrium.core.registry import get_claw_info

runner = CliRunner()


def test_registry_list_shows_table():
    """Test that registry list shows available claws."""
    result = runner.invoke(app, ["registry", "list"])
    assert result.exit_code == 0
    assert "openclaw" in result.output.lower()
    assert "Available Claws" in result.output


def test_registry_list_shows_version():
    """Test that registry list includes latest version from manifest."""
    result = runner.invoke(app, ["registry", "list"])
    assert result.exit_code == 0
    # Dynamically get expected version from registry
    claw_info = get_claw_info("openclaw")
    assert claw_info["latest_version"] in result.output


def test_registry_show_openclaw():
    """Test registry show displays claw details."""
    result = runner.invoke(app, ["registry", "show", "openclaw"])
    assert result.exit_code == 0
    assert "openclaw" in result.output.lower()
    assert "Supported Platforms" in result.output
    assert "ubuntu" in result.output.lower()


def test_registry_show_not_found():
    """Test registry show with unknown claw shows error."""
    result = runner.invoke(app, ["registry", "show", "nonexistent"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()

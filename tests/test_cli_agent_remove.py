"""Tests for clm agent remove command."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from clawrium.cli.main import app

runner = CliRunner()


@pytest.fixture
def host_with_claw(isolated_config: Path) -> tuple[Path, str, str]:
    """Create a host with an installed claw."""
    hostname = "192.168.1.100"
    alias = "testhost"
    claw_name = "openclaw"

    # Ensure config directory exists
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create host with installed claw
    hosts_file = isolated_config / "hosts.json"
    hosts_data = [
        {
            "hostname": hostname,
            "alias": alias,
            "key_id": "testhost",
            "port": 22,
            "user": "xclm",
            "auth_method": "key",
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 4,
                "memtotal_mb": 8192,
            },
            "claws": {
                claw_name: {
                    "version": "1.0.0",
                    "status": "installed",
                    "user": "opc-testhost",
                    "installed_at": "2026-04-01T00:00:00Z",
                    "runtime": {"status": "stopped"},
                }
            },
        }
    ]
    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    # Create SSH key
    key_dir = isolated_config / "keys" / "testhost"
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "xclm_ed25519").write_text("test-private-key")
    (key_dir / "xclm_ed25519").chmod(0o600)

    return isolated_config, alias, claw_name


def test_agent_remove_success(host_with_claw: tuple[Path, str, str]):
    """Successfully remove an agent with confirmation."""
    _, alias, claw_name = host_with_claw

    with patch("clawrium.core.lifecycle.remove_agent") as mock_remove:
        mock_remove.return_value = {
            "success": True,
            "agent": claw_name,
            "host": alias,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": None,
        }

        result = runner.invoke(
            app, ["agent", "remove", f"opc-{alias}"], input="y\n"
        )

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()
        mock_remove.assert_called_once()


def test_agent_remove_with_force(host_with_claw: tuple[Path, str, str]):
    """Remove agent with --force flag skips confirmation."""
    _, alias, claw_name = host_with_claw

    with patch("clawrium.core.lifecycle.remove_agent") as mock_remove:
        mock_remove.return_value = {
            "success": True,
            "agent": claw_name,
            "host": alias,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": None,
        }

        result = runner.invoke(app, ["agent", "remove", f"opc-{alias}", "--force"])

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()
        # Should not prompt for confirmation
        assert "Remove" not in result.output or "Removing" in result.output
        mock_remove.assert_called_once()


def test_agent_remove_cancelled(host_with_claw: tuple[Path, str, str]):
    """User cancels removal at confirmation prompt."""
    _, alias, _ = host_with_claw

    with patch("clawrium.core.lifecycle.remove_agent") as mock_remove:
        result = runner.invoke(
            app, ["agent", "remove", f"opc-{alias}"], input="n\n"
        )

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()
        mock_remove.assert_not_called()


def test_agent_remove_host_not_found(isolated_config: Path):
    """Error when host does not exist."""
    result = runner.invoke(app, ["agent", "remove", "opc-unknown", "--force"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_agent_remove_claw_not_installed(host_with_claw: tuple[Path, str, str]):
    """Error when claw is not installed on host."""
    _, alias, _ = host_with_claw

    # Try to remove a different claw type
    result = runner.invoke(app, ["agent", "remove", f"zc-{alias}", "--force"])

    assert result.exit_code == 1
    assert "not installed" in result.output.lower()


def test_agent_remove_playbook_failure(host_with_claw: tuple[Path, str, str]):
    """Handle playbook execution failure gracefully."""
    _, alias, claw_name = host_with_claw

    with patch("clawrium.core.lifecycle.remove_agent") as mock_remove:
        mock_remove.return_value = {
            "success": False,
            "agent": claw_name,
            "host": alias,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": "SSH connection failed",
        }

        result = runner.invoke(
            app, ["agent", "remove", f"opc-{alias}"], input="y\n"
        )

        assert result.exit_code == 1
        assert "failed" in result.output.lower()
        assert "SSH connection failed" in result.output


def test_agent_remove_lifecycle_error(host_with_claw: tuple[Path, str, str]):
    """Handle LifecycleError exceptions."""
    from clawrium.core.lifecycle import LifecycleError

    _, alias, _ = host_with_claw

    with patch("clawrium.core.lifecycle.remove_agent") as mock_remove:
        mock_remove.side_effect = LifecycleError("Test error message")

        result = runner.invoke(
            app, ["agent", "remove", f"opc-{alias}"], input="y\n"
        )

        assert result.exit_code == 1
        assert "error" in result.output.lower()
        assert "Test error message" in result.output


def test_agent_remove_invalid_name_format(isolated_config: Path):
    """Error on invalid claw name format."""
    result = runner.invoke(app, ["agent", "remove", "invalid", "--force"])

    assert result.exit_code == 1
    assert "invalid" in result.output.lower()


def test_agent_remove_with_running_claw(host_with_claw: tuple[Path, str, str]):
    """Remove stops running claw before removal."""
    config, alias, claw_name = host_with_claw

    # Update claw to be running
    hosts_file = config / "hosts.json"
    hosts = json.loads(hosts_file.read_text())
    hosts[0]["claws"][claw_name]["runtime"]["status"] = "running"
    hosts_file.write_text(json.dumps(hosts, indent=2))

    with patch("clawrium.core.lifecycle.remove_agent") as mock_remove:
        mock_remove.return_value = {
            "success": True,
            "agent": claw_name,
            "host": alias,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": None,
        }

        result = runner.invoke(
            app, ["agent", "remove", f"opc-{alias}"], input="y\n"
        )

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()
        mock_remove.assert_called_once()


def test_agent_remove_event_callbacks(host_with_claw: tuple[Path, str, str]):
    """Verify event callbacks are displayed."""
    _, alias, claw_name = host_with_claw

    def mock_remove_with_events(host, claw, on_event=None):
        if on_event:
            on_event("validate", "Checking claw...")
            on_event("remove", "Stopping agent...")
            on_event("remove", "Removing artifacts...")
            on_event("remove", "Removing from config...")
        return {
            "success": True,
            "agent": claw_name,
            "host": host,
            "operation": "remove",
            "pid": None,
            "started_at": None,
            "error": None,
        }

    with patch(
        "clawrium.core.lifecycle.remove_agent", side_effect=mock_remove_with_events
    ):
        result = runner.invoke(
            app, ["agent", "remove", f"opc-{alias}"], input="y\n"
        )

        assert result.exit_code == 0
        # Event messages should appear in output
        assert "Checking" in result.output or "checking" in result.output.lower()
        assert "Removing" in result.output or "removing" in result.output.lower()


def test_agent_remove_keyboard_interrupt(host_with_claw: tuple[Path, str, str]):
    """Handle KeyboardInterrupt gracefully."""

    _, alias, _ = host_with_claw

    with patch("clawrium.core.lifecycle.remove_agent") as mock_remove:
        mock_remove.side_effect = KeyboardInterrupt()

        result = runner.invoke(
            app, ["agent", "remove", f"opc-{alias}"], input="y\n"
        )

        assert result.exit_code == 1
        assert "cancelled" in result.output.lower()

"""Tests for fleet status CLI command."""

import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from clawrium.cli.main import app
from clawrium.core.health import ClawStatus


runner = CliRunner()


@pytest.fixture
def mock_hosts_with_claws():
    """Hosts with installed claws."""
    return [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "port": 22,
            "user": "xclm",
            "key_id": "server1",
            "claws": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installed",
                    "installed_at": "2026-03-21T10:00:00Z",
                    "user": "opc-server1",
                }
            },
        },
        {
            "hostname": "192.168.1.101",
            "alias": "server2",
            "port": 22,
            "user": "xclm",
            "key_id": "server2",
            "claws": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installed",
                    "installed_at": "2026-03-21T11:00:00Z",
                    "user": "opc-server2",
                }
            },
        },
    ]


def test_status_no_hosts():
    """No hosts shows message to add hosts."""
    with patch("clawrium.cli.status.load_hosts", return_value=[]):
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "No hosts registered" in result.output


def test_status_no_claws():
    """Hosts with no claws shows install message."""
    hosts = [{"hostname": "192.168.1.100", "claws": {}}]

    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "No claws installed" in result.output


def test_status_shows_claw_table(mock_hosts_with_claws):
    """Status shows table grouped by claw type."""
    mock_health = MagicMock(return_value={
        "claw": "openclaw",
        "host": "192.168.1.100",
        "status": ClawStatus.RUNNING,
        "user": "opc-server1",
        "error": None,
    })

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "openclaw" in result.output
    assert "server1" in result.output
    assert "0.1.0" in result.output


def test_status_shows_running_status(mock_hosts_with_claws):
    """Running claw shows green status."""
    mock_health = MagicMock(return_value={
        "claw": "openclaw",
        "host": "192.168.1.100",
        "status": ClawStatus.RUNNING,
        "user": "opc-server1",
        "error": None,
    })

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["status"])

    assert "running" in result.output


def test_status_shows_stopped_status(mock_hosts_with_claws):
    """Stopped claw shows red status."""
    mock_health = MagicMock(return_value={
        "claw": "openclaw",
        "host": "192.168.1.100",
        "status": ClawStatus.STOPPED,
        "user": "opc-server1",
        "error": None,
    })

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["status"])

    assert "stopped" in result.output


def test_status_host_filter(mock_hosts_with_claws):
    """--host flag filters to specific host."""
    mock_health = MagicMock(return_value={
        "claw": "openclaw",
        "host": "192.168.1.100",
        "status": ClawStatus.RUNNING,
        "user": "opc-server1",
        "error": None,
    })

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["status", "--host", "server1"])

    assert result.exit_code == 0
    assert "server1" in result.output
    # Health check should only be called once (for server1)
    assert mock_health.call_count == 1


def test_status_host_filter_not_found(mock_hosts_with_claws):
    """--host with unknown host shows error."""
    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        result = runner.invoke(app, ["status", "--host", "unknown"])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_status_shows_failed_install():
    """Failed installation shows install failed status."""
    hosts = [{
        "hostname": "192.168.1.100",
        "alias": "server1",
        "claws": {
            "openclaw": {
                "version": "0.1.0",
                "status": "failed",
                "error": "Playbook failed",
                "user": "opc-server1",
            }
        },
    }]

    # Health check returns unknown since not really installed
    mock_health = MagicMock(return_value={
        "claw": "openclaw",
        "host": "192.168.1.100",
        "status": ClawStatus.STOPPED,
        "user": "opc-server1",
        "error": None,
    })

    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["status"])

    assert "install failed" in result.output

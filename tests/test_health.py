"""Tests for claw health checking."""

import pytest
from unittest.mock import patch, MagicMock

from clawrium.core.health import (
    check_claw_health,
    check_all_claws_on_host,
    ClawStatus,
)


@pytest.fixture
def mock_host():
    """Host record with installed claw."""
    return {
        "hostname": "192.168.1.100",
        "port": 22,
        "user": "xclm",
        "key_id": "testhost",
        "claws": {
            "openclaw": {
                "version": "0.1.0",
                "status": "installed",
                "user": "opc-testhost",
            }
        },
    }


def test_health_check_running(mock_host):
    """Process running returns RUNNING status."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [
        {"event": "runner_on_ok", "event_data": {"res": {"stdout": "RUNNING"}}}
    ]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.RUNNING
    assert result["claw"] == "openclaw"
    assert result["user"] == "opc-testhost"
    assert result["error"] is None


def test_health_check_stopped(mock_host):
    """Process not running returns STOPPED status."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [
        {"event": "runner_on_ok", "event_data": {"res": {"stdout": "STOPPED"}}}
    ]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.STOPPED


def test_health_check_ssh_fails(mock_host):
    """SSH failure returns UNKNOWN status with error."""
    mock_runner = MagicMock()
    mock_runner.status = "failed"
    mock_runner.events = []

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "SSH failed" in result["error"]


def test_health_check_not_installed(mock_host):
    """Claw not in host record returns NOT_INSTALLED."""
    result = check_claw_health("zeroclaw", mock_host)

    assert result["status"] == ClawStatus.NOT_INSTALLED


def test_health_check_no_ssh_key(mock_host):
    """Missing SSH key returns UNKNOWN."""
    with patch("clawrium.core.health.get_host_private_key", return_value=None):
        result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "SSH key not found" in result["error"]


def test_health_check_timeout(mock_host):
    """Timeout returns UNKNOWN status."""
    mock_runner = MagicMock()
    mock_runner.status = "timeout"
    mock_runner.events = []

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "timed out" in result["error"]


def test_check_all_claws_on_host(mock_host):
    """check_all_claws_on_host returns results for each claw."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [
        {"event": "runner_on_ok", "event_data": {"res": {"stdout": "RUNNING"}}}
    ]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            results = check_all_claws_on_host(mock_host)

    assert len(results) == 1
    assert results[0]["claw"] == "openclaw"
    assert results[0]["status"] == ClawStatus.RUNNING


def test_health_check_no_claw_user():
    """Missing claw user returns UNKNOWN status with error."""
    host = {
        "hostname": "192.168.1.100",
        "claws": {
            "openclaw": {
                "version": "0.1.0",
                "status": "installed",
                # No "user" field
            }
        },
    }

    result = check_claw_health("openclaw", host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "No claw user recorded" in result["error"]


def test_health_check_invalid_claw_user():
    """Invalid claw user format returns UNKNOWN status with error."""
    host = {
        "hostname": "192.168.1.100",
        "claws": {
            "openclaw": {
                "version": "0.1.0",
                "status": "installed",
                "user": "root; rm -rf /",  # Command injection attempt
            }
        },
    }

    result = check_claw_health("openclaw", host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "Invalid claw user format" in result["error"]


def test_health_check_host_unreachable(mock_host):
    """Host unreachable returns UNKNOWN status."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"  # ansible-runner returns successful even for unreachable
    mock_runner.events = [
        {"event": "runner_on_unreachable", "event_data": {}}
    ]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "unreachable" in result["error"].lower()


def test_health_check_unexpected_output(mock_host):
    """Unexpected output returns UNKNOWN status."""
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = [
        {"event": "runner_on_ok", "event_data": {"res": {"stdout": "UNEXPECTED_OUTPUT"}}}
    ]

    with patch("clawrium.core.health.get_host_private_key", return_value="/fake/key"):
        with patch("clawrium.core.health.ansible_runner.run", return_value=mock_runner):
            result = check_claw_health("openclaw", mock_host)

    assert result["status"] == ClawStatus.UNKNOWN
    assert "Unexpected output" in result["error"]

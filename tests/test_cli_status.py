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
            "agent_name": "xclm",
            "key_id": "server1",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installed",
                    "installed_at": "2026-03-21T10:00:00Z",
                    "agent_name": "opc-server1",
                }
            },
        },
        {
            "hostname": "192.168.1.101",
            "alias": "server2",
            "port": 22,
            "agent_name": "xclm",
            "key_id": "server2",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installed",
                    "installed_at": "2026-03-21T11:00:00Z",
                    "agent_name": "opc-server2",
                }
            },
        },
    ]


def test_status_no_hosts():
    """No hosts shows message to add hosts."""
    with patch("clawrium.cli.status.load_hosts", return_value=[]):
        result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "No hosts registered" in result.output


def test_status_no_claws():
    """Hosts with no claws shows install message."""
    hosts = [{"hostname": "192.168.1.100", "agents": {}}]

    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "No agents installed" in result.output


def test_status_shows_claw_table(mock_hosts_with_claws):
    """Status shows table grouped by claw type."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "openclaw" in result.output
    assert "server1" in result.output
    assert "0.1.0" in result.output


def test_status_shows_running_status(mock_hosts_with_claws):
    """Running claw shows green status."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert "running" in result.output


def test_status_shows_stopped_status(mock_hosts_with_claws):
    """Stopped claw shows red status."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.STOPPED,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert "stopped" in result.output


def test_status_host_filter(mock_hosts_with_claws):
    """--host flag filters to specific host."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "--host", "server1"])

    assert result.exit_code == 0
    assert "server1" in result.output
    # Health check should only be called once (for server1)
    assert mock_health.call_count == 1


def test_status_host_filter_not_found(mock_hosts_with_claws):
    """--host with unknown host shows error."""
    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        result = runner.invoke(app, ["ps", "--host", "unknown"])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_status_shows_failed_install():
    """Failed installation shows install failed status with error message."""
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "failed",
                    "error": "Playbook failed",
                    "agent_name": "opc-server1",
                }
            },
        }
    ]

    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.STOPPED,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert "install failed" in result.output
    assert "Playbook failed" in result.output


def test_status_shows_failed_install_truncates_long_error():
    """Failed installation truncates error messages longer than 50 chars."""
    long_error = "A" * 60
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "failed",
                    "error": long_error,
                    "agent_name": "opc-server1",
                }
            },
        }
    ]

    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.STOPPED,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert "install failed" in result.output
    assert "A" * 50 + "..." in result.output
    assert "A" * 60 not in result.output


def test_status_shows_failed_install_no_error_field():
    """Failed installation without error field shows 'unknown error'."""
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "failed",
                    "agent_name": "opc-server1",
                }
            },
        }
    ]

    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.STOPPED,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert "install failed" in result.output
    assert "unknown error" in result.output


def test_status_shows_installing_status():
    """Installing status with installed_at shows 'installing...'."""
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installing",
                    "installed_at": "2026-04-10T10:00:00Z",
                    "agent_name": "opc-server1",
                }
            },
        }
    ]

    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.UNKNOWN,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
        }
    )
    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "installing..." in result.output
    assert mock_health.call_count == 1


def test_status_shows_incomplete_install():
    """Installing status without installed_at shows 'incomplete install'."""
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installing",
                    "installed_at": None,
                    "agent_name": "opc-server1",
                }
            },
        }
    ]

    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.UNKNOWN,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
        }
    )
    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "incomplete install" in result.output


def test_status_shows_incomplete_install_no_installed_at_field():
    """Installing status with missing installed_at key shows 'incomplete install'."""
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installing",
                    "agent_name": "opc-server1",
                }
            },
        }
    ]

    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.UNKNOWN,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": None,
            "onboarding_stages": None,
        }
    )
    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "incomplete install" in result.output


def test_status_successful_install_unchanged(mock_hosts_with_claws):
    """Successfully installed agents display is unchanged."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "install failed" not in result.output
    assert "incomplete install" not in result.output


def test_status_hosts_file_corrupted():
    """HostsFileCorruptedError shows error and exits 1."""
    from clawrium.core.hosts import HostsFileCorruptedError

    with patch(
        "clawrium.cli.status.load_hosts",
        side_effect=HostsFileCorruptedError("JSON parse error"),
    ):
        result = runner.invoke(app, ["ps"])

    assert result.exit_code == 1
    assert "corrupted" in result.output.lower() or "error" in result.output.lower()


def test_status_shows_degraded_with_missing_secrets(mock_hosts_with_claws):
    """Degraded status shows missing secret keys."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.DEGRADED,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "degraded" in result.output
    assert "OPENAI_API_KEY" in result.output
    assert "ANTHROPIC_API_KEY" in result.output


def test_status_degraded_truncates_long_list(mock_hosts_with_claws):
    """Degraded status truncates when more than 3 missing secrets."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.DEGRADED,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": ["KEY1", "KEY2", "KEY3", "KEY4", "KEY5"],
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "degraded" in result.output
    assert "KEY1" in result.output
    assert "KEY2" in result.output
    assert "KEY3" in result.output
    assert "+2 more" in result.output


# Tests for onboarding-aware statuses - Issue #70 / B5/B6 fix


def test_status_shows_pending_onboard(mock_hosts_with_claws):
    """B5: PENDING_ONBOARD shows 'pending onboard' status."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.PENDING_ONBOARD,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "pending onboard" in result.output


def test_status_shows_onboarding_with_step(mock_hosts_with_claws):
    """B5/B6: ONBOARDING shows status with step progress."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.ONBOARDING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": "2/4",
            "process_running": False,
            "onboarding_stages": {
                "providers": {
                    "status": "complete",
                    "completed_at": "2026-04-06T10:00:00Z",
                },
                "identity": {
                    "status": "complete",
                    "completed_at": "2026-04-06T11:00:00Z",
                },
                "channels": {"status": "pending", "completed_at": None},
                "validate": {"status": "pending", "completed_at": None},
            },
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "onboarding" in result.output
    assert "2/4" in result.output


def test_status_shows_onboarding_without_step(mock_hosts_with_claws):
    """B6: ONBOARDING without stages shows fallback '0/4'."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.ONBOARDING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "onboarding" in result.output
    assert "0/4" in result.output


def test_status_shows_ready_stopped(mock_hosts_with_claws):
    """B5: READY shows 'ready (stopped)' status."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.READY,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "ready" in result.output
    assert "stopped" in result.output


# Tests for verbose mode - Issue #73


def test_status_verbose_flag_accepted(mock_hosts_with_claws):
    """--verbose flag is accepted; running claws show no stage breakdown."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "--verbose"])

    assert result.exit_code == 0
    assert "running" in result.output
    # Running claws do not trigger verbose onboarding breakdown
    assert "No onboarding data available" not in result.output
    assert "providers" not in result.output


def test_status_verbose_shows_onboarding_stages(mock_hosts_with_claws):
    """Verbose mode shows onboarding stage breakdown."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.ONBOARDING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": "2/4",
            "process_running": False,
            "onboarding_stages": {
                "providers": {
                    "status": "complete",
                    "completed_at": "2026-04-06T10:00:00Z",
                },
                "identity": {
                    "status": "complete",
                    "completed_at": "2026-04-06T11:00:00Z",
                },
                "channels": {"status": "pending", "completed_at": None},
                "validate": {"status": "pending", "completed_at": None},
            },
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "--verbose"])

    assert result.exit_code == 0
    assert "providers" in result.output
    assert "identity" in result.output
    assert "channels" in result.output
    assert "validate" in result.output


def test_status_verbose_shows_stage_completion_dates(mock_hosts_with_claws):
    """Verbose mode shows completion dates for completed stages."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.ONBOARDING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": "2/4",
            "process_running": False,
            "onboarding_stages": {
                "providers": {
                    "status": "complete",
                    "completed_at": "2026-04-06T10:00:00Z",
                },
                "identity": {"status": "pending", "completed_at": None},
                "channels": {"status": "pending", "completed_at": None},
                "validate": {"status": "pending", "completed_at": None},
            },
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "--verbose"])

    assert result.exit_code == 0
    assert "2026-04-06" in result.output


def test_status_verbose_pending_onboard(mock_hosts_with_claws):
    """Verbose mode shows pending stages for PENDING_ONBOARD status."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.PENDING_ONBOARD,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": {
                "providers": {"status": "pending", "completed_at": None},
                "identity": {"status": "pending", "completed_at": None},
                "channels": {"status": "pending", "completed_at": None},
                "validate": {"status": "pending", "completed_at": None},
            },
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "--verbose"])

    assert result.exit_code == 0
    assert "providers" in result.output
    assert "pending" in result.output


def test_status_verbose_no_stages_for_running(mock_hosts_with_claws):
    """Verbose mode does not show stages for running claws."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "--verbose"])

    assert result.exit_code == 0
    # Running claws should not show stage breakdown
    assert "providers" not in result.output
    assert "No onboarding data available" not in result.output


def test_status_shows_completed_stage_count(mock_hosts_with_claws):
    """Status shows completed stage count (N/4) for onboarding claws."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.ONBOARDING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": "2/4",
            "process_running": False,
            "onboarding_stages": {
                "providers": {
                    "status": "complete",
                    "completed_at": "2026-04-06T10:00:00Z",
                },
                "identity": {
                    "status": "complete",
                    "completed_at": "2026-04-06T11:00:00Z",
                },
                "channels": {"status": "pending", "completed_at": None},
                "validate": {"status": "pending", "completed_at": None},
            },
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "onboarding" in result.output
    assert "2/4" in result.output


def test_status_verbose_ready_status(mock_hosts_with_claws):
    """Verbose mode shows all completed stages for READY status."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.READY,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": False,
            "onboarding_stages": {
                "providers": {
                    "status": "complete",
                    "completed_at": "2026-04-06T10:00:00Z",
                },
                "identity": {
                    "status": "complete",
                    "completed_at": "2026-04-06T11:00:00Z",
                },
                "channels": {
                    "status": "complete",
                    "completed_at": "2026-04-06T12:00:00Z",
                },
                "validate": {
                    "status": "complete",
                    "completed_at": "2026-04-06T13:00:00Z",
                },
            },
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "--verbose"])

    assert result.exit_code == 0
    # Each host shows 4 stages with checkmarks
    assert "✓ providers" in result.output
    assert "✓ identity" in result.output
    assert "✓ channels" in result.output
    assert "✓ validate" in result.output


def test_status_verbose_no_onboarding_stages(mock_hosts_with_claws):
    """Verbose mode shows fallback message when onboarding_stages is None."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.ONBOARDING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": "1/4",
            "process_running": False,
            "onboarding_stages": None,
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "--verbose"])

    assert result.exit_code == 0
    assert "No onboarding data available" in result.output


def test_status_verbose_short_alias(mock_hosts_with_claws):
    """Short -v alias for --verbose is accepted and works."""
    mock_health = MagicMock(
        return_value={
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.ONBOARDING,
            "agent_name": "opc-server1",
            "error": None,
            "missing_secrets": None,
            "onboarding_step": "1/4",
            "process_running": False,
            "onboarding_stages": {
                "providers": {
                    "status": "complete",
                    "completed_at": "2026-04-06T10:00:00Z",
                },
                "identity": {"status": "pending", "completed_at": None},
                "channels": {"status": "pending", "completed_at": None},
                "validate": {"status": "pending", "completed_at": None},
            },
        }
    )

    with patch("clawrium.cli.status.load_hosts", return_value=mock_hosts_with_claws):
        with patch("clawrium.cli.status.check_claw_health", mock_health):
            result = runner.invoke(app, ["ps", "-v"])

    assert result.exit_code == 0
    assert "providers" in result.output

"""Tests for clm agent start command with onboarding guardrails."""

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from clawrium.cli.main import app
from clawrium.core.onboarding import ClawNotFoundError

runner = CliRunner()


def create_host_with_claw(
    config_dir: Path,
    hostname: str = "192.168.1.100",
    alias: str = "work",
    key_id: str = "work",
    claw_type: str = "opc",
    onboarding_state: str = "pending",
) -> None:
    """Create a test host with a claw installed."""
    hosts_file = config_dir / "hosts.json"
    config_dir.mkdir(parents=True, exist_ok=True)

    hosts_data = [
        {
            "hostname": hostname,
            "key_id": key_id,
            "port": 22,
            "user": "xclm",
            "alias": alias,
            "auth_method": "key",
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 4,
                "memtotal_mb": 8192,
                "os": "ubuntu",
                "os_version": "24.04",
                "distribution": "ubuntu",
                "distribution_version": "24.04",
                "gpu": {"present": False},
            },
            "metadata": {
                "added_at": "2026-04-06T00:00:00Z",
                "last_seen": "2026-04-06T00:00:00Z",
                "tags": [],
            },
            "claws": {
                claw_type: {
                    "version": "0.1.0",
                    "status": "installed",
                    "name": "assistant",
                    "user": f"{claw_type}-assistant",
                    "onboarding": {
                        "state": onboarding_state,
                        "started_at": "2026-04-06T00:00:00+00:00",
                        "stages": {
                            "providers": {
                                "status": "complete"
                                if onboarding_state
                                in ["identity", "channels", "validate", "ready"]
                                else "pending",
                                "completed_at": None,
                                "provider_id": None,
                            },
                            "identity": {
                                "status": "complete"
                                if onboarding_state in ["channels", "validate", "ready"]
                                else "pending",
                                "completed_at": None,
                            },
                            "channels": {
                                "status": "complete"
                                if onboarding_state in ["validate", "ready"]
                                else "pending",
                                "completed_at": None,
                            },
                            "validate": {
                                "status": "complete"
                                if onboarding_state == "ready"
                                else "pending",
                                "completed_at": None,
                            },
                        },
                    },
                }
            },
        }
    ]

    hosts_file.write_text(json.dumps(hosts_data, indent=2))


def test_start_ready_state_succeeds(isolated_config: Path):
    """Start when state=READY succeeds."""
    from unittest.mock import MagicMock

    create_host_with_claw(isolated_config, onboarding_state="ready")

    key_path = isolated_config / "test_key"
    key_path.write_text("private key")

    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = []

    with patch("clawrium.core.config.get_config_dir", return_value=isolated_config):
        with patch(
            "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
        ):
            with patch(
                "clawrium.core.lifecycle.ansible_runner.run", return_value=mock_runner
            ):
                with patch(
                    "clawrium.core.lifecycle.get_config_dir",
                    return_value=isolated_config,
                ):
                    result = runner.invoke(app, ["agent", "start", "opc-work"])

    print("Exit code:", result.exit_code)
    print("Output:")
    print(result.output)
    print("---")
    print("[green]Starting agent:[/green] opc on work")
    print("[dim]Checking opc on work...[/dim]")
    print("  Starting opc on work")
    print("[green]✓[/green] Agent started successfully")
    print("  Run 'clm agent ps' to check status")

    assert result.exit_code == 0
    assert "Starting agent" in result.output
    assert "started successfully" in result.output


def test_start_pending_state_blocked(isolated_config: Path):
    """Start when state=PENDING is blocked and shows configure hint."""
    create_host_with_claw(isolated_config, onboarding_state="pending")

    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "Cannot start" in result.output
    assert "onboarding not started" in result.output
    assert "clm agent configure opc-work" in result.output


def test_start_providers_state_blocked(isolated_config: Path):
    """Start when state=PROVIDERS is blocked and shows incomplete stages."""
    create_host_with_claw(isolated_config, onboarding_state="providers")

    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "Cannot start" in result.output
    assert "onboarding incomplete" in result.output
    assert "PROVIDERS" in result.output
    assert "Incomplete stages" in result.output
    assert "identity" in result.output
    assert "channels" in result.output
    assert "validate" in result.output


def test_start_identity_state_blocked(isolated_config: Path):
    """Start when state=IDENTITY (1/4) shows correct stage count."""
    create_host_with_claw(isolated_config, onboarding_state="identity")

    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "Cannot start" in result.output
    assert "IDENTITY (1/4)" in result.output
    assert "Incomplete stages" in result.output
    assert "channels" in result.output
    assert "validate" in result.output


def test_start_channels_state_blocked(isolated_config: Path):
    """Start when state=CHANNELS is blocked."""
    create_host_with_claw(isolated_config, onboarding_state="channels")

    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "Cannot start" in result.output
    assert "CHANNELS" in result.output
    assert "Incomplete stages" in result.output
    assert "validate" in result.output


def test_start_validate_state_blocked(isolated_config: Path):
    """Start when state=VALIDATE is blocked."""
    create_host_with_claw(isolated_config, onboarding_state="validate")

    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "Cannot start" in result.output
    assert "VALIDATE" in result.output


def test_start_with_force_when_not_ready_succeeds(isolated_config: Path):
    """Start with --force when not READY shows warning but succeeds."""
    from unittest.mock import MagicMock

    create_host_with_claw(isolated_config, onboarding_state="providers")

    key_path = isolated_config / "test_key"
    key_path.write_text("private key")

    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.events = []

    with patch("clawrium.core.lifecycle.get_host_private_key", return_value=key_path):
        with patch(
            "clawrium.core.lifecycle.ansible_runner.run", return_value=mock_runner
        ):
            with patch(
                "clawrium.core.lifecycle.get_config_dir", return_value=isolated_config
            ):
                result = runner.invoke(app, ["agent", "start", "opc-work", "--force"])

    assert result.exit_code == 0
    assert "Warning" in result.output or "Starting agent" in result.output
    assert "Starting agent" in result.output


def test_start_invalid_claw_name_fails(isolated_config: Path):
    """Start with invalid claw name format fails."""
    create_host_with_claw(isolated_config)

    result = runner.invoke(app, ["agent", "start", "invalid"])

    assert result.exit_code == 1
    assert "Invalid claw name format" in result.output


def test_start_unknown_host_fails(isolated_config: Path):
    """Start with unknown host fails."""
    result = runner.invoke(app, ["agent", "start", "opc-unknown"])

    assert result.exit_code == 1
    assert "Host 'unknown' not found" in result.output


def test_start_claw_not_installed_fails(isolated_config: Path):
    """Start with claw not installed fails."""
    hosts_file = isolated_config / "hosts.json"
    isolated_config.mkdir(parents=True, exist_ok=True)

    hosts_data = [
        {
            "hostname": "192.168.1.100",
            "alias": "work",
            "key_id": "work",
            "port": 22,
            "user": "xclm",
            "auth_method": "key",
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 4,
                "memtotal_mb": 8192,
                "os": "ubuntu",
                "os_version": "24.04",
                "distribution": "ubuntu",
                "distribution_version": "24.04",
                "gpu": {"present": False},
            },
            "metadata": {
                "added_at": "2026-04-06T00:00:00Z",
                "last_seen": "2026-04-06T00:00:00Z",
                "tags": [],
            },
            "claws": {},
        }
    ]

    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "not installed" in result.output


def test_start_corrupted_hosts_file_fails(isolated_config: Path):
    """Start with corrupted hosts.json fails gracefully."""
    hosts_file = isolated_config / "hosts.json"
    isolated_config.mkdir(parents=True, exist_ok=True)

    hosts_file.write_text("invalid json {")

    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "clm host list" in result.output


def test_start_missing_onboarding_initializes(isolated_config: Path):
    """Start with missing onboarding record initializes it."""
    hosts_file = isolated_config / "hosts.json"
    isolated_config.mkdir(parents=True, exist_ok=True)

    hosts_data = [
        {
            "hostname": "192.168.1.100",
            "alias": "work",
            "key_id": "work",
            "port": 22,
            "user": "xclm",
            "auth_method": "key",
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 4,
                "memtotal_mb": 8192,
                "os": "ubuntu",
                "os_version": "24.04",
                "distribution": "ubuntu",
                "distribution_version": "24.04",
                "gpu": {"present": False},
            },
            "metadata": {
                "added_at": "2026-04-06T00:00:00Z",
                "last_seen": "2026-04-06T00:00:00Z",
                "tags": [],
            },
            "claws": {
                "opc": {
                    "version": "0.1.0",
                    "status": "installed",
                    "name": "assistant",
                    "user": "opc-assistant",
                }
            },
        }
    ]

    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "Cannot start" in result.output
    assert "onboarding not started" in result.output


def test_start_keyboard_interrupt_during_execution(isolated_config: Path):
    """Start handles KeyboardInterrupt gracefully."""
    create_host_with_claw(isolated_config, onboarding_state="ready")

    with patch("clawrium.cli.agent.get_host", side_effect=KeyboardInterrupt):
        result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "Cancelled" in result.output


def test_start_claw_not_found_during_initialization(isolated_config: Path):
    """Start handles ClawNotFoundError when initialize_onboarding fails."""
    hosts_file = isolated_config / "hosts.json"
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Create host with claw but no onboarding record
    hosts_data = [
        {
            "hostname": "192.168.1.100",
            "alias": "work",
            "key_id": "work",
            "port": 22,
            "user": "xclm",
            "auth_method": "key",
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 4,
                "memtotal_mb": 8192,
                "os": "ubuntu",
                "os_version": "24.04",
                "distribution": "ubuntu",
                "distribution_version": "24.04",
                "gpu": {"present": False},
            },
            "metadata": {
                "added_at": "2026-04-06T00:00:00Z",
                "last_seen": "2026-04-06T00:00:00Z",
                "tags": [],
            },
            "claws": {
                "opc": {
                    "version": "0.1.0",
                    "status": "installed",
                    "name": "assistant",
                    "user": "opc-assistant",
                }
            },
        }
    ]

    hosts_file.write_text(json.dumps(hosts_data, indent=2))

    # Mock initialize_onboarding to raise ClawNotFoundError
    with patch(
        "clawrium.cli.agent.initialize_onboarding",
        side_effect=ClawNotFoundError("Claw 'opc' not found on host 'work'"),
    ):
        result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "not found" in result.output

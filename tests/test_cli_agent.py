"""Tests for the agent subcommand group."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from clawrium.cli.main import app

runner = CliRunner()


def create_test_keypair(config_dir: Path, key_id: str) -> None:
    """Create a test keypair for a host (required before install)."""
    key_dir = config_dir / "keys" / key_id
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "xclm_ed25519").write_text("test-private-key")
    (key_dir / "xclm_ed25519").chmod(0o600)
    (key_dir / "xclm_ed25519.pub").write_text("ssh-ed25519 AAAA... clawrium")


def create_host(
    config_dir: Path, hostname: str, alias: str | None = None, key_id: str | None = None
) -> None:
    """Create a test host entry."""
    hosts_file = config_dir / "hosts.json"
    config_dir.mkdir(parents=True, exist_ok=True)

    host_data = {
        "hostname": hostname,
        "key_id": key_id or hostname,
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
            "added_at": "2026-03-21T00:00:00Z",
            "last_seen": "2026-03-21T00:00:00Z",
            "tags": [],
        },
    }

    if alias:
        host_data["alias"] = alias

    # Load existing hosts or create new
    if hosts_file.exists():
        hosts = json.loads(hosts_file.read_text())
    else:
        hosts = []

    hosts.append(host_data)
    hosts_file.write_text(json.dumps(hosts, indent=2))


# Tests for clm agent --help
def test_agent_help():
    """clm agent --help shows agent subcommands."""
    result = runner.invoke(app, ["agent", "--help"])

    assert result.exit_code == 0
    assert "agent" in result.output.lower()
    # Should list subcommands
    assert "install" in result.output.lower()
    assert "ps" in result.output.lower()
    assert "secret" in result.output.lower()
    assert "registry" in result.output.lower()


def test_agent_no_args_shows_help():
    """clm agent without arguments shows help."""
    result = runner.invoke(app, ["agent"])

    # no_args_is_help=True exits with code 2 (standard Typer behavior)
    assert result.exit_code == 2
    assert "install" in result.output.lower() or "usage" in result.output.lower()


# Tests for clm agent install
def test_agent_install_prompts_for_claw(isolated_config: Path):
    """clm agent install with no --claw flag triggers claw selection prompt."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    result = runner.invoke(
        app, ["agent", "install", "--host", "testhost"], input="\n", env=os.environ
    )

    assert (
        "available claw" in result.output.lower()
        or "select claw" in result.output.lower()
    )


def test_agent_install_with_flags(isolated_config: Path):
    """clm agent install --claw --host skips prompts."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.return_value = {
            "success": True,
            "claw": "openclaw",
            "version": "1.0.0",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

        result = runner.invoke(
            app,
            ["agent", "install", "--claw", "openclaw", "--host", "testhost", "--yes"],
            env=os.environ,
        )

        assert result.exit_code == 0
        mock_install.assert_called_once()


# Tests for clm agent ps
def test_agent_ps_no_hosts():
    """clm agent ps with no hosts shows message."""
    with patch("clawrium.cli.status.load_hosts", return_value=[]):
        result = runner.invoke(app, ["agent", "ps"])

    assert result.exit_code == 0
    assert "No hosts registered" in result.output


def test_agent_ps_no_claws():
    """clm agent ps with hosts but no claws shows message."""
    hosts = [{"hostname": "192.168.1.100", "claws": {}}]

    with patch("clawrium.cli.status.load_hosts", return_value=hosts):
        result = runner.invoke(app, ["agent", "ps"])

    assert result.exit_code == 0
    assert "No claws installed" in result.output


# Tests for placeholder commands
def test_agent_configure_requires_valid_name():
    """clm agent configure requires valid claw name format."""
    result = runner.invoke(app, ["agent", "configure", "opc-work"])

    assert result.exit_code == 1
    assert "host" in result.output.lower() and "not found" in result.output.lower()


def test_agent_remove_placeholder():
    """clm agent remove shows not implemented message."""
    result = runner.invoke(app, ["agent", "remove", "opc-work"])

    assert result.exit_code == 1
    assert "not implemented" in result.output.lower()


def test_agent_start_with_missing_host():
    """clm agent start with missing host shows error."""
    result = runner.invoke(app, ["agent", "start", "opc-work"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_agent_stop_placeholder():
    """clm agent stop shows not implemented message."""
    result = runner.invoke(app, ["agent", "stop", "opc-work"])

    assert result.exit_code == 0
    assert "not implemented" in result.output.lower()


def test_agent_logs_placeholder():
    """clm agent logs shows not implemented message."""
    result = runner.invoke(app, ["agent", "logs", "opc-work"])

    assert result.exit_code == 0
    assert "not implemented" in result.output.lower()


# Tests for clm agent secret subcommands
def test_agent_secret_help():
    """clm agent secret --help shows secret subcommands."""
    result = runner.invoke(app, ["agent", "secret", "--help"])

    assert result.exit_code == 0
    assert "set" in result.output.lower()
    assert "list" in result.output.lower()
    assert "remove" in result.output.lower()


def test_agent_secret_import_placeholder():
    """clm agent secret import shows not implemented message."""
    result = runner.invoke(
        app, ["agent", "secret", "import", "source-claw", "target-claw"]
    )

    assert result.exit_code == 0
    assert "not implemented" in result.output.lower()


# Tests for clm agent registry subcommands
def test_agent_registry_help():
    """clm agent registry --help shows registry subcommands."""
    result = runner.invoke(app, ["agent", "registry", "--help"])

    assert result.exit_code == 0
    assert "list" in result.output.lower()
    assert "show" in result.output.lower()


def test_agent_registry_list():
    """clm agent registry list shows available claws."""
    result = runner.invoke(app, ["agent", "registry", "list"])

    assert result.exit_code == 0
    assert "openclaw" in result.output.lower()


def test_agent_registry_show():
    """clm agent registry show displays claw details."""
    result = runner.invoke(app, ["agent", "registry", "show", "openclaw"])

    assert result.exit_code == 0
    assert "openclaw" in result.output.lower()
    assert "Supported Platforms" in result.output


# Tests for clm ps (top-level fleet overview)
def test_ps_no_hosts():
    """clm ps with no hosts shows message."""
    with patch("clawrium.cli.status.load_hosts", return_value=[]):
        result = runner.invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "No hosts registered" in result.output


# Tests for clm snapshot
def test_snapshot_placeholder():
    """clm snapshot shows not implemented message."""
    result = runner.invoke(app, ["snapshot"])

    assert result.exit_code == 0
    assert "not implemented" in result.output.lower()


# Tests for CLI hierarchy
def test_main_help_shows_agent_first():
    """clm --help shows agent as primary command group."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "agent" in result.output
    # Agent should be listed as a command
    assert "Manage AI assistants" in result.output or "agent" in result.output.lower()

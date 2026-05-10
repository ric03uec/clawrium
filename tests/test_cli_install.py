"""Tests for CLI install command."""

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
        "agent_name": "xclm",
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


def test_install_prompts_for_claw(isolated_config: Path):
    """clm install with no --type flag triggers claw selection prompt."""
    # Setup: create host and keypair
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    # Run without --type, answer prompts with EOF to cancel
    result = runner.invoke(
        app, ["agent", "install", "--host", "testhost"], input="\n", env=os.environ
    )

    # Should show claw selection prompt
    assert (
        "available agent type" in result.output.lower()
        or "select claw" in result.output.lower()
    )


def test_install_prompts_for_host(isolated_config: Path):
    """clm install with no --host flag triggers host selection prompt."""
    # Setup: create host and keypair
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    # Run without --host, answer prompts with EOF to cancel
    result = runner.invoke(
        app, ["agent", "install", "--type", "openclaw"], input="\n", env=os.environ
    )

    # Should show host selection prompt
    assert (
        "available host" in result.output.lower()
        or "select host" in result.output.lower()
    )


def test_install_with_flags_skips_prompts(isolated_config: Path):
    """clm install --type openclaw --host testhost skips prompts and goes to confirmation."""
    # Setup: create host and keypair
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    # Mock run_installation to avoid actual execution
    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.return_value = {
            "success": True,
            "agent": "openclaw",
            "version": "1.0.0",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

        # Run with both flags, cancel at confirmation
        result = runner.invoke(
            app,
            ["agent", "install", "--type", "openclaw", "--host", "testhost"],
            input="n\n",
            env=os.environ,
        )

        # Should NOT show claw/host selection prompts
        # Should show confirmation (cancelled)
        assert "proceed" in result.output.lower() or "install" in result.output.lower()
        # Should not have called install due to cancellation
        mock_install.assert_not_called()


def test_install_shows_confirmation(isolated_config: Path):
    """clm install shows confirmation summary before proceeding."""
    # Setup: create host and keypair
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    # Run with flags, cancel at confirmation
    result = runner.invoke(
        app,
        ["agent", "install", "--type", "openclaw", "--host", "testhost"],
        input="n\n",
        env=os.environ,
    )

    # Should show installation summary panel
    assert (
        "installation summary" in result.output.lower()
        or "claw:" in result.output.lower()
    )
    assert "openclaw" in result.output.lower()
    assert "cancelled" in result.output.lower()


def test_install_yes_skips_confirmation(isolated_config: Path):
    """clm install --yes proceeds without confirmation prompt."""
    # Setup: create host and keypair
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    # Mock run_installation
    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.return_value = {
            "success": True,
            "agent": "openclaw",
            "version": "1.0.0",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

        # Run with --yes flag
        result = runner.invoke(
            app,
            ["agent", "install", "--type", "openclaw", "--host", "testhost", "--yes"],
            env=os.environ,
        )

        # Should proceed directly to installation
        assert result.exit_code == 0
        assert "success" in result.output.lower()
        mock_install.assert_called_once()


def test_install_force_flag_propagates(isolated_config: Path):
    """`clm agent install --force` must forward force=True to run_installation."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.return_value = {
            "success": True,
            "agent": "openclaw",
            "version": "2026.4.2",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

        result = runner.invoke(
            app,
            [
                "agent",
                "install",
                "--type",
                "openclaw",
                "--host",
                "testhost",
                "--yes",
                "--force",
            ],
            env=os.environ,
        )

        assert result.exit_code == 0
        mock_install.assert_called_once()
        kwargs = mock_install.call_args.kwargs
        assert kwargs.get("force") is True


def test_install_default_force_is_false(isolated_config: Path):
    """Without --force, run_installation receives force=False."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.return_value = {
            "success": True,
            "agent": "openclaw",
            "version": "2026.4.2",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

        result = runner.invoke(
            app,
            ["agent", "install", "--type", "openclaw", "--host", "testhost", "--yes"],
            env=os.environ,
        )

        assert result.exit_code == 0
        mock_install.assert_called_once()
        kwargs = mock_install.call_args.kwargs
        assert kwargs.get("force") is False


def test_install_yes_shows_skip_message_when_already_installed(isolated_config: Path):
    """clm install --yes reports skip when backend marks install as skipped."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.return_value = {
            "success": True,
            "agent": "openclaw",
            "version": "2026.4.2",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
            "skipped": True,
            "skip_reason": "already_installed_version_match",
        }

        result = runner.invoke(
            app,
            ["agent", "install", "--type", "openclaw", "--host", "testhost", "--yes"],
            env=os.environ,
        )

        assert result.exit_code == 0
        assert "already installed" in result.output.lower()
        assert "skipped" in result.output.lower()


def test_install_cancelled_exits_0(isolated_config: Path):
    """Declining confirmation exits cleanly with code 0."""
    # Setup: create host and keypair
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    # Run and decline confirmation
    result = runner.invoke(
        app,
        ["agent", "install", "--type", "openclaw", "--host", "testhost"],
        input="n\n",
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()


def test_install_error_exits_1(isolated_config: Path):
    """InstallationError shows error message and exits 1."""
    # Setup: create host and keypair
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    # Mock run_installation to raise error
    from clawrium.core.install import InstallationError

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.side_effect = InstallationError("Playbook failed")

        # Run with --yes to skip confirmation
        result = runner.invoke(
            app,
            ["agent", "install", "--type", "openclaw", "--host", "testhost", "--yes"],
            env=os.environ,
        )

        assert result.exit_code == 1
        assert "failed" in result.output.lower()
        assert "playbook" in result.output.lower()


def test_install_incomplete_error_exits_1(isolated_config: Path):
    """IncompleteInstallationError shows interactive prompt and user can abort."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    from clawrium.core.install import IncompleteInstallationError

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.side_effect = IncompleteInstallationError(
            hostname="192.168.1.100",
            claw_name="openclaw",
            details={
                "status": "failed",
                "installed_at": None,
                "error": "Base playbook failed",
                "agent_name": "work-assistant",
                "version": "0.1.0",
            },
        )

        # Mock user selecting "Abort" option (3)
        with patch("typer.prompt", return_value=3):
            result = runner.invoke(
                app,
                [
                    "agent",
                    "install",
                    "--type",
                    "openclaw",
                    "--host",
                    "testhost",
                    "--yes",
                ],
                env=os.environ,
            )

        assert result.exit_code == 0  # Abort exits with 0, not 1
        assert "incomplete installation" in result.output.lower()
        assert "work-assistant" in result.output.lower()
        assert "cancelled" in result.output.lower() or "abort" in result.output.lower()


def test_install_incompatible_exits_1(isolated_config: Path):
    """Incompatible host shows reasons and exits 1."""
    # Setup: create host with incompatible hardware (ARM instead of x86_64)
    create_test_keypair(isolated_config, "armhost")

    hosts_file = isolated_config / "hosts.json"
    isolated_config.mkdir(parents=True, exist_ok=True)

    incompatible_host = {
        "hostname": "192.168.1.200",
        "alias": "armhost",
        "key_id": "armhost",
        "port": 22,
        "agent_name": "xclm",
        "auth_method": "key",
        "hardware": {
            "architecture": "aarch64",  # OpenClaw requires x86_64
            "processor_cores": 4,
            "memtotal_mb": 8192,
            "distribution": "ubuntu",
            "distribution_version": "22.04",
            "gpu": {"present": False},
        },
        "metadata": {
            "added_at": "2026-03-21T00:00:00Z",
            "last_seen": "2026-03-21T00:00:00Z",
            "tags": [],
        },
    }

    hosts_file.write_text(json.dumps([incompatible_host], indent=2))

    # Try to install openclaw (requires x86_64)
    result = runner.invoke(
        app,
        ["agent", "install", "--type", "openclaw", "--host", "armhost"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert (
        "incompatible" in result.output.lower()
        or "architecture" in result.output.lower()
    )


def test_install_hosts_file_corrupted(isolated_config: Path):
    """HostsFileCorruptedError shows error and exits 1."""
    from clawrium.core.hosts import HostsFileCorruptedError

    with patch(
        "clawrium.cli.install.load_hosts",
        side_effect=HostsFileCorruptedError("JSON parse error"),
    ):
        result = runner.invoke(
            app,
            ["agent", "install", "--type", "openclaw", "--host", "testhost"],
            env=os.environ,
        )

    assert result.exit_code == 1
    assert "corrupted" in result.output.lower() or "error" in result.output.lower()


def test_install_claw_flag_rejected(isolated_config: Path):
    """Test that the old --claw flag is rejected with proper error message."""
    # Setup: create host and keypair
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    # Try using the old --claw flag
    result = runner.invoke(
        app,
        ["agent", "install", "--claw", "openclaw", "--host", "testhost"],
        env=os.environ,
    )

    # Should exit with error code 2 (Typer's "no such option" error)
    assert result.exit_code == 2
    # Should mention the flag issue
    assert "no such option" in result.output.lower() or "claw" in result.output.lower()


def test_install_cleanup_failed_flag_is_forwarded_to_run_installation(
    isolated_config: Path,
):
    """--cleanup-failed flag is passed as cleanup_failed=True to run_installation."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.return_value = {
            "success": True,
            "agent": "openclaw",
            "version": "1.0.0",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

        result = runner.invoke(
            app,
            [
                "agent",
                "install",
                "--type",
                "openclaw",
                "--host",
                "testhost",
                "--yes",
                "--cleanup-failed",
            ],
            env=os.environ,
        )

        assert result.exit_code == 0
        mock_install.assert_called_once()
        assert mock_install.call_args.kwargs["cleanup_failed"] is True


def test_install_without_cleanup_failed_defaults_to_false(isolated_config: Path):
    """Without --cleanup-failed, cleanup_failed=False is passed to run_installation."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.return_value = {
            "success": True,
            "agent": "openclaw",
            "version": "1.0.0",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

        result = runner.invoke(
            app,
            [
                "agent",
                "install",
                "--type",
                "openclaw",
                "--host",
                "testhost",
                "--yes",
            ],
            env=os.environ,
        )

        assert result.exit_code == 0
        mock_install.assert_called_once()
        assert mock_install.call_args.kwargs["cleanup_failed"] is False


def test_install_cleanup_failed_skips_prompt(isolated_config: Path):
    """--cleanup-failed skips interactive prompt on IncompleteInstallationError."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    from clawrium.core.install import IncompleteInstallationError

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.side_effect = [
            IncompleteInstallationError(
                hostname="192.168.1.100",
                claw_name="openclaw",
                details={
                    "status": "failed",
                    "installed_at": None,
                    "error": "Base playbook failed",
                    "agent_name": "work-assistant",
                    "version": "0.1.0",
                },
            ),
            {
                "success": True,
                "agent": "openclaw",
                "version": "1.0.0",
                "host": "192.168.1.100",
                "playbooks_run": [],
                "error": None,
            },
        ]

        with patch("typer.prompt") as mock_prompt:
            result = runner.invoke(
                app,
                [
                    "agent",
                    "install",
                    "--type",
                    "openclaw",
                    "--host",
                    "testhost",
                    "--yes",
                    "--cleanup-failed",
                ],
                env=os.environ,
            )

        assert result.exit_code == 0
        assert "success" in result.output.lower()
        assert mock_install.call_count == 2
        second_call = mock_install.call_args_list[1]
        assert second_call.kwargs["cleanup_failed"] is True
        mock_prompt.assert_not_called()


def test_install_cleanup_failed_retry_fails(isolated_config: Path):
    """When --cleanup-failed retry also fails, InstallationError is shown."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    from clawrium.core.install import IncompleteInstallationError, InstallationError

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.side_effect = [
            IncompleteInstallationError(
                hostname="192.168.1.100",
                claw_name="openclaw",
                details={
                    "status": "failed",
                    "installed_at": None,
                    "error": "Base playbook failed",
                    "agent_name": "work-assistant",
                    "version": "0.1.0",
                },
            ),
            InstallationError("Retry playbook failed"),
        ]

        result = runner.invoke(
            app,
            [
                "agent",
                "install",
                "--type",
                "openclaw",
                "--host",
                "testhost",
                "--yes",
                "--cleanup-failed",
            ],
            env=os.environ,
        )

        assert result.exit_code == 1
        assert "failed" in result.output.lower()


def test_install_without_cleanup_failed_shows_prompt(isolated_config: Path):
    """Without --cleanup-failed, IncompleteInstallationError shows interactive prompt."""
    create_test_keypair(isolated_config, "testhost")
    create_host(isolated_config, "192.168.1.100", alias="testhost", key_id="testhost")

    from clawrium.core.install import IncompleteInstallationError

    with patch("clawrium.cli.install.run_installation") as mock_install:
        mock_install.side_effect = IncompleteInstallationError(
            hostname="192.168.1.100",
            claw_name="openclaw",
            details={
                "status": "failed",
                "installed_at": None,
                "error": "Base playbook failed",
                "agent_name": "work-assistant",
                "version": "0.1.0",
            },
        )

        with patch("typer.prompt", return_value=3) as mock_prompt:
            result = runner.invoke(
                app,
                [
                    "agent",
                    "install",
                    "--type",
                    "openclaw",
                    "--host",
                    "testhost",
                    "--yes",
                ],
                env=os.environ,
            )

        assert "incomplete installation" in result.output.lower()
        mock_prompt.assert_called()

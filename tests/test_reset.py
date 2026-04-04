"""Tests for reset core module."""

import pytest
from unittest.mock import MagicMock, patch


class TestResetTargetsDataclass:
    """Tests for ResetTargets dataclass structure."""

    def test_reset_targets_dataclass_structure(self):
        """Verify ResetTargets has users, services, paths fields."""
        from clawrium.core.reset import ResetTargets

        targets = ResetTargets(
            users=["user1", "user2"],
            services=["zeroclaw-zc-test.service"],
            paths=["/etc/clawrium/", "/var/log/clawrium/"],
        )

        assert hasattr(targets, "users")
        assert hasattr(targets, "services")
        assert hasattr(targets, "paths")
        assert targets.users == ["user1", "user2"]
        assert targets.services == ["zeroclaw-zc-test.service"]
        assert targets.paths == ["/etc/clawrium/", "/var/log/clawrium/"]


class TestResetResultDataclass:
    """Tests for ResetResult dataclass structure."""

    def test_reset_result_dataclass_structure(self):
        """Verify ResetResult has success, removed, errors fields."""
        from clawrium.core.reset import ResetResult

        result = ResetResult(
            success=True,
            removed={"users": 2, "services": 1, "paths": 2},
            errors=[],
        )

        assert hasattr(result, "success")
        assert hasattr(result, "removed")
        assert hasattr(result, "errors")
        assert result.success is True
        assert result.removed == {"users": 2, "services": 1, "paths": 2}
        assert result.errors == []

    def test_reset_result_with_errors(self):
        """Verify ResetResult can hold error messages."""
        from clawrium.core.reset import ResetResult

        result = ResetResult(
            success=False,
            removed={"users": 0, "services": 0, "paths": 0},
            errors=["Failed to remove user: permission denied"],
        )

        assert result.success is False
        assert result.errors == ["Failed to remove user: permission denied"]


class TestEnumerateTargets:
    """Tests for enumerate_targets function."""

    def test_enumerate_targets_finds_users(self, monkeypatch):
        """Mock ansible to return users, verify filtering."""
        from clawrium.core.reset import enumerate_targets

        # Mock get_host to return valid host
        mock_host = {
            "hostname": "192.168.1.100",
            "user": "xclm",
            "port": 22,
            "key_id": "192.168.1.100",
        }
        monkeypatch.setattr("clawrium.core.reset.get_host", lambda x: mock_host)
        monkeypatch.setattr(
            "clawrium.core.reset.get_host_private_key",
            lambda x: "/tmp/fake_key",
        )

        # Mock ansible_runner.run to return users
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Get users",
                    "res": {"stdout": "opc-work\nzc-myhost\nnobody"},
                },
            },
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Get services",
                    "res": {"stdout": "zeroclaw-zc-myhost.service"},
                },
            },
        ]

        with patch("clawrium.core.reset.ansible_runner.run", return_value=mock_result):
            targets = enumerate_targets("192.168.1.100")

        assert "opc-work" in targets.users or "zc-myhost" in targets.users

    def test_enumerate_targets_excludes_xclm(self, monkeypatch):
        """Verify xclm is never in users list."""
        from clawrium.core.reset import enumerate_targets

        # Mock get_host to return valid host
        mock_host = {
            "hostname": "192.168.1.100",
            "user": "xclm",
            "port": 22,
            "key_id": "192.168.1.100",
        }
        monkeypatch.setattr("clawrium.core.reset.get_host", lambda x: mock_host)
        monkeypatch.setattr(
            "clawrium.core.reset.get_host_private_key",
            lambda x: "/tmp/fake_key",
        )

        # Mock ansible_runner.run to return users including xclm
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Get users",
                    "res": {"stdout": "xclm\nopc-work\nzc-myhost"},
                },
            },
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Get services",
                    "res": {"stdout": ""},
                },
            },
        ]

        with patch("clawrium.core.reset.ansible_runner.run", return_value=mock_result):
            targets = enumerate_targets("192.168.1.100")

        assert "xclm" not in targets.users

    def test_enumerate_targets_finds_claw_services(self, monkeypatch):
        """Verify *claw*.service pattern matching."""
        from clawrium.core.reset import enumerate_targets

        # Mock get_host to return valid host
        mock_host = {
            "hostname": "192.168.1.100",
            "user": "xclm",
            "port": 22,
            "key_id": "192.168.1.100",
        }
        monkeypatch.setattr("clawrium.core.reset.get_host", lambda x: mock_host)
        monkeypatch.setattr(
            "clawrium.core.reset.get_host_private_key",
            lambda x: "/tmp/fake_key",
        )

        # Mock ansible_runner.run to return services
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Get users",
                    "res": {"stdout": ""},
                },
            },
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Get services",
                    "res": {
                        "stdout": "zeroclaw-zc-myhost.service\nopenclaw-opc-work.service"
                    },
                },
            },
        ]

        with patch("clawrium.core.reset.ansible_runner.run", return_value=mock_result):
            targets = enumerate_targets("192.168.1.100")

        assert "zeroclaw-zc-myhost.service" in targets.services
        assert "openclaw-opc-work.service" in targets.services


class TestExecuteReset:
    """Tests for execute_reset function."""

    def test_execute_reset_returns_result(self, monkeypatch, tmp_path):
        """Verify execute_reset returns ResetResult."""
        from clawrium.core.reset import execute_reset, ResetTargets, ResetResult

        # Mock get_host
        mock_host = {
            "hostname": "192.168.1.100",
            "user": "xclm",
            "port": 22,
            "key_id": "192.168.1.100",
        }
        monkeypatch.setattr("clawrium.core.reset.get_host", lambda x: mock_host)
        monkeypatch.setattr(
            "clawrium.core.reset.get_host_private_key",
            lambda x: "/tmp/fake_key",
        )

        # Mock config dir
        monkeypatch.setattr("clawrium.core.reset.get_config_dir", lambda: tmp_path)

        # Mock ansible_runner.run to succeed
        mock_result = MagicMock()
        mock_result.status = "successful"
        mock_result.events = []

        targets = ResetTargets(
            users=["opc-work"],
            services=["openclaw-opc-work.service"],
            paths=["/etc/clawrium/", "/var/log/clawrium/"],
        )

        with patch("clawrium.core.reset.ansible_runner.run", return_value=mock_result):
            result = execute_reset("192.168.1.100", targets)

        assert isinstance(result, ResetResult)
        assert result.success is True

    def test_execute_reset_no_ssh_key(self, monkeypatch, tmp_path):
        """execute_reset returns error when SSH key is missing."""
        from clawrium.core.reset import execute_reset, ResetTargets

        # Mock get_host to return valid host
        mock_host = {
            "hostname": "192.168.1.100",
            "user": "xclm",
            "port": 22,
            "key_id": "192.168.1.100",
        }
        monkeypatch.setattr("clawrium.core.reset.get_host", lambda x: mock_host)
        # Return None for SSH key
        monkeypatch.setattr("clawrium.core.reset.get_host_private_key", lambda x: None)

        targets = ResetTargets(
            users=["opc-work"],
            services=["openclaw-opc-work.service"],
            paths=["/etc/clawrium/"],
        )

        result = execute_reset("192.168.1.100", targets)

        assert result.success is False
        assert "SSH key" in result.errors[0] or "key" in result.errors[0].lower()


class TestCliReset:
    """Tests for CLI reset command."""

    def test_reset_requires_confirmation_without_yes_flag(
        self, isolated_config, monkeypatch
    ):
        """Reset without --yes should prompt for confirmation."""
        from typer.testing import CliRunner
        from clawrium.cli.main import app
        import json

        runner = CliRunner()

        # Create host
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        host = {
            "hostname": "192.168.1.100",
            "key_id": "192.168.1.100",
            "port": 22,
            "user": "xclm",
        }
        hosts_file.write_text(json.dumps([host]))

        # Create keypair
        key_dir = isolated_config / "keys" / "192.168.1.100"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "xclm_ed25519").write_text("fake-key")
        (key_dir / "xclm_ed25519").chmod(0o600)

        # Mock enumerate_targets
        from clawrium.core.reset import ResetTargets

        mock_targets = ResetTargets(
            users=["opc-work"],
            services=["openclaw-opc-work.service"],
            paths=["/etc/clawrium/"],
        )
        monkeypatch.setattr(
            "clawrium.cli.host.enumerate_targets",
            lambda x: mock_targets,
        )

        # Run without --yes and answer 'n' to cancel
        result = runner.invoke(app, ["host", "reset", "192.168.1.100"], input="n\n")

        # Should abort without confirmation
        assert (
            result.exit_code == 1
            or "abort" in result.output.lower()
            or "cancelled" in result.output.lower()
        )

    def test_reset_dry_run_shows_targets(self, isolated_config, monkeypatch):
        """Reset --dry-run shows targets without executing."""
        from typer.testing import CliRunner
        from clawrium.cli.main import app
        import json

        runner = CliRunner()

        # Create host
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        host = {
            "hostname": "192.168.1.100",
            "key_id": "192.168.1.100",
            "port": 22,
            "user": "xclm",
        }
        hosts_file.write_text(json.dumps([host]))

        # Create keypair
        key_dir = isolated_config / "keys" / "192.168.1.100"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "xclm_ed25519").write_text("fake-key")
        (key_dir / "xclm_ed25519").chmod(0o600)

        # Mock enumerate_targets
        from clawrium.core.reset import ResetTargets

        mock_targets = ResetTargets(
            users=["opc-work", "zc-myhost"],
            services=["openclaw-opc-work.service", "zeroclaw-zc-myhost.service"],
            paths=["/etc/clawrium/", "/var/log/clawrium/"],
        )
        monkeypatch.setattr(
            "clawrium.cli.host.enumerate_targets",
            lambda x: mock_targets,
        )

        # Run with --dry-run
        result = runner.invoke(app, ["host", "reset", "192.168.1.100", "--dry-run"])

        # Should show users and services to be removed
        assert "opc-work" in result.output
        assert "zeroclaw" in result.output or "zc-myhost" in result.output

    def test_reset_yes_flag_skips_confirmation(self, isolated_config, monkeypatch):
        """Reset --yes executes without prompting."""
        from typer.testing import CliRunner
        from clawrium.cli.main import app
        import json

        runner = CliRunner()

        # Create host
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        host = {
            "hostname": "192.168.1.100",
            "key_id": "192.168.1.100",
            "port": 22,
            "user": "xclm",
        }
        hosts_file.write_text(json.dumps([host]))

        # Create keypair
        key_dir = isolated_config / "keys" / "192.168.1.100"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "xclm_ed25519").write_text("fake-key")
        (key_dir / "xclm_ed25519").chmod(0o600)

        # Mock enumerate_targets and execute_reset
        from clawrium.core.reset import ResetTargets, ResetResult

        mock_targets = ResetTargets(
            users=["opc-work"],
            services=["openclaw-opc-work.service"],
            paths=["/etc/clawrium/"],
        )
        mock_result = ResetResult(
            success=True,
            removed={"users": 1, "services": 1, "paths": 1},
            errors=[],
        )
        monkeypatch.setattr(
            "clawrium.cli.host.enumerate_targets", lambda x: mock_targets
        )
        monkeypatch.setattr("clawrium.cli.host.execute_reset", lambda x, y: mock_result)

        # Run with --yes
        result = runner.invoke(app, ["host", "reset", "192.168.1.100", "--yes"])

        # Should succeed without prompting
        assert result.exit_code == 0

    def test_reset_host_not_found(self, isolated_config):
        """Reset unknown host shows error."""
        from typer.testing import CliRunner
        from clawrium.cli.main import app

        runner = CliRunner()

        # Empty hosts
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_file.write_text("[]")

        result = runner.invoke(app, ["host", "reset", "unknown-host", "--yes"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_reset_clears_claws_array(self, isolated_config, monkeypatch):
        """Reset should clear the claws array in host record."""
        from typer.testing import CliRunner
        from clawrium.cli.main import app
        import json

        runner = CliRunner()

        # Create host with claws
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        host = {
            "hostname": "192.168.1.100",
            "key_id": "192.168.1.100",
            "port": 22,
            "user": "xclm",
            "claws": {
                "zeroclaw": {"status": "installed", "user": "zc-myhost"},
                "openclaw": {"status": "installed", "user": "opc-work"},
            },
        }
        hosts_file.write_text(json.dumps([host]))

        # Create keypair
        key_dir = isolated_config / "keys" / "192.168.1.100"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "xclm_ed25519").write_text("fake-key")
        (key_dir / "xclm_ed25519").chmod(0o600)

        # Mock enumerate_targets and execute_reset
        from clawrium.core.reset import ResetTargets, ResetResult

        mock_targets = ResetTargets(
            users=["opc-work", "zc-myhost"],
            services=["openclaw-opc-work.service", "zeroclaw-zc-myhost.service"],
            paths=["/etc/clawrium/"],
        )
        mock_result = ResetResult(
            success=True,
            removed={"users": 2, "services": 2, "paths": 1},
            errors=[],
        )
        monkeypatch.setattr(
            "clawrium.cli.host.enumerate_targets", lambda x: mock_targets
        )
        monkeypatch.setattr("clawrium.cli.host.execute_reset", lambda x, y: mock_result)

        # Run with --yes
        result = runner.invoke(app, ["host", "reset", "192.168.1.100", "--yes"])
        assert result.exit_code == 0

        # Check host record was updated
        hosts = json.loads(hosts_file.read_text())
        host = hosts[0]
        assert host.get("claws", {}) == {}
        # Verify last_reset timestamp was set
        assert "metadata" in host
        assert "last_reset" in host["metadata"]
        # Verify it's a valid ISO timestamp
        from datetime import datetime

        datetime.fromisoformat(host["metadata"]["last_reset"])


class TestResetEdgeCases:
    """Edge case tests for reset functionality."""

    def test_enumerate_targets_host_not_found(self, monkeypatch):
        """enumerate_targets raises ValueError for unknown host."""
        from clawrium.core.reset import enumerate_targets

        monkeypatch.setattr("clawrium.core.reset.get_host", lambda x: None)

        with pytest.raises(ValueError, match="not found"):
            enumerate_targets("unknown-host")

    def test_enumerate_targets_no_key(self, monkeypatch):
        """enumerate_targets raises ValueError if SSH key is missing."""
        from clawrium.core.reset import enumerate_targets

        mock_host = {
            "hostname": "192.168.1.100",
            "key_id": "192.168.1.100",
        }
        monkeypatch.setattr("clawrium.core.reset.get_host", lambda x: mock_host)
        monkeypatch.setattr("clawrium.core.reset.get_host_private_key", lambda x: None)

        with pytest.raises(ValueError, match="key"):
            enumerate_targets("192.168.1.100")

    def test_reset_with_no_targets(self, isolated_config, monkeypatch):
        """Reset with no targets should exit cleanly."""
        from typer.testing import CliRunner
        from clawrium.cli.main import app
        from clawrium.core.reset import ResetTargets
        import json

        runner = CliRunner()

        # Create host
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        host = {
            "hostname": "192.168.1.100",
            "key_id": "192.168.1.100",
            "port": 22,
            "user": "xclm",
        }
        hosts_file.write_text(json.dumps([host]))

        # Create keypair
        key_dir = isolated_config / "keys" / "192.168.1.100"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "xclm_ed25519").write_text("fake-key")
        (key_dir / "xclm_ed25519").chmod(0o600)

        # Mock enumerate_targets to return no targets
        mock_targets = ResetTargets(users=[], services=[], paths=[])
        monkeypatch.setattr(
            "clawrium.cli.host.enumerate_targets", lambda x: mock_targets
        )

        result = runner.invoke(app, ["host", "reset", "192.168.1.100", "--yes"])

        assert result.exit_code == 0
        assert "no targets" in result.output.lower()

    def test_reset_failure_returns_nonzero(self, isolated_config, monkeypatch):
        """Reset failure should return nonzero exit code."""
        from typer.testing import CliRunner
        from clawrium.cli.main import app
        from clawrium.core.reset import ResetTargets, ResetResult
        import json

        runner = CliRunner()

        # Create host
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        host = {
            "hostname": "192.168.1.100",
            "key_id": "192.168.1.100",
            "port": 22,
            "user": "xclm",
        }
        hosts_file.write_text(json.dumps([host]))

        # Create keypair
        key_dir = isolated_config / "keys" / "192.168.1.100"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "xclm_ed25519").write_text("fake-key")
        (key_dir / "xclm_ed25519").chmod(0o600)

        # Mock enumerate and execute to fail
        mock_targets = ResetTargets(
            users=["test-user"],
            services=[],
            paths=[],
        )
        mock_result = ResetResult(
            success=False,
            removed={"users": 0, "services": 0, "paths": 0},
            errors=["Connection refused"],
        )
        monkeypatch.setattr(
            "clawrium.cli.host.enumerate_targets", lambda x: mock_targets
        )
        monkeypatch.setattr("clawrium.cli.host.execute_reset", lambda x, y: mock_result)

        result = runner.invoke(app, ["host", "reset", "192.168.1.100", "--yes"])

        assert result.exit_code == 1
        assert "failed" in result.output.lower()

    def test_reset_with_host_alias(self, isolated_config, monkeypatch):
        """Reset should work when using host alias."""
        from typer.testing import CliRunner
        from clawrium.cli.main import app
        from clawrium.core.reset import ResetTargets, ResetResult
        import json

        runner = CliRunner()

        # Create host with alias
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        host = {
            "hostname": "192.168.1.100",
            "alias": "myhost",
            "key_id": "192.168.1.100",
            "port": 22,
            "user": "xclm",
        }
        hosts_file.write_text(json.dumps([host]))

        # Create keypair
        key_dir = isolated_config / "keys" / "192.168.1.100"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "xclm_ed25519").write_text("fake-key")
        (key_dir / "xclm_ed25519").chmod(0o600)

        # Mock enumerate_targets and execute_reset
        mock_targets = ResetTargets(users=["test"], services=[], paths=[])
        mock_result = ResetResult(
            success=True,
            removed={"users": 1, "services": 0, "paths": 0},
            errors=[],
        )
        monkeypatch.setattr(
            "clawrium.cli.host.enumerate_targets", lambda x: mock_targets
        )
        monkeypatch.setattr("clawrium.cli.host.execute_reset", lambda x, y: mock_result)

        # Use alias to reset
        result = runner.invoke(app, ["host", "reset", "myhost", "--yes"])

        assert result.exit_code == 0

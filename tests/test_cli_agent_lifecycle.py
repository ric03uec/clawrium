"""Integration tests for clm agent lifecycle commands."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from clawrium.cli.main import app

runner = CliRunner()


def create_host_with_ready_claw(
    config_dir: Path,
    hostname: str = "192.168.1.100",
    alias: str = "work",
    claw_type: str = "openclaw",
) -> None:
    """Create a test host with a ready claw."""
    hosts_file = config_dir / "hosts.json"
    config_dir.mkdir(parents=True, exist_ok=True)

    hosts_data = [
        {
            "hostname": hostname,
            "key_id": alias,
            "port": 22,
            "agent_name": "xclm",
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
                "added_at": "2026-04-07T00:00:00Z",
                "last_seen": "2026-04-07T00:00:00Z",
                "tags": [],
            },
            "agents": {
                "assistant": {
                    "type": claw_type,
                    "version": "2026.4.2",
                    "status": "installed",
                    "onboarding": {
                        "state": "ready",
                        "started_at": "2026-04-07T00:00:00Z",
                        "stages": {
                            "providers": {"status": "complete"},
                            "identity": {"status": "complete"},
                            "channels": {"status": "complete"},
                            "validate": {"status": "complete"},
                        },
                    },
                }
            },
        }
    ]

    hosts_file.write_text(json.dumps(hosts_data, indent=2))


class TestAgentStart:
    """Tests for clm agent start command."""

    def test_start_unknown_host_fails(self, isolated_config: Path):
        """Start with unknown agent fails."""
        result = runner.invoke(app, ["agent", "start", "unknown-agent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_start_invalid_claw_name_fails(self, isolated_config: Path):
        """Start with unknown agent name fails."""
        create_host_with_ready_claw(isolated_config)
        result = runner.invoke(app, ["agent", "start", "invalid"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_start_claw_not_installed_fails(self, isolated_config: Path):
        """Start when claw not installed fails."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "work",
                "key_id": "work",
                "agents": {},
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        result = runner.invoke(app, ["agent", "start", "assistant"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_start_incomplete_onboarding_blocked(self, isolated_config: Path):
        """Start with incomplete onboarding is blocked."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "work",
                "key_id": "work",
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "onboarding": {"state": "pending"},
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        result = runner.invoke(app, ["agent", "start", "assistant"])
        assert result.exit_code == 1
        assert "Cannot start" in result.output
        assert "onboarding not started" in result.output

    def test_start_ready_claw_succeeds(self, isolated_config: Path, tmp_path: Path):
        """Start with ready claw succeeds."""
        create_host_with_ready_claw(isolated_config)

        key_path = tmp_path / "work_key"
        key_path.write_text("private key")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.keys.get_host_private_key", return_value=key_path):
            with patch(
                "clawrium.core.lifecycle.ansible_runner.run", return_value=mock_runner
            ):
                with patch(
                    "clawrium.core.lifecycle.get_config_dir",
                    return_value=isolated_config,
                ):
                    result = runner.invoke(app, ["agent", "start", "assistant"])

        assert result.exit_code == 0
        assert "Starting agent" in result.output
        assert "started successfully" in result.output

    def test_start_with_force_bypasses_onboarding(
        self, isolated_config: Path, tmp_path: Path
    ):
        """Start with --force bypasses onboarding check."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "work",
                "key_id": "work",
                "agent_name": "xclm",
                "port": 22,
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "onboarding": {"state": "pending"},
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        key_path = tmp_path / "work_key"
        key_path.write_text("private key")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.config.get_config_dir", return_value=isolated_config):
            with patch(
                "clawrium.core.hosts.get_config_dir", return_value=isolated_config
            ):
                with patch(
                    "clawrium.core.keys.get_host_private_key", return_value=key_path
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=isolated_config,
                        ):
                            result = runner.invoke(
                                app, ["agent", "start", "assistant", "--force"]
                            )

        assert result.exit_code == 0
        assert "Warning" in result.output or "Starting agent" in result.output


class TestAgentStop:
    """Tests for clm agent stop command."""

    def test_stop_unknown_host_fails(self, isolated_config: Path):
        """Stop with unknown agent fails."""
        result = runner.invoke(app, ["agent", "stop", "unknown-agent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_stop_claw_not_installed_fails(self, isolated_config: Path):
        """Stop when claw not installed fails."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "work",
                "key_id": "work",
                "agents": {},
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        result = runner.invoke(app, ["agent", "stop", "assistant"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_stop_installed_claw_succeeds(self, isolated_config: Path, tmp_path: Path):
        """Stop with installed claw succeeds."""
        create_host_with_ready_claw(isolated_config)

        key_path = tmp_path / "work_key"
        key_path.write_text("private key")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.keys.get_host_private_key", return_value=key_path):
            with patch(
                "clawrium.core.lifecycle.ansible_runner.run", return_value=mock_runner
            ):
                with patch(
                    "clawrium.core.lifecycle.get_config_dir",
                    return_value=isolated_config,
                ):
                    result = runner.invoke(app, ["agent", "stop", "assistant"])

        assert result.exit_code == 0
        assert "Stopping agent" in result.output
        assert "stopped successfully" in result.output


class TestAgentRestart:
    """Tests for clm agent restart command."""

    def test_restart_unknown_host_fails(self, isolated_config: Path):
        """Restart with unknown agent fails."""
        result = runner.invoke(app, ["agent", "restart", "unknown-agent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_restart_installed_claw_succeeds(
        self, isolated_config: Path, tmp_path: Path
    ):
        """Restart with installed claw succeeds."""
        create_host_with_ready_claw(isolated_config)

        key_path = tmp_path / "work_key"
        key_path.write_text("private key")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.keys.get_host_private_key", return_value=key_path):
            with patch(
                "clawrium.core.lifecycle.ansible_runner.run", return_value=mock_runner
            ):
                with patch(
                    "clawrium.core.lifecycle.get_config_dir",
                    return_value=isolated_config,
                ):
                    result = runner.invoke(app, ["agent", "restart", "assistant"])

        assert result.exit_code == 0
        assert "Restarting agent" in result.output
        assert "restarted successfully" in result.output


class TestAgentSync:
    """Tests for clm agent sync command."""

    def test_sync_unknown_agent_fails(self, isolated_config: Path):
        """Sync with unknown agent fails."""
        result = runner.invoke(app, ["agent", "sync", "unknown-agent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_sync_agent_not_installed_fails(self, isolated_config: Path):
        """Sync when agent not installed fails."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "work",
                "key_id": "work",
                "agents": {},
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        result = runner.invoke(app, ["agent", "sync", "assistant"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_sync_agent_onboarding_incomplete_fails(self, isolated_config: Path):
        """Sync when agent onboarding is incomplete fails."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "work",
                "key_id": "work",
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "onboarding": {"state": "pending"},
                        "config": {
                            "gateway": {"port": 40000},
                            "provider": {
                                "name": "test",
                                "type": "ollama",
                                "endpoint": "http://localhost:11434",
                                "default_model": "llama3",
                            },
                        },
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        result = runner.invoke(app, ["agent", "sync", "assistant"])
        assert result.exit_code == 1
        assert "onboarding not started" in result.output

    def test_sync_agent_no_config_fails(self, isolated_config: Path):
        """Sync when agent has no config fails."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "work",
                "key_id": "work",
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "onboarding": {"state": "ready"},
                        # No config
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        result = runner.invoke(app, ["agent", "sync", "assistant"])
        assert result.exit_code == 1
        assert "No configuration found" in result.output

    def test_sync_installed_agent_succeeds(
        self, isolated_config: Path, tmp_path: Path
    ):
        """Sync with installed and configured agent succeeds."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "config": {
                            "gateway": {"port": 40000},
                            "provider": {
                                "name": "test",
                                "type": "ollama",
                                "endpoint": "http://localhost:11434",
                                "default_model": "llama3",
                            },
                        },
                        "onboarding": {"state": "ready"},
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        # Issue #437 / ATX W9: sync no longer calls restart_agent, so the
        # dead restart_agent mock is removed and the success string drops
        # the misleading "agent restarted" suffix.
        with patch(
            "clawrium.core.lifecycle.configure_agent",
            return_value=(True, None),
        ):
            result = runner.invoke(app, ["agent", "sync", "assistant"])

        assert result.exit_code == 0
        assert "Syncing agent" in result.output
        assert "Configuration synced" in result.output
        assert "agent restarted" not in result.output

    def test_sync_configure_failure(self, isolated_config: Path, tmp_path: Path):
        """Sync fails when configure step fails."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "onboarding": {"state": "ready"},
                        "config": {
                            "gateway": {"port": 40000},
                            "provider": {
                                "name": "test",
                                "type": "ollama",
                                "endpoint": "http://localhost:11434",
                                "default_model": "llama3",
                            },
                        },
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        with patch(
            "clawrium.core.lifecycle.configure_agent",
            return_value=(False, "Config error"),
        ):
            result = runner.invoke(app, ["agent", "sync", "assistant"])

        assert result.exit_code == 1
        assert "Failed to sync" in result.output
        assert "Configure failed" in result.output

    def test_sync_configure_failure_after_always_repair(
        self, isolated_config: Path, tmp_path: Path
    ):
        """Issue #437: sync no longer calls restart; failure paths now
        come from configure (which performs the always-pair step)."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "onboarding": {"state": "ready"},
                        "config": {
                            "gateway": {"port": 40000},
                            "provider": {
                                "name": "test",
                                "type": "ollama",
                                "endpoint": "http://localhost:11434",
                                "default_model": "llama3",
                            },
                        },
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        with patch(
            "clawrium.core.lifecycle.configure_agent",
            return_value=(False, "Configure error"),
        ):
            result = runner.invoke(app, ["agent", "sync", "assistant"])

        assert result.exit_code == 1
        assert "Failed to sync" in result.output
        assert "Configure failed" in result.output

    def test_sync_with_workspace_flag_skips_restart(
        self, isolated_config: Path, tmp_path: Path
    ):
        """Sync with --workspace flag skips restart and shows correct message."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "config": {
                            "gateway": {"port": 40000},
                            "provider": {
                                "name": "test",
                                "type": "ollama",
                                "endpoint": "http://localhost:11434",
                                "default_model": "llama3",
                            },
                        },
                        "onboarding": {"state": "ready"},
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        with patch(
            "clawrium.core.lifecycle.configure_agent",
            return_value=(True, None),
        ) as mock_configure:
            with patch(
                "clawrium.core.lifecycle.restart_agent",
            ) as mock_restart:
                result = runner.invoke(
                    app, ["agent", "sync", "assistant", "--workspace"]
                )

        assert result.exit_code == 0
        # Issue #437: sync always reports "Configuration synced" now; the
        # --workspace flag is preserved on the CLI surface but the
        # output is the same since sync no longer orchestrates a restart.
        assert "Configuration synced" in result.output
        mock_configure.assert_called_once()
        mock_restart.assert_not_called()

    def test_sync_does_not_call_restart_agent(
        self, isolated_config: Path, tmp_path: Path
    ):
        """Issue #437: `clm agent sync` no longer orchestrates a
        separate restart. configure handles re-pair + handler-driven
        restart in one shot."""
        hosts_file = isolated_config / "hosts.json"
        isolated_config.mkdir(parents=True, exist_ok=True)

        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "agents": {
                    "assistant": {
                        "type": "openclaw",
                        "config": {
                            "gateway": {"port": 40000},
                            "provider": {
                                "name": "test",
                                "type": "ollama",
                                "endpoint": "http://localhost:11434",
                                "default_model": "llama3",
                            },
                        },
                        "onboarding": {"state": "ready"},
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        with patch(
            "clawrium.core.lifecycle.configure_agent",
            return_value=(True, None),
        ) as mock_configure:
            with patch(
                "clawrium.core.lifecycle.restart_agent"
            ) as mock_restart:
                result = runner.invoke(app, ["agent", "sync", "assistant"])

        assert result.exit_code == 0
        mock_configure.assert_called_once()
        mock_restart.assert_not_called()

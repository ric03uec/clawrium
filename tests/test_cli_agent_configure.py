"""Tests for the clm agent configure command."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from clawrium.cli.main import app

runner = CliRunner()


def create_test_keypair(config_dir: Path, key_id: str) -> None:
    """Create a test keypair for a host."""
    key_dir = config_dir / "keys" / key_id
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "xclm_ed25519").write_text("test-private-key")
    (key_dir / "xclm_ed25519").chmod(0o600)
    (key_dir / "xclm_ed25519.pub").write_text("ssh-ed25519 AAAA... clawrium")


def create_host_with_claw(
    config_dir: Path,
    hostname: str = "192.168.1.100",
    alias: str = "work",
    key_id: str = "work",
    claw_type: str = "openclaw",
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
                        "state": "pending",
                        "started_at": "2026-04-06T00:00:00+00:00",
                        "stages": {
                            "providers": {
                                "status": "pending",
                                "completed_at": None,
                                "provider_id": None,
                            },
                            "identity": {"status": "pending", "completed_at": None},
                            "channels": {"status": "pending", "completed_at": None},
                            "validate": {"status": "pending", "completed_at": None},
                        },
                    },
                }
            },
        }
    ]

    hosts_file.write_text(json.dumps(hosts_data, indent=2))


def create_provider(
    config_dir: Path, name: str = "test-openai", ptype: str = "openai"
) -> None:
    """Create a test provider configuration."""
    providers_file = config_dir / "providers.json"
    config_dir.mkdir(parents=True, exist_ok=True)

    if providers_file.exists():
        providers = json.loads(providers_file.read_text())
    else:
        providers = []

    providers.append(
        {
            "name": name,
            "type": ptype,
            "default_model": "gpt-4",
            "created_at": "2026-04-06T00:00:00Z",
            "updated_at": "2026-04-06T00:00:00Z",
        }
    )

    providers_file.write_text(json.dumps(providers, indent=2))

    secrets_dir = config_dir / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    secret_file = secrets_dir / f"provider_{name}.enc"
    secret_file.write_text("encrypted-test-key")


class TestAgentConfigureParse:
    """Tests for claw name parsing."""

    def test_invalid_name_no_dash(self, isolated_config: Path):
        """Rejects names without dash separator."""
        result = runner.invoke(app, ["agent", "configure", "invalidname"])

        assert result.exit_code == 1
        assert "invalid claw name format" in result.output.lower()

    def test_invalid_name_empty_parts(self, isolated_config: Path):
        """Rejects names with empty parts."""
        result = runner.invoke(app, ["agent", "configure", "-work"])

        assert result.exit_code != 0

    def test_invalid_name_trailing_dash(self, isolated_config: Path):
        """Rejects names with trailing dash."""
        result = runner.invoke(app, ["agent", "configure", "opc-"])

        assert result.exit_code == 1


class TestAgentConfigureHostNotFound:
    """Tests for host not found errors."""

    def test_host_not_found(self, isolated_config: Path):
        """Shows error when host doesn't exist."""
        result = runner.invoke(app, ["agent", "configure", "opc-nonexistent"])

        assert result.exit_code == 1
        assert "host" in result.output.lower() and "not found" in result.output.lower()


class TestAgentConfigureClawNotInstalled:
    """Tests for claw not installed errors."""

    def test_claw_not_installed(self, isolated_config: Path):
        """Shows error when claw not installed on host."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, claw_type="zeroclaw")

        result = runner.invoke(app, ["agent", "configure", "openclaw-work"])

        assert result.exit_code == 1
        assert "not installed" in result.output.lower()


class TestAgentConfigureSingleStage:
    """Tests for --stage single stage mode."""

    def test_invalid_stage_name(self, isolated_config: Path):
        """Rejects invalid stage names."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        create_provider(isolated_config)

        result = runner.invoke(
            app,
            ["agent", "configure", "openclaw-work", "--stage", "invalid_stage"],
            env=os.environ,
        )

        assert result.exit_code == 1
        assert "invalid stage" in result.output.lower()

    def test_providers_stage_success(self, isolated_config: Path):
        """Runs providers stage successfully."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        create_provider(isolated_config)

        with patch("clawrium.cli.agent._run_providers_stage") as mock_run:
            mock_run.return_value = True

            result = runner.invoke(
                app,
                [
                    "agent",
                    "configure",
                    "openclaw-work",
                    "--stage",
                    "providers",
                    "--yes",
                ],
                env=os.environ,
            )

            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_identity_stage_success(self, isolated_config: Path):
        """Runs identity stage successfully."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        with patch("clawrium.cli.agent._run_identity_stage") as mock_run:
            mock_run.return_value = True

            result = runner.invoke(
                app,
                ["agent", "configure", "openclaw-work", "--stage", "identity", "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_channels_stage_success(self, isolated_config: Path):
        """Runs channels stage successfully."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        with patch("clawrium.cli.agent._run_channels_stage") as mock_run:
            mock_run.return_value = True

            result = runner.invoke(
                app,
                ["agent", "configure", "openclaw-work", "--stage", "channels", "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_validate_stage_success(self, isolated_config: Path):
        """Runs validate stage successfully."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        with patch("clawrium.cli.agent._run_validate_stage") as mock_run:
            mock_run.return_value = True

            result = runner.invoke(
                app,
                ["agent", "configure", "openclaw-work", "--stage", "validate", "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            mock_run.assert_called_once()


class TestAgentConfigureFullWizard:
    """Tests for full wizard mode."""

    def test_already_configured(self, isolated_config: Path):
        """Shows message when onboarding already complete."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = json.loads(hosts_file.read_text())
        hosts_data[0]["claws"]["openclaw"]["onboarding"]["state"] = "ready"
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        result = runner.invoke(
            app,
            ["agent", "configure", "openclaw-work"],
            env=os.environ,
        )

        assert result.exit_code == 0
        assert "already complete" in result.output.lower()


class TestAgentConfigureYes:
    """Tests for --yes flag."""

    def test_yes_uses_defaults(self, isolated_config: Path):
        """--yes flag skips prompts and uses defaults."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        create_provider(isolated_config)

        with (
            patch("clawrium.cli.agent._run_providers_stage") as mock_providers,
            patch("clawrium.cli.agent._run_identity_stage") as mock_identity,
            patch("clawrium.cli.agent._run_channels_stage") as mock_channels,
            patch("clawrium.cli.agent._run_validate_stage") as mock_validate,
        ):
            mock_providers.return_value = True
            mock_identity.return_value = True
            mock_channels.return_value = True
            mock_validate.return_value = True

            result = runner.invoke(
                app,
                ["agent", "configure", "openclaw-work", "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            mock_providers.assert_called_once()
            mock_identity.assert_called_once()
            mock_channels.assert_called_once()
            mock_validate.assert_called_once()

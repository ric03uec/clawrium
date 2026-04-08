"""Tests for the clm agent configure command."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
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

        assert result.exit_code != 0

    def test_invalid_characters_in_claw_type(self, isolated_config: Path):
        """Rejects claw type with path traversal."""
        result = runner.invoke(app, ["agent", "configure", "../etc-work"])

        assert result.exit_code == 1
        assert "invalid claw type" in result.output.lower()

    def test_invalid_characters_in_host_alias(self, isolated_config: Path):
        """Rejects host alias with invalid characters."""
        result = runner.invoke(app, ["agent", "configure", "opc-../etc"])

        assert result.exit_code == 1
        assert "invalid host alias" in result.output.lower()


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

    @pytest.mark.parametrize(
        "stage_name", ["providers", "identity", "channels", "validate"]
    )
    def test_single_stage_success(self, isolated_config: Path, stage_name: str):
        """Runs each stage successfully."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        if stage_name == "providers":
            create_provider(isolated_config)

        with patch(f"clawrium.cli.agent._run_{stage_name}_stage") as mock_run:
            mock_run.return_value = True

            result = runner.invoke(
                app,
                ["agent", "configure", "openclaw-work", "--stage", stage_name, "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            mock_run.assert_called_once_with("work", "openclaw", True)

    def test_single_stage_failure(self, isolated_config: Path):
        """Stage failure exits with code 1."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        create_provider(isolated_config)

        with patch("clawrium.cli.agent._run_providers_stage") as mock_run:
            mock_run.return_value = False

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

            assert result.exit_code == 1
            assert "failed" in result.output.lower()


class TestAgentConfigureFullWizard:
    """Tests for full wizard mode."""

    def test_already_configured(self, isolated_config: Path):
        """Shows message when onboarding already complete."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, onboarding_state="ready")
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

    def test_wizard_resumes_from_mid_state(self, isolated_config: Path):
        """Wizard resumes from identity state, skipping providers."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, onboarding_state="identity")

        with (
            patch("clawrium.cli.agent._run_providers_stage") as mock_providers,
            patch("clawrium.cli.agent._run_identity_stage") as mock_identity,
            patch("clawrium.cli.agent._run_channels_stage") as mock_channels,
            patch("clawrium.cli.agent._run_validate_stage") as mock_validate,
        ):
            mock_identity.return_value = True
            mock_channels.return_value = True
            mock_validate.return_value = True

            result = runner.invoke(
                app,
                ["agent", "configure", "openclaw-work", "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            mock_providers.assert_not_called()
            mock_identity.assert_called_once()
            mock_channels.assert_called_once()
            mock_validate.assert_called_once()

    def test_wizard_stage_failure(self, isolated_config: Path):
        """Wizard stops on stage failure."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        create_provider(isolated_config)

        with (
            patch("clawrium.cli.agent._run_providers_stage") as mock_providers,
            patch("clawrium.cli.agent._run_identity_stage") as mock_identity,
        ):
            mock_providers.return_value = True
            mock_identity.return_value = False

            result = runner.invoke(
                app,
                ["agent", "configure", "openclaw-work", "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 1
            assert "failed" in result.output.lower()


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


class TestRunProvidersStage:
    """Direct tests for _run_providers_stage."""

    def test_no_providers_configured(self, isolated_config: Path):
        """Returns False when no providers available."""
        from clawrium.cli.agent import _run_providers_stage

        with patch("clawrium.core.providers.load_providers", return_value=[]):
            result = _run_providers_stage("work", "openclaw", True)

        assert result is False

    def test_providers_file_corrupted(self, isolated_config: Path):
        """Returns False when providers file is corrupted."""
        from clawrium.cli.agent import _run_providers_stage
        from clawrium.core.providers import ProvidersFileCorruptedError

        with patch(
            "clawrium.core.providers.load_providers",
            side_effect=ProvidersFileCorruptedError("corrupted"),
        ):
            result = _run_providers_stage("work", "openclaw", True)

        assert result is False

    def test_complete_stage_failure(self, isolated_config: Path):
        """Returns False when complete_stage fails."""
        from clawrium.cli.agent import _run_providers_stage

        with (
            patch("clawrium.core.providers.load_providers") as mock_load,
            patch("clawrium.core.providers.get_provider_api_key", return_value="key"),
            patch(
                "clawrium.cli.agent.complete_stage", side_effect=Exception("disk full")
            ),
            patch("clawrium.cli.agent.typer.prompt", return_value=1),
        ):
            mock_load.return_value = [
                {"name": "test", "type": "openai", "default_model": "gpt-4"}
            ]
            result = _run_providers_stage("work", "openclaw", True)

        assert result is False


class TestRunIdentityStage:
    """Direct tests for _run_identity_stage."""

    def test_personality_too_long(self, isolated_config: Path):
        """Returns False when personality exceeds limit."""
        from clawrium.cli.agent import _run_identity_stage

        long_personality = "x" * 2001
        with patch("clawrium.cli.agent.typer.prompt", return_value=long_personality):
            result = _run_identity_stage("work", "openclaw", False)

        assert result is False

    def test_complete_stage_failure(self, isolated_config: Path):
        """Returns False when complete_stage fails."""
        from clawrium.cli.agent import _run_identity_stage

        with patch(
            "clawrium.cli.agent.complete_stage", side_effect=Exception("failed")
        ):
            result = _run_identity_stage("work", "openclaw", True)

        assert result is False

    def test_creates_soul_md_file(self, isolated_config: Path):
        """Creates SOUL.md in config directory."""
        from clawrium.cli.agent import _run_identity_stage

        with patch("clawrium.cli.agent.complete_stage"):
            result = _run_identity_stage("work", "openclaw", True)

        assert result is True
        soul_path = isolated_config / "claws" / "openclaw" / "SOUL.md"
        assert soul_path.exists()


class TestRunChannelsStage:
    """Direct tests for _run_channels_stage."""

    def test_invalid_selection(self, isolated_config: Path):
        """Returns False on invalid channel selection."""
        from clawrium.cli.agent import _run_channels_stage

        with patch("clawrium.cli.agent.typer.prompt", return_value=99):
            result = _run_channels_stage("work", "openclaw", False)

        assert result is False

    def test_complete_stage_failure(self, isolated_config: Path):
        """Returns False when complete_stage fails."""
        from clawrium.cli.agent import _run_channels_stage

        with patch(
            "clawrium.cli.agent.complete_stage", side_effect=Exception("failed")
        ):
            result = _run_channels_stage("work", "openclaw", True)

        assert result is False


class TestRunValidateStage:
    """Direct tests for _run_validate_stage."""

    def test_complete_stage_failure(self, isolated_config: Path):
        """Returns False when complete_stage fails."""
        from clawrium.cli.agent import _run_validate_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, onboarding_state="validate")
        create_provider(isolated_config)

        hosts_file = isolated_config / "hosts.json"
        hosts_data = json.loads(hosts_file.read_text())
        hosts_data[0]["claws"]["openclaw"]["onboarding"]["stages"]["providers"][
            "provider_id"
        ] = "test-openai"
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        soul_dir = isolated_config / "claws" / "openclaw"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("Test personality")

        secrets_file = isolated_config / "secrets.json"
        secrets_file.write_text(
            json.dumps(
                {
                    "provider:test-openai": {
                        "API_KEY": {
                            "key": "API_KEY",
                            "value": "sk-test-key",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z",
                            "description": "",
                        }
                    }
                }
            )
        )

        with (
            patch(
                "clawrium.core.validation._make_request", return_value=(200, {}, None)
            ),
            patch("clawrium.cli.agent.complete_stage", side_effect=Exception("failed")),
        ):
            result = _run_validate_stage("work", "openclaw", True)

        assert result is False

    def test_soul_md_missing_fails(self, isolated_config: Path):
        """Returns False when SOUL.md is missing."""
        from clawrium.cli.agent import _run_validate_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, onboarding_state="validate")
        create_provider(isolated_config)

        hosts_file = isolated_config / "hosts.json"
        hosts_data = json.loads(hosts_file.read_text())
        hosts_data[0]["claws"]["openclaw"]["onboarding"]["stages"]["providers"][
            "provider_id"
        ] = "test-openai"
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        with patch("clawrium.cli.agent.complete_stage"):
            result = _run_validate_stage("work", "openclaw", True)

        assert result is False

    def test_validation_passes_with_all_checks(self, isolated_config: Path):
        """Returns True when all validation checks pass."""
        from clawrium.cli.agent import _run_validate_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, onboarding_state="validate")
        create_provider(isolated_config)

        hosts_file = isolated_config / "hosts.json"
        hosts_data = json.loads(hosts_file.read_text())
        hosts_data[0]["claws"]["openclaw"]["onboarding"]["stages"]["providers"][
            "provider_id"
        ] = "test-openai"
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        soul_dir = isolated_config / "claws" / "openclaw"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("Test personality")

        secrets_file = isolated_config / "secrets.json"
        secrets_file.write_text(
            json.dumps(
                {
                    "provider:test-openai": {
                        "API_KEY": {
                            "key": "API_KEY",
                            "value": "sk-test-key",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z",
                            "description": "",
                        }
                    }
                }
            )
        )

        with (
            patch(
                "clawrium.core.validation._make_request", return_value=(200, {}, None)
            ),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            result = _run_validate_stage("work", "openclaw", True)

        assert result is True

    def test_provider_not_configured_fails(self, isolated_config: Path):
        """Returns False when provider is not configured."""
        from clawrium.cli.agent import _run_validate_stage

        create_test_keypair(isolated_config, "work")
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "alias": "work",
                "claws": {
                    "openclaw": {
                        "version": "0.1.0",
                        "status": "installed",
                        "onboarding": {
                            "state": "validate",
                            "stages": {
                                "providers": {"status": "pending", "provider_id": None},
                                "identity": {"status": "complete"},
                                "channels": {"status": "complete"},
                                "validate": {"status": "pending"},
                            },
                        },
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data))

        soul_dir = isolated_config / "claws" / "openclaw"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("Test personality")

        with patch("clawrium.cli.agent.complete_stage"):
            result = _run_validate_stage("work", "openclaw", True)

        assert result is False


class TestHostsFileCorruptedError:
    """Tests for HostsFileCorruptedError handling."""

    def test_get_host_corrupted(self, isolated_config: Path):
        """Handles HostsFileCorruptedError from get_host."""
        from clawrium.core.hosts import HostsFileCorruptedError

        create_test_keypair(isolated_config, "work")

        with patch(
            "clawrium.cli.agent.get_host",
            side_effect=HostsFileCorruptedError("corrupted"),
        ):
            result = runner.invoke(app, ["agent", "configure", "opc-work"])

        assert result.exit_code == 1
        assert "corrupted" in result.output.lower()


class TestRichMarkupInjection:
    """Tests for rich markup injection prevention."""

    def test_claw_name_escaped_in_errors(self, isolated_config: Path):
        """Claw name is escaped in error messages."""
        result = runner.invoke(app, ["agent", "configure", "[bold]evil[/bold]-work"])

        assert result.exit_code == 1
        assert "[bold]" not in result.output or "invalid" in result.output.lower()


class TestCanSkipStage:
    """Tests for can_skip_stage path."""

    def test_can_skip_stage_called(self, isolated_config: Path):
        """can_skip_stage is checked during wizard."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        create_provider(isolated_config)

        with (
            patch("clawrium.cli.agent.can_skip_stage") as mock_skip,
            patch("clawrium.cli.agent._run_providers_stage", return_value=True),
            patch("clawrium.cli.agent._run_identity_stage", return_value=True),
            patch("clawrium.cli.agent._run_channels_stage", return_value=True),
            patch("clawrium.cli.agent._run_validate_stage", return_value=True),
        ):
            mock_skip.return_value = False

            result = runner.invoke(
                app,
                ["agent", "configure", "openclaw-work", "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            assert mock_skip.called

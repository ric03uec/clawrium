"""Tests for the clm agent configure command."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from clawrium.cli.main import app
from clawrium.core.validation import ValidationResult

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
    config: dict | None = None,
) -> None:
    """Create a test host with a claw installed."""
    hosts_file = config_dir / "hosts.json"
    config_dir.mkdir(parents=True, exist_ok=True)

    agent_data = {
        "version": "0.1.0",
        "status": "installed",
        "name": "assistant",
        "agent_name": "assistant",
        "onboarding": {
            "state": onboarding_state,
            "started_at": "2026-04-06T00:00:00+00:00",
            "stages": {
                "providers": {
                    "status": "complete"
                    if onboarding_state in ["identity", "channels", "validate", "ready"]
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
                    "status": "complete" if onboarding_state == "ready" else "pending",
                    "completed_at": None,
                },
            },
        },
    }

    # Add config if provided
    if config:
        agent_data["config"] = config

    hosts_data = [
        {
            "hostname": hostname,
            "key_id": key_id,
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
                "added_at": "2026-04-06T00:00:00Z",
                "last_seen": "2026-04-06T00:00:00Z",
                "tags": [],
            },
            "agents": {
                claw_type: agent_data,
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
    """Tests for agent name validation and lookup."""

    def test_invalid_name_no_dash(self, isolated_config: Path):
        """Unknown names are rejected."""
        result = runner.invoke(app, ["agent", "configure", "invalidname"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_invalid_name_empty_parts(self, isolated_config: Path):
        """Rejects names with empty parts."""
        result = runner.invoke(app, ["agent", "configure", "-work"])

        assert result.exit_code != 0

    def test_invalid_name_trailing_dash(self, isolated_config: Path):
        """Rejects names with trailing dash."""
        result = runner.invoke(app, ["agent", "configure", "opc-"])

        assert result.exit_code != 0

    def test_invalid_characters_in_claw_type(self, isolated_config: Path):
        """Rejects invalid characters in agent name."""
        result = runner.invoke(app, ["agent", "configure", "../etc-work"])

        assert result.exit_code == 1
        assert "invalid agent name" in result.output.lower()

    def test_invalid_characters_in_host_alias(self, isolated_config: Path):
        """Rejects invalid characters in agent name."""
        result = runner.invoke(app, ["agent", "configure", "opc-../etc"])

        assert result.exit_code == 1
        assert "invalid agent name" in result.output.lower()


class TestAgentConfigureHostNotFound:
    """Tests for missing agent errors."""

    def test_host_not_found(self, isolated_config: Path):
        """Shows error when agent instance doesn't exist."""
        result = runner.invoke(app, ["agent", "configure", "opc-nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestAgentConfigureClawNotInstalled:
    """Tests for missing agent errors."""

    def test_claw_not_installed(self, isolated_config: Path):
        """Shows error when named agent is not found."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, claw_type="zeroclaw")

        result = runner.invoke(app, ["agent", "configure", "openclaw-work"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestAgentConfigureSingleStage:
    """Tests for --stage single stage mode."""

    def test_invalid_stage_name(self, isolated_config: Path):
        """Rejects invalid stage names."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)
        create_provider(isolated_config)

        result = runner.invoke(
            app,
            ["agent", "configure", "assistant", "--stage", "invalid_stage"],
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
                ["agent", "configure", "assistant", "--stage", stage_name, "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            # Identity stage has extra identity_files parameter (None when not provided)
            if stage_name == "identity":
                mock_run.assert_called_once_with(
                    "192.168.1.100", "openclaw", True, "assistant", None
                )
            elif stage_name == "validate":
                mock_run.assert_called_once_with(
                    "192.168.1.100", "openclaw", True, "assistant", False
                )
            else:
                mock_run.assert_called_once_with(
                    "192.168.1.100", "openclaw", True, "assistant"
                )

    def test_skip_health_rejected_for_non_validate_single_stage(
        self, isolated_config: Path
    ):
        """Rejects --skip-health with non-validate single stage."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        result = runner.invoke(
            app,
            [
                "agent",
                "configure",
                "assistant",
                "--stage",
                "providers",
                "--skip-health",
            ],
            env=os.environ,
        )

        assert result.exit_code == 1
        assert "skip-health" in result.output.lower()

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
                    "assistant",
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
        hosts_data[0]["agents"]["openclaw"]["onboarding"]["state"] = "ready"
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        result = runner.invoke(
            app,
            ["agent", "configure", "assistant"],
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
                ["agent", "configure", "assistant", "--yes"],
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
                ["agent", "configure", "assistant", "--yes"],
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
                ["agent", "configure", "assistant", "--yes"],
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
        """Creates SOUL.md in agent-specific identity directory and syncs to remote."""
        from clawrium.cli.agent import _run_identity_stage
        from unittest.mock import MagicMock

        mock_host = {
            "hostname": "192.168.1.100",
            "agents": {
                "openclaw": {
                    "type": "openclaw",
                    "config": {},
                    "onboarding": {"state": "identity"},
                }
            },
        }

        mock_configure = MagicMock(return_value=(True, None))

        with patch("clawrium.cli.agent.complete_stage"):
            with patch("clawrium.cli.agent.get_host", return_value=mock_host):
                with patch("clawrium.core.lifecycle.configure_agent", mock_configure):
                    result = _run_identity_stage("work", "openclaw", True)

        assert result is True
        # New path: agents/<type>/<agent-name>/identity/SOUL.md
        soul_path = (
            isolated_config
            / "agents"
            / "openclaw"
            / "openclaw"
            / "identity"
            / "SOUL.md"
        )
        assert soul_path.exists()

        # Verify configure_agent was called with identity_files in extra_vars
        mock_configure.assert_called_once()
        call_kwargs = mock_configure.call_args.kwargs
        assert "extra_vars" in call_kwargs
        assert "identity_files" in call_kwargs["extra_vars"]
        assert call_kwargs["extra_vars"]["identity_files"]["sync_workspace"] is True
        assert "soul_path" in call_kwargs["extra_vars"]["identity_files"]


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

    def test_channel_list_shows_cli_discord_and_slack(self, isolated_config: Path):
        """Verify cli, discord, and slack are shown as options."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        result = runner.invoke(
            app,
            ["agent", "configure", "assistant", "--stage", "channels"],
            input="1\n",
            env=os.environ,
        )

        assert "cli" in result.output.lower()
        assert "discord" in result.output.lower()
        assert "slack" in result.output.lower()
        # These channels should NOT be shown
        assert "web" not in result.output.lower()
        assert "whatsapp" not in result.output.lower()


class TestRunChannelsStageDiscord:
    """Tests for Discord channel configuration."""

    def test_discord_channel_prompts_for_credentials(self, isolated_config: Path):
        """Verify prompts appear when selecting discord."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        # Provider config is required for channel sync
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        # Test that discord selection triggers credential prompts
        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.core.secrets.set_instance_secret"),
            patch("clawrium.cli.agent._sync_channel_config"),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            # Bot token must be 50-100 chars with valid format
            valid_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw"
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "123456789012345678",  # Guild ID
                "987654321098765432",  # Channel ID
                "740723459344302120",  # User ID
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is True
        assert mock_p.call_count == 5

    def test_discord_bot_token_stored_as_secret(self, isolated_config: Path):
        """Verify bot token is stored as secret."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        # Provider config is required for channel sync
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        stored_secrets = []

        def capture_secret(instance_key, key, value, description):
            stored_secrets.append(
                {
                    "instance_key": instance_key,
                    "key": key,
                    "value": value,
                    "description": description,
                }
            )

        # Bot token must be 50-100 chars with valid format
        valid_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw"

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch(
                "clawrium.core.secrets.set_instance_secret", side_effect=capture_secret
            ),
            patch("clawrium.cli.agent._sync_channel_config"),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "123456789012345678",  # Guild ID
                "987654321098765432",  # Channel ID
                "740723459344302120",  # User ID
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is True
        assert len(stored_secrets) == 1
        assert stored_secrets[0]["key"] == "DISCORD_BOT_TOKEN"
        assert stored_secrets[0]["value"] == valid_token
        assert "discord" in stored_secrets[0]["description"].lower()

    def test_discord_guild_id_validation(self, isolated_config: Path):
        """Verify format validation for guild ID (17-19 digits)."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        # Bot token must be 50-100 chars with valid format
        valid_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw"

        # Test invalid guild ID (too short)
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "1234",  # Invalid guild ID - too short
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

        # Test invalid guild ID (contains letters)
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "12345678901234567a",  # Invalid - contains letter
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

    def test_discord_channel_id_validation(self, isolated_config: Path):
        """Verify format validation for channel ID (17-19 digits)."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        # Bot token must be 50-100 chars with valid format
        valid_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw"

        # Test invalid channel ID (too short)
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "123456789012345678",  # Valid guild ID
                "1234",  # Invalid channel ID - too short
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

    def test_discord_config_synced_to_agent(self, isolated_config: Path):
        """Verify config sync is called with correct data."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        # Provider config is required for channel sync
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        synced_configs = []

        def capture_sync(host, claw_type, channels_config, installed_name):
            synced_configs.append(
                {
                    "host": host,
                    "claw_type": claw_type,
                    "channels_config": channels_config,
                    "installed_name": installed_name,
                }
            )

        # Bot token must be 50-100 chars with valid format
        valid_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw"

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.core.secrets.set_instance_secret"),
            patch("clawrium.cli.agent._sync_channel_config", side_effect=capture_sync),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "123456789012345678",  # Guild ID
                "987654321098765432",  # Channel ID
                "740723459344302120",  # User ID
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is True
        assert len(synced_configs) == 1
        config = synced_configs[0]["channels_config"]
        assert "discord" in config
        assert config["discord"]["enabled"] is True
        assert config["discord"]["token"]["source"] == "env"
        assert config["discord"]["token"]["id"] == "DISCORD_BOT_TOKEN"
        assert config["discord"]["allowFrom"] == ["740723459344302120"]
        assert config["discord"]["groupPolicy"] == "allowlist"
        assert "123456789012345678" in config["discord"]["guilds"]
        assert config["discord"]["guilds"]["123456789012345678"]["users"] == [
            "740723459344302120"
        ]
        assert (
            "987654321098765432"
            in config["discord"]["guilds"]["123456789012345678"]["channels"]
        )
        assert (
            config["discord"]["guilds"]["123456789012345678"]["channels"][
                "987654321098765432"
            ]["allow"]
            is True
        )

    def test_discord_sync_failure_returns_false(self, isolated_config: Path):
        """Returns False when channel config sync fails."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        # Bot token must be 50-100 chars with valid format
        valid_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw"

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch(
                "clawrium.cli.agent._sync_channel_config",
                side_effect=Exception("SSH connection failed"),
            ),
        ):
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "123456789012345678",  # Guild ID
                "987654321098765432",  # Channel ID
                "740723459344302120",  # User ID
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

    def test_discord_user_id_validation(self, isolated_config: Path):
        """Verify format validation for user ID (17-19 digits)."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        # Bot token must be 50-100 chars with valid format
        valid_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw"

        # Test invalid user ID (too short - 16 digits)
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "123456789012345678",  # Valid guild ID
                "987654321098765432",  # Valid channel ID
                "1234567890123456",  # Invalid user ID - 16 digits
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

        # Test invalid user ID (too long - 20 digits)
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "123456789012345678",  # Valid guild ID
                "987654321098765432",  # Valid channel ID
                "12345678901234567890",  # Invalid user ID - 20 digits
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

        # Test invalid user ID (non-numeric)
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                valid_token,  # Bot token
                "123456789012345678",  # Valid guild ID
                "987654321098765432",  # Valid channel ID
                "notanumber",  # Invalid user ID - non-numeric
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

    def test_discord_bot_token_validation(self, isolated_config: Path):
        """Verify bot token format validation."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        # Test empty bot token
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                "",  # Empty bot token
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

        # Test bot token too short (less than 50 chars)
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                "short-token",  # Too short
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is False

    def test_sync_channel_config_calls_configure_agent(self, isolated_config: Path):
        """Verify _sync_channel_config calls configure_agent with correct data."""
        from clawrium.cli.agent import _sync_channel_config

        create_test_keypair(isolated_config, "work")
        # Create host with configured provider - agent stored under claw_type key
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        captured_calls = []

        def capture_configure(*args, **kwargs):
            captured_calls.append({"args": args, "kwargs": kwargs})
            return True, None

        with patch(
            "clawrium.core.lifecycle.configure_agent",
            side_effect=capture_configure,
        ):
            channels_config = {"discord": {"enabled": True}}
            # Use claw_type as agent lookup key (no installed_name) to match fixture structure
            _sync_channel_config("192.168.1.100", "openclaw", channels_config, None)

        assert len(captured_calls) == 1
        call = captured_calls[0]
        # Verify configure_agent was called with correct host and agent type
        assert call["args"][0] == "192.168.1.100"  # host
        assert call["args"][1] == "openclaw"  # claw_type
        # Verify channels config is in the config_data
        config_data = call["args"][2]
        assert "channels" in config_data
        assert config_data["channels"] == {"discord": {"enabled": True}}



class TestRunChannelsStageSlack:
    """Tests for Slack channel configuration (Socket Mode)."""

    VALID_BOT_TOKEN = "xoxb-123456789012-123456789012-AbCdEfGhIjKlMnOpQrStUvWx"
    VALID_APP_TOKEN = "xapp-1-A01BC2DEF-abcdef0123456789fedcba9876543210"

    def test_slack_channel_prompts_for_credentials(self, isolated_config: Path):
        """Verify prompts appear when selecting slack."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.core.secrets.set_instance_secret"),
            patch("clawrium.cli.agent._sync_channel_config"),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                3,  # Select slack
                self.VALID_BOT_TOKEN,
                self.VALID_APP_TOKEN,
                "U01ABC2DEF",  # User ID
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is True
        assert mock_p.call_count == 4

    def test_slack_bot_token_stored_as_secret(self, isolated_config: Path):
        """Verify bot token is stored as secret."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        stored_secrets = []

        def capture_secret(instance_key, key, value, description):
            stored_secrets.append({"key": key, "value": value, "description": description})

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.core.secrets.set_instance_secret", side_effect=capture_secret),
            patch("clawrium.cli.agent._sync_channel_config"),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                3,  # Select slack
                self.VALID_BOT_TOKEN,
                self.VALID_APP_TOKEN,
                "U01ABC2DEF",
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is True
        bot_secrets = [s for s in stored_secrets if s["key"] == "SLACK_BOT_TOKEN"]
        assert len(bot_secrets) == 1
        assert bot_secrets[0]["value"] == self.VALID_BOT_TOKEN

    def test_slack_app_token_stored_as_secret(self, isolated_config: Path):
        """Verify app token is stored as secret."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        stored_secrets = []

        def capture_secret(instance_key, key, value, description):
            stored_secrets.append({"key": key, "value": value, "description": description})

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.core.secrets.set_instance_secret", side_effect=capture_secret),
            patch("clawrium.cli.agent._sync_channel_config"),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                3,  # Select slack
                self.VALID_BOT_TOKEN,
                self.VALID_APP_TOKEN,
                "U01ABC2DEF",
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is True
        app_secrets = [s for s in stored_secrets if s["key"] == "SLACK_APP_TOKEN"]
        assert len(app_secrets) == 1
        assert app_secrets[0]["value"] == self.VALID_APP_TOKEN

    def test_slack_bot_token_validation(self, isolated_config: Path):
        """Verify bot token format validation."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        # Empty bot token
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [3, "", self.VALID_APP_TOKEN, "U01ABC2DEF"]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")
        assert result is False

        # Wrong prefix
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [3, "invalid-token", self.VALID_APP_TOKEN, "U01ABC2DEF"]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")
        assert result is False

    def test_slack_app_token_validation(self, isolated_config: Path):
        """Verify app token format validation (must start with xapp-)."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        # Empty app token
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [3, self.VALID_BOT_TOKEN, "", "U01ABC2DEF"]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")
        assert result is False

        # Wrong prefix
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [3, self.VALID_BOT_TOKEN, "invalid-token", "U01ABC2DEF"]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")
        assert result is False

    def test_slack_user_id_validation(self, isolated_config: Path):
        """Verify user ID format validation (starts with U, 8+ alphanumeric)."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        # Wrong prefix
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [3, self.VALID_BOT_TOKEN, self.VALID_APP_TOKEN, "V01ABC2DEF"]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")
        assert result is False

        # Too short
        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [3, self.VALID_BOT_TOKEN, self.VALID_APP_TOKEN, "U01"]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")
        assert result is False

    def test_slack_config_has_socket_mode(self, isolated_config: Path):
        """Verify config includes mode, groupPolicy, and dmPolicy."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        synced_configs = []

        def capture_sync(host, claw_type, channels_config, installed_name):
            synced_configs.append(channels_config)

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.core.secrets.set_instance_secret"),
            patch("clawrium.cli.agent._sync_channel_config", side_effect=capture_sync),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                3, self.VALID_BOT_TOKEN, self.VALID_APP_TOKEN, "U01ABC2DEF",
            ]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")

        assert result is True
        config = synced_configs[0]["slack"]
        assert config["mode"] == "socket"
        assert config["groupPolicy"] == "allowlist"
        assert config["dmPolicy"] == "pairing"

    def test_slack_config_synced_to_agent(self, isolated_config: Path):
        """Verify full config structure is passed to sync."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        synced_configs = []

        def capture_sync(host, claw_type, channels_config, installed_name):
            synced_configs.append(channels_config)

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.core.secrets.set_instance_secret"),
            patch("clawrium.cli.agent._sync_channel_config", side_effect=capture_sync),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                3, self.VALID_BOT_TOKEN, self.VALID_APP_TOKEN, "U01ABC2DEF",
            ]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")

        assert result is True
        config = synced_configs[0]["slack"]
        assert config["enabled"] is True
        assert config["mode"] == "socket"
        assert config["appToken"]["source"] == "env"
        assert config["appToken"]["id"] == "SLACK_APP_TOKEN"
        assert config["botToken"]["source"] == "env"
        assert config["botToken"]["id"] == "SLACK_BOT_TOKEN"
        assert config["allowFrom"] == ["U01ABC2DEF"]
        assert config["groupPolicy"] == "allowlist"
        assert config["dmPolicy"] == "pairing"

    def test_slack_sync_failure_returns_false(self, isolated_config: Path):
        """Returns False when channel config sync fails."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch(
                "clawrium.cli.agent._sync_channel_config",
                side_effect=Exception("SSH connection failed"),
            ),
        ):
            mock_p.side_effect = [
                3, self.VALID_BOT_TOKEN, self.VALID_APP_TOKEN, "U01ABC2DEF",
            ]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")

        assert result is False


class TestSlackIntegration:
    """Integration tests for Slack channel that verify actual disk persistence."""

    VALID_BOT_TOKEN = "xoxb-123456789012-123456789012-AbCdEfGhIjKlMnOpQrStUvWx"
    VALID_APP_TOKEN = "xapp-1-A01BC2DEF-abcdef0123456789fedcba9876543210"

    def test_slack_both_tokens_persisted_to_secrets_json(self, isolated_config: Path):
        """Verify both Slack tokens are written to secrets.json and readable back."""
        from clawrium.cli.agent import _run_channels_stage
        from clawrium.core.secrets import load_secrets, get_instance_key

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.cli.agent._sync_channel_config"),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                3, self.VALID_BOT_TOKEN, self.VALID_APP_TOKEN, "U01ABC2DEF",
            ]
            result = _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")

        assert result is True

        instance_key = get_instance_key("192.168.1.100", "openclaw", "assistant")
        secrets = load_secrets()
        assert instance_key in secrets
        assert "SLACK_BOT_TOKEN" in secrets[instance_key]
        assert secrets[instance_key]["SLACK_BOT_TOKEN"]["value"] == self.VALID_BOT_TOKEN
        assert "SLACK_APP_TOKEN" in secrets[instance_key]
        assert secrets[instance_key]["SLACK_APP_TOKEN"]["value"] == self.VALID_APP_TOKEN

    def test_slack_tokens_readable_by_configure_agent(self, isolated_config: Path):
        """Verify both tokens can be loaded via get_instance_secrets."""
        from clawrium.cli.agent import _run_channels_stage
        from clawrium.core.secrets import get_instance_key, get_instance_secrets

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            onboarding_state="channels",
            config={"provider": {"name": "test-provider", "type": "openai"}},
        )

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.cli.agent._sync_channel_config"),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                3, self.VALID_BOT_TOKEN, self.VALID_APP_TOKEN, "U01ABC2DEF",
            ]
            _run_channels_stage("192.168.1.100", "openclaw", False, "assistant")

        instance_key = get_instance_key("192.168.1.100", "openclaw", "assistant")
        instance_secrets = get_instance_secrets(instance_key)
        assert instance_secrets["SLACK_BOT_TOKEN"]["value"] == self.VALID_BOT_TOKEN
        assert instance_secrets["SLACK_APP_TOKEN"]["value"] == self.VALID_APP_TOKEN

    def test_slack_and_discord_coexist_in_secrets(self, isolated_config: Path):
        """Both Slack and Discord tokens can be stored for the same agent."""
        from clawrium.core.secrets import set_instance_secret, get_instance_secrets, get_instance_key

        instance_key = get_instance_key("192.168.1.100", "openclaw", "assistant")

        set_instance_secret(instance_key, "DISCORD_BOT_TOKEN", "discord-token-value", "Discord token")
        set_instance_secret(instance_key, "SLACK_BOT_TOKEN", self.VALID_BOT_TOKEN, "Slack bot token")
        set_instance_secret(instance_key, "SLACK_APP_TOKEN", self.VALID_APP_TOKEN, "Slack app token")

        secrets = get_instance_secrets(instance_key)
        assert "DISCORD_BOT_TOKEN" in secrets
        assert "SLACK_BOT_TOKEN" in secrets
        assert "SLACK_APP_TOKEN" in secrets
        assert secrets["DISCORD_BOT_TOKEN"]["value"] == "discord-token-value"
        assert secrets["SLACK_BOT_TOKEN"]["value"] == self.VALID_BOT_TOKEN
        assert secrets["SLACK_APP_TOKEN"]["value"] == self.VALID_APP_TOKEN

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
        hosts_data[0]["agents"]["openclaw"]["onboarding"]["stages"]["providers"][
            "provider_id"
        ] = "test-openai"
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        soul_dir = isolated_config / "agents" / "openclaw"
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
            patch(
                "clawrium.core.validation.validate_openclaw_gateway",
                return_value=ValidationResult(passed=True),
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
        hosts_data[0]["agents"]["openclaw"]["onboarding"]["stages"]["providers"][
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
        hosts_data[0]["agents"]["openclaw"]["onboarding"]["stages"]["providers"][
            "provider_id"
        ] = "test-openai"
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        soul_dir = isolated_config / "agents" / "openclaw"
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
            patch(
                "clawrium.core.validation.validate_openclaw_gateway",
                return_value=ValidationResult(
                    passed=True,
                    details={"gateway_url": "ws://192.168.1.100:40123"},
                ),
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
                "agents": {
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

        soul_dir = isolated_config / "agents" / "openclaw"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("Test personality")

        with patch("clawrium.cli.agent.complete_stage"):
            result = _run_validate_stage("work", "openclaw", True)

        assert result is False

    def test_skip_health_marks_validate_metadata(self, isolated_config: Path):
        """Stores skip metadata when validate runs with --skip-health."""
        from clawrium.cli.agent import _run_validate_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, onboarding_state="validate")
        create_provider(isolated_config)

        hosts_file = isolated_config / "hosts.json"
        hosts_data = json.loads(hosts_file.read_text())
        hosts_data[0]["agents"]["openclaw"]["onboarding"]["stages"]["providers"][
            "provider_id"
        ] = "test-openai"
        hosts_data[0]["agents"]["openclaw"]["config"] = {
            "gateway": {
                "url": "ws://192.168.1.100:40123",
                "auth": "token-123",
                "port": 40123,
            }
        }
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        soul_dir = isolated_config / "agents" / "openclaw"
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
            patch("clawrium.core.validation.validate_openclaw_gateway") as mock_gateway,
            patch("clawrium.cli.agent.complete_stage") as mock_complete,
        ):
            result = _run_validate_stage("work", "openclaw", True, skip_health=True)

        assert result is True
        mock_gateway.assert_not_called()
        args = mock_complete.call_args[0]
        metadata = args[4]
        assert metadata["gateway_health_checked"] is False
        assert metadata["gateway_health_status"] == "skipped"

    def test_gateway_health_failure_blocks_validate(self, isolated_config: Path):
        """Validate fails when OpenClaw gateway health check fails."""
        from clawrium.cli.agent import _run_validate_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, onboarding_state="validate")
        create_provider(isolated_config)

        hosts_file = isolated_config / "hosts.json"
        hosts_data = json.loads(hosts_file.read_text())
        hosts_data[0]["agents"]["openclaw"]["onboarding"]["stages"]["providers"][
            "provider_id"
        ] = "test-openai"
        hosts_data[0]["agents"]["openclaw"]["config"] = {
            "gateway": {
                "url": "ws://192.168.1.100:40123",
                "auth": "token-123",
                "port": 40123,
            }
        }
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        soul_dir = isolated_config / "agents" / "openclaw"
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
            patch(
                "clawrium.core.validation.validate_openclaw_gateway",
                return_value=ValidationResult(
                    passed=False, errors=["Could not connect to OpenClaw gateway"]
                ),
            ),
            patch("clawrium.cli.agent.complete_stage") as mock_complete,
        ):
            result = _run_validate_stage("work", "openclaw", True)

        assert result is False
        mock_complete.assert_not_called()


class TestHostsFileCorruptedError:
    """Tests for HostsFileCorruptedError handling."""

    def test_get_host_corrupted(self, isolated_config: Path):
        """Handles HostsFileCorruptedError from get_host."""
        from clawrium.core.hosts import HostsFileCorruptedError

        create_test_keypair(isolated_config, "work")

        with patch(
            "clawrium.cli.agent.load_hosts",
            side_effect=HostsFileCorruptedError("corrupted"),
        ):
            result = runner.invoke(app, ["agent", "configure", "assistant"])

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
                ["agent", "configure", "assistant", "--yes"],
                env=os.environ,
            )

            assert result.exit_code == 0
            assert mock_skip.called


class TestConfigurePreservesGatewayAuth:
    """Tests that configuration preserves gateway authentication."""

    def test_preserves_gateway_token_during_reconfiguration(
        self, isolated_config: Path
    ):
        """Gateway auth token is preserved when reconfiguring provider."""
        from clawrium.cli.agent import _sync_provider_config

        create_test_keypair(isolated_config, "work")

        # Create host with gateway auth already set
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "auth_method": "key",
                "agents": {
                    "openclaw": {
                        "version": "0.1.0",
                        "status": "installed",
                        "agent_name": "assistant",
                        "onboarding": {"state": "pending"},
                        "config": {
                            "gateway": {
                                "url": "ws://192.168.1.100:40123",
                                "auth": "original-token-abc123",
                                "port": 40123,
                                "bind": "lan",
                            }
                        },
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        # Test provider
        provider = {
            "name": "test-openai",
            "type": "openai",
            "endpoint": "",
            "default_model": "gpt-4",
        }

        # Mock configure_agent to verify it receives preserved auth
        captured_config = []

        def mock_configure(
            hostname, claw_name, config_data, agent_name=None, on_event=None
        ):
            captured_config.append(config_data.copy())
            return True, None

        with patch(
            "clawrium.core.lifecycle.configure_agent", side_effect=mock_configure
        ):
            _sync_provider_config(
                "work", "openclaw", provider, installed_name="openclaw"
            )

        # Verify gateway auth was preserved
        assert len(captured_config) > 0
        gateway_config = captured_config[0]["gateway"]
        assert gateway_config["url"] == "ws://192.168.1.100:40123"
        assert gateway_config["auth"] == "original-token-abc123"

    def test_preserves_gateway_url_during_reconfiguration(self, isolated_config: Path):
        """Gateway URL is preserved when reconfiguring provider."""
        from clawrium.cli.agent import _sync_provider_config

        create_test_keypair(isolated_config, "work")

        # Create host with gateway URL
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "auth_method": "key",
                "agents": {
                    "openclaw": {
                        "version": "0.1.0",
                        "status": "installed",
                        "agent_name": "assistant",
                        "onboarding": {"state": "pending"},
                        "config": {
                            "gateway": {
                                "url": "ws://custom-host:9999",
                                "port": 9999,
                                "bind": "lan",
                            }
                        },
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        provider = {
            "name": "test-openai",
            "type": "openai",
            "endpoint": "",
            "default_model": "gpt-4",
        }

        captured_config = []

        def mock_configure(
            hostname, claw_name, config_data, agent_name=None, on_event=None
        ):
            captured_config.append(config_data.copy())
            return True, None

        with patch(
            "clawrium.core.lifecycle.configure_agent", side_effect=mock_configure
        ):
            _sync_provider_config(
                "work", "openclaw", provider, installed_name="openclaw"
            )

        # Verify URL was preserved
        gateway_config = captured_config[0]["gateway"]
        assert gateway_config["url"] == "ws://custom-host:9999"

    def test_preserves_channels_during_provider_switch(self, isolated_config: Path):
        """Test that channels config is preserved when switching providers."""
        from clawrium.cli.agent import _sync_provider_config

        create_test_keypair(isolated_config, "work")

        # Create host with channels config
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "auth_method": "key",
                "agents": {
                    "openclaw": {
                        "version": "0.1.0",
                        "status": "installed",
                        "agent_name": "assistant",
                        "onboarding": {"state": "ready"},
                        "config": {
                            "gateway": {"port": 40000, "bind": "lan"},
                            "provider": {
                                "name": "old-provider",
                                "type": "openrouter",
                                "default_model": "openai/gpt-4o",
                            },
                            "channels": {
                                "discord": {
                                    "enabled": True,
                                    "token": {
                                        "source": "env",
                                        "id": "DISCORD_BOT_TOKEN",
                                    },
                                    "allowFrom": ["123456789"],
                                }
                            },
                        },
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        # New provider to switch to
        provider = {
            "name": "new-provider",
            "type": "ollama",
            "endpoint": "http://localhost:11434",
            "default_model": "llama3.1:8b",
        }

        # Capture the config_data passed to configure_agent
        captured_config = []

        def mock_configure(
            hostname, claw_name, config_data, agent_name=None, on_event=None
        ):
            captured_config.append(config_data.copy())
            return True, None

        with patch(
            "clawrium.core.lifecycle.configure_agent", side_effect=mock_configure
        ):
            _sync_provider_config(
                "work", "openclaw", provider, installed_name="openclaw"
            )

        # Verify channels were preserved
        assert "channels" in captured_config[0]
        assert captured_config[0]["channels"]["discord"]["enabled"] is True
        assert captured_config[0]["channels"]["discord"]["allowFrom"] == ["123456789"]

    def test_does_not_add_channels_when_absent(self, isolated_config: Path):
        """Test that channels key is not added when not present in existing config."""
        from clawrium.cli.agent import _sync_provider_config

        create_test_keypair(isolated_config, "work")

        # Create host without channels config
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "key_id": "work",
                "port": 22,
                "agent_name": "xclm",
                "alias": "work",
                "auth_method": "key",
                "agents": {
                    "openclaw": {
                        "version": "0.1.0",
                        "status": "installed",
                        "agent_name": "assistant",
                        "onboarding": {"state": "ready"},
                        "config": {
                            "gateway": {"port": 40000, "bind": "lan"},
                            "provider": {
                                "name": "old-provider",
                                "type": "openrouter",
                                "default_model": "openai/gpt-4o",
                            },
                            # No channels key
                        },
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data, indent=2))

        provider = {
            "name": "new-provider",
            "type": "ollama",
            "endpoint": "http://localhost:11434",
            "default_model": "llama3.1:8b",
        }

        captured_config = []

        def mock_configure(
            hostname, claw_name, config_data, agent_name=None, on_event=None
        ):
            captured_config.append(config_data.copy())
            return True, None

        with patch(
            "clawrium.core.lifecycle.configure_agent", side_effect=mock_configure
        ):
            _sync_provider_config(
                "work", "openclaw", provider, installed_name="openclaw"
            )

        # Verify channels key was not added
        assert "channels" not in captured_config[0]


class TestEditConfigOptions:
    """Tests for --edit-config and --editor CLI options."""

    def test_edit_config_routes_to_edit_flow(self, isolated_config: Path):
        """--edit-config flag routes to _run_edit_config with correct parameters."""
        create_host_with_claw(isolated_config, onboarding_state="ready")
        create_test_keypair(isolated_config, "work")

        with patch("clawrium.cli.agent._run_edit_config") as mock_edit:
            result = runner.invoke(
                app, ["agent", "configure", "assistant", "--edit-config"]
            )

        # Verify _run_edit_config was called
        mock_edit.assert_called_once()
        call_kwargs = mock_edit.call_args.kwargs
        assert call_kwargs["hostname"] == "192.168.1.100"
        assert call_kwargs["installed_name"] == "assistant"
        assert call_kwargs["claw_type"] == "openclaw"
        assert call_kwargs["editor"] is None
        assert result.exit_code == 0

    def test_edit_config_passes_editor_option(self, isolated_config: Path):
        """--editor option is passed to _run_edit_config."""
        create_host_with_claw(isolated_config, onboarding_state="ready")
        create_test_keypair(isolated_config, "work")

        with patch("clawrium.cli.agent._run_edit_config") as mock_edit:
            result = runner.invoke(
                app,
                [
                    "agent",
                    "configure",
                    "assistant",
                    "--edit-config",
                    "--editor",
                    "nano",
                ],
            )

        mock_edit.assert_called_once()
        assert mock_edit.call_args.kwargs["editor"] == "nano"
        assert result.exit_code == 0

    def test_edit_config_no_config_shows_error(self, isolated_config: Path):
        """--edit-config without existing config shows clear error."""
        create_host_with_claw(isolated_config, onboarding_state="ready")
        create_test_keypair(isolated_config, "work")

        result = runner.invoke(
            app, ["agent", "configure", "assistant", "--edit-config"]
        )

        assert result.exit_code == 1
        assert "no configuration found" in result.output.lower()
        assert "clm agent configure assistant" in result.output

    def test_edit_config_with_stage_fails(self, isolated_config: Path):
        """--edit-config with --stage fails with actionable error."""
        create_host_with_claw(isolated_config, onboarding_state="ready")
        create_test_keypair(isolated_config, "work")

        result = runner.invoke(
            app,
            [
                "agent",
                "configure",
                "assistant",
                "--edit-config",
                "--stage",
                "providers",
            ],
        )

        assert result.exit_code == 1
        assert "--edit-config cannot be used with --stage" in result.output

    def test_edit_config_with_file_fails(self, isolated_config: Path):
        """--edit-config with --file fails with actionable error."""
        create_host_with_claw(isolated_config, onboarding_state="ready")
        create_test_keypair(isolated_config, "work")

        # Create a dummy file
        dummy_file = isolated_config / "SOUL.md"
        dummy_file.write_text("# Test Soul")

        result = runner.invoke(
            app,
            [
                "agent",
                "configure",
                "assistant",
                "--edit-config",
                "--file",
                str(dummy_file),
            ],
        )

        assert result.exit_code == 1
        assert "--edit-config cannot be used with --file" in result.output

    def test_edit_config_with_skip_health_fails(self, isolated_config: Path):
        """--edit-config with --skip-health fails with actionable error."""
        create_host_with_claw(isolated_config, onboarding_state="ready")
        create_test_keypair(isolated_config, "work")

        result = runner.invoke(
            app,
            ["agent", "configure", "assistant", "--edit-config", "--skip-health"],
        )

        assert result.exit_code == 1
        assert "--edit-config cannot be used with --skip-health" in result.output

    def test_editor_without_edit_config_fails(self, isolated_config: Path):
        """--editor without --edit-config fails with actionable error."""
        create_host_with_claw(isolated_config, onboarding_state="ready")
        create_test_keypair(isolated_config, "work")

        result = runner.invoke(
            app, ["agent", "configure", "assistant", "--editor", "vim"]
        )

        assert result.exit_code == 1
        assert "--editor can only be used with --edit-config" in result.output

    def test_edit_config_does_not_run_onboarding(self, isolated_config: Path):
        """--edit-config routes to edit flow, not onboarding wizard."""
        create_host_with_claw(isolated_config, onboarding_state="pending")
        create_test_keypair(isolated_config, "work")

        with patch("clawrium.cli.agent._run_edit_config"):
            result = runner.invoke(
                app, ["agent", "configure", "assistant", "--edit-config"]
            )

        # Should NOT show onboarding flow
        assert "Starting onboarding" not in result.output
        assert "Stage 1" not in result.output

    def test_edit_config_agent_not_found(self, isolated_config: Path):
        """--edit-config with non-existent agent fails with error."""
        create_host_with_claw(isolated_config, onboarding_state="ready")
        create_test_keypair(isolated_config, "work")

        result = runner.invoke(
            app, ["agent", "configure", "nonexistent", "--edit-config"]
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestEditConfigWorkflow:
    """Tests for the actual edit-config workflow implementation."""

    @pytest.fixture
    def agent_config(self):
        """Return a sample agent config for testing."""
        return {
            "provider": {
                "name": "test-openai",
                "type": "openai",
                "default_model": "gpt-4",
            },
            "gateway": {
                "port": 40000,
                "host": "0.0.0.0",
            },
        }

    def test_editor_resolution_option_takes_precedence(
        self, isolated_config: Path, monkeypatch
    ):
        """--editor option takes precedence over environment variables."""
        from clawrium.cli.agent import _resolve_editor

        monkeypatch.setenv("VISUAL", "emacs")
        monkeypatch.setenv("EDITOR", "nano")

        assert _resolve_editor("vim") == "vim"

    def test_editor_resolution_visual_over_editor(
        self, isolated_config: Path, monkeypatch
    ):
        """VISUAL env var takes precedence over EDITOR."""
        from clawrium.cli.agent import _resolve_editor

        monkeypatch.setenv("VISUAL", "emacs")
        monkeypatch.setenv("EDITOR", "nano")

        assert _resolve_editor(None) == "emacs"

    def test_editor_resolution_editor_fallback(
        self, isolated_config: Path, monkeypatch
    ):
        """EDITOR env var is used when VISUAL is not set."""
        from clawrium.cli.agent import _resolve_editor

        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setenv("EDITOR", "nano")

        assert _resolve_editor(None) == "nano"

    def test_editor_resolution_vi_default(self, isolated_config: Path, monkeypatch):
        """vi is used as default when no env vars are set."""
        from clawrium.cli.agent import _resolve_editor

        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)

        assert _resolve_editor(None) == "vi"

    def test_invalid_json_blocks_sync(self, isolated_config: Path, agent_config):
        """Invalid JSON after editing blocks sync and shows file path."""
        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        def mock_editor_writes_invalid_json(args, **kwargs):
            # Find the config file and write invalid JSON
            config_path = args[1]
            with open(config_path, "w") as f:
                f.write('{"invalid": json missing bracket')
            return type("Result", (), {"returncode": 0})()

        with patch("subprocess.run", side_effect=mock_editor_writes_invalid_json):
            result = runner.invoke(
                app, ["agent", "configure", "assistant", "--edit-config"]
            )

        assert result.exit_code == 1
        assert "invalid json" in result.output.lower()
        assert "preserved at" in result.output.lower()
        # Verify file path is shown in output for recovery
        assert "/tmp/" in result.output or "clm-edit-" in result.output

    def test_no_change_skips_sync(self, isolated_config: Path, agent_config):
        """No changes in editor skips sync."""
        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        def mock_editor_no_change(args, **kwargs):
            # Editor exits without modifying file
            return type("Result", (), {"returncode": 0})()

        with patch("subprocess.run", side_effect=mock_editor_no_change):
            with patch("clawrium.core.lifecycle.configure_agent") as mock_configure:
                result = runner.invoke(
                    app, ["agent", "configure", "assistant", "--edit-config"]
                )

        assert "no changes detected" in result.output.lower()
        mock_configure.assert_not_called()

    def test_successful_edit_syncs_config(self, isolated_config: Path, agent_config):
        """Valid config change triggers sync."""
        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        def mock_editor_changes_port(args, **kwargs):
            config_path = args[1]
            with open(config_path) as f:
                config = json.load(f)
            config["gateway"]["port"] = 50000
            with open(config_path, "w") as f:
                json.dump(config, f)
            return type("Result", (), {"returncode": 0})()

        with patch("subprocess.run", side_effect=mock_editor_changes_port):
            with patch(
                "clawrium.core.lifecycle.configure_agent", return_value=(True, None)
            ) as mock_configure:
                with patch(
                    "clawrium.core.lifecycle.restart_agent",
                    return_value={"success": True, "error": None},
                ):
                    result = runner.invoke(
                        app,
                        ["agent", "configure", "assistant", "--edit-config"],
                        input="y\n",  # Confirm restart
                    )

        assert "synced" in result.output.lower()
        mock_configure.assert_called_once()
        # Verify the new config was passed
        call_args = mock_configure.call_args
        assert call_args[0][2]["gateway"]["port"] == 50000

    def test_restart_prompt_only_after_sync(self, isolated_config: Path, agent_config):
        """Restart prompt appears only when config was synced."""
        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        def mock_editor_changes_model(args, **kwargs):
            config_path = args[1]
            with open(config_path) as f:
                config = json.load(f)
            config["provider"]["default_model"] = "gpt-4-turbo"
            with open(config_path, "w") as f:
                json.dump(config, f)
            return type("Result", (), {"returncode": 0})()

        with patch("subprocess.run", side_effect=mock_editor_changes_model):
            with patch(
                "clawrium.core.lifecycle.configure_agent", return_value=(True, None)
            ):
                with patch(
                    "clawrium.core.lifecycle.restart_agent",
                    return_value={"success": True, "error": None},
                ) as mock_restart:
                    # User declines restart
                    result = runner.invoke(
                        app,
                        ["agent", "configure", "assistant", "--edit-config"],
                        input="n\n",
                    )

        assert "restart agent to apply changes" in result.output.lower()
        mock_restart.assert_not_called()
        assert "restart manually" in result.output.lower()

    def test_sync_failure_shows_error(self, isolated_config: Path, agent_config):
        """Sync failure shows error and preserves file."""
        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        def mock_editor_changes_port(args, **kwargs):
            config_path = args[1]
            with open(config_path) as f:
                config = json.load(f)
            config["gateway"]["port"] = 50000
            with open(config_path, "w") as f:
                json.dump(config, f)
            return type("Result", (), {"returncode": 0})()

        with patch("subprocess.run", side_effect=mock_editor_changes_port):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(False, "SSH connection failed"),
            ):
                result = runner.invoke(
                    app, ["agent", "configure", "assistant", "--edit-config"]
                )

        assert result.exit_code == 1
        assert "sync failed" in result.output.lower()
        assert "ssh connection failed" in result.output.lower()
        assert "preserved at" in result.output.lower()

    def test_editor_not_found_shows_error(self, isolated_config: Path, agent_config):
        """Editor not found shows clear error with suggestion."""
        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = runner.invoke(
                app,
                [
                    "agent",
                    "configure",
                    "assistant",
                    "--edit-config",
                    "--editor",
                    "nonexistent-editor",
                ],
            )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()
        assert "--editor" in result.output

    def test_editor_error_exit_code(self, isolated_config: Path, agent_config):
        """Editor non-zero exit shows error."""
        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        with patch(
            "subprocess.run",
            return_value=type("Result", (), {"returncode": 1})(),
        ):
            result = runner.invoke(
                app, ["agent", "configure", "assistant", "--edit-config"]
            )

        assert result.exit_code == 1
        assert "editor exited with code 1" in result.output.lower()

    def test_restart_agent_returns_failure(self, isolated_config: Path, agent_config):
        """restart_agent returning failure dict shows error."""
        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        def mock_editor_changes_port(args, **kwargs):
            config_path = args[1]
            with open(config_path) as f:
                config = json.load(f)
            config["gateway"]["port"] = 50000
            with open(config_path, "w") as f:
                json.dump(config, f)
            return type("Result", (), {"returncode": 0})()

        with patch("subprocess.run", side_effect=mock_editor_changes_port):
            with patch(
                "clawrium.core.lifecycle.configure_agent", return_value=(True, None)
            ):
                with patch(
                    "clawrium.core.lifecycle.restart_agent",
                    return_value={"success": False, "error": "Service failed to start"},
                ):
                    result = runner.invoke(
                        app,
                        ["agent", "configure", "assistant", "--edit-config"],
                        input="y\n",  # Confirm restart
                    )

        assert result.exit_code == 1
        assert "restart failed" in result.output.lower()
        assert "service failed to start" in result.output.lower()

    def test_restart_agent_raises_lifecycle_error(
        self, isolated_config: Path, agent_config
    ):
        """restart_agent raising LifecycleError shows error."""
        from clawrium.core.lifecycle import LifecycleError

        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        def mock_editor_changes_port(args, **kwargs):
            config_path = args[1]
            with open(config_path) as f:
                config = json.load(f)
            config["gateway"]["port"] = 50000
            with open(config_path, "w") as f:
                json.dump(config, f)
            return type("Result", (), {"returncode": 0})()

        with patch("subprocess.run", side_effect=mock_editor_changes_port):
            with patch(
                "clawrium.core.lifecycle.configure_agent", return_value=(True, None)
            ):
                with patch(
                    "clawrium.core.lifecycle.restart_agent",
                    side_effect=LifecycleError("Host not reachable"),
                ):
                    result = runner.invoke(
                        app,
                        ["agent", "configure", "assistant", "--edit-config"],
                        input="y\n",  # Confirm restart
                    )

        assert result.exit_code == 1
        assert "restart failed" in result.output.lower()
        assert "host not reachable" in result.output.lower()

    def test_sync_failure_preserves_temp_dir(self, isolated_config: Path, agent_config):
        """Sync failure preserves temp directory for recovery with path shown."""
        import re

        create_host_with_claw(
            isolated_config, onboarding_state="ready", config=agent_config
        )
        create_test_keypair(isolated_config, "work")

        def mock_editor_changes_port(args, **kwargs):
            config_path = args[1]
            with open(config_path) as f:
                config = json.load(f)
            config["gateway"]["port"] = 50000
            with open(config_path, "w") as f:
                json.dump(config, f)
            return type("Result", (), {"returncode": 0})()

        with patch("subprocess.run", side_effect=mock_editor_changes_port):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(False, "Connection refused"),
            ):
                result = runner.invoke(
                    app, ["agent", "configure", "assistant", "--edit-config"]
                )

        assert result.exit_code == 1
        assert "preserved at" in result.output.lower()
        # Extract the preserved file path from output and verify it exists
        # The path looks like: /tmp/clm-edit-XXXX/assistant.json
        path_match = re.search(r"(/tmp/clm-edit-[^/]+/[^\s]+)", result.output)
        if path_match:
            preserved_path = path_match.group(1)
            assert Path(preserved_path).exists(), (
                f"Preserved file should exist: {preserved_path}"
            )


class TestRunChannelsStageHermesDiscord:
    """Tests for the hermes-specific Discord channels branch (issue #324)."""

    def _valid_token(self) -> str:
        # 50-120 chars matching ^[A-Za-z0-9._+/=-]+$
        return "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw"

    def test_hermes_channel_list_includes_discord(self, isolated_config: Path):
        """The hermes guard is gone: discord is offered to hermes agents."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config, claw_type="hermes")

        # Choose option 1 (cli) — we only want to inspect the rendered menu.
        result = runner.invoke(
            app,
            ["agent", "configure", "assistant", "--stage", "channels"],
            input="1\n",
            env=os.environ,
        )

        assert "cli" in result.output.lower()
        assert "discord" in result.output.lower()
        # Slack stays out of the hermes list (no wiring yet).
        assert "slack" not in result.output.lower()

    def test_hermes_discord_writes_token_secret_and_hosts_config(
        self, isolated_config: Path
    ):
        """Selecting discord on hermes stores the token in secrets.json and
        the non-sensitive config (allowed_users / home_channel / etc.) in
        hosts.json — no bot_token in the synced shape."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            onboarding_state="channels",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        stored_secrets: list[dict] = []
        synced_configs: list[dict] = []

        def capture_secret(instance_key, key, value, description):
            stored_secrets.append(
                {"instance_key": instance_key, "key": key, "value": value}
            )

        def capture_sync(host, claw_type, channels_config, installed_name):
            synced_configs.append(channels_config)

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.cli.agent.typer.confirm", return_value=True),
            patch(
                "clawrium.core.secrets.set_instance_secret", side_effect=capture_secret
            ),
            patch("clawrium.cli.agent._sync_channel_config", side_effect=capture_sync),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                2,  # Select discord
                self._valid_token(),  # Bot token
                "740723459344302120",  # Allowed user IDs
                "1503238729962356777",  # Home channel ID
                "Home",  # Home channel name
                "",  # Allowed channels (any)
            ]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )

        assert result is True
        assert len(stored_secrets) == 1
        assert stored_secrets[0]["key"] == "DISCORD_BOT_TOKEN"
        assert stored_secrets[0]["value"] == self._valid_token()

        assert len(synced_configs) == 1
        discord_cfg = synced_configs[0]["discord"]
        # Hermes shape — flat, env-var-mapped.
        assert discord_cfg["enabled"] is True
        assert discord_cfg["allowed_users"] == ["740723459344302120"]
        assert discord_cfg["allow_all_users"] is False
        assert discord_cfg["home_channel"] == "1503238729962356777"
        assert discord_cfg["home_channel_name"] == "Home"
        assert discord_cfg["require_mention"] is True
        # CRITICAL: bot_token must NOT be in the hosts.json shape.
        assert "bot_token" not in discord_cfg
        # And we must not regress to the openclaw guilds-shape.
        assert "guilds" not in discord_cfg
        assert "groupPolicy" not in discord_cfg

    def test_hermes_discord_rejects_invalid_user_id(self, isolated_config: Path):
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # Select discord
                self._valid_token(),
                "1234",  # Invalid user ID (too short)
            ]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )
        assert result is False

    def test_hermes_discord_all_requires_confirmation(
        self, isolated_config: Path
    ):
        """Passing 'all' for allowed users triggers a second confirm prompt
        and only sets allow_all_users when the user confirms."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            onboarding_state="channels",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        synced: list[dict] = []

        def capture_sync(host, claw_type, channels_config, installed_name):
            synced.append(channels_config)

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.cli.agent.typer.confirm") as mock_c,
            patch("clawrium.core.secrets.set_instance_secret"),
            patch("clawrium.cli.agent._sync_channel_config", side_effect=capture_sync),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                2,
                self._valid_token(),
                "all",  # open-bot
                "",  # home channel skip
                "",  # allowed channels any
            ]
            # First confirm = open-bot acceptance, second = require_mention default
            mock_c.side_effect = [True, True]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )

        assert result is True
        assert synced[0]["discord"]["allow_all_users"] is True
        assert synced[0]["discord"]["allowed_users"] == []

    def test_hermes_discord_all_aborts_when_not_confirmed(
        self, isolated_config: Path
    ):
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.cli.agent.typer.confirm", return_value=False),
        ):
            mock_p.side_effect = [
                2,
                self._valid_token(),
                "all",
            ]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )
        assert result is False

    def test_hermes_discord_skip_home_channel(self, isolated_config: Path):
        """An empty home_channel input is accepted; home_channel and
        home_channel_name are absent from the synced shape."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            onboarding_state="channels",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        synced: list[dict] = []

        def capture_sync(host, claw_type, channels_config, installed_name):
            synced.append(channels_config)

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.cli.agent.typer.confirm", return_value=True),
            patch("clawrium.core.secrets.set_instance_secret"),
            patch("clawrium.cli.agent._sync_channel_config", side_effect=capture_sync),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                2,
                self._valid_token(),
                "740723459344302120",
                "",  # skip home channel
                "",  # allowed channels any
            ]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )

        assert result is True
        d = synced[0]["discord"]
        assert "home_channel" not in d
        assert "home_channel_name" not in d

    def test_hermes_discord_allowed_channels_validated(
        self, isolated_config: Path
    ):
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            onboarding_state="channels",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,
                self._valid_token(),
                "740723459344302120",
                "1503238729962356777",  # home channel
                "Home",
                "abc,123",  # invalid allowed channels
            ]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )

        assert result is False

    def test_hermes_discord_rejects_newline_in_home_channel_name(
        self, isolated_config: Path
    ):
        """Newline (or other shell metachars) in home_channel_name would
        inject arbitrary env vars into .env on render. CLI must reject
        before persisting."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            onboarding_state="channels",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,  # discord
                self._valid_token(),
                "740723459344302120",
                "1503238729962356777",  # home channel
                "Home\nMALICIOUS_VAR=pwned",  # injection attempt
            ]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )
        assert result is False

    def test_hermes_discord_rejects_too_long_home_channel_name(
        self, isolated_config: Path
    ):
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,
                self._valid_token(),
                "740723459344302120",
                "1503238729962356777",
                "A" * 100,  # > 64 chars
            ]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )
        assert result is False

    def test_hermes_discord_rejects_user_id_boundaries(
        self, isolated_config: Path
    ):
        """User IDs outside the 17-19 digit range are rejected before any
        secret is stored. Tests both ends of the boundary plus a shell-meta
        injection attempt."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        for bad_id in [
            "1234567890123456",  # 16 digits — too short
            "12345678901234567890",  # 20 digits — too long
            "1234567890123456789;rm -rf /",  # shell metachar injection
            "[bold red]inject[/bold red]",  # rich markup injection
        ]:
            with patch("clawrium.cli.agent.typer.prompt") as mock_p:
                mock_p.side_effect = [
                    2,  # discord
                    self._valid_token(),
                    bad_id,
                ]
                result = _run_channels_stage(
                    "192.168.1.100", "hermes", False, "assistant"
                )
            assert result is False, f"accepted invalid user ID: {bad_id!r}"

    def test_hermes_discord_rejects_home_channel_id_boundaries(
        self, isolated_config: Path
    ):
        """Home channel ID outside 17-19 digits is rejected."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        for bad_id in [
            "1234567890123456",  # 16 digits
            "12345678901234567890",  # 20 digits
            "1234567890123456789;evil",
        ]:
            with patch("clawrium.cli.agent.typer.prompt") as mock_p:
                mock_p.side_effect = [
                    2,
                    self._valid_token(),
                    "740723459344302120",
                    bad_id,  # invalid home channel
                ]
                result = _run_channels_stage(
                    "192.168.1.100", "hermes", False, "assistant"
                )
            assert result is False, f"accepted invalid home channel: {bad_id!r}"

    def test_hermes_discord_rejects_allowed_channels_boundaries(
        self, isolated_config: Path
    ):
        """Any malformed allowed_channels entry rejects the whole list."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="hermes",
            config={
                "provider": {
                    "name": "p",
                    "type": "ollama",
                    "default_model": "x",
                    "endpoint": "http://h/v1",
                }
            },
        )

        with patch("clawrium.cli.agent.typer.prompt") as mock_p:
            mock_p.side_effect = [
                2,
                self._valid_token(),
                "740723459344302120",
                "1503238729962356777",  # home channel
                "Home",
                # Mix of valid + invalid — the invalid entry must reject.
                "1503238729962356777,not-a-channel",
            ]
            result = _run_channels_stage(
                "192.168.1.100", "hermes", False, "assistant"
            )
        assert result is False

    def test_openclaw_discord_still_uses_guilds_shape(
        self, isolated_config: Path
    ):
        """Regression guard: openclaw's existing guilds-{} shape is preserved
        — the hermes branch must not infect non-hermes claws."""
        from clawrium.cli.agent import _run_channels_stage

        create_test_keypair(isolated_config, "work")
        create_host_with_claw(
            isolated_config,
            claw_type="openclaw",
            onboarding_state="channels",
            config={"provider": {"name": "p", "type": "openai"}},
        )

        synced: list[dict] = []

        def capture_sync(host, claw_type, channels_config, installed_name):
            synced.append(channels_config)

        with (
            patch("clawrium.cli.agent.typer.prompt") as mock_p,
            patch("clawrium.core.secrets.set_instance_secret"),
            patch("clawrium.cli.agent._sync_channel_config", side_effect=capture_sync),
            patch("clawrium.cli.agent.complete_stage"),
        ):
            mock_p.side_effect = [
                2,
                self._valid_token(),
                "123456789012345678",  # guild ID
                "987654321098765432",  # channel ID
                "740723459344302120",  # user ID
            ]
            result = _run_channels_stage(
                "192.168.1.100", "openclaw", False, "assistant"
            )

        assert result is True
        d = synced[0]["discord"]
        # openclaw shape preserved
        assert "guilds" in d
        assert "123456789012345678" in d["guilds"]
        assert d["groupPolicy"] == "allowlist"
        # And the hermes-only flat fields are NOT injected.
        assert "allowed_users" not in d
        assert "home_channel" not in d

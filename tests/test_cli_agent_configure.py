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
            mock_run.assert_called_once_with(
                "192.168.1.100", "openclaw", True, "assistant"
            )

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
        """Creates SOUL.md in config directory."""
        from clawrium.cli.agent import _run_identity_stage

        with patch("clawrium.cli.agent.complete_stage"):
            result = _run_identity_stage("work", "openclaw", True)

        assert result is True
        soul_path = isolated_config / "agents" / "openclaw" / "SOUL.md"
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

    def test_channel_list_shows_cli_and_discord(self, isolated_config: Path):
        """Verify only cli and discord are shown as options."""
        create_test_keypair(isolated_config, "work")
        create_host_with_claw(isolated_config)

        result = runner.invoke(
            app,
            ["agent", "configure", "assistant", "--stage", "channels"],
            input="1\n",  # Select cli
            env=os.environ,
        )

        assert "cli" in result.output.lower()
        assert "discord" in result.output.lower()
        # These channels should NOT be shown
        assert "web" not in result.output.lower()
        assert "whatsapp" not in result.output.lower()
        assert "slack" not in result.output.lower()


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
                                    "token": {"source": "env", "id": "DISCORD_BOT_TOKEN"},
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

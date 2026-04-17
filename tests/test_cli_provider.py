"""Tests for provider CLI commands."""

import json
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner

from clawrium.cli.main import app
from clawrium.core.providers import PROVIDERS_FILE, save_providers


runner = CliRunner()


class TestProviderTypes:
    """Tests for 'clm provider types' command."""

    def test_types_lists_all_providers(self, isolated_config):
        """'clm provider types' lists all supported provider types."""
        result = runner.invoke(app, ["provider", "types"])

        assert result.exit_code == 0
        assert "openai" in result.output
        assert "anthropic" in result.output
        assert "openrouter" in result.output
        assert "bedrock" in result.output
        assert "vertex" in result.output
        assert "zai" in result.output
        assert "ollama" in result.output


class TestProviderTypesModels:
    """Tests for 'clm provider types <type> models' command."""

    def test_types_models_by_type(self, isolated_config):
        """'clm provider types openai models' lists OpenAI models."""
        result = runner.invoke(app, ["provider", "types", "openai", "models"])

        assert result.exit_code == 0
        assert "gpt-4o" in result.output
        assert "gpt-4o-mini" in result.output

    def test_types_models_ollama_shows_message(self, isolated_config):
        """'clm provider types ollama models' shows dynamic discovery message."""
        result = runner.invoke(app, ["provider", "types", "ollama", "models"])

        assert result.exit_code == 0
        assert "dynamically" in result.output.lower()

    def test_types_invalid_type(self, isolated_config):
        """'clm provider types <invalid> models' shows error."""
        result = runner.invoke(app, ["provider", "types", "nonexistent", "models"])

        assert result.exit_code == 1
        assert "not a valid provider type" in result.output.lower()

    def test_types_no_action_shows_hint(self, isolated_config):
        """'clm provider types openai' (no action) shows available actions."""
        result = runner.invoke(app, ["provider", "types", "openai"])

        assert result.exit_code == 0
        assert "available actions" in result.output.lower()
        assert "models" in result.output

    def test_types_invalid_action(self, isolated_config):
        """'clm provider types openai invalid' shows error."""
        result = runner.invoke(app, ["provider", "types", "openai", "invalid"])

        assert result.exit_code == 1
        assert "unknown action" in result.output.lower()


class TestProviderList:
    """Tests for 'clm provider list' command."""

    def test_list_empty(self, isolated_config):
        """'clm provider list' shows message when no providers."""
        result = runner.invoke(app, ["provider", "list"])

        assert result.exit_code == 0
        assert "no providers configured" in result.output.lower()

    def test_list_with_providers(self, isolated_config, sample_provider_data):
        """'clm provider list' shows configured providers."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(app, ["provider", "list"])

        assert result.exit_code == 0
        assert "test-openai" in result.output
        assert "openai" in result.output
        assert "gpt-4o" in result.output

    def test_list_ollama_shows_endpoint(self, isolated_config, sample_ollama_provider):
        """'clm provider list' shows endpoint for Ollama instead of API key."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_ollama_provider])

        result = runner.invoke(app, ["provider", "list"])

        assert result.exit_code == 0
        assert "localhost:11434" in result.output

    def test_list_corrupted_file(self, isolated_config):
        """'clm provider list' handles corrupted providers.json."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / PROVIDERS_FILE).write_text("not valid json")

        result = runner.invoke(app, ["provider", "list"])

        assert result.exit_code == 1
        assert "corrupted" in result.output.lower()


class TestProviderAdd:
    """Tests for 'clm provider add' command."""

    def test_add_requires_type(self, isolated_config):
        """'clm provider add' requires --type option."""
        result = runner.invoke(app, ["provider", "add", "myopenai"])

        assert result.exit_code != 0
        assert "type" in result.output.lower()

    def test_add_invalid_type(self, isolated_config):
        """'clm provider add' rejects invalid provider type."""
        result = runner.invoke(
            app, ["provider", "add", "myopenai", "--type", "invalid"]
        )

        assert result.exit_code == 1
        assert "invalid provider type" in result.output.lower()

    def test_add_invalid_name(self, isolated_config):
        """'clm provider add' rejects invalid provider name."""
        # Need to provide API key via prompt
        result = runner.invoke(
            app,
            ["provider", "add", "1invalid", "--type", "openai"],
            input="sk-test\n1\n",
        )

        assert result.exit_code == 1
        assert "invalid provider name" in result.output.lower()

    def test_add_openai_prompts_for_api_key(self, isolated_config):
        """'clm provider add' prompts for API key securely."""
        result = runner.invoke(
            app,
            ["provider", "add", "myopenai", "--type", "openai", "--model", "gpt-4o"],
            input="sk-test123\n",
        )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()

        # Verify provider was created
        providers_path = isolated_config / PROVIDERS_FILE
        assert providers_path.exists()

        with open(providers_path) as f:
            providers = json.load(f)

        assert len(providers) == 1
        assert providers[0]["name"] == "myopenai"
        assert providers[0]["type"] == "openai"
        assert providers[0]["default_model"] == "gpt-4o"
        # API key should NOT be in providers.json (stored in secrets)
        assert "api_key" not in providers[0]

    def test_add_duplicate_fails(self, isolated_config, sample_provider_data):
        """'clm provider add' fails for duplicate name."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(
            app,
            ["provider", "add", "test-openai", "--type", "anthropic"],
            input="sk-test\n1\n",
        )

        assert result.exit_code == 1
        assert "already exists" in result.output.lower()

    def test_add_ollama_rejects_metadata_endpoint(self, isolated_config):
        """'clm provider add --type ollama' rejects cloud metadata endpoints."""
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("169.254.169.254", 0))]
            result = runner.invoke(
                app,
                [
                    "provider",
                    "add",
                    "bad-provider",
                    "--type",
                    "ollama",
                    "--url",
                    "http://169.254.169.254",
                ],
            )

        assert result.exit_code == 1
        assert "metadata" in result.output.lower()

    def test_add_ollama_success(self, isolated_config):
        """'clm provider add --type ollama' works with valid public URL."""
        # Mock URL validation to allow the URL
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            # Mock the Ollama server connection
            mock_response = MagicMock()
            mock_response.json.return_value = {"models": [{"name": "llama3:latest"}]}
            mock_response.raise_for_status = MagicMock()

            with patch(
                "clawrium.core.providers.storage.requests.get", return_value=mock_response
            ):
                result = runner.invoke(
                    app,
                    [
                        "provider",
                        "add",
                        "local-llm",
                        "--type",
                        "ollama",
                        "--url",
                        "http://ollama.example.com:11434",
                        "--model",
                        "llama3:latest",
                    ],
                )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()

    def test_add_ollama_no_models_fails(self, isolated_config):
        """'clm provider add --type ollama' fails when no models on server."""
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            mock_response = MagicMock()
            mock_response.json.return_value = {"models": []}
            mock_response.raise_for_status = MagicMock()

            with patch(
                "clawrium.core.providers.storage.requests.get", return_value=mock_response
            ):
                result = runner.invoke(
                    app,
                    [
                        "provider",
                        "add",
                        "local-llm",
                        "--type",
                        "ollama",
                        "--url",
                        "http://ollama.example.com:11434",
                    ],
                )

        assert result.exit_code == 1
        assert "no models" in result.output.lower()

    def test_add_ollama_connection_failure(self, isolated_config):
        """'clm provider add --type ollama' handles connection failure."""
        import requests

        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            with patch(
                "clawrium.core.providers.storage.requests.get",
                side_effect=requests.exceptions.ConnectionError(),
            ):
                result = runner.invoke(
                    app,
                    [
                        "provider",
                        "add",
                        "local-llm",
                        "--type",
                        "ollama",
                        "--url",
                        "http://ollama.example.com:11434",
                    ],
                )

        assert result.exit_code == 1
        assert "could not connect" in result.output.lower()


class TestProviderEdit:
    """Tests for 'clm provider edit' command."""

    def test_edit_not_found(self, isolated_config):
        """'clm provider edit' fails for nonexistent provider."""
        result = runner.invoke(
            app, ["provider", "edit", "nonexistent", "--model", "gpt-4"]
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_edit_no_changes(self, isolated_config, sample_provider_data):
        """'clm provider edit' with no options shows warning."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(app, ["provider", "edit", "test-openai"])

        assert result.exit_code == 0
        assert "no changes" in result.output.lower()

    def test_edit_model(self, isolated_config, sample_provider_data):
        """'clm provider edit --model' updates model."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(
            app,
            ["provider", "edit", "test-openai", "--model", "gpt-4o-mini"],
        )

        assert result.exit_code == 0
        assert "updated successfully" in result.output.lower()

        # Verify update
        providers_path = isolated_config / PROVIDERS_FILE
        with open(providers_path) as f:
            providers = json.load(f)
        assert providers[0]["default_model"] == "gpt-4o-mini"

    def test_edit_url_non_ollama_fails(self, isolated_config, sample_provider_data):
        """'clm provider edit --url' fails for non-Ollama provider."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(
            app,
            ["provider", "edit", "test-openai", "--url", "http://example.com:11434"],
        )

        assert result.exit_code == 1
        assert "only valid for ollama" in result.output.lower()

    def test_edit_ollama_url_success(self, isolated_config, sample_ollama_provider):
        """'clm provider edit --url' updates Ollama endpoint."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_ollama_provider])

        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "models": [{"name": "llama3:latest"}, {"name": "phi3:latest"}]
            }
            mock_response.raise_for_status = MagicMock()

            with patch(
                "clawrium.core.providers.storage.requests.get", return_value=mock_response
            ):
                result = runner.invoke(
                    app,
                    [
                        "provider",
                        "edit",
                        "local-llm",
                        "--url",
                        "http://newserver.example.com:11434",
                    ],
                )

        assert result.exit_code == 0
        assert "updated successfully" in result.output.lower()

        # Verify endpoint was updated
        providers_path = isolated_config / PROVIDERS_FILE
        with open(providers_path) as f:
            providers = json.load(f)
        assert providers[0]["endpoint"] == "http://newserver.example.com:11434"

    def test_edit_ollama_url_connection_failure(
        self, isolated_config, sample_ollama_provider
    ):
        """'clm provider edit --url' handles connection failure."""
        import requests

        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_ollama_provider])

        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            with patch(
                "clawrium.core.providers.storage.requests.get",
                side_effect=requests.exceptions.ConnectionError(),
            ):
                result = runner.invoke(
                    app,
                    [
                        "provider",
                        "edit",
                        "local-llm",
                        "--url",
                        "http://newserver.example.com:11434",
                    ],
                )

        assert result.exit_code == 1
        assert "could not connect" in result.output.lower()

    def test_edit_update_key(self, isolated_config, sample_provider_data):
        """'clm provider edit --update-key' prompts for new API key."""
        from clawrium.core.providers import get_provider_api_key

        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(
            app,
            ["provider", "edit", "test-openai", "--update-key"],
            input="sk-new-key\n",
        )

        assert result.exit_code == 0
        assert "updated" in result.output.lower()
        # Verify the secret was actually persisted
        assert get_provider_api_key("test-openai") == "sk-new-key"


class TestProviderRemove:
    """Tests for 'clm provider remove' command."""

    def test_remove_not_found(self, isolated_config):
        """'clm provider remove' fails for nonexistent provider."""
        result = runner.invoke(app, ["provider", "remove", "nonexistent", "--force"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_remove_with_confirmation(self, isolated_config, sample_provider_data):
        """'clm provider remove' prompts for confirmation."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        # Decline confirmation
        result = runner.invoke(app, ["provider", "remove", "test-openai"], input="n\n")

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()

        # Provider should still exist
        providers_path = isolated_config / PROVIDERS_FILE
        with open(providers_path) as f:
            providers = json.load(f)
        assert len(providers) == 1

    def test_remove_with_force(self, isolated_config, sample_provider_data):
        """'clm provider remove --force' removes without confirmation."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(app, ["provider", "remove", "test-openai", "--force"])

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()

        # Provider should be gone
        providers_path = isolated_config / PROVIDERS_FILE
        with open(providers_path) as f:
            providers = json.load(f)
        assert len(providers) == 0


class TestProviderRefresh:
    """Tests for 'clm provider refresh' command."""

    def test_refresh_not_found(self, isolated_config):
        """'clm provider refresh' fails for nonexistent provider."""
        result = runner.invoke(app, ["provider", "refresh", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_refresh_non_ollama(self, isolated_config, sample_provider_data):
        """'clm provider refresh' warns for non-Ollama provider."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(app, ["provider", "refresh", "test-openai"])

        # S3 fix: exits 0 for wrong provider type (not an actual failure)
        assert result.exit_code == 0
        assert "ollama" in result.output.lower()

    def test_refresh_ollama_success(self, isolated_config, sample_ollama_provider):
        """'clm provider refresh' updates Ollama models."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_ollama_provider])

        # Mock new models from server
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:latest"},
                {"name": "mistral:latest"},
                {"name": "phi3:latest"},  # New model
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("clawrium.core.providers.storage.requests.get", return_value=mock_response):
            result = runner.invoke(app, ["provider", "refresh", "local-llm"])

        assert result.exit_code == 0
        assert "updated" in result.output.lower()
        assert "phi3:latest" in result.output

        # Verify models were updated
        providers_path = isolated_config / PROVIDERS_FILE
        with open(providers_path) as f:
            providers = json.load(f)
        assert "phi3:latest" in providers[0]["available_models"]

    def test_refresh_ollama_connection_failure(
        self, isolated_config, sample_ollama_provider
    ):
        """'clm provider refresh' handles connection failure."""
        import requests

        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_ollama_provider])

        with patch(
            "clawrium.core.providers.storage.requests.get",
            side_effect=requests.exceptions.ConnectionError(),
        ):
            result = runner.invoke(app, ["provider", "refresh", "local-llm"])

        assert result.exit_code == 1
        assert "could not connect" in result.output.lower()

    def test_refresh_ollama_missing_endpoint(self, isolated_config):
        """'clm provider refresh' handles missing endpoint."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        # Provider without endpoint field
        provider_no_endpoint = {
            "name": "broken-ollama",
            "type": "ollama",
            "default_model": "llama3:latest",
            "available_models": [],
        }
        save_providers([provider_no_endpoint])

        result = runner.invoke(app, ["provider", "refresh", "broken-ollama"])

        assert result.exit_code == 1
        assert "no endpoint" in result.output.lower()


class TestProviderBedrock:
    """Tests for Bedrock provider with AWS credentials."""

    def test_add_bedrock_prompts_for_aws_credentials(self, isolated_config):
        """'clm provider add --type bedrock' prompts for AWS Access Key and Secret Key."""
        result = runner.invoke(
            app,
            [
                "provider",
                "add",
                "my-bedrock",
                "--type",
                "bedrock",
                "--model",
                "anthropic.claude-sonnet-4-20250514-v1:0",
            ],
            input="AKIAIOSFODNN7EXAMPLE\nwJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
        )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()
        assert "aws access key" in result.output.lower()
        assert "aws secret access key" in result.output.lower()

        # Verify provider was created
        providers_path = isolated_config / PROVIDERS_FILE
        assert providers_path.exists()

        with open(providers_path) as f:
            providers = json.load(f)

        assert len(providers) == 1
        assert providers[0]["name"] == "my-bedrock"
        assert providers[0]["type"] == "bedrock"
        assert (
            providers[0]["default_model"] == "anthropic.claude-sonnet-4-20250514-v1:0"
        )
        # AWS credentials should NOT be in providers.json (stored in secrets)
        assert "access_key" not in providers[0]
        assert "secret_key" not in providers[0]

    def test_add_bedrock_requires_access_key(self, isolated_config):
        """'clm provider add --type bedrock' requires AWS Access Key."""
        result = runner.invoke(
            app,
            ["provider", "add", "my-bedrock", "--type", "bedrock"],
            input="\ntest-secret\n",  # Empty access key
        )

        assert result.exit_code == 1
        assert "access key" in result.output.lower()

    def test_add_bedrock_requires_secret_key(self, isolated_config):
        """'clm provider add --type bedrock' requires AWS Secret Key."""
        result = runner.invoke(
            app,
            ["provider", "add", "my-bedrock", "--type", "bedrock"],
            input="AKIAIOSFODNN7EXAMPLE\n\n",  # Empty secret key
        )

        assert result.exit_code == 1
        assert "secret key" in result.output.lower()

    def test_add_bedrock_empty_access_key_guard(self, isolated_config):
        """Test application guard against empty access key (mocked prompt)."""
        # This tests the app guard, not Typer's abort behavior
        with patch(
            "clawrium.cli.provider.typer.prompt",
            side_effect=["", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"],
        ):
            result = runner.invoke(
                app,
                ["provider", "add", "my-bedrock", "--type", "bedrock"],
            )

        assert result.exit_code == 1
        assert "access key" in result.output.lower()
        assert "required" in result.output.lower()

    def test_add_bedrock_empty_secret_key_guard(self, isolated_config):
        """Test application guard against empty secret key (mocked prompt)."""
        # This tests the app guard, not Typer's abort behavior
        with patch(
            "clawrium.cli.provider.typer.prompt",
            side_effect=["AKIAIOSFODNN7EXAMPLE", ""],
        ):
            result = runner.invoke(
                app,
                ["provider", "add", "my-bedrock", "--type", "bedrock"],
            )

        assert result.exit_code == 1
        assert "secret key" in result.output.lower()
        assert "required" in result.output.lower()

    def test_edit_bedrock_update_key(self, isolated_config):
        """'clm provider edit --update-key' prompts for AWS credentials for Bedrock."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        bedrock_provider = {
            "name": "my-bedrock",
            "type": "bedrock",
            "default_model": "anthropic.claude-sonnet-4-20250514-v1:0",
            "created_at": "2026-04-01T00:00:00+00:00",
            "updated_at": "2026-04-01T00:00:00+00:00",
        }
        save_providers([bedrock_provider])

        result = runner.invoke(
            app,
            ["provider", "edit", "my-bedrock", "--update-key"],
            input="AKIANEWKEY123456\nnewsecretkey123\n",
        )

        assert result.exit_code == 0
        assert "aws credentials updated" in result.output.lower()
        assert "new aws access key" in result.output.lower()
        assert "new aws secret access key" in result.output.lower()

    def test_edit_bedrock_update_key_empty_secret_aborts(self, isolated_config):
        """'clm provider edit --update-key' aborts when secret key is empty."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        bedrock_provider = {
            "name": "my-bedrock",
            "type": "bedrock",
            "default_model": "anthropic.claude-sonnet-4-20250514-v1:0",
            "created_at": "2026-04-01T00:00:00+00:00",
            "updated_at": "2026-04-01T00:00:00+00:00",
        }
        save_providers([bedrock_provider])

        # Typer's hidden prompt aborts on empty input
        result = runner.invoke(
            app,
            ["provider", "edit", "my-bedrock", "--update-key"],
            input="AKIANEWKEY123456\n\n",  # Empty secret key causes Typer abort
        )

        # Hidden prompts abort on empty input, resulting in exit code 1
        assert result.exit_code == 1

    def test_list_bedrock_shows_masked_access_key(self, isolated_config):
        """'clm provider list' shows masked AWS Access Key for Bedrock."""
        from clawrium.core.providers import set_provider_aws_credentials

        isolated_config.mkdir(parents=True, exist_ok=True)
        bedrock_provider = {
            "name": "my-bedrock",
            "type": "bedrock",
            "default_model": "anthropic.claude-sonnet-4-20250514-v1:0",
            "created_at": "2026-04-01T00:00:00+00:00",
            "updated_at": "2026-04-01T00:00:00+00:00",
        }
        save_providers([bedrock_provider])
        set_provider_aws_credentials(
            "my-bedrock",
            "AKIAIOSFODNN7EXAMPLE",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )

        result = runner.invoke(app, ["provider", "list"])

        assert result.exit_code == 0
        assert "my-bedrock" in result.output
        assert "bedrock" in result.output
        # Should show masked access key (first 4 ... last 4)
        assert "AKIA" in result.output
        assert "MPLE" in result.output

    def test_remove_bedrock_cleans_up_credentials(self, isolated_config):
        """'clm provider remove' cleans up AWS credentials for Bedrock."""
        from clawrium.core.providers import (
            set_provider_aws_credentials,
            get_provider_aws_credentials,
        )

        isolated_config.mkdir(parents=True, exist_ok=True)
        bedrock_provider = {
            "name": "my-bedrock",
            "type": "bedrock",
            "default_model": "anthropic.claude-sonnet-4-20250514-v1:0",
            "created_at": "2026-04-01T00:00:00+00:00",
            "updated_at": "2026-04-01T00:00:00+00:00",
        }
        save_providers([bedrock_provider])
        set_provider_aws_credentials(
            "my-bedrock",
            "AKIAIOSFODNN7EXAMPLE",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )

        # Verify credentials exist
        access_key, secret_key = get_provider_aws_credentials("my-bedrock")
        assert access_key is not None
        assert secret_key is not None

        result = runner.invoke(app, ["provider", "remove", "my-bedrock", "--force"])

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()

        # Verify credentials were cleaned up
        access_key, secret_key = get_provider_aws_credentials("my-bedrock")
        assert access_key is None
        assert secret_key is None

    def test_edit_bedrock_partial_credentials_fails(self, isolated_config):
        """'clm provider edit --update-key' fails when only access key provided."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        bedrock_provider = {
            "name": "my-bedrock",
            "type": "bedrock",
            "default_model": "anthropic.claude-sonnet-4-20250514-v1:0",
            "created_at": "2026-04-01T00:00:00+00:00",
            "updated_at": "2026-04-01T00:00:00+00:00",
        }
        save_providers([bedrock_provider])

        # Mock typer.prompt to return access key but empty secret key
        # This tests the application guard (not Typer's abort behavior)
        with patch(
            "clawrium.cli.provider.typer.prompt",
            side_effect=["AKIANEWKEY123456", ""],
        ):
            result = runner.invoke(
                app,
                ["provider", "edit", "my-bedrock", "--update-key"],
            )

        assert result.exit_code == 1
        assert "both" in result.output.lower()
        assert "required" in result.output.lower()

    def test_add_bedrock_regional_model_accepted(self, isolated_config):
        """'clm provider add --type bedrock' accepts regional model variants from catalog."""
        # Regional models like us.anthropic.* exist in models.json but not in
        # the old hardcoded PROVIDER_MODELS list. After fixing issue #266,
        # these should be accepted without --force flag.
        # Mock get_model_ids_for_provider to verify the new code path is used
        with patch(
            "clawrium.cli.provider.get_model_ids_for_provider"
        ) as mock_get_models:
            mock_get_models.return_value = [
                "anthropic.claude-opus-4-20250514-v1:0",
                "us.anthropic.claude-opus-4-20250514-v1:0",
                "eu.anthropic.claude-opus-4-20250514-v1:0",
            ]

            result = runner.invoke(
                app,
                [
                    "provider",
                    "add",
                    "regional-bedrock",
                    "--type",
                    "bedrock",
                    "--model",
                    "us.anthropic.claude-opus-4-20250514-v1:0",
                ],
                input="AKIAIOSFODNN7EXAMPLE\nwJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
            )

            # Verify get_model_ids_for_provider was called with 'bedrock'
            mock_get_models.assert_called_with("bedrock")

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()

        # Verify provider was created with the regional model
        providers_path = isolated_config / PROVIDERS_FILE
        assert providers_path.exists()

        with open(providers_path) as f:
            providers = json.load(f)

        assert len(providers) == 1
        assert providers[0]["name"] == "regional-bedrock"
        assert providers[0]["type"] == "bedrock"
        assert providers[0]["default_model"] == "us.anthropic.claude-opus-4-20250514-v1:0"


class TestProviderTypesModelsMetadata:
    """Tests for 'clm provider types <type> models' with metadata display."""

    def test_types_models_shows_metadata_columns(self, isolated_config):
        """'clm provider types openai models' shows metadata (name, lab, context)."""
        result = runner.invoke(app, ["provider", "types", "openai", "models"])

        assert result.exit_code == 0
        # Should show model count in header
        assert "models" in result.output.lower()
        # Should show model ID
        assert "gpt-4o" in result.output
        # Should show model name (not just ID)
        assert "GPT-4o" in result.output
        # Should show context window formatted with K suffix
        assert "128K" in result.output
        # Should show lab
        assert "OpenAI" in result.output

    def test_types_models_shows_lab_column(self, isolated_config):
        """'clm provider types openai models' shows lab in output."""
        result = runner.invoke(app, ["provider", "types", "openai", "models"])

        assert result.exit_code == 0
        # OpenAI provider should show OpenAI lab
        assert "OpenAI" in result.output
        # Verify lab appears multiple times (in table rows)
        assert result.output.count("OpenAI") > 1

    def test_types_models_openrouter_groups_by_lab(self, isolated_config):
        """'clm provider types openrouter models' groups models by lab."""
        result = runner.invoke(app, ["provider", "types", "openrouter", "models"])

        assert result.exit_code == 0
        # Should show lab count
        assert "labs" in result.output.lower()
        # Should show lab headers for multi-lab provider
        assert "Anthropic" in result.output
        assert "OpenAI" in result.output or "Openai" in result.output

    def test_types_models_format_context_window_k(self, isolated_config):
        """Context windows are formatted with K suffix (e.g., 128K)."""
        result = runner.invoke(app, ["provider", "types", "anthropic", "models"])

        assert result.exit_code == 0
        # Anthropic models have 200K context
        assert "200K" in result.output

    def test_types_models_format_context_window_m(self, isolated_config):
        """Context windows >= 1M are formatted with M suffix."""
        result = runner.invoke(app, ["provider", "types", "openai", "models"])

        assert result.exit_code == 0
        # GPT-4.1 has 1M+ context
        assert "1M" in result.output


class TestInteractiveModelSelection:
    """Tests for interactive model selection with fuzzy search."""

    def test_add_provider_uses_interactive_selection(self, isolated_config):
        """'clm provider add' uses interactive model selection."""
        # Input: API key, then "1" to select first model
        result = runner.invoke(
            app,
            ["provider", "add", "myanthropic", "--type", "anthropic"],
            input="sk-test\n1\n",
        )

        assert result.exit_code == 0
        # Should show model selection prompt with metadata
        assert "Select a model" in result.output or "available" in result.output.lower()
        assert "added successfully" in result.output.lower()

    def test_add_with_model_flag_skips_selection(self, isolated_config):
        """'clm provider add --model' skips interactive selection."""
        result = runner.invoke(
            app,
            [
                "provider",
                "add",
                "myopenai2",
                "--type",
                "openai",
                "--model",
                "gpt-4o",
            ],
            input="sk-test\n",
        )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()
        # Should not show model selection
        assert "Select a model" not in result.output

    def test_interactive_selection_shows_model_info(self, isolated_config):
        """Interactive selection shows model name, lab, and context."""
        result = runner.invoke(
            app,
            ["provider", "add", "mytest", "--type", "anthropic"],
            input="sk-test\n1\n",
        )

        assert result.exit_code == 0
        # Should show model info in selection list
        output_lower = result.output.lower()
        assert "claude" in output_lower or "anthropic" in output_lower

    def test_interactive_selection_exact_model_id(self, isolated_config):
        """User can enter exact model ID to select directly."""
        result = runner.invoke(
            app,
            ["provider", "add", "mytest2", "--type", "openai"],
            input="sk-test\ngpt-4o\n",
        )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()

        # Verify the correct model was selected
        providers_path = isolated_config / PROVIDERS_FILE
        with open(providers_path) as f:
            providers = json.load(f)
        assert providers[0]["default_model"] == "gpt-4o"

    def test_interactive_selection_fuzzy_search(self, isolated_config):
        """User can search by typing partial model name."""
        # Type "gpt" to search, then select first match
        result = runner.invoke(
            app,
            ["provider", "add", "mytest3", "--type", "openai"],
            input="sk-test\ngpt\n1\n",
        )

        assert result.exit_code == 0
        # Should show matches for "gpt"
        assert "Matches for" in result.output or "gpt" in result.output.lower()
        assert "added successfully" in result.output.lower()


class TestProviderModelValidation:
    """Tests for model validation with --model flag."""

    def test_add_invalid_model_returns_error(self, isolated_config):
        """'clm provider add --model invalid' returns error, not warning."""
        result = runner.invoke(
            app,
            ["provider", "add", "test", "--type", "openai", "--model", "gpt-4-invalid"],
            input="sk-test\n",
        )

        assert result.exit_code == 1
        assert "error" in result.output.lower()
        assert "gpt-4-invalid" in result.output

    def test_add_invalid_model_shows_suggestion(self, isolated_config):
        """'clm provider add --model invalid' shows 'Did you mean...' suggestion."""
        # Use 'gpt4o' (missing hyphen) which fuzzy matches to 'gpt-4o'
        result = runner.invoke(
            app,
            ["provider", "add", "test", "--type", "openai", "--model", "gpt4o"],
            input="sk-test\n",
        )

        assert result.exit_code == 1
        assert "did you mean" in result.output.lower()
        assert "gpt-4o" in result.output

    def test_add_valid_model_succeeds(self, isolated_config):
        """'clm provider add --model valid' succeeds."""
        result = runner.invoke(
            app,
            ["provider", "add", "test", "--type", "openai", "--model", "gpt-4o"],
            input="sk-test\n",
        )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()

    def test_add_force_bypasses_validation(self, isolated_config):
        """'clm provider add --model invalid --force' bypasses validation."""
        result = runner.invoke(
            app,
            [
                "provider",
                "add",
                "test",
                "--type",
                "openai",
                "--model",
                "custom-model",
                "--force",
            ],
            input="sk-test\n",
        )

        assert result.exit_code == 0
        assert "warning" in result.output.lower()
        assert "added successfully" in result.output.lower()

    def test_add_force_flag_short_form(self, isolated_config):
        """'-f' short form works for --force flag."""
        result = runner.invoke(
            app,
            [
                "provider",
                "add",
                "test",
                "--type",
                "openai",
                "--model",
                "my-custom",
                "-f",
            ],
            input="sk-test\n",
        )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()

    def test_add_invalid_model_shows_force_hint(self, isolated_config):
        """Error message shows hint about --force flag."""
        result = runner.invoke(
            app,
            ["provider", "add", "test", "--type", "openai", "--model", "invalid-model"],
            input="sk-test\n",
        )

        assert result.exit_code == 1
        assert "--force" in result.output


class TestProviderCatalogLoadError:
    """Tests for CatalogLoadError handling in provider commands."""

    def test_add_bedrock_catalog_unavailable_without_force(self, isolated_config):
        """'clm provider add --type bedrock' exits with error when catalog unavailable."""
        from clawrium.core.providers import CatalogLoadError

        with patch(
            "clawrium.cli.provider.get_model_ids_for_provider"
        ) as mock_get_models:
            mock_get_models.side_effect = CatalogLoadError("Test catalog load failure")

            result = runner.invoke(
                app,
                [
                    "provider",
                    "add",
                    "test-bedrock",
                    "--type",
                    "bedrock",
                    "--model",
                    "anthropic.claude-opus-4-20250514-v1:0",
                ],
                input="AKIAIOSFODNN7EXAMPLE\nwJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
            )

            assert result.exit_code == 1
            assert "model catalog unavailable" in result.output.lower()
            assert "--force" in result.output

    def test_add_bedrock_catalog_unavailable_with_force(self, isolated_config):
        """'clm provider add --type bedrock --force' succeeds when catalog unavailable."""
        from clawrium.core.providers import CatalogLoadError

        with patch(
            "clawrium.cli.provider.get_model_ids_for_provider"
        ) as mock_get_models:
            mock_get_models.side_effect = CatalogLoadError("Test catalog load failure")

            result = runner.invoke(
                app,
                [
                    "provider",
                    "add",
                    "test-bedrock",
                    "--type",
                    "bedrock",
                    "--model",
                    "anthropic.claude-opus-4-20250514-v1:0",
                    "--force",
                ],
                input="AKIAIOSFODNN7EXAMPLE\nwJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
            )

            assert result.exit_code == 0
            assert "added successfully" in result.output.lower()

            # Verify provider was created with model despite catalog failure
            providers_path = isolated_config / PROVIDERS_FILE
            assert providers_path.exists()

            with open(providers_path) as f:
                providers = json.load(f)

            assert len(providers) == 1
            assert providers[0]["name"] == "test-bedrock"
            assert (
                providers[0]["default_model"] == "anthropic.claude-opus-4-20250514-v1:0"
            )

    def test_types_models_catalog_unavailable(self, isolated_config):
        """'clm provider types <type> models' shows error when catalog unavailable."""
        from clawrium.core.providers import CatalogLoadError

        with patch(
            "clawrium.cli.provider.get_models_for_provider"
        ) as mock_get_models:
            mock_get_models.side_effect = CatalogLoadError("Test catalog load failure")

            result = runner.invoke(app, ["provider", "types", "bedrock", "models"])

            assert result.exit_code == 0  # Graceful degradation, not hard failure
            assert "model catalog unavailable" in result.output.lower()


class TestGetModelSuggestion:
    """Tests for _get_model_suggestion() private function."""

    def test_get_model_suggestion_catalog_load_error_returns_none(self, isolated_config):
        """_get_model_suggestion returns None when CatalogLoadError is raised."""
        from clawrium.cli.provider import _get_model_suggestion
        from clawrium.core.providers import CatalogLoadError

        with patch("clawrium.cli.provider.search_models") as mock_search:
            mock_search.side_effect = CatalogLoadError("Test catalog load failure")

            result = _get_model_suggestion("invalid-model", "openai")

            assert result is None
            mock_search.assert_called_once()

    def test_get_model_suggestion_provider_not_found_returns_none(self, isolated_config):
        """_get_model_suggestion returns None when ProviderNotFoundError is raised."""
        from clawrium.cli.provider import _get_model_suggestion
        from clawrium.core.providers import ProviderNotFoundError

        with patch("clawrium.cli.provider.search_models") as mock_search:
            mock_search.side_effect = ProviderNotFoundError("unknown-provider")

            result = _get_model_suggestion("any-model", "unknown-provider")

            assert result is None
            mock_search.assert_called_once()

    def test_get_model_suggestion_valid_returns_match(self, isolated_config):
        """_get_model_suggestion returns matching model ID when found."""
        from clawrium.cli.provider import _get_model_suggestion

        with patch("clawrium.cli.provider.search_models") as mock_search:
            mock_search.return_value = [{"id": "gpt-4o", "name": "GPT-4o"}]

            result = _get_model_suggestion("gpt-4", "openai")

            assert result == "gpt-4o"
            mock_search.assert_called_once_with("gpt-4", provider_type="openai", limit=1)

    def test_get_model_suggestion_no_match_returns_none(self, isolated_config):
        """_get_model_suggestion returns None when no matches found."""
        from clawrium.cli.provider import _get_model_suggestion

        with patch("clawrium.cli.provider.search_models") as mock_search:
            mock_search.return_value = []

            result = _get_model_suggestion("completely-invalid", "openai")

            assert result is None

    def test_get_model_suggestion_none_response_returns_none(self, isolated_config):
        """_get_model_suggestion returns None when search_models returns None."""
        from clawrium.cli.provider import _get_model_suggestion

        with patch("clawrium.cli.provider.search_models") as mock_search:
            mock_search.return_value = None

            result = _get_model_suggestion("any-model", "openai")

            assert result is None

    def test_get_model_suggestion_multi_match_returns_first(self, isolated_config):
        """_get_model_suggestion returns first match when multiple found."""
        from clawrium.cli.provider import _get_model_suggestion

        with patch("clawrium.cli.provider.search_models") as mock_search:
            mock_search.return_value = [
                {"id": "gpt-4o", "name": "GPT-4o"},
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            ]

            result = _get_model_suggestion("gpt-4", "openai")

            assert result == "gpt-4o"

    def test_get_model_suggestion_exception_not_propagated(self, isolated_config):
        """_get_model_suggestion catches exceptions without re-raising."""
        from clawrium.cli.provider import _get_model_suggestion
        from clawrium.core.providers import CatalogLoadError

        with patch("clawrium.cli.provider.search_models") as mock_search:
            mock_search.side_effect = CatalogLoadError("Test error")

            # Should not raise - exception is caught
            result = _get_model_suggestion("any-model", "openai")

            assert result is None
            mock_search.assert_called_once()


class TestInteractiveModelSelectionErrorPaths:
    """Tests for _interactive_model_selection() error handling."""

    def test_interactive_model_selection_catalog_load_error_returns_none(
        self, isolated_config
    ):
        """_interactive_model_selection returns None when CatalogLoadError is raised."""
        from clawrium.cli.provider import _interactive_model_selection
        from clawrium.core.providers import CatalogLoadError

        with patch("clawrium.cli.provider.get_models_for_provider") as mock_get:
            mock_get.side_effect = CatalogLoadError("Test catalog load failure")

            result = _interactive_model_selection("bedrock")

            assert result is None
            mock_get.assert_called_once_with("bedrock")

    def test_interactive_model_selection_provider_not_found_returns_none(
        self, isolated_config
    ):
        """_interactive_model_selection returns None when ProviderNotFoundError is raised."""
        from clawrium.cli.provider import _interactive_model_selection
        from clawrium.core.providers import ProviderNotFoundError

        with patch("clawrium.cli.provider.get_models_for_provider") as mock_get:
            mock_get.side_effect = ProviderNotFoundError("unknown-provider")

            result = _interactive_model_selection("unknown-provider")

            assert result is None

    def test_interactive_model_selection_empty_models_returns_none(self, isolated_config):
        """_interactive_model_selection returns None when models list is empty."""
        from clawrium.cli.provider import _interactive_model_selection

        with patch("clawrium.cli.provider.get_models_for_provider") as mock_get:
            mock_get.return_value = []

            result = _interactive_model_selection("openai")

            assert result is None

    def test_interactive_model_selection_none_response_returns_none(self, isolated_config):
        """_interactive_model_selection returns None when get_models_for_provider returns None."""
        from clawrium.cli.provider import _interactive_model_selection

        with patch("clawrium.cli.provider.get_models_for_provider") as mock_get:
            mock_get.return_value = None

            result = _interactive_model_selection("openai")

            assert result is None

    def test_interactive_model_selection_exception_not_propagated(self, isolated_config):
        """_interactive_model_selection catches exceptions without re-raising."""
        from clawrium.cli.provider import _interactive_model_selection
        from clawrium.core.providers import CatalogLoadError

        with patch("clawrium.cli.provider.get_models_for_provider") as mock_get:
            mock_get.side_effect = CatalogLoadError("Test error")

            # Should not raise - exception is caught
            result = _interactive_model_selection("bedrock")

            assert result is None
            mock_get.assert_called_once()

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


class TestProviderModels:
    """Tests for 'clm provider models' command."""

    def test_models_by_type(self, isolated_config):
        """'clm provider models openai' lists OpenAI models."""
        result = runner.invoke(app, ["provider", "models", "openai"])

        assert result.exit_code == 0
        assert "gpt-4o" in result.output
        assert "gpt-4o-mini" in result.output

    def test_models_ollama_type_shows_message(self, isolated_config):
        """'clm provider models ollama' shows dynamic discovery message."""
        result = runner.invoke(app, ["provider", "models", "ollama"])

        assert result.exit_code == 0
        assert "dynamically" in result.output.lower()

    def test_models_by_provider_name(self, isolated_config, sample_provider_data):
        """'clm provider models <name>' shows models for configured provider."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_provider_data])

        result = runner.invoke(app, ["provider", "models", "test-openai"])

        assert result.exit_code == 0
        assert "gpt-4o" in result.output

    def test_models_ollama_provider_shows_available(
        self, isolated_config, sample_ollama_provider
    ):
        """'clm provider models <ollama-name>' shows cached models."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([sample_ollama_provider])

        result = runner.invoke(app, ["provider", "models", "local-llm"])

        assert result.exit_code == 0
        assert "llama3:latest" in result.output
        assert "mistral:latest" in result.output

    def test_models_invalid_identifier(self, isolated_config):
        """'clm provider models <invalid>' shows error."""
        result = runner.invoke(app, ["provider", "models", "nonexistent"])

        assert result.exit_code == 1
        assert "not a valid provider type" in result.output.lower()


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
        with patch("clawrium.core.providers.socket.getaddrinfo") as mock_gai:
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
        with patch("clawrium.core.providers.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            # Mock the Ollama server connection
            mock_response = MagicMock()
            mock_response.json.return_value = {"models": [{"name": "llama3:latest"}]}
            mock_response.raise_for_status = MagicMock()

            with patch(
                "clawrium.core.providers.requests.get", return_value=mock_response
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
        with patch("clawrium.core.providers.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            mock_response = MagicMock()
            mock_response.json.return_value = {"models": []}
            mock_response.raise_for_status = MagicMock()

            with patch(
                "clawrium.core.providers.requests.get", return_value=mock_response
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

        with patch("clawrium.core.providers.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            with patch(
                "clawrium.core.providers.requests.get",
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

        with patch("clawrium.core.providers.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "models": [{"name": "llama3:latest"}, {"name": "phi3:latest"}]
            }
            mock_response.raise_for_status = MagicMock()

            with patch(
                "clawrium.core.providers.requests.get", return_value=mock_response
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

        with patch("clawrium.core.providers.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]

            with patch(
                "clawrium.core.providers.requests.get",
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

        with patch("clawrium.core.providers.requests.get", return_value=mock_response):
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
            "clawrium.core.providers.requests.get",
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

"""Tests for provider storage module."""

import json
import pytest
from unittest.mock import MagicMock, patch

from clawrium.core.providers import (
    PROVIDERS_FILE,
    PROVIDER_MODELS,
    load_providers,
    save_providers,
    add_provider,
    get_provider,
    update_provider,
    remove_provider,
    validate_provider_name,
    validate_provider_type,
    validate_ollama_url,
    get_models_for_type,
    fetch_ollama_models,
    get_provider_instance_key,
    set_provider_api_key,
    get_provider_api_key,
    remove_provider_api_key,
    set_provider_aws_credentials,
    get_provider_aws_credentials,
    remove_provider_aws_credentials,
    ProvidersFileCorruptedError,
    DuplicateProviderError,
    InvalidProviderNameError,
    InvalidProviderTypeError,
    OllamaConnectionError,
    InvalidOllamaUrlError,
)


class TestValidation:
    """Tests for validation functions."""

    def test_validate_provider_name_valid(self):
        """validate_provider_name accepts valid names."""
        valid_names = [
            "myopenai",
            "my-openai",
            "my_openai",
            "MyOpenAI",
            "a",
            "A1",
            "provider123",
            "a" * 64,  # Max length
        ]
        for name in valid_names:
            try:
                validate_provider_name(name)  # Should not raise
            except InvalidProviderNameError:
                pytest.fail(
                    f"'{name}' should be valid but raised InvalidProviderNameError"
                )

    def test_validate_provider_name_invalid(self):
        """validate_provider_name rejects invalid names."""
        invalid_names = [
            "",  # Empty
            "1provider",  # Starts with number
            "-provider",  # Starts with hyphen
            "_provider",  # Starts with underscore
            "my provider",  # Contains space
            "my.provider",  # Contains dot
            "my/provider",  # Contains slash
            "../path",  # Path traversal attempt
            "a" * 65,  # Too long
        ]
        for name in invalid_names:
            with pytest.raises(InvalidProviderNameError):
                validate_provider_name(name)

    def test_validate_provider_name_none(self):
        """validate_provider_name raises for None input."""
        with pytest.raises(InvalidProviderNameError) as exc_info:
            validate_provider_name(None)
        assert "must be a string" in str(exc_info.value).lower()

    def test_validate_provider_name_non_string(self):
        """validate_provider_name raises for non-string input."""
        with pytest.raises(InvalidProviderNameError):
            validate_provider_name(123)

    def test_validate_provider_type_valid(self):
        """validate_provider_type accepts all valid types."""
        for provider_type in PROVIDER_MODELS.keys():
            validate_provider_type(provider_type)  # Should not raise

    def test_validate_provider_type_invalid(self):
        """validate_provider_type rejects unknown types."""
        with pytest.raises(InvalidProviderTypeError) as exc_info:
            validate_provider_type("unknown-provider")
        assert "invalid provider type" in str(exc_info.value).lower()

    def test_get_models_for_type_returns_models(self):
        """get_models_for_type returns model list for valid types."""
        models = get_models_for_type("openai")
        assert isinstance(models, list)
        assert "gpt-4o" in models

    def test_get_models_for_type_ollama_returns_none(self):
        """get_models_for_type returns None for Ollama (dynamic discovery)."""
        models = get_models_for_type("ollama")
        assert models is None

    def test_get_models_for_type_invalid_raises(self):
        """get_models_for_type raises for invalid type."""
        with pytest.raises(InvalidProviderTypeError):
            get_models_for_type("invalid")


class TestOllamaUrlValidation:
    """Tests for Ollama URL validation (SSRF prevention)."""

    def test_validate_ollama_url_valid_http(self):
        """validate_ollama_url accepts valid http URLs."""
        # Mock socket.getaddrinfo to return public IP
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 0, "", ("93.184.216.34", 0))  # example.com IP
            ]
            url = validate_ollama_url("http://example.com:11434")
            assert url == "http://example.com:11434"

    def test_validate_ollama_url_valid_https(self):
        """validate_ollama_url accepts valid https URLs."""
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]
            url = validate_ollama_url("https://example.com:11434")
            assert url == "https://example.com:11434"

    def test_validate_ollama_url_strips_trailing_slash(self):
        """validate_ollama_url removes trailing slashes."""
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("93.184.216.34", 0))]
            url = validate_ollama_url("http://example.com:11434/")
            assert url == "http://example.com:11434"

    def test_validate_ollama_url_rejects_ftp(self):
        """validate_ollama_url rejects ftp scheme."""
        with pytest.raises(InvalidOllamaUrlError) as exc_info:
            validate_ollama_url("ftp://example.com")
        assert "only http and https" in str(exc_info.value).lower()

    def test_validate_ollama_url_rejects_file(self):
        """validate_ollama_url rejects file scheme."""
        with pytest.raises(InvalidOllamaUrlError) as exc_info:
            validate_ollama_url("file:///etc/passwd")
        assert "only http and https" in str(exc_info.value).lower()

    def test_validate_ollama_url_allows_private_ip(self):
        """validate_ollama_url allows private IP addresses (Ollama is self-hosted)."""
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("192.168.1.100", 0))]
            url = validate_ollama_url("http://myserver.local:11434")
            assert url == "http://myserver.local:11434"

    def test_validate_ollama_url_allows_lan_ip(self):
        """validate_ollama_url allows LAN IP addresses like 192.168.x.x."""
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("192.168.1.17", 0))]
            url = validate_ollama_url("http://192.168.1.17:11434")
            assert url == "http://192.168.1.17:11434"

    def test_validate_ollama_url_allows_loopback(self):
        """validate_ollama_url allows loopback addresses (Ollama is self-hosted)."""
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("127.0.0.1", 0))]
            url = validate_ollama_url("http://localhost:11434")
            assert url == "http://localhost:11434"

    def test_validate_ollama_url_rejects_metadata_endpoint(self):
        """validate_ollama_url rejects cloud metadata endpoints (169.254.x.x)."""
        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 0, "", ("169.254.169.254", 0))]
            with pytest.raises(InvalidOllamaUrlError) as exc_info:
                validate_ollama_url("http://169.254.169.254")
            assert "metadata" in str(exc_info.value).lower()

    def test_validate_ollama_url_allows_unresolvable_hostname(self):
        """validate_ollama_url allows hostnames that don't resolve (let requests handle)."""
        import socket as sock

        with patch("clawrium.core.providers.storage.socket.getaddrinfo") as mock_gai:
            mock_gai.side_effect = sock.gaierror("Name resolution failed")
            # Should not raise - let requests.get handle the error later
            url = validate_ollama_url("http://nonexistent.example.com:11434")
            assert url == "http://nonexistent.example.com:11434"


class TestOllamaDiscovery:
    """Tests for Ollama model discovery."""

    def test_fetch_ollama_models_success(self):
        """fetch_ollama_models returns model names on success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:latest", "size": 1234567890},
                {"name": "mistral:latest", "size": 987654321},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "clawrium.core.providers.storage.requests.get", return_value=mock_response
        ):
            models = fetch_ollama_models("http://example.com:11434")

        assert models == ["llama3:latest", "mistral:latest"]

    def test_fetch_ollama_models_empty(self):
        """fetch_ollama_models returns empty list when no models."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "clawrium.core.providers.storage.requests.get", return_value=mock_response
        ):
            models = fetch_ollama_models("http://example.com:11434")

        assert models == []

    def test_fetch_ollama_models_connection_error(self):
        """fetch_ollama_models raises OllamaConnectionError on connection failure."""
        import requests

        with patch(
            "clawrium.core.providers.storage.requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        ):
            with pytest.raises(OllamaConnectionError) as exc_info:
                fetch_ollama_models("http://example.com:11434")
            assert "could not connect" in str(exc_info.value).lower()

    def test_fetch_ollama_models_timeout(self):
        """fetch_ollama_models raises OllamaConnectionError on timeout."""
        import requests

        with patch(
            "clawrium.core.providers.storage.requests.get",
            side_effect=requests.exceptions.Timeout("Request timed out"),
        ):
            with pytest.raises(OllamaConnectionError) as exc_info:
                fetch_ollama_models("http://example.com:11434")
            assert "timed out" in str(exc_info.value).lower()

    def test_fetch_ollama_models_http_error(self):
        """fetch_ollama_models raises OllamaConnectionError on HTTP error."""
        import requests

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        with patch(
            "clawrium.core.providers.storage.requests.get", return_value=mock_response
        ):
            with pytest.raises(OllamaConnectionError) as exc_info:
                fetch_ollama_models("http://example.com:11434")
            assert "error" in str(exc_info.value).lower()

    def test_fetch_ollama_models_http_error_no_response(self):
        """fetch_ollama_models handles HTTPError with no response object."""
        import requests

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=None
        )

        with patch(
            "clawrium.core.providers.storage.requests.get", return_value=mock_response
        ):
            with pytest.raises(OllamaConnectionError) as exc_info:
                fetch_ollama_models("http://example.com:11434")
            assert "unknown" in str(exc_info.value).lower()

    def test_fetch_ollama_models_invalid_json(self):
        """fetch_ollama_models raises OllamaConnectionError on invalid JSON."""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("Invalid", "", 0)
        mock_response.raise_for_status = MagicMock()

        with patch(
            "clawrium.core.providers.storage.requests.get", return_value=mock_response
        ):
            with pytest.raises(OllamaConnectionError) as exc_info:
                fetch_ollama_models("http://example.com:11434")
            assert "invalid response" in str(exc_info.value).lower()

    def test_fetch_ollama_models_uses_allow_redirects_false(self):
        """fetch_ollama_models disables redirects for security."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "clawrium.core.providers.storage.requests.get", return_value=mock_response
        ) as mock_get:
            fetch_ollama_models("http://example.com:11434")
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs.get("allow_redirects") is False
            assert call_kwargs.get("verify") is True


class TestProviderApiKeyStorage:
    """Tests for secure API key storage."""

    def test_get_provider_instance_key(self):
        """get_provider_instance_key returns correct format."""
        key = get_provider_instance_key("myopenai")
        assert key == "provider:myopenai"

    def test_set_and_get_provider_api_key(self, isolated_config):
        """set_provider_api_key stores and get_provider_api_key retrieves."""
        set_provider_api_key("testprovider", "sk-test123")
        retrieved = get_provider_api_key("testprovider")
        assert retrieved == "sk-test123"

    def test_get_provider_api_key_not_found(self, isolated_config):
        """get_provider_api_key returns None when not found."""
        result = get_provider_api_key("nonexistent")
        assert result is None

    def test_remove_provider_api_key(self, isolated_config):
        """remove_provider_api_key removes stored key."""
        set_provider_api_key("testprovider", "sk-test123")
        assert get_provider_api_key("testprovider") == "sk-test123"

        result = remove_provider_api_key("testprovider")
        assert result is True
        assert get_provider_api_key("testprovider") is None

    def test_remove_provider_api_key_not_found(self, isolated_config):
        """remove_provider_api_key returns False when key doesn't exist."""
        result = remove_provider_api_key("nonexistent")
        assert result is False


class TestProviderAwsCredentialsStorage:
    """Tests for secure AWS credentials storage (Bedrock)."""

    def test_set_and_get_provider_aws_credentials(self, isolated_config):
        """set_provider_aws_credentials stores and get_provider_aws_credentials retrieves."""
        set_provider_aws_credentials(
            "my-bedrock",
            "AKIAIOSFODNN7EXAMPLE",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        access_key, secret_key = get_provider_aws_credentials("my-bedrock")
        assert access_key == "AKIAIOSFODNN7EXAMPLE"
        assert secret_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    def test_get_provider_aws_credentials_not_found(self, isolated_config):
        """get_provider_aws_credentials returns (None, None) when not found."""
        access_key, secret_key = get_provider_aws_credentials("nonexistent")
        assert access_key is None
        assert secret_key is None

    def test_get_provider_aws_credentials_partial(self, isolated_config):
        """get_provider_aws_credentials handles partial credentials."""
        from clawrium.core.secrets import set_instance_secret
        from clawrium.core.providers import get_provider_instance_key

        # Only set access key, not secret key
        instance_key = get_provider_instance_key("partial-bedrock")
        set_instance_secret(instance_key, "AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")

        access_key, secret_key = get_provider_aws_credentials("partial-bedrock")
        assert access_key == "AKIAIOSFODNN7EXAMPLE"
        assert secret_key is None

    def test_remove_provider_aws_credentials(self, isolated_config):
        """remove_provider_aws_credentials removes stored credentials."""
        set_provider_aws_credentials(
            "my-bedrock",
            "AKIAIOSFODNN7EXAMPLE",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        access_key, secret_key = get_provider_aws_credentials("my-bedrock")
        assert access_key is not None
        assert secret_key is not None

        result = remove_provider_aws_credentials("my-bedrock")
        assert result is True
        access_key, secret_key = get_provider_aws_credentials("my-bedrock")
        assert access_key is None
        assert secret_key is None

    def test_remove_provider_aws_credentials_not_found(self, isolated_config):
        """remove_provider_aws_credentials returns False when credentials don't exist."""
        result = remove_provider_aws_credentials("nonexistent")
        assert result is False

    def test_set_provider_aws_credentials_update(self, isolated_config):
        """set_provider_aws_credentials can update existing credentials."""
        set_provider_aws_credentials("my-bedrock", "AKIAOLD", "secretold")
        set_provider_aws_credentials("my-bedrock", "AKIANEW", "secretnew")

        access_key, secret_key = get_provider_aws_credentials("my-bedrock")
        assert access_key == "AKIANEW"
        assert secret_key == "secretnew"


class TestProviderStorage:
    """Tests for provider CRUD operations."""

    def test_load_providers_no_file(self, isolated_config):
        """load_providers returns empty list when file doesn't exist."""
        providers = load_providers()
        assert providers == []

    def test_load_providers_valid_json(self, isolated_config):
        """load_providers returns list of providers from valid JSON."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_path = isolated_config / PROVIDERS_FILE
        test_data = [
            {"name": "openai-1", "type": "openai"},
            {"name": "claude-1", "type": "anthropic"},
        ]
        providers_path.write_text(json.dumps(test_data))

        providers = load_providers()
        assert providers == test_data

    def test_load_providers_invalid_json(self, isolated_config):
        """load_providers raises ProvidersFileCorruptedError on invalid JSON."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_path = isolated_config / PROVIDERS_FILE
        providers_path.write_text("not valid json {{{")

        with pytest.raises(ProvidersFileCorruptedError) as exc_info:
            load_providers()
        assert "corrupted" in str(exc_info.value).lower()

    def test_load_providers_non_list_json(self, isolated_config):
        """load_providers raises ProvidersFileCorruptedError when JSON is not a list."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_path = isolated_config / PROVIDERS_FILE
        providers_path.write_text('{"key": "value"}')

        with pytest.raises(ProvidersFileCorruptedError) as exc_info:
            load_providers()
        assert "not a list" in str(exc_info.value).lower()

    def test_load_providers_list_with_non_dict_items(self, isolated_config):
        """load_providers raises ProvidersFileCorruptedError when list contains non-dicts."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_path = isolated_config / PROVIDERS_FILE
        providers_path.write_text('[1, 2, "string"]')

        with pytest.raises(ProvidersFileCorruptedError) as exc_info:
            load_providers()
        assert "invalid entries" in str(exc_info.value).lower()

    def test_save_providers_creates_file(self, isolated_config):
        """save_providers creates providers.json with correct content."""
        test_providers = [{"name": "test", "type": "openai"}]

        save_providers(test_providers)

        providers_path = isolated_config / PROVIDERS_FILE
        assert providers_path.exists()

        with open(providers_path) as f:
            saved_data = json.load(f)
        assert saved_data == test_providers

    def test_save_providers_creates_dir(self, tmp_path, monkeypatch):
        """save_providers creates config directory if it doesn't exist."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        config_dir = tmp_path / "clawrium"

        assert not config_dir.exists()

        test_providers = [{"name": "test", "type": "openai"}]
        save_providers(test_providers)

        assert config_dir.exists()
        assert (config_dir / PROVIDERS_FILE).exists()

    def test_save_providers_file_permissions(self, isolated_config):
        """save_providers creates file with 0600 permissions."""
        test_providers = [{"name": "test", "type": "openai"}]
        save_providers(test_providers)

        providers_path = isolated_config / PROVIDERS_FILE
        mode = providers_path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_add_provider_appends(self, isolated_config):
        """add_provider appends to existing providers."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        initial = [{"name": "existing", "type": "openai"}]
        save_providers(initial)

        new_provider = {"name": "newprovider", "type": "anthropic"}
        add_provider(new_provider)

        providers = load_providers()
        assert len(providers) == 2
        assert providers[0] == initial[0]
        assert providers[1] == new_provider

    def test_add_provider_duplicate_raises(self, isolated_config):
        """add_provider raises DuplicateProviderError when name exists."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        initial = [{"name": "existing", "type": "openai"}]
        save_providers(initial)

        duplicate = {"name": "existing", "type": "anthropic"}

        with pytest.raises(DuplicateProviderError) as exc_info:
            add_provider(duplicate)
        assert "already exists" in str(exc_info.value).lower()

    def test_add_provider_invalid_name_raises(self, isolated_config):
        """add_provider raises InvalidProviderNameError for invalid names."""
        provider = {"name": "1invalid", "type": "openai"}

        with pytest.raises(InvalidProviderNameError):
            add_provider(provider)

    def test_add_provider_missing_name_raises(self, isolated_config):
        """add_provider raises InvalidProviderNameError when name is missing."""
        provider = {"type": "openai"}

        with pytest.raises(InvalidProviderNameError):
            add_provider(provider)

    def test_get_provider_found(self, isolated_config):
        """get_provider returns provider when found."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        test_providers = [
            {"name": "provider1", "type": "openai"},
            {"name": "provider2", "type": "anthropic"},
        ]
        save_providers(test_providers)

        provider = get_provider("provider1")

        assert provider is not None
        assert provider["name"] == "provider1"
        assert provider["type"] == "openai"

    def test_get_provider_not_found(self, isolated_config):
        """get_provider returns None when not found."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        test_providers = [{"name": "existing", "type": "openai"}]
        save_providers(test_providers)

        provider = get_provider("nonexistent")

        assert provider is None

    def test_update_provider_success(self, isolated_config):
        """update_provider updates provider and returns True."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        initial = [{"name": "test", "type": "openai", "model": "gpt-4"}]
        save_providers(initial)

        def update_model(p):
            p["model"] = "gpt-4o"
            return p

        result = update_provider("test", update_model)

        assert result is True
        providers = load_providers()
        assert providers[0]["model"] == "gpt-4o"

    def test_update_provider_not_found(self, isolated_config):
        """update_provider returns False when provider not found."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([{"name": "existing", "type": "openai"}])

        def noop(p):
            return p

        result = update_provider("nonexistent", noop)

        assert result is False

    def test_remove_provider_success(self, isolated_config):
        """remove_provider removes provider and returns True."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        test_providers = [
            {"name": "provider1", "type": "openai"},
            {"name": "provider2", "type": "anthropic"},
        ]
        save_providers(test_providers)

        result = remove_provider("provider1")

        assert result is True
        providers = load_providers()
        assert len(providers) == 1
        assert providers[0]["name"] == "provider2"

    def test_remove_provider_not_found(self, isolated_config):
        """remove_provider returns False when not found."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        save_providers([{"name": "existing", "type": "openai"}])

        result = remove_provider("nonexistent")

        assert result is False
        providers = load_providers()
        assert len(providers) == 1


class TestProviderModelsConstant:
    """Tests for PROVIDER_MODELS constant."""

    def test_all_expected_providers_present(self):
        """PROVIDER_MODELS contains all expected provider types."""
        expected = {
            "openai",
            "anthropic",
            "openrouter",
            "bedrock",
            "vertex",
            "zai",
            "ollama",
        }
        assert set(PROVIDER_MODELS.keys()) == expected

    def test_cloud_providers_have_models(self):
        """Cloud providers have non-empty model lists in the catalog."""
        from clawrium.core.providers.storage import get_models_for_type

        cloud_providers = [
            "openai",
            "anthropic",
            "openrouter",
            "bedrock",
            "vertex",
            "zai",
        ]
        for provider_type in cloud_providers:
            models = get_models_for_type(provider_type)
            assert isinstance(models, list)
            assert len(models) > 0, f"{provider_type} should have models"

    def test_ollama_has_no_hardcoded_models(self):
        """Ollama provider returns None for models (dynamic discovery)."""
        from clawrium.core.providers.storage import get_models_for_type

        assert get_models_for_type("ollama") is None

    def test_providers_with_endpoints(self):
        """Providers with fixed endpoints have them set."""
        assert PROVIDER_MODELS["openai"]["endpoint"] == "https://api.openai.com/v1"
        assert PROVIDER_MODELS["anthropic"]["endpoint"] == "https://api.anthropic.com"
        assert (
            PROVIDER_MODELS["openrouter"]["endpoint"] == "https://openrouter.ai/api/v1"
        )

    def test_sdk_providers_have_no_endpoint(self):
        """SDK-based providers have None for endpoint."""
        assert PROVIDER_MODELS["bedrock"]["endpoint"] is None
        assert PROVIDER_MODELS["vertex"]["endpoint"] is None
        assert PROVIDER_MODELS["ollama"]["endpoint"] is None

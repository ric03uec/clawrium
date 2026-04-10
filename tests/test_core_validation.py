"""Tests for the validation module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from clawrium.core.validation import (
    ValidationResult,
    validate_soul_md,
    validate_provider_config,
    validate_provider_api_key,
    verify_provider_connectivity,
    validate_agent_installation,
    ERROR_MESSAGES,
    WARNING_MESSAGES,
)


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_passed_result(self):
        """ValidationResult with passed=True is successful."""
        result = ValidationResult(passed=True)
        assert result.passed is True
        assert result.errors == []
        assert result.warnings == []

    def test_failed_result(self):
        """ValidationResult with errors indicates failure."""
        result = ValidationResult(passed=False, errors=["Something failed"])
        assert result.passed is False
        assert len(result.errors) == 1
        assert "Something failed" in result.errors

    def test_result_with_warnings(self):
        """ValidationResult can have warnings even when passed."""
        result = ValidationResult(passed=True, warnings=["Minor issue"])
        assert result.passed is True
        assert len(result.warnings) == 1

    def test_result_with_details(self):
        """ValidationResult can store details dict."""
        result = ValidationResult(passed=True, details={"key": "value"})
        assert result.details["key"] == "value"


class TestValidateSoulMd:
    """Tests for validate_soul_md function."""

    def test_soul_md_missing(self, isolated_config: Path):
        """Returns failure when SOUL.md doesn't exist."""
        result = validate_soul_md("openclaw")
        assert result.passed is False
        assert len(result.errors) == 1
        assert "SOUL.md" in result.errors[0]

    def test_soul_md_exists_and_readable(self, isolated_config: Path):
        """Returns success when SOUL.md exists and is readable."""
        soul_dir = isolated_config / "agents" / "openclaw"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("# OpenClaw Personality\n\nBe helpful.")

        result = validate_soul_md("openclaw")
        assert result.passed is True
        assert len(result.errors) == 0

    def test_soul_md_empty_warning(self, isolated_config: Path):
        """Returns warning when SOUL.md is empty."""
        soul_dir = isolated_config / "agents" / "openclaw"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("")

        result = validate_soul_md("openclaw")
        assert result.passed is True
        assert len(result.warnings) == 1
        assert "empty" in result.warnings[0].lower()

    def test_soul_md_large_warning(self, isolated_config: Path):
        """Returns warning when SOUL.md is larger than 10KB."""
        soul_dir = isolated_config / "agents" / "openclaw"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("x" * 11000)

        result = validate_soul_md("openclaw")
        assert result.passed is True
        assert len(result.warnings) == 1
        assert "larger" in result.warnings[0].lower()


class TestValidateProviderConfig:
    """Tests for validate_provider_config function."""

    def test_provider_not_assigned(self, isolated_config: Path):
        """Returns failure when provider not assigned."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "openclaw": {
                        "onboarding": {
                            "state": "validate",
                            "stages": {
                                "providers": {"status": "pending", "provider_id": None}
                            },
                        }
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data))

        result = validate_provider_config("192.168.1.100", "openclaw")
        assert result.passed is False
        assert len(result.errors) == 1

    def test_provider_assigned(self, isolated_config: Path):
        """Returns success when provider is assigned."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps(
                [{"name": "test-openai", "type": "openai", "default_model": "gpt-4"}]
            )
        )

        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "openclaw": {
                        "onboarding": {
                            "state": "validate",
                            "stages": {
                                "providers": {
                                    "status": "complete",
                                    "provider_id": "test-openai",
                                }
                            },
                        }
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data))

        result = validate_provider_config("192.168.1.100", "openclaw")
        assert result.passed is True
        assert result.details.get("provider_id") == "test-openai"

    def test_provider_config_missing(self, isolated_config: Path):
        """Returns failure when provider ID not found in providers."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "openclaw": {
                        "onboarding": {
                            "state": "validate",
                            "stages": {
                                "providers": {
                                    "status": "complete",
                                    "provider_id": "nonexistent",
                                }
                            },
                        }
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data))

        result = validate_provider_config("192.168.1.100", "openclaw")
        assert result.passed is False
        assert "not found" in result.errors[0].lower()


class TestValidateProviderApiKey:
    """Tests for validate_provider_api_key function."""

    def test_provider_not_found(self, isolated_config: Path):
        """Returns failure when provider doesn't exist."""
        result = validate_provider_api_key("nonexistent")
        assert result.passed is False
        assert "not found" in result.errors[0].lower()

    def test_ollama_no_key_needed(self, isolated_config: Path):
        """Ollama doesn't require API key."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps(
                [
                    {
                        "name": "test-ollama",
                        "type": "ollama",
                        "endpoint": "http://localhost:11434",
                    }
                ]
            )
        )

        result = validate_provider_api_key("test-ollama")
        assert result.passed is True
        assert result.details.get("key_required") is False

    def test_bedrock_uses_cloud_auth(self, isolated_config: Path):
        """Bedrock uses AWS credentials, not API key."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": "test-bedrock", "type": "bedrock"}])
        )

        result = validate_provider_api_key("test-bedrock")
        assert result.passed is True
        assert result.details.get("uses_cloud_auth") is True

    def test_openai_missing_key(self, isolated_config: Path):
        """Returns failure when OpenAI API key missing."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": "test-openai", "type": "openai"}])
        )

        result = validate_provider_api_key("test-openai")
        assert result.passed is False
        assert "API key" in result.errors[0]

    def test_openai_has_key(self, isolated_config: Path):
        """Returns success when API key is configured."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": "test-openai", "type": "openai"}])
        )

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

        result = validate_provider_api_key("test-openai")
        assert result.passed is True
        assert result.details.get("key_configured") is True


class TestTestProviderConnectivity:
    """Tests for verify_provider_connectivity function."""

    def test_provider_not_found(self, isolated_config: Path):
        """Returns failure when provider doesn't exist."""
        result = verify_provider_connectivity("nonexistent")
        assert result.passed is False

    def test_openai_missing_key(self, isolated_config: Path):
        """Returns failure when API key missing for connectivity test."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": "test-openai", "type": "openai"}])
        )

        result = verify_provider_connectivity("test-openai")
        assert result.passed is False
        assert "API key" in result.errors[0]

    @patch("clawrium.core.validation._make_request")
    def test_openai_success(self, mock_request, isolated_config: Path):
        """Returns success on valid OpenAI response."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": "test-openai", "type": "openai"}])
        )

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

        mock_request.return_value = (200, {"data": [{"id": "gpt-4"}]}, None)

        result = verify_provider_connectivity("test-openai")
        assert result.passed is True

    @patch("clawrium.core.validation._make_request")
    def test_openai_invalid_key(self, mock_request, isolated_config: Path):
        """Returns failure on 401 response."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": "test-openai", "type": "openai"}])
        )

        secrets_file = isolated_config / "secrets.json"
        secrets_file.write_text(
            json.dumps(
                {
                    "provider:test-openai": {
                        "API_KEY": {
                            "key": "API_KEY",
                            "value": "invalid-key",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z",
                            "description": "",
                        }
                    }
                }
            )
        )

        mock_request.return_value = (401, None, "Unauthorized")

        result = verify_provider_connectivity("test-openai")
        assert result.passed is False
        assert "invalid" in result.errors[0].lower()

    @patch("clawrium.core.validation._make_request")
    def test_openai_rate_limited(self, mock_request, isolated_config: Path):
        """Returns failure on 429 response."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": "test-openai", "type": "openai"}])
        )

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

        mock_request.return_value = (429, None, "Rate limited")

        result = verify_provider_connectivity("test-openai")
        assert result.passed is False
        assert "rate" in result.errors[0].lower()

    @patch("clawrium.core.validation._make_request")
    def test_anthropic_success(self, mock_request, isolated_config: Path):
        """Returns success on valid Anthropic response."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": "test-anthropic", "type": "anthropic"}])
        )

        secrets_file = isolated_config / "secrets.json"
        secrets_file.write_text(
            json.dumps(
                {
                    "provider:test-anthropic": {
                        "API_KEY": {
                            "key": "API_KEY",
                            "value": "sk-ant-test",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z",
                            "description": "",
                        }
                    }
                }
            )
        )

        mock_request.return_value = (200, {}, None)

        result = verify_provider_connectivity("test-anthropic")
        assert result.passed is True


class TestTestOllamaConnectivity:
    """Tests for Ollama connectivity."""

    def test_ollama_running(self, isolated_config: Path):
        """Returns success when Ollama is running."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps(
                [
                    {
                        "name": "test-ollama",
                        "type": "ollama",
                        "endpoint": "http://localhost:11434",
                    }
                ]
            )
        )

        with patch("clawrium.core.validation.urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(
                {"models": [{"name": "llama3:latest"}]}
            ).encode()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            result = verify_provider_connectivity("test-ollama")
            assert result.passed is True
            assert "llama3:latest" in result.details.get("models", [])

    def test_ollama_no_models(self, isolated_config: Path):
        """Returns warning when Ollama has no models."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps(
                [
                    {
                        "name": "test-ollama",
                        "type": "ollama",
                        "endpoint": "http://localhost:11434",
                    }
                ]
            )
        )

        with patch("clawrium.core.validation.urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({"models": []}).encode()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            result = verify_provider_connectivity("test-ollama")
            assert result.passed is True
            assert len(result.warnings) == 1
            assert "no models" in result.warnings[0].lower()


class TestValidateAgentInstallation:
    """Tests for validate_agent_installation function."""

    def test_host_not_found(self, isolated_config: Path):
        """Returns failure when host doesn't exist."""
        result = validate_agent_installation("nonexistent", "openclaw")
        assert result.passed is False
        assert "not found" in result.errors[0].lower()

    def test_claw_not_installed(self, isolated_config: Path):
        """Returns failure when claw not installed."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [{"hostname": "192.168.1.100", "agents": {}}]
        hosts_file.write_text(json.dumps(hosts_data))

        result = validate_agent_installation("192.168.1.100", "openclaw")
        assert result.passed is False
        assert (
            "not found" in result.errors[0].lower()
            or "not installed" in result.errors[0].lower()
        )

    def test_claw_installed(self, isolated_config: Path):
        """Returns success when claw is installed."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "openclaw": {
                        "version": "0.1.0",
                        "status": "installed",
                    }
                },
            }
        ]
        hosts_file.write_text(json.dumps(hosts_data))

        result = validate_agent_installation("192.168.1.100", "openclaw")
        assert result.passed is True
        assert result.details.get("version") == "0.1.0"


class TestErrorMessages:
    """Tests for error message templates."""

    def test_error_messages_exist(self):
        """All expected error messages are defined."""
        expected_keys = [
            "soul_md_missing",
            "soul_md_unreadable",
            "provider_not_found",
            "provider_config_missing",
            "api_key_missing",
            "api_key_invalid",
            "connection_failed",
            "connection_timeout",
            "rate_limited",
        ]
        for key in expected_keys:
            assert key in ERROR_MESSAGES, f"Missing error message: {key}"

    def test_warning_messages_exist(self):
        """All expected warning messages are defined."""
        expected_keys = [
            "soul_md_empty",
            "soul_md_large",
        ]
        for key in expected_keys:
            assert key in WARNING_MESSAGES, f"Missing warning message: {key}"

    def test_error_messages_formattable(self):
        """Error messages can be formatted with placeholders."""
        msg = ERROR_MESSAGES["soul_md_unreadable"]
        formatted = msg.format(error="test error")
        assert "test error" in formatted

        msg = ERROR_MESSAGES["connection_timeout"]
        formatted = msg.format(provider="OpenAI", timeout=10)
        assert "OpenAI" in formatted
        assert "10" in formatted

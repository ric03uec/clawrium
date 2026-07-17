"""Tests for the validation module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from clawrium.core.validation import (
    ValidationResult,
    validate_soul_md,
    validate_provider_config,
    validate_provider_api_key,
    verify_provider_connectivity,
    validate_openclaw_gateway,
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

    @pytest.mark.parametrize(
        "provider_type,expected_endpoint",
        [
            ("opencode", "opencode.ai/zen/v1"),
            ("opencode-go", "opencode.ai/zen/go/v1"),
        ],
    )
    @patch("clawrium.core.validation._make_request")
    def test_opencode_success(
        self, mock_request, isolated_config: Path, provider_type: str, expected_endpoint: str
    ):
        """Returns success on valid OpenCode response."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": f"test-{provider_type}", "type": provider_type}])
        )

        secrets_file = isolated_config / "secrets.json"
        secrets_file.write_text(
            json.dumps(
                {
                    f"provider:test-{provider_type}": {
                        "API_KEY": {
                            "key": "API_KEY",
                            "value": f"sk-{provider_type}-test",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z",
                            "description": "",
                        }
                    }
                }
            )
        )

        mock_request.return_value = (200, {}, None)

        result = verify_provider_connectivity(f"test-{provider_type}")
        assert result.passed is True
        assert expected_endpoint in result.details["endpoint"]

    @pytest.mark.parametrize(
        "provider_type,status,error,expected_error_substring",
        [
            ("opencode", 401, None, "invalid"),
            ("opencode", 0, "connection refused", "connect"),
            ("opencode", None, "timeout", "timed out"),
            ("opencode-go", 401, None, "invalid"),
            ("opencode-go", 0, "connection refused", "connect"),
            ("opencode-go", None, "timeout", "timed out"),
        ],
    )
    @patch("clawrium.core.validation._make_request")
    def test_opencode_failure_paths(
        self,
        mock_request,
        isolated_config: Path,
        provider_type: str,
        status: int | None,
        error: str | None,
        expected_error_substring: str,
    ):
        """Returns failure on 401, connection failure, and timeout."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": f"test-{provider_type}", "type": provider_type}])
        )

        secrets_file = isolated_config / "secrets.json"
        secrets_file.write_text(
            json.dumps(
                {
                    f"provider:test-{provider_type}": {
                        "API_KEY": {
                            "key": "API_KEY",
                            "value": f"sk-{provider_type}-test",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z",
                            "description": "",
                        }
                    }
                }
            )
        )

        mock_request.return_value = (status, {}, error)

        result = verify_provider_connectivity(f"test-{provider_type}")
        assert result.passed is False
        assert expected_error_substring in result.errors[0].lower()

    @pytest.mark.parametrize("provider_type", ["opencode", "opencode-go"])
    def test_opencode_missing_key(
        self, isolated_config: Path, provider_type: str
    ):
        """Returns failure when the API key is missing."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        providers_file = isolated_config / "providers.json"
        providers_file.write_text(
            json.dumps([{"name": f"test-{provider_type}", "type": provider_type}])
        )

        result = verify_provider_connectivity(f"test-{provider_type}")
        assert result.passed is False
        assert "api key" in result.errors[0].lower()


class TestTestOllamaConnectivity:
    """Tests for Ollama connectivity skip behaviour.

    `clawctl` runs on the control machine but the agent (which will actually
    talk to Ollama) runs on a remote host. A control-machine HTTP probe
    can fail purely because the operator's laptop is on a different
    network than the agent host. The check is deliberately skipped with
    a warning so the operator knows to verify reachability themselves.
    """

    def _write_ollama_provider(
        self, isolated_config: Path, endpoint: str = "http://192.168.1.17:11434"
    ) -> None:
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / "providers.json").write_text(
            json.dumps(
                [{"name": "test-ollama", "type": "ollama", "endpoint": endpoint}]
            )
        )

    def test_ollama_connectivity_check_is_skipped_with_warning(
        self, isolated_config: Path
    ):
        """verify_provider_connectivity must NOT probe Ollama from the
        control machine. It returns passed=True with a warning that names
        the endpoint and points the operator at the agent host."""
        self._write_ollama_provider(isolated_config)

        with patch("clawrium.core.validation.urllib.request.urlopen") as mock_urlopen:
            result = verify_provider_connectivity("test-ollama")
            mock_urlopen.assert_not_called()

        assert result.passed is True
        assert result.errors == []
        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert "192.168.1.17:11434" in warning
        assert "agent host" in warning.lower()
        assert "curl" in warning
        assert result.details.get("skipped") is True
        assert result.details.get("type") == "ollama"
        assert result.details.get("endpoint") == "http://192.168.1.17:11434"

    def test_ollama_skip_warning_uses_fallback_when_endpoint_missing(
        self, isolated_config: Path
    ):
        """When the provider entry has no endpoint, the warning still
        renders cleanly (no empty-string artifact) and the empty-endpoint
        path must not probe the network either."""
        self._write_ollama_provider(isolated_config, endpoint="")

        with patch("clawrium.core.validation.urllib.request.urlopen") as mock_urlopen:
            result = verify_provider_connectivity("test-ollama")
            mock_urlopen.assert_not_called()

        assert result.passed is True
        assert result.errors == []
        assert result.details.get("skipped") is True
        assert result.details.get("type") == "ollama"
        assert result.details.get("endpoint") == ""
        assert any("<endpoint not configured>" in w for w in result.warnings), (
            result.warnings
        )


class TestValidateOpenClawGateway:
    """Tests for validate_openclaw_gateway function."""

    def test_missing_gateway_config_fails(self, isolated_config: Path):
        """Returns failure when gateway endpoint is not configured."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_file.write_text(
            json.dumps(
                [
                    {
                        "hostname": "192.168.1.100",
                        "agents": {
                            "assistant": {
                                "type": "openclaw",
                                "onboarding": {
                                    "state": "validate",
                                    "stages": {
                                        "providers": {
                                            "status": "complete",
                                            "provider_id": "test-openai",
                                        },
                                        "identity": {"status": "complete"},
                                        "channels": {"status": "complete"},
                                        "validate": {"status": "pending"},
                                    },
                                },
                                "config": {"gateway": {}},
                            }
                        },
                    }
                ]
            )
        )

        result = validate_openclaw_gateway("192.168.1.100", "assistant")

        assert result.passed is False
        assert "gateway endpoint not configured" in result.errors[0].lower()

    def test_missing_gateway_auth_fails(self, isolated_config: Path):
        """Returns failure when gateway auth token is missing."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_file.write_text(
            json.dumps(
                [
                    {
                        "hostname": "192.168.1.100",
                        "agents": {
                            "assistant": {
                                "type": "openclaw",
                                "onboarding": {
                                    "state": "validate",
                                    "stages": {
                                        "providers": {
                                            "status": "complete",
                                            "provider_id": "test-openai",
                                        },
                                        "identity": {"status": "complete"},
                                        "channels": {"status": "complete"},
                                        "validate": {"status": "pending"},
                                    },
                                },
                                "config": {
                                    "gateway": {
                                        "url": "ws://192.168.1.100:40123",
                                        "port": 40123,
                                    }
                                },
                            }
                        },
                    }
                ]
            )
        )

        result = validate_openclaw_gateway("192.168.1.100", "assistant")

        assert result.passed is False
        assert "auth token not configured" in result.errors[0].lower()

    @patch("clawrium.core.validation._probe_openclaw_gateway")
    def test_gateway_probe_success(self, mock_probe, isolated_config: Path):
        """Returns success when gateway probe connects and authenticates."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_file.write_text(
            json.dumps(
                [
                    {
                        "hostname": "192.168.1.100",
                        "agents": {
                            "assistant": {
                                "type": "openclaw",
                                "onboarding": {
                                    "state": "validate",
                                    "stages": {
                                        "providers": {
                                            "status": "complete",
                                            "provider_id": "test-openai",
                                        },
                                        "identity": {"status": "complete"},
                                        "channels": {"status": "complete"},
                                        "validate": {"status": "pending"},
                                    },
                                },
                                "config": {
                                    "gateway": {
                                        "url": "ws://192.168.1.100:40123",
                                        "auth": {"token": "test-token"},
                                        "port": 40123,
                                    }
                                },
                            }
                        },
                    }
                ]
            )
        )

        result = validate_openclaw_gateway("192.168.1.100", "assistant")

        assert result.passed is True
        assert result.details.get("gateway_url") == "ws://192.168.1.100:40123"

    @patch("clawrium.core.validation._probe_openclaw_gateway")
    def test_gateway_probe_auth_failure(self, mock_probe, isolated_config: Path):
        """Returns auth failure when gateway rejects credentials."""
        from clawrium.core.chat import ChatAuthenticationError

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_file.write_text(
            json.dumps(
                [
                    {
                        "hostname": "192.168.1.100",
                        "agents": {
                            "assistant": {
                                "type": "openclaw",
                                "onboarding": {
                                    "state": "validate",
                                    "stages": {
                                        "providers": {
                                            "status": "complete",
                                            "provider_id": "test-openai",
                                        },
                                        "identity": {"status": "complete"},
                                        "channels": {"status": "complete"},
                                        "validate": {"status": "pending"},
                                    },
                                },
                                "config": {
                                    "gateway": {
                                        "url": "ws://192.168.1.100:40123",
                                        "auth": "bad-token",
                                        "port": 40123,
                                    }
                                },
                            }
                        },
                    }
                ]
            )
        )
        mock_probe.side_effect = ChatAuthenticationError("unauthorized")

        result = validate_openclaw_gateway("192.168.1.100", "assistant")

        assert result.passed is False
        assert "authentication failed" in result.errors[0].lower()

    @patch("clawrium.core.validation._probe_openclaw_gateway")
    def test_gateway_probe_retries_and_recovers(
        self, mock_probe, isolated_config: Path
    ):
        """Retries transient connection failures and succeeds on a later attempt."""
        from clawrium.core.chat import ChatConnectionError

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_file.write_text(
            json.dumps(
                [
                    {
                        "hostname": "192.168.1.100",
                        "agents": {
                            "assistant": {
                                "type": "openclaw",
                                "onboarding": {
                                    "state": "validate",
                                    "stages": {
                                        "providers": {
                                            "status": "complete",
                                            "provider_id": "test-openai",
                                        },
                                        "identity": {"status": "complete"},
                                        "channels": {"status": "complete"},
                                        "validate": {"status": "pending"},
                                    },
                                },
                                "config": {
                                    "gateway": {
                                        "url": "ws://192.168.1.100:40123",
                                        "auth": "token-123",
                                        "port": 40123,
                                    }
                                },
                            }
                        },
                    }
                ]
            )
        )
        mock_probe.side_effect = [ChatConnectionError("timeout"), None]

        result = validate_openclaw_gateway(
            "192.168.1.100", "assistant", retries=3, retry_delay=0
        )

        assert result.passed is True
        assert result.details.get("attempts") == 2
        assert mock_probe.call_count == 2

    @patch("clawrium.core.validation._probe_openclaw_gateway")
    def test_gateway_probe_retries_exhausted(self, mock_probe, isolated_config: Path):
        """Fails after exhausting connection retry attempts."""
        from clawrium.core.chat import ChatConnectionError

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_file = isolated_config / "hosts.json"
        hosts_file.write_text(
            json.dumps(
                [
                    {
                        "hostname": "192.168.1.100",
                        "agents": {
                            "assistant": {
                                "type": "openclaw",
                                "onboarding": {
                                    "state": "validate",
                                    "stages": {
                                        "providers": {
                                            "status": "complete",
                                            "provider_id": "test-openai",
                                        },
                                        "identity": {"status": "complete"},
                                        "channels": {"status": "complete"},
                                        "validate": {"status": "pending"},
                                    },
                                },
                                "config": {
                                    "gateway": {
                                        "url": "ws://192.168.1.100:40123",
                                        "auth": "token-123",
                                        "port": 40123,
                                    }
                                },
                            }
                        },
                    }
                ]
            )
        )
        mock_probe.side_effect = ChatConnectionError("timeout")

        result = validate_openclaw_gateway(
            "192.168.1.100", "assistant", retries=3, retry_delay=0
        )

        assert result.passed is False
        assert result.details.get("attempts") == 3
        assert mock_probe.call_count == 3


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

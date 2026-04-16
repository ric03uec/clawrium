"""Validation utilities for agent onboarding.

This module provides validation functions to verify agent configuration
and connectivity before transitioning to READY state.
"""

import asyncio
import json
import socket
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host

__all__ = [
    "ValidationResult",
    "validate_soul_md",
    "validate_provider_config",
    "validate_provider_api_key",
    "verify_provider_connectivity",
    "validate_openclaw_gateway",
    "validate_agent_installation",
    "ERROR_MESSAGES",
    "WARNING_MESSAGES",
]


@dataclass
class ValidationResult:
    """Result of a validation check.

    Attributes:
        passed: True if validation passed, False if errors found.
        errors: List of error messages (blocking issues).
        warnings: List of warning messages (non-blocking issues).
        details: Additional details about what was checked.
    """

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


ERROR_MESSAGES = {
    "soul_md_missing": (
        "SOUL.md personality file not found. "
        "Run 'clm agent configure <claw> --stage identity' first."
    ),
    "soul_md_unreadable": "SOUL.md exists but cannot be read: {error}",
    "provider_not_found": (
        "No provider assigned to this agent. "
        "Run 'clm agent configure <claw> --stage providers' first."
    ),
    "provider_config_missing": "Provider '{provider}' not found in configuration.",
    "api_key_missing": (
        "No API key configured for provider '{provider}'. "
        "Run 'clm provider add' with --api-key to set it."
    ),
    "api_key_invalid": (
        "API key for '{provider}' appears to be invalid. Check your API key is correct."
    ),
    "connection_failed": (
        "Could not connect to {provider} API. Check your network connection."
    ),
    "connection_timeout": "Connection to {provider} timed out after {timeout}s.",
    "rate_limited": ("Rate limited by {provider}. Wait a moment or upgrade your plan."),
    "insufficient_quota": (
        "Insufficient quota for {provider}. "
        "Check your account balance or upgrade your plan."
    ),
    "ollama_not_running": (
        "Ollama server is not running at {endpoint}. Start it with: ollama serve"
    ),
    "ollama_no_models": (
        "No models found on Ollama server. Pull a model with: ollama pull <model>"
    ),
    "bedrock_credentials": (
        "AWS credentials not configured for Bedrock. "
        "Run 'aws configure' or set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY."
    ),
    "vertex_credentials": (
        "GCP credentials not configured for Vertex AI. "
        "Set GOOGLE_APPLICATION_CREDENTIALS or run 'gcloud auth application-default login'."
    ),
    "agent_not_installed": (
        "Agent binary not found on host. "
        "Run 'clm agent install --type {claw_type} --host {host}' first."
    ),
    "agent_wrong_permissions": (
        "Agent binary has incorrect permissions. Expected {expected}, found {actual}."
    ),
    "onboarding_not_found": "Onboarding record not found for {claw_name} on {host}.",
    "gateway_not_configured": (
        "Gateway endpoint not configured for this agent. "
        "Re-run 'clm agent configure <claw> --stage providers' to sync config."
    ),
    "gateway_auth_missing": (
        "Gateway auth token not configured for this agent. "
        "Re-run 'clm agent install' or 'clm agent configure <claw> --stage providers'."
    ),
    "gateway_unreachable": (
        "Could not connect to OpenClaw gateway at {endpoint}. "
        "Check host, port, and network connectivity."
    ),
    "gateway_auth_failed": (
        "Gateway authentication failed. "
        "Verify gateway auth token and device credentials."
    ),
    "gateway_protocol_failed": "Gateway protocol error: {error}",
}

WARNING_MESSAGES = {
    "soul_md_empty": "SOUL.md file is empty. Agent will use default personality.",
    "soul_md_large": "SOUL.md is larger than 10KB. Consider shortening for better performance.",
    "ollama_no_models": "No models found on Ollama server. Pull a model with: ollama pull <model>",
}


def validate_soul_md(claw_type: str, agent_name: str | None = None) -> ValidationResult:
    """Validate SOUL.md personality file exists and is readable.

    Args:
        claw_type: Type of claw (e.g., "openclaw", "zeroclaw").
        agent_name: Optional agent instance name. If provided, checks
            the new agent-specific identity path first.

    Returns:
        ValidationResult with pass/fail status and any errors/warnings.
    """
    config_dir = get_config_dir()

    # Check new agent-specific path first (if agent_name provided)
    # New path: agents/<type>/<agent-name>/identity/SOUL.md
    if agent_name:
        new_path = (
            config_dir / "agents" / claw_type / agent_name / "identity" / "SOUL.md"
        )
        if new_path.exists():
            soul_path = new_path
        else:
            # Fall back to legacy path
            soul_path = config_dir / "agents" / claw_type / "SOUL.md"
    else:
        # Legacy path: agents/<type>/SOUL.md
        soul_path = config_dir / "agents" / claw_type / "SOUL.md"

    if not soul_path.exists():
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["soul_md_missing"]],
            details={"path": str(soul_path), "exists": False},
        )

    try:
        content = soul_path.read_text()
    except Exception as e:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["soul_md_unreadable"].format(error=str(e))],
            details={"path": str(soul_path), "exists": True, "readable": False},
        )

    warnings = []
    if not content.strip():
        warnings.append(WARNING_MESSAGES["soul_md_empty"])
    elif len(content) > 10240:
        warnings.append(WARNING_MESSAGES["soul_md_large"])

    return ValidationResult(
        passed=True,
        warnings=warnings,
        details={
            "path": str(soul_path),
            "exists": True,
            "readable": True,
            "size": len(content),
        },
    )


def validate_provider_config(host: str, claw_name: str) -> ValidationResult:
    """Validate provider is configured for this agent.

    Reads onboarding metadata to find the assigned provider.

    Args:
        host: Host alias or hostname.
        claw_name: Name of the claw instance.

    Returns:
        ValidationResult with provider info or error.
    """
    from clawrium.core.onboarding import _get_claw_record

    claw_record = _get_claw_record(host, claw_name)
    if claw_record is None:
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["onboarding_not_found"].format(
                    claw_name=claw_name, host=host
                )
            ],
        )

    onboarding = claw_record.get("onboarding", {})
    stages = onboarding.get("stages", {})
    providers_stage = stages.get("providers", {})
    provider_id = providers_stage.get("provider_id")

    if not provider_id:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["provider_not_found"]],
            details={"onboarding_state": onboarding.get("state")},
        )

    from clawrium.core.providers import get_provider

    provider = get_provider(provider_id)
    if not provider:
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["provider_config_missing"].format(provider=provider_id)
            ],
            details={"provider_id": provider_id},
        )

    return ValidationResult(
        passed=True,
        details={
            "provider_id": provider_id,
            "provider_type": provider.get("type"),
            "default_model": provider.get("default_model"),
        },
    )


def validate_provider_api_key(provider_name: str) -> ValidationResult:
    """Check if API key is configured for a provider.

    Args:
        provider_name: Name of the provider.

    Returns:
        ValidationResult indicating if API key is configured.
    """
    from clawrium.core.providers import get_provider_api_key, get_provider

    provider = get_provider(provider_name)
    if not provider:
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["provider_config_missing"].format(provider=provider_name)
            ],
        )

    provider_type = provider.get("type", "")

    if provider_type == "ollama":
        return ValidationResult(
            passed=True, details={"type": "ollama", "key_required": False}
        )

    if provider_type in ("bedrock", "vertex"):
        return ValidationResult(
            passed=True,
            details={
                "type": provider_type,
                "key_required": False,
                "uses_cloud_auth": True,
            },
        )

    api_key = get_provider_api_key(provider_name)
    if not api_key:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["api_key_missing"].format(provider=provider_name)],
            details={"type": provider_type, "key_configured": False},
        )

    return ValidationResult(
        passed=True,
        details={"type": provider_type, "key_configured": True},
    )


def verify_provider_connectivity(
    provider_name: str, timeout: int = 10
) -> ValidationResult:
    """Test connectivity to provider API.

    Performs a minimal API call to verify credentials and connectivity.

    Args:
        provider_name: Name of the provider.
        timeout: Request timeout in seconds.

    Returns:
        ValidationResult with connectivity status.
    """
    from clawrium.core.providers import (
        get_provider,
        get_provider_api_key,
    )

    provider = get_provider(provider_name)
    if not provider:
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["provider_config_missing"].format(provider=provider_name)
            ],
        )

    provider_type = provider.get("type", "")

    if provider_type == "ollama":
        return _test_ollama_connectivity(provider, timeout)

    if provider_type == "bedrock":
        return _test_bedrock_connectivity(provider, timeout)

    if provider_type == "vertex":
        return _test_vertex_connectivity(provider, timeout)

    api_key = get_provider_api_key(provider_name)
    if not api_key:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["api_key_missing"].format(provider=provider_name)],
        )

    if provider_type == "openai":
        return _test_openai_connectivity(api_key, timeout)

    if provider_type == "anthropic":
        return _test_anthropic_connectivity(api_key, timeout)

    if provider_type == "openrouter":
        return _test_openrouter_connectivity(api_key, timeout)

    if provider_type == "zai":
        return _test_zai_connectivity(api_key, timeout)

    return ValidationResult(
        passed=True,
        warnings=[f"Connectivity test not implemented for {provider_type}"],
    )


def _make_request(
    url: str,
    headers: dict[str, str],
    method: str = "GET",
    data: bytes | None = None,
    timeout: int = 10,
) -> tuple[int, dict | None, str | None]:
    """Make HTTP request and return status code, response body, and error.

    Uses urllib to avoid additional dependencies.
    """
    req = urllib.request.Request(url, headers=headers, method=method)
    if data:
        req.data = data

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None, None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        return e.code, json.loads(body) if body else None, str(e)
    except urllib.error.URLError as e:
        return 0, None, str(e.reason)
    except socket.timeout:
        return 0, None, "timeout"
    except json.JSONDecodeError as e:
        return 0, None, f"Invalid response: {e}"


def _test_openai_connectivity(api_key: str, timeout: int) -> ValidationResult:
    """Test OpenAI API connectivity."""
    url = "https://api.openai.com/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    status, body, error = _make_request(url, headers, timeout=timeout)

    if error == "timeout":
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["connection_timeout"].format(
                    provider="OpenAI", timeout=timeout
                )
            ],
        )

    if status == 0:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["connection_failed"].format(provider="OpenAI")],
            details={"error": error},
        )

    if status == 401:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["api_key_invalid"].format(provider="OpenAI")],
        )

    if status == 429:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["rate_limited"].format(provider="OpenAI")],
        )

    if status >= 500:
        return ValidationResult(
            passed=False,
            errors=[f"OpenAI API error: HTTP {status}"],
        )

    if status == 200:
        models = []
        if body and "data" in body:
            models = [
                m.get("id", "") for m in body.get("data", []) if isinstance(m, dict)
            ]
        return ValidationResult(
            passed=True,
            details={"endpoint": url, "models_available": len(models)},
        )

    return ValidationResult(passed=True)


def _test_anthropic_connectivity(api_key: str, timeout: int) -> ValidationResult:
    """Test Anthropic API connectivity using a minimal message request."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    data = json.dumps(
        {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "Hi"}],
        }
    ).encode()

    status, body, error = _make_request(
        url, headers, method="POST", data=data, timeout=timeout
    )

    if error == "timeout":
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["connection_timeout"].format(
                    provider="Anthropic", timeout=timeout
                )
            ],
        )

    if status == 0:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["connection_failed"].format(provider="Anthropic")],
            details={"error": error},
        )

    if status == 401:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["api_key_invalid"].format(provider="Anthropic")],
        )

    if status == 429:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["rate_limited"].format(provider="Anthropic")],
        )

    if status in (200, 201):
        return ValidationResult(passed=True, details={"endpoint": url})

    if status >= 400:
        error_msg = body.get("error", {}).get("message", "") if body else ""
        if "invalid_api_key" in str(body).lower():
            return ValidationResult(
                passed=False,
                errors=[ERROR_MESSAGES["api_key_invalid"].format(provider="Anthropic")],
            )
        return ValidationResult(
            passed=True, details={"status": status, "message": error_msg}
        )

    return ValidationResult(passed=True)


def _test_openrouter_connectivity(api_key: str, timeout: int) -> ValidationResult:
    """Test OpenRouter API connectivity."""
    url = "https://openrouter.ai/api/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    status, body, error = _make_request(url, headers, timeout=timeout)

    if error == "timeout":
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["connection_timeout"].format(
                    provider="OpenRouter", timeout=timeout
                )
            ],
        )

    if status == 0:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["connection_failed"].format(provider="OpenRouter")],
            details={"error": error},
        )

    if status == 401:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["api_key_invalid"].format(provider="OpenRouter")],
        )

    if status == 200:
        return ValidationResult(passed=True, details={"endpoint": url})

    return ValidationResult(passed=True)


def _test_zai_connectivity(api_key: str, timeout: int) -> ValidationResult:
    """Test ZAI (GLM) API connectivity."""
    url = "https://open.bigmodel.cn/api/paas/v4/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    status, body, error = _make_request(url, headers, timeout=timeout)

    if error == "timeout":
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["connection_timeout"].format(
                    provider="ZAI", timeout=timeout
                )
            ],
        )

    if status == 0:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["connection_failed"].format(provider="ZAI")],
            details={"error": error},
        )

    if status == 401:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["api_key_invalid"].format(provider="ZAI")],
        )

    if status == 200:
        return ValidationResult(passed=True, details={"endpoint": url})

    return ValidationResult(passed=True)


def _test_ollama_connectivity(provider: dict, timeout: int) -> ValidationResult:
    """Test Ollama server connectivity."""
    endpoint = provider.get("endpoint", "http://localhost:11434")

    if endpoint.endswith("/"):
        endpoint = endpoint.rstrip("/")

    url = f"{endpoint}/api/tags"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body) if body else {}
            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models if isinstance(m, dict)]

            warnings = []
            if not model_names:
                warnings.append(WARNING_MESSAGES["ollama_no_models"])

            return ValidationResult(
                passed=True,
                warnings=warnings,
                details={"endpoint": endpoint, "models": model_names},
            )
    except urllib.error.URLError as e:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["ollama_not_running"].format(endpoint=endpoint)],
            details={"endpoint": endpoint, "error": str(e.reason)},
        )
    except socket.timeout:
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["connection_timeout"].format(
                    provider="Ollama", timeout=timeout
                )
            ],
        )
    except Exception as e:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["ollama_not_running"].format(endpoint=endpoint)],
            details={"error": str(e)},
        )


def _test_bedrock_connectivity(provider: dict, timeout: int) -> ValidationResult:
    """Test AWS Bedrock connectivity by checking credentials."""
    import os

    aws_key = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY")
    aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get(
        "AWS_SECRET_KEY"
    )

    if not aws_key or not aws_secret:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["bedrock_credentials"]],
        )

    return ValidationResult(
        passed=True,
        details={"type": "bedrock", "credentials_configured": True},
    )


def _test_vertex_connectivity(provider: dict, timeout: int) -> ValidationResult:
    """Test GCP Vertex AI connectivity by checking credentials."""
    import os

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if creds_path:
        from pathlib import Path

        if Path(creds_path).exists():
            return ValidationResult(
                passed=True,
                details={"type": "vertex", "credentials_file": creds_path},
            )

    return ValidationResult(
        passed=False,
        errors=[ERROR_MESSAGES["vertex_credentials"]],
    )


async def _probe_openclaw_gateway(
    gateway_url: str,
    auth_token: str,
    timeout: int,
    device_id: str | None,
    device_private_key: str | None,
) -> None:
    """Open and close an authenticated gateway connection."""
    from clawrium.core.chat import OpenClawChatClient

    client = OpenClawChatClient(
        gateway_url=gateway_url,
        auth_token=auth_token,
        device_id=device_id,
        device_private_key=device_private_key,
        timeout_seconds=float(timeout),
    )
    try:
        await client.connect()
    finally:
        await client.close()


def validate_openclaw_gateway(
    host: str,
    claw_name: str,
    timeout: int = 10,
    retries: int = 3,
    retry_delay: float = 1.0,
) -> ValidationResult:
    """Validate OpenClaw gateway reachability and authentication.

    Args:
        host: Host alias, hostname, or key_id.
        claw_name: Name of the claw instance.
        timeout: Connection timeout in seconds.
        retries: Number of connection attempts on transient connection errors.
        retry_delay: Delay between retries in seconds.

    Returns:
        ValidationResult with gateway health verification status.
    """
    from clawrium.core.chat import (
        ChatAuthenticationError,
        ChatConnectionError,
        ChatProtocolError,
    )
    from clawrium.core.hosts import get_host_by_key_id
    from clawrium.core.onboarding import _get_claw_record

    host_data = get_host(host)
    if not host_data:
        host_data = get_host_by_key_id(host)
    if not host_data:
        return ValidationResult(
            passed=False,
            errors=[f"Host '{host}' not found."],
        )

    # Resolve claw from canonical hostname/alias to avoid key_id lookup gaps.
    claw_record = _get_claw_record(host_data["hostname"], claw_name)
    if claw_record is None:
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["onboarding_not_found"].format(
                    claw_name=claw_name, host=host
                )
            ],
        )

    config = claw_record.get("config", {})
    gateway = config.get("gateway", {})

    gateway_url = gateway.get("url")
    if not gateway_url:
        port = gateway.get("port")
        if not port:
            return ValidationResult(
                passed=False,
                errors=[ERROR_MESSAGES["gateway_not_configured"]],
            )
        gateway_url = f"ws://{host_data['hostname']}:{port}"

    auth = gateway.get("auth")
    auth_token = ""
    if isinstance(auth, str):
        auth_token = auth
    elif isinstance(auth, dict):
        maybe_token = auth.get("token")
        if isinstance(maybe_token, str):
            auth_token = maybe_token

    auth_token = auth_token.strip()
    if not auth_token:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["gateway_auth_missing"]],
            details={"gateway_url": gateway_url},
        )

    device = gateway.get("device", {})
    device_id = device.get("id") if isinstance(device, dict) else None
    device_private_key = device.get("privateKey") if isinstance(device, dict) else None

    retries = max(1, int(retries))
    last_connection_error: ChatConnectionError | None = None

    for attempt in range(1, retries + 1):
        try:
            asyncio.run(
                _probe_openclaw_gateway(
                    gateway_url,
                    auth_token,
                    timeout,
                    device_id,
                    device_private_key,
                )
            )
            return ValidationResult(
                passed=True,
                details={
                    "gateway_url": gateway_url,
                    "timeout": timeout,
                    "device_auth": bool(device_id and device_private_key),
                    "attempts": attempt,
                },
            )
        except ChatConnectionError as e:
            last_connection_error = e
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            break
        except ChatAuthenticationError as e:
            return ValidationResult(
                passed=False,
                errors=[ERROR_MESSAGES["gateway_auth_failed"]],
                details={"error": str(e), "gateway_url": gateway_url},
            )
        except ChatProtocolError as e:
            return ValidationResult(
                passed=False,
                errors=[ERROR_MESSAGES["gateway_protocol_failed"].format(error=str(e))],
                details={"gateway_url": gateway_url},
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                errors=[ERROR_MESSAGES["gateway_protocol_failed"].format(error=str(e))],
                details={"gateway_url": gateway_url},
            )

    if last_connection_error is not None:
        return ValidationResult(
            passed=False,
            errors=[ERROR_MESSAGES["gateway_unreachable"].format(endpoint=gateway_url)],
            details={
                "error": str(last_connection_error),
                "gateway_url": gateway_url,
                "attempts": retries,
            },
        )

    return ValidationResult(
        passed=False,
        errors=[
            ERROR_MESSAGES["gateway_protocol_failed"].format(error="Unknown error")
        ],
        details={"gateway_url": gateway_url},
    )


def validate_agent_installation(host: str, claw_name: str) -> ValidationResult:
    """Validate agent is installed on the host.

    This is a placeholder for agent installation validation.
    In the future, this will verify:
    - Claw binary/installation exists
    - File permissions are correct
    - User/group ownership is correct

    Args:
        host: Host alias, hostname, or key_id.
        claw_name: Name of the claw instance.

    Returns:
        ValidationResult with installation status.
    """
    from clawrium.core.hosts import get_host_by_key_id

    host_data = get_host(host)
    # Fallback to key_id lookup if hostname/alias lookup failed
    if not host_data:
        host_data = get_host_by_key_id(host)
    if not host_data:
        return ValidationResult(
            passed=False,
            errors=[f"Host '{host}' not found."],
        )

    agents = host_data.get("agents", {})
    claw_data = agents.get(claw_name)

    if not claw_data:
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["agent_not_installed"].format(
                    claw_type=claw_name, host=host
                )
            ],
        )

    return ValidationResult(
        passed=True,
        details={
            "claw_name": claw_name,
            "version": claw_data.get("version"),
            "status": claw_data.get("status"),
        },
    )

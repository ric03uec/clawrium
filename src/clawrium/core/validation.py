"""Validation utilities for agent onboarding.

This module provides validation functions to verify agent configuration
and connectivity before transitioning to READY state.
"""

import asyncio
import json
import re
import socket
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host


# Reused for shell-argument safety in validate_hermes_health: the agent name is
# interpolated into a sudo command line, so we re-validate at point of use
# (defense-in-depth) even though hosts.json is normally trusted.
_AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

__all__ = [
    "ValidationResult",
    "validate_soul_md",
    "validate_provider_config",
    "validate_provider_api_key",
    "verify_provider_connectivity",
    "validate_openclaw_gateway",
    "validate_hermes_health",
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
    "bedrock_credentials": (
        "AWS credentials not configured for Bedrock provider '{provider}'. "
        "Run: clm provider add --type bedrock --name <name>"
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
    "hermes_binary_missing": (
        "`hermes --version` failed on host '{host}'. "
        "The hermes binary is missing or not in the agent user's PATH."
    ),
    "hermes_env_missing": (
        "`~/.hermes/.env` does not exist for agent '{claw_name}' on host '{host}'. "
        "Run 'clm agent configure {claw_name} --stage providers' first."
    ),
    "hermes_health_failed": (
        "api_server /health did not return 200 for agent '{claw_name}' on host '{host}'. "
        "The hermes service is not healthy. Inspect 'journalctl -u hermes-{claw_name}.service'."
    ),
}

WARNING_MESSAGES = {
    "soul_md_empty": "SOUL.md file is empty. Agent will use default personality.",
    "soul_md_large": "SOUL.md is larger than 10KB. Consider shortening for better performance.",
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

    # Ollama connectivity is skipped: this check runs on the control
    # machine (where `clm` is invoked), but Ollama will be reached from
    # the agent host at runtime. A control-machine probe can fail purely
    # because the operator's laptop is on a different network than the
    # agent host, even when the agent → Ollama path works fine. The
    # correct fix is to move the probe into the configure playbook so
    # ansible runs it on the agent host. Tracked as a follow-up; the
    # implementation must use Ansible's `uri:` module (not shell/curl)
    # and re-run validate_ollama_url() at read time to block SSRF from
    # a hand-edited providers.json.
    if provider_type == "ollama":
        endpoint = provider.get("endpoint", "")
        endpoint_display = endpoint or "<endpoint not configured>"
        return ValidationResult(
            passed=True,
            warnings=[
                f"Ollama endpoint {endpoint_display}: this probe runs on the "
                "control machine, but the agent will reach Ollama from the "
                "agent host. Verify reachability manually from the agent "
                f"host, e.g.: ssh <agent-host> curl -fsS "
                f"{endpoint_display}/api/tags"
            ],
            details={"type": "ollama", "skipped": True, "endpoint": endpoint},
        )

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


def _test_bedrock_connectivity(provider: dict, timeout: int) -> ValidationResult:
    """Verify AWS credentials are configured for Bedrock (local check only;
    no network probe)."""
    from clawrium.core.providers.storage import get_provider_aws_credentials

    provider_name = provider.get("name", "")
    aws_key, aws_secret = get_provider_aws_credentials(provider_name)

    if not aws_key or not aws_secret:
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["bedrock_credentials"].format(provider=provider_name)
            ],
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


def validate_hermes_health(
    host: str,
    claw_name: str,
    timeout: int = 30,
) -> ValidationResult:
    """Validate hermes agent health on a remote host.

    Runs three checks via Ansible against the agent user on the remote host:

    1. ``hermes --version`` exits 0 (binary present and runnable).
    2. ``~/.hermes/.env`` exists (configure has been run at least once).
    3. ``curl -fsS http://127.0.0.1:8642/health`` returns 200 (api_server up).

    The api_server platform binds to loopback on the agent host by design,
    so the /health probe must be issued from inside that host. We use the
    same ansible-runner infrastructure as the rest of clm rather than
    setting up a port-forward.

    Args:
        host: Host alias, hostname, or key_id.
        claw_name: Name of the hermes agent instance.
        timeout: Ansible-runner timeout in seconds.

    Returns:
        ValidationResult with pass/fail status. On failure, ``errors``
        contains one entry per failed check; ``details`` carries the raw
        stdout/stderr/rc for the failing check (when available).
    """
    import ansible_runner
    import os
    import shutil
    import tempfile
    from clawrium.core import keys as core_keys
    from clawrium.core.hosts import get_host_by_key_id

    # Defense-in-depth: claw_name is interpolated into a `sudo -u <name>` shell
    # command below. hosts.json is normally trusted (the canonical writer is
    # `clm agent install` which validates the name via validate_agent_name()),
    # but we re-validate at point of use so a corrupted record can never
    # trigger shell injection through this path.
    if not _AGENT_NAME_PATTERN.match(claw_name):
        return ValidationResult(
            passed=False,
            errors=[
                f"Invalid agent name '{claw_name}'. Must start with a lowercase "
                f"letter and contain only lowercase letters, digits, hyphens, "
                f"underscores (max 32 chars)."
            ],
        )

    host_data = get_host(host)
    if not host_data:
        host_data = get_host_by_key_id(host)
    if not host_data:
        return ValidationResult(
            passed=False,
            errors=[f"Host '{host}' not found."],
        )

    hostname = host_data["hostname"]
    display_host = host_data.get("alias") or hostname

    agents = host_data.get("agents", {})
    claw_record = agents.get(claw_name)
    if not isinstance(claw_record, dict):
        return ValidationResult(
            passed=False,
            errors=[
                ERROR_MESSAGES["agent_not_installed"].format(
                    claw_type=claw_name, host=display_host
                )
            ],
        )

    key_id = host_data.get("key_id") or hostname
    ssh_key = core_keys.get_host_private_key(key_id)
    if not ssh_key:
        return ValidationResult(
            passed=False,
            errors=[
                f"SSH key for host '{key_id}' not found. "
                f"Run 'clm host init {hostname}' to provision it."
            ],
        )

    inventory = {
        "all": {
            "hosts": {
                hostname: {
                    "ansible_user": host_data.get("user", "xclm"),
                    "ansible_port": host_data.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            }
        }
    }

    # Three independent checks. Each runs as the agent user on the remote host
    # via `sudo -u <agent_name> bash` (NOT `-i`/login shell — the hermes user
    # ships with /usr/sbin/nologin as its login shell by design, so a login
    # shell would refuse to start). We set HOME and PATH explicitly so the
    # `hermes` symlink in ~/.local/bin resolves and ~/.hermes/.env is found.
    # Ansible's `shell` module defaults to /bin/sh (dash) which doesn't
    # support `set -o pipefail`; we don't need a pipefail since each check
    # captures its own rc into a sentinel line.
    agent_home = f"/home/{claw_name}"
    shell_cmd = (
        f"sudo -u {claw_name} bash -c '"
        f"  export HOME={agent_home}; "
        f'  export PATH={agent_home}/.local/bin:$PATH; '
        f"  echo BINARY_CHECK; "
        f"  hermes --version 2>&1; "
        f"  echo BINARY_RC=$?; "
        f"  echo ENV_CHECK; "
        f"  test -f {agent_home}/.hermes/.env && echo ENV_OK || echo ENV_MISSING; "
        f"  echo HEALTH_CHECK; "
        f'  curl -fsS -o /dev/null -w "%{{http_code}}\\n" http://127.0.0.1:8642/health '
        f"     || echo CURL_FAILED"
        f"'"
    )

    errors: list[str] = []
    details: dict[str, Any] = {}

    # Ansible-runner writes the inventory (host IPs, SSH key paths) into
    # `private_data_dir`. Using /tmp directly would leak those to other local
    # users; create a per-run 0o700 directory and clean it up unconditionally.
    # IMPORTANT: ansible_runner.Runner.events is a lazy iterator that reads
    # the on-disk job_events directory at iteration time, so we must keep the
    # directory alive while collecting stdout below and only clean up at the
    # very end of the function.
    runner_dir = tempfile.mkdtemp(prefix="clawrium-validate-hermes-")
    try:
        os.chmod(runner_dir, 0o700)
        try:
            result = ansible_runner.run(
                private_data_dir=runner_dir,
                inventory=inventory,
                host_pattern=hostname,
                module="shell",
                module_args=shell_cmd,
                quiet=True,
                timeout=timeout,
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                errors=[
                    f"Failed to run hermes health checks on '{display_host}': {e}"
                ],
            )

        # Drain events while the runner dir is still on disk; the iterator
        # reads job_events lazily so it MUST be consumed inside this try.
        stdout = ""
        rc = None
        unreachable_msg: str | None = None
        for event in result.events:
            ev_type = event.get("event")
            if ev_type in ("runner_on_ok", "runner_on_failed"):
                res = event.get("event_data", {}).get("res", {})
                stdout = res.get("stdout", "") or ""
                rc = res.get("rc")
                break
            if ev_type == "runner_on_unreachable":
                res = event.get("event_data", {}).get("res", {})
                unreachable_msg = res.get("msg", "host unreachable")
                break
    finally:
        shutil.rmtree(runner_dir, ignore_errors=True)

    if unreachable_msg is not None:
        return ValidationResult(
            passed=False,
            errors=[f"Host '{display_host}' unreachable: {unreachable_msg}"],
        )

    details["raw_stdout"] = stdout
    details["rc"] = rc

    # Parse stdout line-by-line. We tolerate ordering surprises by scanning
    # for each marker and the value on the following line(s).
    lines = stdout.splitlines()

    # Binary check: BINARY_RC line carries the rc of `hermes --version`.
    binary_rc: int | None = None
    for line in lines:
        if line.startswith("BINARY_RC="):
            try:
                binary_rc = int(line.split("=", 1)[1].strip())
            except (ValueError, IndexError):
                binary_rc = None
            break
    if binary_rc != 0:
        errors.append(
            ERROR_MESSAGES["hermes_binary_missing"].format(host=display_host)
        )

    # Env check: literal token ENV_OK or ENV_MISSING.
    env_ok = "ENV_OK" in lines
    env_missing = "ENV_MISSING" in lines
    if env_missing or not env_ok:
        errors.append(
            ERROR_MESSAGES["hermes_env_missing"].format(
                claw_name=claw_name, host=display_host
            )
        )

    # Health check: the curl line prints the HTTP status code (e.g. "200"),
    # or "CURL_FAILED" on connection failure. Find the line immediately
    # after the HEALTH_CHECK marker.
    health_status = None
    for i, line in enumerate(lines):
        if line.strip() == "HEALTH_CHECK" and i + 1 < len(lines):
            health_status = lines[i + 1].strip()
            break
    if health_status != "200":
        errors.append(
            ERROR_MESSAGES["hermes_health_failed"].format(
                claw_name=claw_name, host=display_host
            )
        )
    details["health_status"] = health_status
    details["binary_rc"] = binary_rc
    details["env_ok"] = env_ok

    return ValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        details=details,
    )

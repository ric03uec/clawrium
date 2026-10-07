"""Bounded provider selection and private activation for Pi agents.

Pi 0.73.1 accepts the ``openrouter`` and ``amazon-bedrock`` providers directly
on its CLI. Clawrium owns the selection and writes only agent-scoped activation
files. In particular, Bedrock uses an AWS Identity Center profile in the Pi
account; static AWS keys and a controller's AWS directory are never copied.
"""

from __future__ import annotations

import fcntl
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from clawrium.core.config import init_config_dir

__all__ = [
    "PI_PROVIDER_ENVIRONMENT_PATH",
    "PI_AWS_CONFIG_PATH",
    "PiProvisioningError",
    "PiProviderSelection",
    "pi_credential_lock",
    "pi_chat_argv",
    "render_bedrock_sso_environment",
    "render_bedrock_sso_config",
    "render_openrouter_environment",
    "validate_bedrock_sso_provider",
    "validate_pi_provider",
    "validate_openrouter_provider",
]

PI_PROVIDER_ENVIRONMENT_PATH = ".pi/agent/clawrium-provider.env"
PI_AWS_CONFIG_PATH = ".pi/agent/clawrium-aws-config"
_PI_LOCK_STATE = threading.local()
# ``init_config_dir`` temporarily changes the process-wide umask. Serialize
# first-time lock-directory setup so concurrent lifecycle operations cannot
# restore each other's prior umask value.
_PI_LOCK_DIRECTORY_INIT = threading.Lock()
# Provider/model IDs accepted by Pi 0.73.1. Reject whitespace, option-like
# values, provider prefixes, and shell/control characters.
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_REGION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_ACCOUNT_RE = re.compile(r"^\d{12}$")
_ROLE_RE = re.compile(r"^[A-Za-z0-9+=,.@_-]{1,64}$")
_SSO_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?$")


@contextmanager
def pi_credential_lock(agent_name: str):
    """Serialize Pi credential lifecycle actions across local CLI processes."""
    held = getattr(_PI_LOCK_STATE, "held", {})
    if agent_name in held:
        held[agent_name] += 1
        _PI_LOCK_STATE.held = held
        try:
            yield
        finally:
            held[agent_name] -= 1
        return

    with _PI_LOCK_DIRECTORY_INIT:
        lock_dir = init_config_dir() / "locks"
        lock_dir.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(str(lock_dir / f"pi-{agent_name}.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        held[agent_name] = 1
        _PI_LOCK_STATE.held = held
        yield
    finally:
        held.pop(agent_name, None)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class PiProvisioningError(ValueError):
    """A Pi provider selection cannot be provisioned safely."""


@dataclass(frozen=True)
class PiProviderSelection:
    provider: str
    model: str


def _model(provider: dict, provider_label: str = "") -> str:
    model = provider.get("default_model")
    if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
        prefix = (
            f"Pi requires a supported {provider_label} default_model"
            if provider_label
            else "Pi requires a supported default_model"
        )
        raise PiProvisioningError(
            f"{prefix} (1-192 characters: letters, digits, '.', '_', ':', '/', '-')"
        )
    return model


def validate_openrouter_provider(provider: object) -> str:
    """Return the selected OpenRouter model or a secret-free error."""
    if not isinstance(provider, dict) or provider.get("type") != "openrouter":
        raise PiProvisioningError(
            "Pi supports only an OpenRouter or AWS SSO-backed Bedrock provider"
        )
    model = _model(provider, "OpenRouter")
    if model.startswith("openrouter/"):
        raise PiProvisioningError(
            "Pi OpenRouter model IDs must not include the 'openrouter/' provider prefix"
        )
    return model


def validate_bedrock_sso_provider(provider: object) -> str:
    """Validate the non-secret Identity Center profile metadata for Pi."""
    if not isinstance(provider, dict) or provider.get("type") != "bedrock":
        raise PiProvisioningError("Pi Bedrock requires a registered bedrock provider")
    if provider.get("credential_source") != "aws-sso":
        raise PiProvisioningError(
            "Pi Bedrock requires AWS Identity Center SSO; static AWS keys are not supported"
        )
    model = _model(provider, "Bedrock")
    required = {
        "aws_profile": _PROFILE_RE,
        "region": _REGION_RE,
        "sso_start_url": _SSO_URL_RE,
        "sso_region": _REGION_RE,
        "sso_account_id": _ACCOUNT_RE,
        "sso_role_name": _ROLE_RE,
    }
    for key, pattern in required.items():
        value = provider.get(key)
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise PiProvisioningError(
                "Pi Bedrock requires valid AWS SSO profile, region, start URL, SSO region, account ID, and role name"
            )
    if model.startswith("amazon-bedrock/"):
        raise PiProvisioningError(
            "Pi Bedrock model IDs must not include the 'amazon-bedrock/' provider prefix"
        )
    return model


def validate_pi_provider(provider: object) -> PiProviderSelection:
    """Return Pi's fixed provider/model pair for supported control-plane records."""
    if isinstance(provider, dict) and provider.get("type") == "openrouter":
        return PiProviderSelection("openrouter", validate_openrouter_provider(provider))
    return PiProviderSelection("amazon-bedrock", validate_bedrock_sso_provider(provider))


def render_openrouter_environment(api_key: str | None) -> str:
    """Render the secret-bearing activation file for the dedicated account."""
    if not isinstance(api_key, str) or any(ord(char) < 32 or ord(char) == 127 for char in api_key):
        raise PiProvisioningError("OpenRouter provider API key contains unsupported control characters")
    if not api_key:
        raise PiProvisioningError(
            "OpenRouter provider is missing API key in secrets.json; set it with `clawctl provider registry update <provider> --api-key-stdin`"
        )
    return f"OPENROUTER_API_KEY={api_key}\n"


def render_bedrock_sso_environment(profile: str, region: str) -> str:
    """Render non-secret, agent-local AWS activation for Pi's credential chain."""
    if not _PROFILE_RE.fullmatch(profile) or not _REGION_RE.fullmatch(region):
        raise PiProvisioningError("Pi Bedrock AWS profile or region is invalid")
    return f"AWS_PROFILE={profile}\nAWS_REGION={region}\nAWS_CONFIG_FILE=$HOME/{PI_AWS_CONFIG_PATH}\n"


def render_bedrock_sso_config(provider: object) -> str:
    """Render one isolated Identity Center profile, never a token cache or key."""
    validate_bedrock_sso_provider(provider)
    assert isinstance(provider, dict)
    return (
        f"[profile {provider['aws_profile']}]\n"
        f"sso_start_url = {provider['sso_start_url']}\n"
        f"sso_region = {provider['sso_region']}\n"
        f"sso_account_id = {provider['sso_account_id']}\n"
        f"sso_role_name = {provider['sso_role_name']}\n"
        f"region = {provider['region']}\n"
    )


def pi_chat_argv(model: str, session_id: str, *, resume: bool, provider: str = "openrouter") -> list[str]:
    """Build fixed Pi print-mode argv; all caller values are validated first."""
    selection = validate_pi_provider(
        {"type": "openrouter", "default_model": model}
        if provider == "openrouter"
        else {
            "type": "bedrock", "credential_source": "aws-sso", "default_model": model,
            "aws_profile": "profile", "region": "us-east-1", "sso_start_url": "https://example.awsapps.com/start",
            "sso_region": "us-east-1", "sso_account_id": "123456789012", "sso_role_name": "Role",
        }
    )
    if provider not in {"openrouter", "amazon-bedrock"}:
        raise PiProvisioningError("Pi provider is unsupported")
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27,35}", session_id):
        raise PiProvisioningError("Pi chat session is invalid")
    argv = ["--provider", selection.provider, "--model", selection.model, "--print", "--no-tools", "--no-context-files", "--no-extensions"]
    argv.extend(["--session-dir", f".pi/agent/clawrium-sessions/{session_id}"])
    if resume:
        argv.append("--continue")
    return argv

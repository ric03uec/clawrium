"""Local-only credential modes for dedicated Claude Code agents.

This module owns only the local credential-selection boundary. It never
renders credentials, updates host/provider metadata, or opens a remote
transport; those concerns deliberately belong to later Claude phases.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from clawrium.core.secrets import (
    AgentNotFoundError,
    get_instance_key,
    get_instance_secrets,
    get_installed_claw,
    replace_instance_secret,
)

__all__ = [
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ClaudeCredentialError",
    "ClaudeCredentialMode",
    "ClaudeCredentialState",
    "ClaudeOAuthSourceError",
    "OAUTH_TOKEN_ENVIRONMENT_VARIABLE",
    "configure_claude_credentials",
    "get_active_claude_credential",
    "get_claude_credential_state",
    "import_claude_oauth_from_environment",
]


CLAUDE_CODE_OAUTH_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
OAUTH_TOKEN_ENVIRONMENT_VARIABLE = CLAUDE_CODE_OAUTH_TOKEN


class ClaudeCredentialError(ValueError):
    """Raised when Claude Code credential modes are invalid or ambiguous."""


class ClaudeOAuthSourceError(ClaudeCredentialError):
    """Raised when the explicit portable OAuth environment source is absent."""


class ClaudeCredentialMode(str, Enum):
    """The two mutually exclusive Claude Code credential modes."""

    OAUTH = "oauth"
    API_KEY = "api_key"


@dataclass(frozen=True)
class ClaudeCredentialState:
    """Non-secret local credential state for one Claude Code instance.

    ``mode`` is derived from encrypted per-instance secret keys. It carries
    neither a credential value nor a source path so the state is safe to use
    in validation and status code.
    """

    mode: ClaudeCredentialMode | None


_MODE_KEYS: dict[ClaudeCredentialMode, str] = {
    ClaudeCredentialMode.OAUTH: CLAUDE_CODE_OAUTH_TOKEN,
    ClaudeCredentialMode.API_KEY: ANTHROPIC_API_KEY,
}
_CONTROL_OR_WHITESPACE = re.compile(r"[\x00-\x20\x7f]")


def _resolve_claude_instance_key(agent_name: str) -> str:
    """Resolve a dedicated Claude agent to its stable per-instance key."""
    try:
        host_key, agent_type, canonical_name = get_installed_claw(agent_name)
    except AgentNotFoundError:
        raise
    if agent_type != "claude":
        raise ClaudeCredentialError(
            f"agent {agent_name!r} is type {agent_type!r}, not a Claude Code agent"
        )
    return get_instance_key(host_key, agent_type, canonical_name)


def _normalize_credential(value: object, *, label: str) -> str:
    """Normalize a caller-supplied credential without ever echoing it."""
    if not isinstance(value, str):
        raise ClaudeCredentialError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ClaudeCredentialError(f"{label} cannot be empty")
    if _CONTROL_OR_WHITESPACE.search(normalized):
        raise ClaudeCredentialError(
            f"{label} must not contain whitespace or control characters"
        )
    return normalized


def _normalize_oauth_token(value: object) -> str:
    """Normalize a portable bearer token to its token-only form."""
    if not isinstance(value, str):
        raise ClaudeCredentialError("OAuth token must be a string")
    normalized = value.strip()
    if normalized.lower() == "bearer":
        raise ClaudeCredentialError("OAuth token cannot be empty")
    if normalized[:7].lower() == "bearer ":
        normalized = normalized[7:].strip()
    return _normalize_credential(normalized, label="OAuth token")


def get_claude_credential_state(agent_name: str) -> ClaudeCredentialState:
    """Return the non-secret active credential mode for ``agent_name``.

    A manually-created or stale pair of Claude credential keys is unsafe:
    callers must resolve it explicitly instead of guessing which credential is
    active.
    """
    instance_key = _resolve_claude_instance_key(agent_name)
    entries = get_instance_secrets(instance_key)
    active_modes = [mode for mode, key in _MODE_KEYS.items() if key in entries]
    if len(active_modes) > 1:
        raise ClaudeCredentialError(
            f"agent {agent_name!r} has conflicting Claude credential modes; "
            "configure exactly one OAuth token or Anthropic API key"
        )
    return ClaudeCredentialState(mode=active_modes[0] if active_modes else None)


def get_active_claude_credential(agent_name: str) -> tuple[str, str]:
    """Return the selected local credential for remote activation.

    The tuple is intentionally the narrow bridge to the next lifecycle phase:
    callers receive one already-selected key and its value, never both modes or
    any host/settings/provider state.  Errors name only the invalid state, not
    the credential value.
    """
    state = get_claude_credential_state(agent_name)
    if state.mode is None:
        raise ClaudeCredentialError(
            "Claude Code credential is not configured; select OAuth or an Anthropic API key"
        )

    secret_key = _MODE_KEYS[state.mode]
    instance_key = _resolve_claude_instance_key(agent_name)
    entry = get_instance_secrets(instance_key).get(secret_key)
    value = entry.get("value") if isinstance(entry, dict) else None
    try:
        normalized = (
            _normalize_oauth_token(value)
            if state.mode is ClaudeCredentialMode.OAUTH
            else _normalize_credential(value, label="Anthropic API key")
        )
    except ClaudeCredentialError as exc:
        raise ClaudeCredentialError(
            "Claude Code credential in the encrypted secrets store is invalid"
        ) from exc
    if normalized != value:
        raise ClaudeCredentialError(
            "Claude Code credential in the encrypted secrets store is invalid"
        )
    return secret_key, value


def configure_claude_credentials(
    agent_name: str,
    *,
    oauth_token: str | None = None,
    anthropic_api_key: str | None = None,
) -> ClaudeCredentialState:
    """Select and securely store exactly one Claude Code credential mode.

    The replacement is committed through ``replace_instance_secret`` so a
    failed switch leaves the old local secret intact. No host record,
    settings object, provider record, event, or remote transport is involved.
    """
    has_oauth = oauth_token is not None
    has_api_key = anthropic_api_key is not None
    if has_oauth == has_api_key:
        raise ClaudeCredentialError(
            "configure exactly one Claude credential mode: OAuth token or Anthropic API key"
        )

    # Fail closed if a hand-edited or legacy store already has both modes.
    get_claude_credential_state(agent_name)
    instance_key = _resolve_claude_instance_key(agent_name)

    if has_oauth:
        mode = ClaudeCredentialMode.OAUTH
        secret_key = CLAUDE_CODE_OAUTH_TOKEN
        secret_value = _normalize_oauth_token(oauth_token)
        superseded_key = ANTHROPIC_API_KEY
        description = "Claude Code OAuth credential"
    else:
        mode = ClaudeCredentialMode.API_KEY
        secret_key = ANTHROPIC_API_KEY
        secret_value = _normalize_credential(
            anthropic_api_key, label="Anthropic API key"
        )
        superseded_key = CLAUDE_CODE_OAUTH_TOKEN
        description = "Claude Code Anthropic API credential"

    replace_instance_secret(
        instance_key,
        secret_key,
        secret_value,
        remove_key=superseded_key,
        description=description,
    )
    return ClaudeCredentialState(mode=mode)


def import_claude_oauth_from_environment(
    agent_name: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> ClaudeCredentialState:
    """Import OAuth only from an explicitly exported environment variable.

    The portable source contract is ``CLAUDE_CODE_OAUTH_TOKEN`` in the
    invoking process environment. This deliberately does not inspect a
    keychain, browser profile, ``~/.claude`` directory, database, or guessed
    OAuth-file path.
    """
    source = os.environ if environment is None else environment
    value = source.get(OAUTH_TOKEN_ENVIRONMENT_VARIABLE)
    if value is None:
        raise ClaudeOAuthSourceError(
            "OAuth import requires an explicitly exported CLAUDE_CODE_OAUTH_TOKEN; "
            "keychains, browser profiles, local .claude directories, and credential "
            "databases are not supported sources"
        )
    return configure_claude_credentials(agent_name, oauth_token=value)

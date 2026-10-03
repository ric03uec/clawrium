"""Local-only credential modes for dedicated Claude Code agents.

This module owns only the local credential-selection boundary. It never
renders credentials, updates host/provider metadata, or opens a remote
transport; those concerns deliberately belong to later Claude phases.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
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
    "ClaudeOAuthCredentialReader",
    "OAUTH_TOKEN_ENVIRONMENT_VARIABLE",
    "configure_claude_credentials",
    "get_active_claude_credential",
    "get_claude_credential_state",
    "import_claude_oauth_from_environment",
    "import_claude_oauth_from_local_reader",
    "read_local_claude_oauth_token",
]


CLAUDE_CODE_OAUTH_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
OAUTH_TOKEN_ENVIRONMENT_VARIABLE = CLAUDE_CODE_OAUTH_TOKEN

# Anthropic documents `claude setup-token` as the supported way to mint a
# long-lived `CLAUDE_CODE_OAUTH_TOKEN` for scripts. The Linux adapter below
# invokes that CLI in a private subprocess rather than reading any local
# credential file, keychain, browser profile, or database.
_CLAUDE_SETUP_TOKEN_PLATFORM = "linux"
_CLAUDE_SETUP_TOKEN_COMMAND = "claude"
_CLAUDE_SETUP_TOKEN_TIMEOUT_SECONDS = 120
_CLAUDE_SETUP_TOKEN_LINE = re.compile(
    r"(?m)^\s*(?:export\s+)?CLAUDE_CODE_OAUTH_TOKEN\s*=\s*(?P<value>[^\s]+)\s*$"
)
_CREDENTIAL_SOURCE_ENVIRONMENT_VARIABLES = (
    CLAUDE_CODE_OAUTH_TOKEN,
    ANTHROPIC_API_KEY,
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
)

ClaudeOAuthCredentialReader = Callable[[], object]


class ClaudeCredentialError(ValueError):
    """Raised when Claude Code credential modes are invalid or ambiguous."""


class ClaudeOAuthSourceError(ClaudeCredentialError):
    """Raised when the supported local Claude OAuth source is unavailable."""


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


def read_local_claude_oauth_token() -> str:
    """Mint an OAuth token through Claude Code's documented Linux CLI path.

    `claude setup-token` performs Claude Code's browser authorization flow
    and writes the resulting token to its standard streams. Both streams are
    captured in memory and are deliberately never forwarded to a terminal,
    logger, exception, or subprocess argument. The caller environment's
    credential overrides are removed so this source cannot silently fall back
    to an already-exported bearer or API key.
    """
    if sys.platform != _CLAUDE_SETUP_TOKEN_PLATFORM:
        raise ClaudeOAuthSourceError(
            "local Claude OAuth import is supported only on Linux controllers; "
            "no safe credential reader is registered for this platform"
        )

    executable = shutil.which(_CLAUDE_SETUP_TOKEN_COMMAND)
    if executable is None:
        raise ClaudeOAuthSourceError(
            "local Claude OAuth import requires the Claude Code CLI on this Linux controller"
        )

    environment = os.environ.copy()
    for key in _CREDENTIAL_SOURCE_ENVIRONMENT_VARIABLES:
        environment.pop(key, None)

    try:
        result = subprocess.run(
            [executable, "setup-token"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_CLAUDE_SETUP_TOKEN_TIMEOUT_SECONDS,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        raise ClaudeOAuthSourceError(
            "local Claude OAuth import timed out; complete Claude Code authorization and retry"
        ) from None
    except OSError:
        raise ClaudeOAuthSourceError(
            "could not run the local Claude Code credential reader"
        ) from None

    if result.returncode != 0:
        raise ClaudeOAuthSourceError(
            "local Claude OAuth import failed; sign in with Claude Code and retry"
        )

    matches = list(
        _CLAUDE_SETUP_TOKEN_LINE.finditer(result.stdout + "\n" + result.stderr)
    )
    if len(matches) != 1:
        raise ClaudeOAuthSourceError(
            "local Claude OAuth import returned an unrecognized credential response; "
            "update Claude Code and retry"
        )
    return matches[0].group("value")


def import_claude_oauth_from_local_reader(
    agent_name: str,
    *,
    reader: ClaudeOAuthCredentialReader | None = None,
) -> ClaudeCredentialState:
    """Read and store OAuth through the selected safe local-reader seam.

    Tests inject ``reader`` so ordinary test runs never access local Claude
    credentials. Reader failures are normalized to fixed, secret-free errors;
    only the normalized token reaches the encrypted per-instance secret store.
    """
    source = read_local_claude_oauth_token if reader is None else reader
    try:
        value = source()
    except ClaudeOAuthSourceError:
        raise ClaudeOAuthSourceError(
            "local Claude OAuth credential reader is unavailable"
        ) from None
    except Exception:
        raise ClaudeOAuthSourceError(
            "local Claude OAuth credential reader failed"
        ) from None
    return configure_claude_credentials(agent_name, oauth_token=value)


def import_claude_oauth_from_environment(
    agent_name: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> ClaudeCredentialState:
    """Import a caller-supplied OAuth value for backwards-compatible APIs.

    This helper remains available to code that already supplies a value, but
    the normal Claude provider workflow uses ``claude setup-token`` through
    ``import_claude_oauth_from_local_reader`` instead. It never probes local
    credential stores.
    """
    source = os.environ if environment is None else environment
    value = source.get(OAUTH_TOKEN_ENVIRONMENT_VARIABLE)
    if value is None:
        raise ClaudeOAuthSourceError(
            "OAuth token value is not available from the supplied environment"
        )
    return configure_claude_credentials(agent_name, oauth_token=value)

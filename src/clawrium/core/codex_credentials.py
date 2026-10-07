"""Local-only OAuth credential import for dedicated Codex agents.

This module owns the controller-side ``$CODEX_HOME/auth.json`` reader and
per-instance encrypted snapshot.  It never renders or transfers the snapshot;
credential activation is deliberately a later lifecycle phase.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from clawrium.core.config import init_config_dir
from clawrium.core.secrets import (
    AgentNotFoundError,
    get_instance_key,
    get_instance_secrets,
    get_installed_claw,
    replace_instance_secret,
)

__all__ = [
    "CODEX_OAUTH_DOCUMENT",
    "CODEX_OAUTH_PENDING_ACTIVATION",
    "CodexCredentialError",
    "CodexCredentialState",
    "CodexOAuthCredentialReader",
    "CodexOAuthSourceError",
    "configure_codex_oauth",
    "codex_oauth_activation_error_for_display",
    "codex_oauth_activation_id",
    "codex_oauth_activation_pending",
    "codex_oauth_operation_lock",
    "get_codex_oauth_document",
    "mark_codex_oauth_activated",
    "get_codex_oauth_instance_key",
    "get_codex_credential_state",
    "import_codex_oauth_from_local_reader",
    "normalize_codex_oauth_document",
    "read_local_codex_oauth_document",
]

CODEX_OAUTH_DOCUMENT = "CODEX_OAUTH_DOCUMENT"
# Set by provider attach (including an explicit re-attach).  Lifecycle consumes
# this private marker only after a successful remote replacement, so routine
# syncs leave a Codex-refreshed remote document alone.
CODEX_OAUTH_PENDING_ACTIVATION = "CODEX_OAUTH_PENDING_ACTIVATION"
_CODEX_OAUTH_REATTACH_MESSAGE = "credential activation failed; re-attach the codex-oauth provider"
# These strings originate solely from the lifecycle's fixed failure categories.
# Never display a backend/playbook exception that is not on this allowlist.
_CODEX_SAFE_ACTIVATION_ERRORS = frozenset({
    "Codex configuration does not accept extra variables",
    "SSH key not found",
    "Codex activation playbook did not complete successfully; inspect agent-host Ansible logs",
    "Codex activation playbook is unavailable",
    "Codex activation encountered an internal error",
})
_CODEX_HOME_ENVIRONMENT_VARIABLE = "CODEX_HOME"
_CODEX_AUTH_FILENAME = "auth.json"
_CODEX_AUTH_MAX_BYTES = 64 * 1024

# Codex 0.160.1's file-backed ChatGPT login schema.  API-key and keyring
# modes are intentionally not importable: a selection-only provider must not
# mistake either for subscription OAuth credentials.
_CODEX_AUTH_ROOT_FIELDS = {"auth_mode": str, "tokens": dict, "last_refresh": str}
_CODEX_AUTH_TOKEN_FIELDS = {
    "access_token": str,
    "refresh_token": str,
    "id_token": str,
    "account_id": str,
}
_CODEX_AUTH_REQUIRED_TOKEN_FIELDS = frozenset(
    {"access_token", "refresh_token", "id_token"}
)

CodexOAuthCredentialReader = Callable[[], object]


class CodexCredentialError(ValueError):
    """Raised when Codex OAuth selection or stored state is invalid."""


_OAUTH_SOURCE_CATEGORIES = frozenset(
    {
        "credentials_artifact_unavailable",
        "credentials_artifact_insecure",
        "credentials_artifact_too_large",
        "credentials_artifact_malformed",
        "credentials_auth_mode_unsupported",
        "credentials_token_missing",
        "unknown_reader_failure",
    }
)


class CodexOAuthSourceError(CodexCredentialError):
    """A secret-free category for an unavailable local Codex OAuth source."""

    def __init__(self, category: str):
        self.category = (
            category
            if category in _OAUTH_SOURCE_CATEGORIES
            else "unknown_reader_failure"
        )
        super().__init__(
            f"local Codex OAuth source unavailable (category={self.category})"
        )


@dataclass(frozen=True)
class CodexCredentialState:
    """Non-secret selected credential state for a Codex instance."""

    configured: bool


@contextmanager
def codex_oauth_operation_lock(agent_name: str):
    """Serialize OAuth changes for one canonical Codex agent instance."""
    digest = hashlib.sha256(
        get_codex_oauth_instance_key(agent_name).encode()
    ).hexdigest()
    lock_path = init_config_dir() / f".codex-oauth-{digest}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _resolve_codex_instance_key(agent_name: str) -> str:
    try:
        host_key, agent_type, canonical_name = get_installed_claw(agent_name)
    except AgentNotFoundError:
        raise
    if agent_type != "codex":
        raise CodexCredentialError(
            f"agent {agent_name!r} is type {agent_type!r}, not a Codex agent"
        )
    return get_instance_key(host_key, agent_type, canonical_name)


def _auth_path() -> Path:
    """Return the one supported file-backed Codex auth location."""
    configured_home = os.environ.get(_CODEX_HOME_ENVIRONMENT_VARIABLE)
    home = (
        Path(configured_home).expanduser()
        if configured_home
        else Path.home() / ".codex"
    )
    return home / _CODEX_AUTH_FILENAME


def _validate_native_codex_oauth_document(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) - set(_CODEX_AUTH_ROOT_FIELDS):
        raise CodexOAuthSourceError("credentials_artifact_malformed")
    for key, expected_type in _CODEX_AUTH_ROOT_FIELDS.items():
        if key in raw and not isinstance(raw[key], expected_type):
            raise CodexOAuthSourceError("credentials_artifact_malformed")
    if raw.get("auth_mode") != "chatgpt":
        raise CodexOAuthSourceError("credentials_auth_mode_unsupported")

    tokens = raw.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexOAuthSourceError("credentials_token_missing")
    if set(tokens) - set(_CODEX_AUTH_TOKEN_FIELDS):
        raise CodexOAuthSourceError("credentials_artifact_malformed")
    if not _CODEX_AUTH_REQUIRED_TOKEN_FIELDS.issubset(tokens):
        raise CodexOAuthSourceError("credentials_token_missing")
    if any(
        not isinstance(value, str) or not value.strip() for value in tokens.values()
    ):
        raise CodexOAuthSourceError("credentials_artifact_malformed")

    cleaned: dict[str, object] = {
        "auth_mode": "chatgpt",
        "tokens": {key: tokens[key] for key in sorted(tokens)},
    }
    if "last_refresh" in raw:
        cleaned["last_refresh"] = raw["last_refresh"]
    return cleaned


def _serialize_oauth_document_for_storage(document: dict[str, object]) -> str:
    return json.dumps(document, separators=(",", ":"), sort_keys=True)


def _read_private_codex_auth_artifact() -> str:
    path = _auth_path()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise CodexOAuthSourceError("credentials_artifact_unavailable") from None

    payload = bytearray()
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or details.st_mode & 0o077
        ):
            raise CodexOAuthSourceError("credentials_artifact_insecure")
        if details.st_size > _CODEX_AUTH_MAX_BYTES:
            raise CodexOAuthSourceError("credentials_artifact_too_large")
        while True:
            chunk = os.read(descriptor, _CODEX_AUTH_MAX_BYTES + 1 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > _CODEX_AUTH_MAX_BYTES:
                raise CodexOAuthSourceError("credentials_artifact_too_large")
    except CodexOAuthSourceError:
        raise
    except OSError:
        raise CodexOAuthSourceError("credentials_artifact_unavailable") from None
    finally:
        os.close(descriptor)

    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise CodexOAuthSourceError("credentials_artifact_malformed") from None
    finally:
        payload.clear()
    return _serialize_oauth_document_for_storage(
        _validate_native_codex_oauth_document(parsed)
    )


def read_local_codex_oauth_document() -> str:
    """Read and validate the file-backed ``$CODEX_HOME/auth.json`` snapshot."""
    return _read_private_codex_auth_artifact()


def get_codex_oauth_instance_key(agent_name: str) -> str:
    """Return the canonical encrypted-secret scope for a Codex agent."""
    return _resolve_codex_instance_key(agent_name)


def get_codex_credential_state(agent_name: str) -> CodexCredentialState:
    entries = get_instance_secrets(_resolve_codex_instance_key(agent_name))
    return CodexCredentialState(configured=CODEX_OAUTH_DOCUMENT in entries)


def normalize_codex_oauth_document(document: object) -> str:
    """Validate and canonically serialize an OAuth document without storing it."""
    if not isinstance(document, str):
        raise CodexCredentialError("Codex OAuth document must be a string")
    try:
        parsed = json.loads(document)
    except (TypeError, json.JSONDecodeError):
        raise CodexCredentialError("Codex OAuth document is invalid") from None
    return _serialize_oauth_document_for_storage(
        _validate_native_codex_oauth_document(parsed)
    )


def configure_codex_oauth(agent_name: str, *, document: object) -> CodexCredentialState:
    """Validate and atomically store one full native Codex OAuth document."""
    serialized = normalize_codex_oauth_document(document)
    replace_instance_secret(
        _resolve_codex_instance_key(agent_name),
        CODEX_OAUTH_DOCUMENT,
        serialized,
        description="Codex OAuth credential document",
    )
    return CodexCredentialState(configured=True)


def codex_oauth_activation_error_for_display(error: object) -> str:
    """Return only a fixed, credential-safe Codex activation diagnostic."""
    if isinstance(error, str) and (
        error in _CODEX_SAFE_ACTIVATION_ERRORS
        or error.startswith("Codex activation is interrupted; preserve the current auth. ")
    ):
        return error
    return _CODEX_OAUTH_REATTACH_MESSAGE


def codex_oauth_activation_id(agent_name: str) -> str | None:
    """Return the durable, non-secret activation attempt identifier, if any."""
    entries = get_instance_secrets(_resolve_codex_instance_key(agent_name))
    entry = entries.get(CODEX_OAUTH_PENDING_ACTIVATION)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, str) and value.startswith("pending:") else None


def codex_oauth_activation_pending(agent_name: str) -> bool:
    """Whether the selected snapshot must explicitly replace remote auth."""
    return codex_oauth_activation_id(agent_name) is not None


def mark_codex_oauth_activated(agent_name: str) -> None:
    """Clear the replacement request after the remote activation succeeds."""
    from clawrium.core.secrets import remove_instance_secret

    remove_instance_secret(
        _resolve_codex_instance_key(agent_name), CODEX_OAUTH_PENDING_ACTIVATION
    )


def get_codex_oauth_document(agent_name: str) -> str:
    entries = get_instance_secrets(_resolve_codex_instance_key(agent_name))
    entry = entries.get(CODEX_OAUTH_DOCUMENT)
    value = entry.get("value") if isinstance(entry, dict) else None
    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = json.loads(value)
        normalized = _serialize_oauth_document_for_storage(
            _validate_native_codex_oauth_document(parsed)
        )
        if normalized != value:
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError, CodexOAuthSourceError):
        raise CodexCredentialError(
            "Codex OAuth document in the encrypted secrets store is invalid"
        ) from None
    return value


def import_codex_oauth_from_local_reader(
    agent_name: str, *, reader: CodexOAuthCredentialReader | None = None
) -> CodexCredentialState:
    source = read_local_codex_oauth_document if reader is None else reader
    try:
        document = source()
    except CodexOAuthSourceError as exc:
        raise CodexOAuthSourceError(exc.category) from None
    except Exception:
        raise CodexOAuthSourceError("unknown_reader_failure") from None
    return configure_codex_oauth(agent_name, document=document)

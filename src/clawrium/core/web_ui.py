"""Web UI resolver for native agent dashboards.

Phase 1 mechanism for issue #478. Reads `features.web_ui` from an agent's
manifest and `hosts.json` agent record, returning enough structured data
for downstream callers (tunnel manager, CLI `clm agent open`, GUI button)
to act on. URL construction is intentionally *not* performed here.

Returns `None` whenever an agent is not installed or its manifest does
not declare `features.web_ui` — callers should treat `None` as "no native
UI available for this agent".

Bind contract: `bind: "loopback"` in this iteration MUST be interpreted
by downstream callers as the IPv4 address `127.0.0.1`. The `BIND_ADDRESS_MAP`
constant is the single source of truth — Phase 2's tunnel manager and any
future consumer must import it rather than re-deriving the mapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from clawrium.core.hosts import get_agent_by_name
from clawrium.core.registry import (
    ManifestNotFoundError,
    ManifestParseError,
    load_manifest,
)

logger = logging.getLogger(__name__)

# Single source of truth for the `bind` enum → concrete network address.
# Downstream callers MUST consult this map rather than hard-coding 127.0.0.1,
# so that adding new bind modes later remains a single-file change.
BIND_ADDRESS_MAP: dict[str, str] = {"loopback": "127.0.0.1"}

# Characters that must never appear in a host-supplied identity-file path.
# Phase 2's tunnel manager will pass this value to `ssh -i <path>`; rejecting
# null bytes, newlines, and shell metachars at resolve-time means the
# subprocess invocation downstream can trust its inputs.
_FORBIDDEN_IDENTITY_FILE_CHARS = ("\x00", "\n", "\r", ";", "&", "|", "`", "$")


@dataclass(frozen=True)
class ResolvedUI:
    """Resolved native-UI endpoint for an installed agent.

    Attributes:
        host: Primary address (IP or DNS name) of the agent host. Caller
            decides whether this is local (skip SSH) or remote (tunnel).
            Guaranteed non-empty — `resolve()` returns `None` rather than
            constructing a `ResolvedUI` with an empty host.
        remote_port: TCP port the dashboard listens on inside the agent
            host. Sourced from `agent_record.config.<port_field>` when
            persisted, else the manifest's `default_port`.
        bind: Bind scope advertised by the manifest. Closed enum — only
            `"loopback"` is accepted in this iteration. Downstream callers
            should look up the concrete address via `BIND_ADDRESS_MAP[bind]`.
        ssh_config: SSH-tunnel parameters: `user`, optional `port`,
            optional `identity_file`. Empty dict when the host record
            provides no SSH details.
    """

    host: str
    remote_port: int
    bind: Literal["loopback"]
    ssh_config: dict[str, Any] = field(default_factory=dict)


def _dotted_lookup(data: dict[str, Any], path: str) -> Any:
    """Walk a dotted path into a nested dict. Returns None if any step misses."""
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _primary_address(host: dict[str, Any]) -> str:
    """Return the primary address for a host, falling back to `hostname`.

    Empty string indicates "no usable address" — `resolve()` treats that
    as `None` rather than producing a `ResolvedUI` with an empty host.
    """
    addresses = host.get("addresses") or []
    for addr in addresses:
        if isinstance(addr, dict) and addr.get("is_primary"):
            address = addr.get("address")
            if isinstance(address, str) and address:
                return address
    hostname = host.get("hostname")
    return hostname if isinstance(hostname, str) else ""


def _safe_identity_file(value: object) -> str | None:
    """Return a sanitized identity-file path or `None` if it fails the safety check."""
    if not isinstance(value, str) or not value:
        return None
    if any(ch in value for ch in _FORBIDDEN_IDENTITY_FILE_CHARS):
        logger.warning(
            "Dropping identity_file containing forbidden character "
            "(null/newline/shell metachar)"
        )
        return None
    return value


def _build_ssh_config(host: dict[str, Any]) -> dict[str, Any]:
    """Extract SSH connection params from a host record."""
    ssh: dict[str, Any] = {}
    user = host.get("user")
    if isinstance(user, str) and user:
        ssh["user"] = user
    port = host.get("ssh_port")
    if isinstance(port, int) and not isinstance(port, bool) and port > 0:
        ssh["port"] = port
    identity = _safe_identity_file(host.get("ssh_key") or host.get("identity_file"))
    if identity is not None:
        ssh["identity_file"] = identity
    return ssh


def resolve(agent_key: str) -> ResolvedUI | None:
    """Resolve native-UI parameters for an installed agent.

    Args:
        agent_key: User-facing agent name (the key in `hosts.json.agents`).

    Returns:
        `ResolvedUI` if the agent is installed and its manifest declares
        `features.web_ui` with `enabled: true`. Otherwise `None`.

        Specifically returns `None` when:
          - the agent name is empty / whitespace,
          - the agent name is not found in `hosts.json`,
          - the agent name is ambiguous across hosts,
          - the host record has no usable primary address,
          - the agent's manifest cannot be loaded,
          - the manifest does not declare `features.web_ui`,
          - `features.web_ui.enabled` is `False`.
    """
    if not isinstance(agent_key, str) or not agent_key.strip():
        return None

    try:
        match = get_agent_by_name(agent_key)
    except ValueError as exc:
        # `get_agent_by_name` raises `ValueError` on ambiguous matches across
        # hosts. We treat that as "no native UI available" rather than
        # crashing — callers (CLI / GUI) render "not available" instead of
        # a stack trace. Logged at WARNING so operators can act on it.
        logger.warning(
            "resolve(%s): agent name is ambiguous across multiple hosts — "
            "use '<name>@<host>' to disambiguate (%s)",
            agent_key,
            exc,
        )
        return None

    if match is None:
        return None

    host_record, agent_type, agent_record = match

    try:
        manifest = load_manifest(agent_type)
    except ManifestNotFoundError as exc:
        # Agent type with no bundled manifest — legitimate "no feature" path.
        # Debug-level keeps production logs quiet.
        logger.debug(
            "resolve(%s): no manifest for type %r: %s", agent_key, agent_type, exc
        )
        return None
    except ManifestParseError as exc:
        # Corrupt manifest is operator-actionable — surface it.
        logger.warning(
            "resolve(%s): manifest for type %r is corrupted: %s — "
            "run 'clm registry list' to verify",
            agent_key,
            agent_type,
            exc,
        )
        return None

    web_ui = manifest.get("features", {}).get("web_ui")
    if not web_ui or not web_ui.get("enabled"):
        return None

    host = _primary_address(host_record)
    if not host:
        return None

    config = agent_record.get("config") or {}
    persisted_port = _dotted_lookup(config, web_ui["port_field"])
    if (
        isinstance(persisted_port, int)
        and not isinstance(persisted_port, bool)
        and 0 < persisted_port <= 65535
    ):
        remote_port = persisted_port
    else:
        remote_port = web_ui["default_port"]

    return ResolvedUI(
        host=host,
        remote_port=remote_port,
        bind=web_ui["bind"],
        ssh_config=_build_ssh_config(host_record),
    )

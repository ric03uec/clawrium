"""Web UI resolver for native agent dashboards.

Phase 1 mechanism for issue #478. Reads `features.web_ui` from an agent's
manifest and `hosts.json` agent record, returning enough structured data
for downstream callers (tunnel manager, CLI `clm agent open`, GUI button)
to act on. URL construction is intentionally *not* performed here.

Returns `None` whenever an agent is not installed or its manifest does
not declare `features.web_ui` — callers should treat `None` as "no native
UI available for this agent".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from clawrium.core.hosts import get_agent_by_name
from clawrium.core.registry import (
    ManifestNotFoundError,
    ManifestParseError,
    load_manifest,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedUI:
    """Resolved native-UI endpoint for an installed agent.

    Attributes:
        host: Primary address (IP or DNS name) of the agent host. Caller
            decides whether this is local (skip SSH) or remote (tunnel).
        remote_port: TCP port the dashboard listens on inside the agent
            host. Sourced from `agent_record.config.<port_field>` when
            persisted, else the manifest's `default_port`.
        bind: Bind scope advertised by the manifest. Always `loopback`
            in this iteration.
        ssh_config: SSH-tunnel parameters: `user`, optional `port`,
            optional `identity_file`. Empty dict for a local-only host.
    """

    host: str
    remote_port: int
    bind: str
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
    """Return the primary address for a host, falling back to `hostname`."""
    addresses = host.get("addresses") or []
    for addr in addresses:
        if isinstance(addr, dict) and addr.get("is_primary"):
            address = addr.get("address")
            if isinstance(address, str) and address:
                return address
    hostname = host.get("hostname")
    return hostname if isinstance(hostname, str) else ""


def _build_ssh_config(host: dict[str, Any]) -> dict[str, Any]:
    """Extract SSH connection params from a host record."""
    ssh: dict[str, Any] = {}
    user = host.get("user")
    if isinstance(user, str) and user:
        ssh["user"] = user
    port = host.get("ssh_port")
    if isinstance(port, int) and port > 0:
        ssh["port"] = port
    identity = host.get("ssh_key") or host.get("identity_file")
    if isinstance(identity, str) and identity:
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
          - the agent name is not found in `hosts.json`,
          - the agent name is ambiguous across hosts,
          - the agent's manifest cannot be loaded,
          - the manifest does not declare `features.web_ui`,
          - `features.web_ui.enabled` is `False`.
    """
    if not isinstance(agent_key, str) or not agent_key.strip():
        return None

    try:
        match = get_agent_by_name(agent_key)
    except ValueError:
        return None

    if match is None:
        return None

    host_record, agent_type, agent_record = match

    try:
        manifest = load_manifest(agent_type)
    except (ManifestNotFoundError, ManifestParseError):
        return None

    web_ui = manifest.get("features", {}).get("web_ui")
    if not web_ui or not web_ui.get("enabled"):
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
        host=_primary_address(host_record),
        remote_port=remote_port,
        bind=web_ui["bind"],
        ssh_config=_build_ssh_config(host_record),
    )

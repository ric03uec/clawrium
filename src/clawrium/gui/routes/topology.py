"""Topology API route.

Provides the network graph data for the Topology view.
Returns hosts, agents, and connection data in a format
suitable for React Flow rendering.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter

from clawrium.cli.tui.data import get_fleet_data, load_hosts_safe
from clawrium.core.health import ClawStatus
from clawrium.core.providers.storage import (
    ProvidersFileCorruptedError,
    load_providers,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet", tags=["topology"])


def _load_provider_endpoints() -> dict[str, str | None]:
    """Return a {provider_name: endpoint} map from providers.json.

    Endpoint is only present on provider types that need one (e.g. ollama).
    Returns an empty dict if the providers file is missing, unreadable, or
    corrupted, so topology never fails just because providers can't be loaded.
    PermissionError is a subclass of OSError and is therefore covered.
    """
    try:
        providers = load_providers()
    except (ProvidersFileCorruptedError, OSError) as exc:
        logger.warning("providers unavailable; topology omits endpoints: %s", exc)
        return {}
    return {
        p.get("name"): (_normalize_endpoint(p.get("endpoint")))
        for p in providers
        if p.get("name")
    }


def _normalize_endpoint(ep: object) -> str | None:
    """Coerce missing / blank / whitespace endpoint values to None."""
    if not isinstance(ep, str):
        return None
    stripped = ep.strip()
    return stripped or None


@router.get("/topology")
async def get_topology():
    """Get full topology data for network diagram rendering.

    Returns:
        - control: The control machine node
        - hosts: List of host nodes with their agents
        - connections: SSH connection lines from control to each host
    """
    agents, summary = await asyncio.to_thread(get_fleet_data, None)
    hosts_raw = await asyncio.to_thread(load_hosts_safe)
    provider_endpoints = await asyncio.to_thread(_load_provider_endpoints)

    # Build host map with nested agents
    hosts: list[dict[str, Any]] = []
    for h in hosts_raw:
        hostname = h.get("hostname", "unknown")
        alias = h.get("alias") or hostname
        addresses = h.get("addresses", [])
        user = h.get("user", "root")
        key_id = h.get("key_id")

        # Collect agents belonging to this host
        host_agents: list[dict[str, Any]] = []
        for agent in agents:
            if agent["host"] == hostname:
                status = agent["status"]
                host_agents.append(
                    {
                        "agent_key": agent["agent_key"],
                        "agent_name": agent["agent_name"],
                        "agent_type": agent["agent_type"],
                        "status": status.value
                        if isinstance(status, ClawStatus)
                        else status,
                        "model": agent["model"],
                        "version": agent["version"],
                        "uptime": agent["uptime"],
                        "provider": agent["provider"],
                        "provider_type": agent["provider_type"],
                        "provider_endpoint": provider_endpoints.get(
                            agent["provider"]
                        )
                        if agent["provider"]
                        else None,
                    }
                )

        hosts.append(
            {
                "hostname": hostname,
                "alias": alias,
                "user": user,
                "addresses": addresses,
                "has_key": key_id is not None,
                "agent_count": len(host_agents),
                "agents": host_agents,
            }
        )

    # Control node represents the local machine running clm
    control = {
        "label": "Control Machine",
        "description": "clm CLI",
    }

    # Connections: one SSH link per host
    connections = [
        {
            "source": "control",
            "target": h["hostname"],
            "protocol": "ssh",
        }
        for h in hosts
    ]

    return {
        "control": control,
        "hosts": hosts,
        "connections": connections,
        "summary": {
            "total_agents": summary["total"],
            "running": summary["running"],
            "total_hosts": summary["hosts"],
        },
    }

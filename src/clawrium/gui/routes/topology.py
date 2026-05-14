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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet", tags=["topology"])


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

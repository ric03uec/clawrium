"""Topology API route.

Provides the network graph data for the Topology view.
Returns hosts, agents, and connection data in a format
suitable for React Flow rendering.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter

from clawrium.cli.tui.data import get_fleet_data_local, load_hosts_safe
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


def _load_provider_accelerator_vendors() -> dict[str, str | None]:
    """Return {provider_name: accelerator_vendor} for local-inference providers.

    Defaults ollama to "nvidia" when the stored record omits the field, so
    the topology badge stays stable for legacy providers.json entries.
    Returns an empty dict when providers can't be loaded.
    """
    try:
        providers = load_providers()
    except (ProvidersFileCorruptedError, OSError):
        return {}
    out: dict[str, str | None] = {}
    for p in providers:
        name = p.get("name")
        if not name:
            continue
        stored = p.get("accelerator_vendor")
        if stored in ("nvidia", "amd"):
            out[name] = stored
        elif p.get("type") == "ollama":
            out[name] = "nvidia"
        else:
            out[name] = None
    return out


def _normalize_endpoint(ep: object) -> str | None:
    """Coerce missing / blank / whitespace endpoint values to None."""
    if not isinstance(ep, str):
        return None
    stripped = ep.strip()
    return stripped or None


def _summarize_hardware(hw: dict[str, Any]) -> dict[str, Any]:
    """Reduce stored hardware dict to fields used by the topology UI.

    Stable shape decouples the API from the stored fact schema, so older
    host records (missing the new fields) still produce a well-formed dict.
    """
    gpu_raw = hw.get("gpu")
    if isinstance(gpu_raw, dict):
        gpu = {
            "present": gpu_raw.get("present", False),
            "vendor": gpu_raw.get("vendor"),
            "error": gpu_raw.get("error"),
        }
    else:
        gpu = {"present": False, "vendor": None, "error": None}

    return {
        "architecture": hw.get("architecture"),
        "cores": hw.get("processor_cores"),
        "memtotal_mb": hw.get("memtotal_mb"),
        "gpu": gpu,
        "product_name": hw.get("product_name"),
        "system_vendor": hw.get("system_vendor"),
    }


@router.get("/topology")
async def get_topology():
    """Get full topology data for network diagram rendering.

    Uses local-only data for instant rendering. Agent status fields
    will show "checking" until the frontend polls /api/fleet/health.

    Returns:
        - control: The control machine node
        - hosts: List of host nodes with their agents
        - connections: SSH connection lines from control to each host
    """
    agents, summary = await asyncio.to_thread(get_fleet_data_local, None)
    hosts_raw = await asyncio.to_thread(load_hosts_safe)
    provider_endpoints = await asyncio.to_thread(_load_provider_endpoints)
    provider_accelerators = await asyncio.to_thread(_load_provider_accelerator_vendors)

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
                        "provider_endpoint": provider_endpoints.get(agent["provider"])
                        if agent["provider"]
                        else None,
                        "provider_accelerator_vendor": (
                            provider_accelerators.get(agent["provider"])
                            if agent["provider"]
                            else None
                        ),
                    }
                )

        hw_raw = h.get("hardware")
        hardware = _summarize_hardware(hw_raw) if hw_raw else None

        hosts.append(
            {
                "hostname": hostname,
                "alias": alias,
                "user": user,
                "addresses": addresses,
                "has_key": key_id is not None,
                "agent_count": len(host_agents),
                "agents": host_agents,
                "hardware": hardware,
            }
        )

    # Control node represents the local machine running clawctl
    control = {
        "label": "Control Machine",
        "description": "clawctl CLI",
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

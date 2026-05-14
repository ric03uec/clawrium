"""Fleet and agent management API routes.

Provides endpoints for fleet overview, agent detail, and lifecycle
operations (start/stop/restart). Wraps existing core modules with
async-safe thread offloading for SSH-based health checks.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from clawrium.cli.tui.data import (
    AgentViewModel,
    get_agent_detail,
    get_fleet_data,
    load_hosts_safe,
)
from clawrium.core.health import ClawStatus
from clawrium.core.lifecycle import (
    LifecycleError,
    start_agent,
    stop_agent,
    restart_agent,
)
from clawrium.gui.routes._common import resolve_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["fleet"])


def _agent_to_dict(agent: AgentViewModel) -> dict[str, Any]:
    # gateway_auth is a bearer token and must not be sent to the browser.
    # Both chat proxies (hermes + openclaw) resolve it from the secrets store
    # server-side; no frontend consumer needs it on the wire.
    return {
        "agent_key": agent["agent_key"],
        "agent_name": agent["agent_name"],
        "agent_type": agent["agent_type"],
        "host": agent["host"],
        "host_alias": agent["host_alias"],
        "version": agent["version"],
        "status": agent["status"].value
        if isinstance(agent["status"], ClawStatus)
        else agent["status"],
        "model": agent["model"],
        "uptime": agent["uptime"],
        "missing_secrets": agent["missing_secrets"],
        "onboarding_step": agent["onboarding_step"],
        "process_running": agent["process_running"],
        "health_error": agent["health_error"],
        "addresses": agent["addresses"],
        "provider": agent["provider"],
        "provider_type": agent["provider_type"],
        "cpu_count": agent["cpu_count"],
        "memory_total_mb": agent["memory_total_mb"],
        "gateway_port": agent["gateway_port"],
        "gateway_url": agent["gateway_url"],
        "device_id": agent["device_id"],
    }


@router.get("/fleet")
async def fleet_overview(host: str | None = None):
    """Get fleet summary and all agents.

    Runs health checks in a thread pool since they involve SSH connections.
    """
    agents, summary = await asyncio.to_thread(get_fleet_data, host)
    return {
        "summary": {
            "total": summary["total"],
            "running": summary["running"],
            "provisioning": summary["provisioning"],
            "hosts": summary["hosts"],
        },
        "agents": [_agent_to_dict(a) for a in agents],
    }


@router.get("/fleet/agents/{agent_key}")
async def agent_detail(agent_key: str, host: str | None = None):
    """Get detailed info for a single agent.

    Searches across all hosts unless host is specified.
    """
    hosts = await asyncio.to_thread(load_hosts_safe)

    # Find the agent across hosts
    for h in hosts:
        hostname = h.get("hostname", "")
        alias = h.get("alias", "")
        if host and hostname != host and alias != host:
            continue
        agents = h.get("agents", {})
        if agent_key in agents:
            detail = await asyncio.to_thread(get_agent_detail, agent_key, hostname)
            if detail:
                return _agent_to_dict(detail)

    raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")


@router.post("/agents/{agent_key}/start")
async def start_agent_endpoint(agent_key: str):
    """Start an agent instance."""
    resolved = await asyncio.to_thread(resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    host_record, _agent_type, _agent_record = resolved

    try:
        result = await asyncio.to_thread(
            start_agent,
            agent_key,
            host_record["hostname"],
            host_record.get("user", "root"),
        )
        return {"success": result["success"], "operation": "start", "agent": agent_key}
    except LifecycleError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/{agent_key}/stop")
async def stop_agent_endpoint(agent_key: str):
    """Stop an agent instance."""
    resolved = await asyncio.to_thread(resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    host_record, _agent_type, _agent_record = resolved

    try:
        result = await asyncio.to_thread(
            stop_agent,
            agent_key,
            host_record["hostname"],
            host_record.get("user", "root"),
        )
        return {"success": result["success"], "operation": "stop", "agent": agent_key}
    except LifecycleError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/{agent_key}/restart")
async def restart_agent_endpoint(agent_key: str):
    """Restart an agent instance."""
    resolved = await asyncio.to_thread(resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    host_record, _agent_type, _agent_record = resolved

    try:
        result = await asyncio.to_thread(
            restart_agent,
            agent_key,
            host_record["hostname"],
            host_record.get("user", "root"),
        )
        return {
            "success": result["success"],
            "operation": "restart",
            "agent": agent_key,
        }
    except LifecycleError as e:
        raise HTTPException(status_code=500, detail=str(e))



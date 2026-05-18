"""Fleet and agent management API routes.

Provides endpoints for fleet overview, agent detail, and lifecycle
operations (start/stop/restart). Wraps existing core modules with
async-safe thread offloading for SSH-based health checks.
"""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException

from clawrium.cli.tui.data import (
    AgentViewModel,
    get_agent_detail,
    get_fleet_data,
    get_fleet_data_local,
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

# Cap concurrent SSH probe sweeps. Each /fleet/health call dispatches one
# ansible-runner subprocess per agent, so a tight polling loop can
# exhaust fd / thread-pool limits on small homelab hardware.
_FLEET_HEALTH_SEMAPHORE = asyncio.Semaphore(2)
_FLEET_HEALTH_TIMEOUT_S = 60.0
# Dedicated thread pool so a leaked / still-running SSH thread (asyncio
# can't actually cancel a sync function past `wait_for`) cannot starve
# the default executor that backs every other `asyncio.to_thread` site.
_FLEET_HEALTH_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="fleet-health"
)

# Strip absolute filesystem paths from error strings before sending them
# to the browser. Some `HealthResult.error` strings constructed inside
# `core/health.py` interpolate `str(e)` from filesystem exceptions and
# include the user's config path (e.g. ~/.config/clawrium/secrets.json).
_ABS_PATH_RE = re.compile(r"(?:/[\w.\-]+)+")


def _sanitize_health_error(error: str | None) -> str | None:
    if not error:
        return error
    return _ABS_PATH_RE.sub("<path>", error)


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
        "health_error": _sanitize_health_error(agent["health_error"]),
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
    """Get fleet summary and all agents using local config only.

    Returns immediately with agent data from hosts.json. Agents that
    haven't completed onboarding get their real status; others show
    status="checking" until the /fleet/health endpoint confirms their
    live state via SSH.
    """
    agents, summary = await asyncio.to_thread(get_fleet_data_local, host)
    return {
        "summary": {
            "total": summary["total"],
            "running": summary["running"],
            "provisioning": summary["provisioning"],
            "hosts": summary["hosts"],
        },
        "agents": [_agent_to_dict(a) for a in agents],
    }


@router.get("/fleet/health")
async def fleet_health(host: str | None = None):
    """Get live health status for all agents via SSH checks.

    This is the slow endpoint that performs actual SSH connectivity
    checks. The frontend polls this separately after the initial
    fleet overview has rendered.
    """
    loop = asyncio.get_running_loop()
    async with _FLEET_HEALTH_SEMAPHORE:
        try:
            agents, summary = await asyncio.wait_for(
                loop.run_in_executor(_FLEET_HEALTH_EXECUTOR, get_fleet_data, host),
                timeout=_FLEET_HEALTH_TIMEOUT_S,
            )
        except asyncio.TimeoutError as e:
            raise HTTPException(
                status_code=504, detail="fleet health probe timed out"
            ) from e
    # Return only health-relevant fields to minimize payload
    health_data = []
    for a in agents:
        status = a["status"]
        health_data.append(
            {
                "agent_key": a["agent_key"],
                "status": status.value if isinstance(status, ClawStatus) else status,
                "process_running": a["process_running"],
                "health_error": _sanitize_health_error(a["health_error"]),
                "cpu_count": a["cpu_count"],
                "memory_total_mb": a["memory_total_mb"],
                "missing_secrets": a["missing_secrets"],
            }
        )
    return {
        "summary": {
            "total": summary["total"],
            "running": summary["running"],
            "provisioning": summary["provisioning"],
            "hosts": summary["hosts"],
        },
        "agents": health_data,
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



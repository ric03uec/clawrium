"""Fleet and agent management API routes.

Provides endpoints for fleet overview, agent detail, and lifecycle
operations (start/stop/restart). Wraps existing core modules with
async-safe thread offloading for SSH-based health checks.
"""

import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException

from clawrium.cli.tui.data import (
    AgentViewModel,
    get_agent_detail,
    get_agent_static,
    get_fleet_data,
    get_fleet_data_local,
)
from clawrium.core import web_ui as web_ui_module
from clawrium.core import web_ui_tunnel
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
_FLEET_HEALTH_TIMEOUT_S = 60.0
# Dedicated thread pool so a leaked / still-running SSH thread (asyncio
# can't actually cancel a sync function past `wait_for`) cannot starve
# the default executor that backs every other `asyncio.to_thread` site.
#
# Both the semaphore and executor are lazy-initialized rather than
# bound at module import. `asyncio.Semaphore` latches to the event loop
# active on first use, so a module-level instance breaks under pytest
# (each TestClient spins up a fresh loop). The executor is rebound by
# the FastAPI lifespan in `gui/server.py`, but tests that hit the route
# outside the lifespan, or after the lifespan has shut down, can race
# against a stale handle. The accessors below give us per-loop
# semaphores and a "recreate-if-shutdown" executor.
_FLEET_HEALTH_EXECUTOR: ThreadPoolExecutor | None = None


def _get_fleet_health_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = getattr(loop, "_clawrium_fleet_sem", None)
    if sem is None:
        sem = asyncio.Semaphore(2)
        loop._clawrium_fleet_sem = sem  # type: ignore[attr-defined]
    return sem


def _get_fleet_health_executor() -> ThreadPoolExecutor:
    global _FLEET_HEALTH_EXECUTOR
    if _FLEET_HEALTH_EXECUTOR is None or _FLEET_HEALTH_EXECUTOR._shutdown:
        _FLEET_HEALTH_EXECUTOR = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="fleet-health"
        )
    return _FLEET_HEALTH_EXECUTOR

# Strip absolute filesystem paths from error strings before sending them
# to the browser. Some `HealthResult.error` strings constructed inside
# `core/health.py` interpolate `str(e)` from filesystem exceptions and
# include the user's config path (e.g. ~/.config/clawrium/secrets.json).
_ABS_PATH_RE = re.compile(r"(?:/[\w.\-]+)+")

# Generic error message for lifecycle operations to avoid path leakage
_LIFECYCLE_GENERIC_ERROR = "Lifecycle operation failed. Check server logs."

# Per-agent last-access timestamp for the GUI web-ui tunnel reaper. Keys
# are agent_key strings; values are wall-clock unix seconds from the most
# recent /web-ui hit. The reaper task in server.py reads this map.
_LAST_ACCESS_LOCK = asyncio.Lock()
WEB_UI_LAST_ACCESS: dict[str, float] = {}


def _host_is_local(host: str) -> bool:
    """Same heuristic as the CLI helper. Loopback / localhost only."""
    import ipaddress

    if not host:
        return False
    candidate = host.strip().lower()
    if candidate in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


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
        "host_os_family": agent.get("host_os_family"),
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
    async with _get_fleet_health_semaphore():
        try:
            agents, summary = await asyncio.wait_for(
                loop.run_in_executor(
                    _get_fleet_health_executor(), get_fleet_data, host
                ),
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
    """Return static identity + persisted config for a single agent.

    Reads hosts.json only — no SSH probe, no registry lookup. The GUI
    uses this to paint the detail-page shell instantly; the slow
    runtime fields are served by the sibling /health endpoint below.
    """
    resolved = await asyncio.to_thread(resolve_agent, agent_key)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    host_record, _agent_type, _ = resolved

    if host and host_record.get("hostname") != host and host_record.get("alias") != host:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_key}' not found on host '{host}'",
        )

    hostname = host_record.get("hostname", "")
    detail = await asyncio.to_thread(get_agent_static, agent_key, hostname)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    return _agent_to_dict(detail)


@router.get("/fleet/agents/{agent_key}/health")
async def agent_health(agent_key: str, host: str | None = None):
    """Return live runtime fields for a single agent via SSH probe.

    Companion to /fleet/agents/{key}. Runs check_claw_health and the
    registry version lookup — the slow work the static endpoint
    intentionally skips. The frontend fetches this in parallel with
    the static call so the page shell never blocks on it.

    Routed through the same dedicated executor + semaphore + timeout
    as `/fleet/health` (#758 ATX B1). `useAgentHealth`'s 10s poll on
    every open detail tab would otherwise pin Starlette's default
    threadpool indefinitely on a dead host and starve every other
    route that shares it.
    """
    resolved = await asyncio.to_thread(resolve_agent, agent_key)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    host_record, _agent_type, _ = resolved

    if host and host_record.get("hostname") != host and host_record.get("alias") != host:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_key}' not found on host '{host}'",
        )

    hostname = host_record.get("hostname", "")
    loop = asyncio.get_running_loop()
    async with _get_fleet_health_semaphore():
        try:
            detail = await asyncio.wait_for(
                loop.run_in_executor(
                    _get_fleet_health_executor(),
                    get_agent_detail,
                    agent_key,
                    hostname,
                ),
                timeout=_FLEET_HEALTH_TIMEOUT_S,
            )
        except asyncio.TimeoutError as e:
            raise HTTPException(
                status_code=504, detail="agent health probe timed out"
            ) from e
    if not detail:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")

    from clawrium.core.registry import latest_supported_version

    try:
        latest_version = latest_supported_version(
            detail["agent_type"], host_record.get("hardware") or {}
        )
    except (KeyError, ValueError, FileNotFoundError) as e:
        # W1: previously a bare `except Exception`. A malformed manifest
        # or genuine bug would silently render as a missing upgrade
        # badge — operators think they're on the newest build when
        # they're not. Narrow the catch and log so the failure is
        # visible server-side without breaking the rest of the
        # response payload.
        logger.warning(
            "latest_supported_version lookup failed for %s: %s",
            agent_key,
            e,
            exc_info=True,
        )
        latest_version = None

    status = detail["status"]
    # S5: `uptime` is computed from claw_record.runtime.started_at and
    # has no SSH-derived component — keeping it here would be a second,
    # unsynchronized source of truth. The static endpoint owns uptime;
    # the frontend reads it from useAgent which now polls (W2) so the
    # value still advances.
    return {
        "agent_key": detail["agent_key"],
        "status": status.value if isinstance(status, ClawStatus) else status,
        "process_running": detail["process_running"],
        "health_error": _sanitize_health_error(detail["health_error"]),
        "cpu_count": detail["cpu_count"],
        "memory_total_mb": detail["memory_total_mb"],
        "missing_secrets": detail["missing_secrets"],
        "onboarding_step": detail["onboarding_step"],
        "latest_supported_version": latest_version,
    }


@router.post("/agents/{agent_key}/start")
async def start_agent_endpoint(agent_key: str):
    """Start an agent instance."""
    resolved = await asyncio.to_thread(resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    host_record, agent_type, _agent_record = resolved

    try:
        result = await asyncio.to_thread(
            start_agent,
            host_record["hostname"],
            agent_type,
            agent_name=agent_key,
        )
        return {
            "success": result["success"],
            "operation": "start",
            "agent": agent_key,
            "error": result.get("error"),
        }
    except LifecycleError as e:
        logger.error("start_agent failed for %s: %s", agent_key, e, exc_info=True)
        raise HTTPException(status_code=500, detail=_sanitize_health_error(str(e)))
    except Exception as e:
        logger.error("start_agent failed for %s: %s", agent_key, e, exc_info=True)
        raise HTTPException(status_code=500, detail=_LIFECYCLE_GENERIC_ERROR)


@router.post("/agents/{agent_key}/stop")
async def stop_agent_endpoint(agent_key: str):
    """Stop an agent instance."""
    resolved = await asyncio.to_thread(resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    host_record, agent_type, _agent_record = resolved

    try:
        result = await asyncio.to_thread(
            stop_agent,
            host_record["hostname"],
            agent_type,
            agent_name=agent_key,
        )
        return {
            "success": result["success"],
            "operation": "stop",
            "agent": agent_key,
            "error": result.get("error"),
        }
    except LifecycleError as e:
        logger.error("stop_agent failed for %s: %s", agent_key, e, exc_info=True)
        raise HTTPException(status_code=500, detail=_sanitize_health_error(str(e)))
    except Exception as e:
        logger.error("stop_agent failed for %s: %s", agent_key, e, exc_info=True)
        raise HTTPException(status_code=500, detail=_LIFECYCLE_GENERIC_ERROR)


@router.post("/agents/{agent_key}/restart")
async def restart_agent_endpoint(agent_key: str):
    """Restart an agent instance."""
    resolved = await asyncio.to_thread(resolve_agent, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    host_record, agent_type, _agent_record = resolved

    try:
        result = await asyncio.to_thread(
            restart_agent,
            host_record["hostname"],
            agent_type,
            agent_name=agent_key,
        )
        return {
            "success": result["success"],
            "operation": "restart",
            "agent": agent_key,
            "error": result.get("error"),
        }
    except LifecycleError as e:
        logger.error("restart_agent failed for %s: %s", agent_key, e, exc_info=True)
        raise HTTPException(status_code=500, detail=_sanitize_health_error(str(e)))
    except Exception as e:
        logger.error("restart_agent failed for %s: %s", agent_key, e, exc_info=True)
        raise HTTPException(status_code=500, detail=_LIFECYCLE_GENERIC_ERROR)


@router.get("/fleet/agents/{agent_key}/web-ui")
async def agent_web_ui(agent_key: str) -> dict[str, Any]:
    """Resolve / establish the native-UI tunnel for an agent.

    Returns ``{ available, local_url, reason }``. ``available: true`` means
    a tunnel is up (or the agent is local) and ``local_url`` points at the
    browser-openable URL. ``available: false`` carries a human-readable
    ``reason`` (e.g. agent type does not expose a UI, agent not running).
    404 is returned only when the agent cannot be found at all.
    """
    resolved_match = await asyncio.to_thread(resolve_agent, agent_key)
    if resolved_match is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    _host_record, agent_type, _agent_record = resolved_match

    ui = await asyncio.to_thread(web_ui_module.resolve, agent_key)
    if ui is None:
        return {
            "available": False,
            "local_url": None,
            "reason": (f"Agent type '{agent_type}' does not expose a native web UI."),
        }

    if _host_is_local(ui.host):
        # Local agents don't need a tunnel, so we deliberately do NOT stamp
        # WEB_UI_LAST_ACCESS here (ATX suggestion: keep the reaper map
        # focused on tunneled agents only).
        return {
            "available": True,
            "local_url": f"http://127.0.0.1:{ui.remote_port}/",
            "reason": None,
        }

    try:
        local_port = await asyncio.to_thread(web_ui_tunnel.ensure, agent_key)
    except web_ui_tunnel.TunnelError as e:
        logger.warning("web-ui tunnel failed for %s: %s", agent_key, e)
        # TunnelError messages may contain ssh stderr that includes
        # filesystem paths; reuse the existing path-redaction regex so
        # nothing internal leaks to the browser body.
        return {
            "available": False,
            "local_url": None,
            "reason": _ABS_PATH_RE.sub("<path>", str(e)),
        }
    except Exception:  # noqa: BLE001 — log full trace, return generic message
        logger.error("web-ui tunnel unexpected error for %s", agent_key, exc_info=True)
        return {
            "available": False,
            "local_url": None,
            "reason": "Internal error establishing tunnel; see server logs.",
        }

    async with _LAST_ACCESS_LOCK:
        WEB_UI_LAST_ACCESS[agent_key] = time.time()

    return {
        "available": True,
        "local_url": f"http://127.0.0.1:{local_port}/",
        "reason": None,
    }


# Agent types whose web UI requires an in-browser pairing handshake. Today
# only zeroclaw — hermes serves its dashboard without an in-process auth
# step (the SSH key is the boundary). Keep this in sync with the frontend
# allowlist in `gui/src/hooks/use-agent.ts`.
_PAIRING_AGENT_TYPES = {"zeroclaw"}

# Agent types whose dashboard SPA prompts for a long-lived gateway bearer
# token on first open (paste-from-clipboard). Today only openclaw — its
# Control UI WebSocket auth uses the token persisted at
# `hosts.json.agents.<name>.config.gateway.auth`. Distinct from
# `_PAIRING_AGENT_TYPES` (zeroclaw mints a fresh one-shot pairing code on
# every connect; openclaw reuses the static install-time bearer). Keep in
# sync with `TOKEN_REVEAL_AGENT_TYPES` in `gui/src/hooks/use-agent.ts`.
_TOKEN_REVEAL_AGENT_TYPES = {"openclaw"}

# Bound the upstream call to the agent daemon so a hung / unreachable
# daemon doesn't pin a FastAPI worker. The pairing endpoint is in-process
# on the agent and should respond in milliseconds; 10s is a generous
# ceiling that still surfaces hangs as 504 to the browser.
_PAIRING_UPSTREAM_TIMEOUT_S = 10.0


@router.post("/fleet/agents/{agent_key}/pairing-code")
async def agent_pairing_code(agent_key: str) -> dict[str, Any]:
    """Mint a fresh pairing code for the agent's native web UI.

    Only meaningful for agent types whose dashboard SPA gates browser
    sessions with an in-process pairing handshake (zeroclaw today). The
    endpoint:

      1. Resolves the agent in ``hosts.json``.
      2. Reuses the existing ``web_ui_tunnel`` to reach the agent's
         dashboard daemon over SSH local-forward.
      3. Reads the bearer token persisted at
         ``agents.<name>.config.gateway.auth`` (the same one ansible
         lifecycle ops mint via ``/pair`` and write to disk).
      4. POSTs ``/api/pairing/initiate`` with that bearer; the daemon
         overwrites its in-memory ``pairing_code`` slot and returns
         the new code.

    Each call invalidates the previous code (zeroclaw stores exactly
    one). Callers MUST treat the response code as ephemeral and not
    cache it. The returned bearer never leaves the gateway side; only
    the short pairing code is sent to the browser.
    """
    import httpx

    resolved_match = await asyncio.to_thread(resolve_agent, agent_key)
    if resolved_match is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    _host_record, agent_type, agent_record = resolved_match

    if agent_type not in _PAIRING_AGENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Agent type '{agent_type}' does not use an in-browser "
                "pairing handshake."
            ),
        )

    ui = await asyncio.to_thread(web_ui_module.resolve, agent_key)
    if ui is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Agent '{agent_key}' does not declare a native web UI in its manifest."
            ),
        )

    gateway = (agent_record.get("config") or {}).get("gateway") or {}
    bearer = gateway.get("auth")
    if not isinstance(bearer, str) or not bearer.strip():
        # No persisted bearer means lifecycle ops have not run successfully
        # against this agent. Without it /api/pairing/initiate would 401 on
        # the daemon side and the browser would see an opaque upstream
        # error. Surface the actionable next step instead.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Agent '{agent_key}' has no gateway bearer persisted. Run "
                f"`clawctl agent configure {agent_key}` first."
            ),
        )

    if _host_is_local(ui.host):
        base = f"http://127.0.0.1:{ui.remote_port}"
    else:
        try:
            local_port = await asyncio.to_thread(web_ui_tunnel.ensure, agent_key)
        except web_ui_tunnel.TunnelError as e:
            logger.warning("pairing-code tunnel failed for %s: %s", agent_key, e)
            raise HTTPException(
                status_code=502,
                detail=_ABS_PATH_RE.sub("<path>", str(e)),
            ) from e
        except Exception as e:  # noqa: BLE001 — log full trace, generic body
            logger.error(
                "pairing-code tunnel unexpected error for %s",
                agent_key,
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal error establishing tunnel; see server logs.",
            ) from e

        async with _LAST_ACCESS_LOCK:
            WEB_UI_LAST_ACCESS[agent_key] = time.time()
        base = f"http://127.0.0.1:{local_port}"

    try:
        async with httpx.AsyncClient(timeout=_PAIRING_UPSTREAM_TIMEOUT_S) as client:
            resp = await client.post(
                f"{base}/api/pairing/initiate",
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except httpx.TimeoutException as e:
        logger.warning("pairing-code upstream timeout for %s", agent_key)
        raise HTTPException(
            status_code=504,
            detail=(
                f"Timed out talking to the agent daemon for '{agent_key}'. "
                "The tunnel may be up but the daemon is unresponsive."
            ),
        ) from e
    except httpx.HTTPError as e:
        logger.warning("pairing-code upstream error for %s: %s", agent_key, e)
        raise HTTPException(
            status_code=502,
            detail="Could not reach the agent daemon to mint a pairing code.",
        ) from e

    if resp.status_code == 401:
        # Stale bearer in hosts.json (devices.db wiped or rebuilt on the
        # agent host). Map to the same operator guidance the ansible
        # pair.yaml validator emits.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Agent daemon rejected the persisted bearer for "
                f"'{agent_key}' (401). Re-run `clawctl agent configure "
                f"{agent_key}` to re-pair from scratch."
            ),
        )
    if resp.status_code == 503:
        raise HTTPException(
            status_code=503,
            detail=(
                "Agent daemon reports pairing disabled or unavailable (503). "
                f"Check the daemon and restart with `clawctl agent restart "
                f"{agent_key}`."
            ),
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Agent daemon returned unexpected status "
                f"{resp.status_code} for pairing-code request."
            ),
        )

    try:
        body = resp.json()
    except ValueError as e:
        raise HTTPException(
            status_code=502,
            detail="Agent daemon returned a non-JSON pairing response.",
        ) from e

    code = body.get("pairing_code")
    if not isinstance(code, str) or not code:
        raise HTTPException(
            status_code=502,
            detail="Agent daemon returned an empty pairing code.",
        )

    return {"pairing_code": code}


@router.post("/fleet/agents/{agent_key}/connection-token")
async def agent_connection_token(agent_key: str) -> dict[str, Any]:
    """Reveal the gateway bearer token for an agent's native UI login.

    For agent types whose dashboard SPA prompts the user to paste a
    long-lived gateway token on first open (openclaw today). Distinct
    from ``/pairing-code``: openclaw's token is the same install-time
    bearer already persisted in ``hosts.json`` under
    ``agents.<name>.config.gateway.auth``, so the endpoint is a
    privileged read — no daemon round-trip and no mutation.

    POST (not GET) because the body is a long-lived secret: GET URLs
    can land in browser history, proxy logs, and referer headers;
    POST bodies do not. Symmetric with the ``/pairing-code`` mutation
    pattern. The endpoint relies on the GUI server's existing
    local-only / authenticated session model — anyone who can hit
    this URL can already read ``hosts.json`` directly on disk.
    """
    resolved_match = await asyncio.to_thread(resolve_agent, agent_key)
    if resolved_match is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found")
    _host_record, agent_type, agent_record = resolved_match

    if agent_type not in _TOKEN_REVEAL_AGENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Agent type '{agent_type}' does not use a long-lived "
                "gateway token for browser auth."
            ),
        )

    ui = await asyncio.to_thread(web_ui_module.resolve, agent_key)
    if ui is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Agent '{agent_key}' does not declare a native web UI in its manifest."
            ),
        )

    # Route the lookup through `_resolve_openclaw_credentials` (the same
    # source the openclaw chat proxy uses) so this endpoint stays
    # consistent with future bearer rotations. The helper reads the
    # secrets store first and falls back to the legacy hosts.json field,
    # auto-migrating on first hit — if we read hosts.json directly here,
    # a rotation that landed only in the secrets store would silently
    # return a stale token and the user would see an opaque 401 in the
    # Control UI. Strip on return to defend against operators who
    # hand-edited the legacy field with trailing whitespace.
    from clawrium.core.secrets import get_instance_key
    from clawrium.gui.routes.agents import _resolve_openclaw_credentials

    hostname = _host_record.get("hostname", "")
    agent_name = agent_record.get("agent_name") or agent_record.get("name") or ""
    host_key = _host_record.get("key_id") or hostname
    instance_key = get_instance_key(host_key, agent_type, agent_name)
    gateway = (agent_record.get("config") or {}).get("gateway") or {}
    bearer, _ = await asyncio.to_thread(
        _resolve_openclaw_credentials, instance_key, gateway
    )
    if not isinstance(bearer, str) or not bearer.strip():
        # No persisted bearer in either source means lifecycle ops have
        # not run successfully. Mirror the pairing-code endpoint's 409.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Agent '{agent_key}' has no gateway token persisted. Run "
                f"`clawctl agent configure {agent_key}` first."
            ),
        )

    return {"token": bearer.strip()}


async def reap_idle_tunnels(threshold_seconds: float = 1800.0) -> int:
    """Close tunnels that have been idle longer than ``threshold_seconds``.

    Returns the number of tunnels closed. The reaper task in
    ``gui.server`` calls this every 5 minutes. The lock guards the
    in-memory access map against the /web-ui handler bumping a timestamp
    mid-sweep; the tunnel close itself is best-effort.

    ATX W6: re-check each candidate under the lock immediately before
    calling ``close()``. A concurrent ``/web-ui`` request could re-stamp
    a key between the initial pop and the close — without the recheck
    we would kill a brand-new tunnel.
    """
    closed = 0
    now = time.time()
    async with _LAST_ACCESS_LOCK:
        stale = [
            key
            for key, ts in WEB_UI_LAST_ACCESS.items()
            if (now - ts) > threshold_seconds
        ]
        for key in stale:
            WEB_UI_LAST_ACCESS.pop(key, None)
    for key in stale:
        # Re-check under the lock: a concurrent /web-ui request may have
        # re-stamped this key between the initial snapshot and now.
        async with _LAST_ACCESS_LOCK:
            if key in WEB_UI_LAST_ACCESS:
                continue
        # Lock released before the blocking close() so concurrent /web-ui
        # handlers are not stalled for the full SIGTERM→SIGKILL teardown.
        try:
            await asyncio.to_thread(web_ui_tunnel.close, key)
            closed += 1
        except Exception:  # noqa: BLE001
            logger.debug("reaper close failed for %s", key, exc_info=True)
    return closed

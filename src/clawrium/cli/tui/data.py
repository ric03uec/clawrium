"""Data fetching and transformation for TUI."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TypedDict
from urllib.parse import urlparse

from clawrium.core.health import (
    ClawStatus,
    HealthResult,
    check_claw_health,
    get_onboarding_status,
)
from clawrium.core.hosts import HostsFileCorruptedError, load_hosts

logger = logging.getLogger(__name__)

AGENT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# Provider names share the agent-key grammar (lowercase, digits, _-).
_PROVIDER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _resolve_provider_name(claw_record: dict) -> str | None:
    """Resolve the attached provider name from tier-1 only.

    The top-level ``providers`` attachment list is the single source of truth
    for which provider is attached — the same list ``build_render_inputs`` and
    ``_first_provider`` read. The tier-2 ``config.provider`` render payload is
    intentionally NOT consulted here; it is read separately for display-only
    enrichment (default_model / type) that tier-1 does not carry.
    """
    attached = claw_record.get("providers")
    if not isinstance(attached, list) or not attached:
        return None
    first = attached[0]
    if isinstance(first, dict):
        first = first.get("name")
    if isinstance(first, str) and first and _PROVIDER_NAME_PATTERN.match(first):
        return first
    return None


class AgentViewModel(TypedDict):
    agent_key: str
    agent_name: str
    agent_type: str
    host: str
    host_alias: str
    # The host's OS family ("linux" | "darwin"). Surfaced to the GUI so
    # agent cards can show an OS indicator (issue #469 follow-up).
    # Backed by hosts.json `os_family` (set at bootstrap, never re-detected).
    host_os_family: str | None
    version: str
    status: ClawStatus
    model: str
    uptime: str
    missing_secrets: list[str] | None
    onboarding_step: str | None
    process_running: bool | None
    health_error: str | None
    addresses: list[dict]
    provider: str | None
    provider_type: str | None
    cpu_count: int | None
    memory_total_mb: int | None
    gateway_port: int | None
    gateway_url: str | None
    gateway_auth: str | None
    device_id: str | None
    device_private_key: str | None


class FleetSummary(TypedDict):
    total: int
    running: int
    provisioning: int
    hosts: int


def calculate_uptime(started_at: str | None) -> str:
    if not started_at:
        return "-"
    try:
        started = datetime.fromisoformat(started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - started
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "-"
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or not parts:
            parts.append(f"{minutes}m")
        return " ".join(parts)
    except (ValueError, TypeError):
        return "-"


def _gateway_scheme(stored_url: object) -> str:
    """Return the scheme from a stored gateway URL, defaulting to ws.

    The gateway serves plain WebSocket; using wss by default would break
    connections to gateways that aren't fronted by TLS.
    """
    if isinstance(stored_url, str) and stored_url:
        parsed_scheme = urlparse(stored_url).scheme
        if parsed_scheme in {"ws", "wss"}:
            return parsed_scheme
    return "ws"


def get_fleet_data_local(
    host_filter: str | None = None,
) -> tuple[list[AgentViewModel], FleetSummary]:
    """Return fleet data using only local config (no SSH health checks).

    This is the fast path for GUI rendering. Returns agents with
    status=CHECKING for agents that haven't completed onboarding-based
    status determination, and without CPU/memory/process info that
    requires SSH. The GUI can render immediately and poll a separate
    health endpoint for live status updates.
    """
    hosts = load_hosts_safe()
    if host_filter:
        hosts = [
            h
            for h in hosts
            if h.get("hostname") == host_filter or h.get("alias") == host_filter
        ]

    agents: list[AgentViewModel] = []
    provisioning_count = 0
    seen_hosts: set[str] = set()

    for h in hosts:
        hostname = h.get("hostname", "unknown")
        host_alias = h.get("alias") or hostname
        seen_hosts.add(hostname)

        for agent_key, claw_record in h.get("agents", {}).items():
            if not isinstance(claw_record, dict):
                continue
            if not AGENT_KEY_PATTERN.match(agent_key):
                logger.warning("Invalid agent_key format: %.64r", agent_key)
                continue

            agent_name = (
                claw_record.get("agent_name") or claw_record.get("name") or agent_key
            )
            agent_type = claw_record.get("type", "unknown")
            version = claw_record.get("version", "?")
            config = claw_record.get("config", {})
            model = "-"
            provider_name = None
            provider_type = None
            gateway_port = None
            gateway_url = None
            gateway_auth = None
            device_id = None
            device_private_key = None
            if isinstance(config, dict):
                provider_cfg = config.get("provider")
                if isinstance(provider_cfg, dict):
                    model = provider_cfg.get("default_model", "-")
                    provider_type = provider_cfg.get("type")
                # Tier-1 attachment list is canonical for the provider name;
                # fall back to the tier-2 render payload only for display.
                provider_name = _resolve_provider_name(claw_record)
                if provider_name is None and isinstance(provider_cfg, dict):
                    provider_name = provider_cfg.get("name") or provider_cfg.get(
                        "type"
                    )
                gateway_cfg = config.get("gateway")
                if isinstance(gateway_cfg, dict):
                    port_val = gateway_cfg.get("port")
                    if isinstance(port_val, int):
                        gateway_port = port_val
                    auth_val = gateway_cfg.get("auth")
                    if isinstance(auth_val, str) and auth_val.strip():
                        gateway_auth = auth_val
                    if gateway_port is not None:
                        scheme = _gateway_scheme(gateway_cfg.get("url"))
                        gateway_url = f"{scheme}://{hostname}:{gateway_port}"
                    device_cfg = gateway_cfg.get("device")
                    if isinstance(device_cfg, dict):
                        dev_id = device_cfg.get("id")
                        dev_key = device_cfg.get("privateKey")
                        if isinstance(dev_id, str) and dev_id.strip():
                            device_id = dev_id
                        if isinstance(dev_key, str) and dev_key.strip():
                            device_private_key = dev_key

            started_at = None
            runtime = claw_record.get("runtime", {})
            if isinstance(runtime, dict):
                started_at = runtime.get("started_at")

            # Determine status from local onboarding data only.
            # Agents still in onboarding get their real status (no SSH needed).
            # Agents that have completed onboarding (READY) or have no
            # onboarding record get CHECKING since we can't confirm
            # running/stopped without SSH.
            onboard_status, onboard_step = get_onboarding_status(claw_record)
            if onboard_status in (
                ClawStatus.ONBOARDING,
                ClawStatus.PENDING_ONBOARD,
            ):
                status = onboard_status
                provisioning_count += 1
            else:
                status = ClawStatus.CHECKING

            agents.append(
                AgentViewModel(
                    agent_key=agent_key,
                    agent_name=agent_name,
                    agent_type=agent_type,
                    host=hostname,
                    host_alias=host_alias,
                    host_os_family=h.get("os_family"),
                    version=version,
                    status=status,
                    model=model,
                    uptime=calculate_uptime(started_at),
                    missing_secrets=None,
                    onboarding_step=onboard_step,
                    process_running=None,
                    health_error=None,
                    addresses=h.get("addresses", []),
                    provider=provider_name,
                    provider_type=provider_type,
                    cpu_count=None,
                    memory_total_mb=None,
                    gateway_port=gateway_port,
                    gateway_url=gateway_url,
                    gateway_auth=gateway_auth,
                    device_id=device_id,
                    device_private_key=device_private_key,
                )
            )

    summary = FleetSummary(
        total=len(agents),
        running=0,  # Unknown until health checks complete
        provisioning=provisioning_count,
        hosts=len(seen_hosts),
    )
    return agents, summary


def get_fleet_data(
    host_filter: str | None = None,
) -> tuple[list[AgentViewModel], FleetSummary]:
    hosts = load_hosts_safe()
    if host_filter:
        hosts = [
            h
            for h in hosts
            if h.get("hostname") == host_filter or h.get("alias") == host_filter
        ]

    agents: list[AgentViewModel] = []
    running_count = 0
    provisioning_count = 0
    seen_hosts: set[str] = set()

    for h in hosts:
        hostname = h.get("hostname", "unknown")
        host_alias = h.get("alias") or hostname
        seen_hosts.add(hostname)

        for agent_key, claw_record in h.get("agents", {}).items():
            if not isinstance(claw_record, dict):
                continue
            if not AGENT_KEY_PATTERN.match(agent_key):
                logger.warning("Invalid agent_key format: %.64r", agent_key)
                continue
            result = check_claw_health_safe(agent_key, h)
            agent_name = (
                claw_record.get("agent_name") or claw_record.get("name") or agent_key
            )
            agent_type = claw_record.get("type", "unknown")
            version = claw_record.get("version", "?")
            config = claw_record.get("config", {})
            model = "-"
            provider_name = None
            provider_type = None
            gateway_port = None
            gateway_url = None
            gateway_auth = None
            device_id = None
            device_private_key = None
            if isinstance(config, dict):
                provider_cfg = config.get("provider")
                if isinstance(provider_cfg, dict):
                    model = provider_cfg.get("default_model", "-")
                    provider_type = provider_cfg.get("type")
                # Tier-1 attachment list is canonical for the provider name;
                # fall back to the tier-2 render payload only for display.
                provider_name = _resolve_provider_name(claw_record)
                if provider_name is None and isinstance(provider_cfg, dict):
                    provider_name = provider_cfg.get("name") or provider_cfg.get(
                        "type"
                    )
                gateway_cfg = config.get("gateway")
                if isinstance(gateway_cfg, dict):
                    port_val = gateway_cfg.get("port")
                    if isinstance(port_val, int):
                        gateway_port = port_val
                    auth_val = gateway_cfg.get("auth")
                    if isinstance(auth_val, str) and auth_val.strip():
                        gateway_auth = auth_val
                    # Reconstruct gateway URL using host's current address and port,
                    # preserving the scheme stored at install/configure time.
                    if gateway_port is not None:
                        scheme = _gateway_scheme(gateway_cfg.get("url"))
                        gateway_url = f"{scheme}://{hostname}:{gateway_port}"
                    # Extract device credentials for operator.write scope
                    device_cfg = gateway_cfg.get("device")
                    if isinstance(device_cfg, dict):
                        dev_id = device_cfg.get("id")
                        dev_key = device_cfg.get("privateKey")
                        if isinstance(dev_id, str) and dev_id.strip():
                            device_id = dev_id
                        if isinstance(dev_key, str) and dev_key.strip():
                            device_private_key = dev_key

            started_at = None
            runtime = claw_record.get("runtime", {})
            if isinstance(runtime, dict):
                started_at = runtime.get("started_at")

            status = result.get("status", ClawStatus.UNKNOWN)

            if status == ClawStatus.RUNNING:
                running_count += 1
            elif status in (ClawStatus.ONBOARDING, ClawStatus.PENDING_ONBOARD):
                provisioning_count += 1

            agents.append(
                AgentViewModel(
                    agent_key=agent_key,
                    agent_name=agent_name,
                    agent_type=agent_type,
                    host=hostname,
                    host_alias=host_alias,
                    host_os_family=h.get("os_family"),
                    version=version,
                    status=status,
                    model=model,
                    uptime=calculate_uptime(started_at),
                    missing_secrets=result.get("missing_secrets"),
                    onboarding_step=result.get("onboarding_step"),
                    process_running=result.get("process_running"),
                    health_error=result.get("error"),
                    addresses=h.get("addresses", []),
                    provider=provider_name,
                    provider_type=provider_type,
                    cpu_count=result.get("cpu_count"),
                    memory_total_mb=result.get("memory_total_mb"),
                    gateway_port=gateway_port,
                    gateway_url=gateway_url,
                    gateway_auth=gateway_auth,
                    device_id=device_id,
                    device_private_key=device_private_key,
                )
            )

    summary = FleetSummary(
        total=len(agents),
        running=running_count,
        provisioning=provisioning_count,
        hosts=len(seen_hosts),
    )
    return agents, summary


def load_hosts_safe() -> list[dict]:
    try:
        return load_hosts()
    except HostsFileCorruptedError:
        return []


_HEALTH_ERROR_LABELS = {
    FileNotFoundError: "ssh key or config not found",
    PermissionError: "permission denied accessing ssh key or config",
    TimeoutError: "ssh probe timed out",
    ConnectionError: "could not connect to host",
}


def check_claw_health_safe(claw_name: str, host: dict) -> HealthResult:
    try:
        return check_claw_health(claw_name, host)
    except Exception as e:
        logger.warning("Health check failed for %s: %s", claw_name, e)
        # Surface a generic label to the wire so we don't leak filesystem
        # paths or other host internals through the API. Full exception
        # detail is captured server-side via the WARNING log above.
        label = _HEALTH_ERROR_LABELS.get(type(e), "health probe failed")
        return HealthResult(
            agent=claw_name,
            host=host.get("hostname", "unknown"),
            status=ClawStatus.UNKNOWN,
            user=None,
            error=label,
            missing_secrets=None,
            onboarding_step=None,
            process_running=None,
            onboarding_stages=None,
            cpu_count=None,
            memory_total_mb=None,
        )


def get_agent_detail(agent_key: str, host_identifier: str) -> AgentViewModel | None:
    if not AGENT_KEY_PATTERN.match(agent_key):
        logger.warning("Invalid agent_key format: %s", agent_key)
        return None
    hosts = load_hosts_safe()
    for h in hosts:
        hostname = h.get("hostname", "")
        if hostname != host_identifier and h.get("alias") != host_identifier:
            continue
        agents = h.get("agents", {})
        if agent_key not in agents:
            continue
        claw_record = agents[agent_key]
        if not isinstance(claw_record, dict):
            continue
        result = check_claw_health_safe(agent_key, h)
        agent_name = (
            claw_record.get("agent_name") or claw_record.get("name") or agent_key
        )
        agent_type = claw_record.get("type", "unknown")
        version = claw_record.get("version", "?")
        config = claw_record.get("config", {})
        model = "-"
        provider_name = None
        provider_type = None
        gateway_port = None
        gateway_url = None
        gateway_auth = None
        device_id = None
        device_private_key = None
        if isinstance(config, dict):
            provider_cfg = config.get("provider")
            if isinstance(provider_cfg, dict):
                model = provider_cfg.get("default_model", "-")
                provider_type = provider_cfg.get("type")
            # Tier-1 attachment list is canonical for the provider name;
            # fall back to the tier-2 render payload only for display.
            provider_name = _resolve_provider_name(claw_record)
            if provider_name is None and isinstance(provider_cfg, dict):
                provider_name = provider_cfg.get("name") or provider_cfg.get("type")
            gateway_cfg = config.get("gateway")
            if isinstance(gateway_cfg, dict):
                port_val = gateway_cfg.get("port")
                if isinstance(port_val, int):
                    gateway_port = port_val
                auth_val = gateway_cfg.get("auth")
                if isinstance(auth_val, str) and auth_val.strip():
                    gateway_auth = auth_val
                # Reconstruct gateway URL using host's current address and port,
                # preserving the scheme stored at install/configure time.
                if gateway_port is not None:
                    scheme = _gateway_scheme(gateway_cfg.get("url"))
                    gateway_url = f"{scheme}://{hostname}:{gateway_port}"
                # Extract device credentials for operator.write scope
                device_cfg = gateway_cfg.get("device")
                if isinstance(device_cfg, dict):
                    dev_id = device_cfg.get("id")
                    dev_key = device_cfg.get("privateKey")
                    if isinstance(dev_id, str) and dev_id.strip():
                        device_id = dev_id
                    if isinstance(dev_key, str) and dev_key.strip():
                        device_private_key = dev_key

        started_at = None
        runtime = claw_record.get("runtime", {})
        if isinstance(runtime, dict):
            started_at = runtime.get("started_at")

        status = result.get("status", ClawStatus.UNKNOWN)

        return AgentViewModel(
            agent_key=agent_key,
            agent_name=agent_name,
            agent_type=agent_type,
            host=hostname,
            host_alias=h.get("alias") or hostname,
            host_os_family=h.get("os_family"),
            version=version,
            status=status,
            model=model,
            uptime=calculate_uptime(started_at),
            missing_secrets=result.get("missing_secrets"),
            onboarding_step=result.get("onboarding_step"),
            process_running=result.get("process_running"),
            health_error=result.get("error"),
            addresses=h.get("addresses", []),
            provider=provider_name,
            provider_type=provider_type,
            cpu_count=result.get("cpu_count"),
            memory_total_mb=result.get("memory_total_mb"),
            gateway_port=gateway_port,
            gateway_url=gateway_url,
            gateway_auth=gateway_auth,
            device_id=device_id,
            device_private_key=device_private_key,
        )
    return None

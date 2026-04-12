"""Data fetching and transformation for TUI."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TypedDict

from clawrium.core.health import ClawStatus, HealthResult, check_claw_health
from clawrium.core.hosts import HostsFileCorruptedError, load_hosts

logger = logging.getLogger(__name__)

AGENT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class AgentViewModel(TypedDict):
    agent_key: str
    agent_name: str
    agent_type: str
    host: str
    host_alias: str
    version: str
    status: ClawStatus
    model: str
    uptime: str
    missing_secrets: list[str] | None
    onboarding_step: str | None
    process_running: bool | None
    health_error: str | None


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
            result = check_claw_health_safe(agent_key, h)
            agent_name = (
                claw_record.get("agent_name") or claw_record.get("name") or agent_key
            )
            agent_type = claw_record.get("type", "unknown")
            version = claw_record.get("version", "?")
            config = claw_record.get("config", {})
            model = "-"
            if isinstance(config, dict):
                provider = config.get("provider")
                if isinstance(provider, dict):
                    model = provider.get("default_model", "-")

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
                    version=version,
                    status=status,
                    model=model,
                    uptime=calculate_uptime(started_at),
                    missing_secrets=result.get("missing_secrets"),
                    onboarding_step=result.get("onboarding_step"),
                    process_running=result.get("process_running"),
                    health_error=result.get("error"),
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


def check_claw_health_safe(claw_name: str, host: dict) -> HealthResult:
    try:
        return check_claw_health(claw_name, host)
    except Exception as e:
        logger.warning("Health check failed for %s: %s", claw_name, e)
        return HealthResult(
            agent=claw_name,
            host=host.get("hostname", "unknown"),
            status=ClawStatus.UNKNOWN,
            user=None,
            error=str(e),
            missing_secrets=None,
            onboarding_step=None,
            process_running=None,
            onboarding_stages=None,
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
        agent_type = claw_record.get("type", agent_key)
        version = claw_record.get("version", "?")
        config = claw_record.get("config", {})
        model = "-"
        if isinstance(config, dict):
            provider = config.get("provider")
            if isinstance(provider, dict):
                model = provider.get("default_model", "-")

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
            version=version,
            status=status,
            model=model,
            uptime=calculate_uptime(started_at),
            missing_secrets=result.get("missing_secrets"),
            onboarding_step=result.get("onboarding_step"),
            process_running=result.get("process_running"),
            health_error=result.get("error"),
        )
    return None

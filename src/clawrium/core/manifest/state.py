"""Read actual fleet state from disk (hosts.json, providers.json)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ActualAgent:
    name: str
    type: str
    host: str  # primary hostname / IP
    status: str
    providers: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass
class ActualState:
    hosts: dict[str, dict]          # hostname or alias → host record
    providers: dict[str, dict]      # name → provider record
    channels: dict[str, dict]       # name → channel record
    integrations: dict[str, dict]   # name → integration record
    agents: dict[str, ActualAgent]  # agent name → ActualAgent

    @classmethod
    def from_disk(cls) -> ActualState:
        from clawrium.core.hosts import load_hosts
        from clawrium.core.providers.storage import load_providers

        hosts_raw = load_hosts()
        hosts: dict[str, dict] = {}
        agents: dict[str, ActualAgent] = {}

        for host in hosts_raw:
            hostname = host["hostname"]
            hosts[hostname] = host
            alias = host.get("alias")
            if alias:
                hosts[alias] = host

            for agent_name, agent_data in (host.get("agents") or {}).items():
                runtime = agent_data.get("runtime") or {}
                onboarding = agent_data.get("onboarding") or {}
                if runtime.get("status"):
                    status = runtime["status"]
                elif onboarding.get("state"):
                    status = onboarding["state"]
                else:
                    status = agent_data.get("status", "unknown")

                def _as_list(v) -> list:
                    return list(v) if isinstance(v, (list, tuple)) else []

                agents[agent_name] = ActualAgent(
                    name=agent_name,
                    type=agent_data.get("type", ""),
                    host=hostname,
                    status=status,
                    providers=_as_list(agent_data.get("providers")),
                    channels=_as_list(agent_data.get("channels")),
                    integrations=_as_list(agent_data.get("integrations")),
                    skills=_as_list(agent_data.get("skills")),
                )

        providers_raw = load_providers()
        providers: dict[str, dict] = {p["name"]: p for p in providers_raw}

        return cls(
            hosts=hosts,
            providers=providers,
            channels={},
            integrations={},
            agents=agents,
        )

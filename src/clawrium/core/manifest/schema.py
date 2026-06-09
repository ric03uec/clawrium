"""Dataclass schema for clawrium fleet manifests (apiVersion: clawrium.io/v1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class ResourceMetadata:
    name: str
    labels: dict[str, str] = field(default_factory=dict)


# ── Host ──────────────────────────────────────────────────────────────────────

@dataclass
class HostSpec:
    hostname: str
    user: str = "xclm"
    port: int = 22
    bootstrap: bool = False


@dataclass
class HostResource:
    metadata: ResourceMetadata
    spec: HostSpec
    kind: str = "host"


# ── Provider ──────────────────────────────────────────────────────────────────

@dataclass
class CredentialRef:
    secretRef: str


@dataclass
class ProviderCredentials:
    apiKey: Optional[CredentialRef] = None


@dataclass
class ProviderConfig:
    defaultModel: Optional[str] = None


@dataclass
class ProviderSpec:
    type: str
    config: ProviderConfig = field(default_factory=ProviderConfig)
    credentials: Optional[ProviderCredentials] = None


@dataclass
class ProviderResource:
    metadata: ResourceMetadata
    spec: ProviderSpec
    kind: str = "provider"


# ── Channel ───────────────────────────────────────────────────────────────────

@dataclass
class ChannelConfig:
    allowedUsers: list[str] = field(default_factory=list)


@dataclass
class ChannelSpec:
    type: str
    config: ChannelConfig = field(default_factory=ChannelConfig)


@dataclass
class ChannelResource:
    metadata: ResourceMetadata
    spec: ChannelSpec
    kind: str = "channel"


# ── Integration ───────────────────────────────────────────────────────────────

@dataclass
class IntegrationSpec:
    type: str


@dataclass
class IntegrationResource:
    metadata: ResourceMetadata
    spec: IntegrationSpec
    kind: str = "integration"


# ── Agent ─────────────────────────────────────────────────────────────────────

@dataclass
class AgentLifecycle:
    autoStart: bool = False
    autoRestart: bool = False


@dataclass
class AgentSpec:
    type: str
    host: Optional[str] = None
    provider: Optional[str] = None
    channels: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    version: Optional[str] = None
    config: dict = field(default_factory=dict)
    lifecycle: AgentLifecycle = field(default_factory=AgentLifecycle)


@dataclass
class AgentResource:
    metadata: ResourceMetadata
    spec: AgentSpec
    kind: str = "agent"


# ── Document ──────────────────────────────────────────────────────────────────

ManifestResource = Union[
    HostResource, ProviderResource, ChannelResource, IntegrationResource, AgentResource
]


@dataclass
class ManifestDocument:
    resources: list[ManifestResource] = field(default_factory=list)

    def hosts(self) -> list[HostResource]:
        return [r for r in self.resources if isinstance(r, HostResource)]

    def providers(self) -> list[ProviderResource]:
        return [r for r in self.resources if isinstance(r, ProviderResource)]

    def channels(self) -> list[ChannelResource]:
        return [r for r in self.resources if isinstance(r, ChannelResource)]

    def integrations(self) -> list[IntegrationResource]:
        return [r for r in self.resources if isinstance(r, IntegrationResource)]

    def agents(self) -> list[AgentResource]:
        return [r for r in self.resources if isinstance(r, AgentResource)]

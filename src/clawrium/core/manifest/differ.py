"""Compute the ChangeSet between a desired ManifestDocument and actual state."""
from __future__ import annotations

from dataclasses import dataclass, field

from .schema import ManifestDocument
from .state import ActualState


@dataclass
class Op:
    kind: str    # host | provider | channel | integration | agent
    name: str
    action: str  # create | update | delete | noop
    details: str = ""


@dataclass
class AttachOp:
    agent: str
    resource_kind: str   # provider | channel | integration | skill
    resource_name: str


@dataclass
class ChangeSet:
    creates: list[Op] = field(default_factory=list)
    updates: list[Op] = field(default_factory=list)
    deletes: list[Op] = field(default_factory=list)
    attaches: list[AttachOp] = field(default_factory=list)
    detaches: list[AttachOp] = field(default_factory=list)
    starts: list[str] = field(default_factory=list)
    restarts: list[str] = field(default_factory=list)
    noops: list[Op] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.creates, self.updates, self.deletes,
            self.attaches, self.detaches, self.starts, self.restarts,
        ])


def compute(
    doc: ManifestDocument,
    actual: ActualState,
    for_delete: bool = False,
) -> ChangeSet:
    cs = ChangeSet()
    if for_delete:
        _compute_deletes(doc, actual, cs)
    else:
        _compute_hosts(doc, actual, cs)
        _compute_providers(doc, actual, cs)
        _compute_channels(doc, actual, cs)
        _compute_integrations(doc, actual, cs)
        _compute_agents(doc, actual, cs)
    return cs


# ── apply helpers ─────────────────────────────────────────────────────────────

def _compute_hosts(doc: ManifestDocument, actual: ActualState, cs: ChangeSet) -> None:
    for host in doc.hosts():
        name = host.metadata.name
        hostname = host.spec.hostname
        if hostname in actual.hosts or name in actual.hosts:
            cs.noops.append(Op(kind="host", name=name, action="noop"))
        else:
            cs.creates.append(Op(kind="host", name=name, action="create"))


def _compute_providers(
    doc: ManifestDocument, actual: ActualState, cs: ChangeSet
) -> None:
    for provider in doc.providers():
        name = provider.metadata.name
        if name in actual.providers:
            cs.noops.append(Op(kind="provider", name=name, action="noop"))
        else:
            cs.creates.append(Op(kind="provider", name=name, action="create"))


def _compute_channels(
    doc: ManifestDocument, actual: ActualState, cs: ChangeSet
) -> None:
    for channel in doc.channels():
        name = channel.metadata.name
        if name in actual.channels:
            cs.noops.append(Op(kind="channel", name=name, action="noop"))
        else:
            cs.creates.append(Op(kind="channel", name=name, action="create"))


def _compute_integrations(
    doc: ManifestDocument, actual: ActualState, cs: ChangeSet
) -> None:
    for integration in doc.integrations():
        name = integration.metadata.name
        if name in actual.integrations:
            cs.noops.append(Op(kind="integration", name=name, action="noop"))
        else:
            cs.creates.append(Op(kind="integration", name=name, action="create"))


def _compute_agents(
    doc: ManifestDocument, actual: ActualState, cs: ChangeSet
) -> None:
    for agent in doc.agents():
        name = agent.metadata.name
        if name not in actual.agents:
            cs.creates.append(Op(kind="agent", name=name, action="create"))
            # All attachments are new
            if agent.spec.provider:
                cs.attaches.append(
                    AttachOp(agent=name, resource_kind="provider", resource_name=agent.spec.provider)
                )
            for ch in agent.spec.channels:
                cs.attaches.append(AttachOp(agent=name, resource_kind="channel", resource_name=ch))
            for intg in agent.spec.integrations:
                cs.attaches.append(
                    AttachOp(agent=name, resource_kind="integration", resource_name=intg)
                )
            if agent.spec.lifecycle.autoStart:
                cs.starts.append(name)
        else:
            actual_agent = actual.agents[name]

            # Version change → upgrade op + restart after
            desired_version = agent.spec.version
            if desired_version and desired_version != actual_agent.version:
                cs.updates.append(
                    Op(
                        kind="agent",
                        name=name,
                        action="update",
                        details=f"{actual_agent.version} → {desired_version}",
                    )
                )
                cs.restarts.append(name)
            else:
                cs.noops.append(Op(kind="agent", name=name, action="noop"))

            desired_providers = [agent.spec.provider] if agent.spec.provider else []
            for p in desired_providers:
                if p not in actual_agent.providers:
                    cs.attaches.append(AttachOp(agent=name, resource_kind="provider", resource_name=p))
            for p in actual_agent.providers:
                if p not in desired_providers:
                    cs.detaches.append(AttachOp(agent=name, resource_kind="provider", resource_name=p))

            for ch in agent.spec.channels:
                if ch not in actual_agent.channels:
                    cs.attaches.append(AttachOp(agent=name, resource_kind="channel", resource_name=ch))
            for ch in actual_agent.channels:
                if ch not in agent.spec.channels:
                    cs.detaches.append(AttachOp(agent=name, resource_kind="channel", resource_name=ch))

            for intg in agent.spec.integrations:
                if intg not in actual_agent.integrations:
                    cs.attaches.append(
                        AttachOp(agent=name, resource_kind="integration", resource_name=intg)
                    )
            for intg in actual_agent.integrations:
                if intg not in agent.spec.integrations:
                    cs.detaches.append(
                        AttachOp(agent=name, resource_kind="integration", resource_name=intg)
                    )


# ── delete helper ─────────────────────────────────────────────────────────────

def _compute_deletes(
    doc: ManifestDocument, actual: ActualState, cs: ChangeSet
) -> None:
    for agent in doc.agents():
        name = agent.metadata.name
        if name in actual.agents:
            cs.deletes.append(Op(kind="agent", name=name, action="delete"))
        else:
            cs.noops.append(Op(kind="agent", name=name, action="noop"))

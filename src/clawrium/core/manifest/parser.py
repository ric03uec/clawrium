"""Parse single or multi-document YAML files into a ManifestDocument."""
from __future__ import annotations

from pathlib import Path

import yaml

from .schema import (
    AgentLifecycle,
    AgentResource,
    AgentSpec,
    ChannelConfig,
    ChannelResource,
    ChannelSpec,
    CredentialRef,
    HostResource,
    HostSpec,
    IntegrationResource,
    IntegrationSpec,
    ManifestDocument,
    ManifestResource,
    ProviderConfig,
    ProviderCredentials,
    ProviderResource,
    ProviderSpec,
    ResourceMetadata,
)

_KNOWN_KINDS = {"Host", "Provider", "Channel", "Integration", "Agent"}


def parse_file(path: Path) -> ManifestDocument:
    """Parse a single YAML file (may contain multiple documents separated by ---)."""
    text = path.read_text(encoding="utf-8")
    resources: list[ManifestResource] = []
    for raw in yaml.safe_load_all(text):
        if raw is None:
            continue
        resources.append(_parse_resource(raw, source=str(path)))
    return ManifestDocument(resources=resources)


def parse_directory(path: Path) -> ManifestDocument:
    """Parse all *.yaml / *.yml files in a directory, sorted by name."""
    resources: list[ManifestResource] = []
    files = sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml"))
    seen: set[str] = set()
    for f in files:
        if f.name in seen:
            continue
        seen.add(f.name)
        resources.extend(parse_file(f).resources)
    return ManifestDocument(resources=resources)


# ── internal ──────────────────────────────────────────────────────────────────

def _parse_resource(raw: dict, source: str = "") -> ManifestResource:
    kind = raw.get("kind", "")
    if kind not in _KNOWN_KINDS:
        raise ValueError(
            f"Unknown kind {kind!r} in {source or 'manifest'}. "
            f"Valid kinds: {sorted(_KNOWN_KINDS)}"
        )

    meta_raw = raw.get("metadata") or {}
    metadata = ResourceMetadata(
        name=meta_raw["name"],
        labels=meta_raw.get("labels") or {},
    )
    spec = raw.get("spec") or {}

    if kind == "Host":
        return HostResource(
            metadata=metadata,
            spec=HostSpec(
                hostname=spec["hostname"],
                user=spec.get("user", "xclm"),
                port=int(spec.get("port", 22)),
                bootstrap=bool(spec.get("bootstrap", False)),
            ),
        )

    if kind == "Provider":
        config_raw = spec.get("config") or {}
        creds_raw = spec.get("credentials") or {}
        api_key_raw = creds_raw.get("apiKey") or {}
        credentials = None
        if api_key_raw and api_key_raw.get("secretRef"):
            credentials = ProviderCredentials(
                apiKey=CredentialRef(secretRef=api_key_raw["secretRef"])
            )
        return ProviderResource(
            metadata=metadata,
            spec=ProviderSpec(
                type=spec["type"],
                config=ProviderConfig(defaultModel=config_raw.get("defaultModel")),
                credentials=credentials,
            ),
        )

    if kind == "Channel":
        config_raw = spec.get("config") or {}
        return ChannelResource(
            metadata=metadata,
            spec=ChannelSpec(
                type=spec["type"],
                config=ChannelConfig(
                    allowedUsers=list(config_raw.get("allowedUsers") or [])
                ),
            ),
        )

    if kind == "Integration":
        return IntegrationResource(
            metadata=metadata,
            spec=IntegrationSpec(type=spec["type"]),
        )

    # kind == "Agent"
    lifecycle_raw = spec.get("lifecycle") or {}
    return AgentResource(
        metadata=metadata,
        spec=AgentSpec(
            type=spec["type"],
            host=spec.get("host"),
            provider=spec.get("provider"),
            channels=list(spec.get("channels") or []),
            integrations=list(spec.get("integrations") or []),
            skills=list(spec.get("skills") or []),
            version=spec.get("version"),
            config=dict(spec.get("config") or {}),
            lifecycle=AgentLifecycle(
                autoStart=bool(lifecycle_raw.get("autoStart", False)),
                autoRestart=bool(lifecycle_raw.get("autoRestart", False)),
            ),
        ),
    )

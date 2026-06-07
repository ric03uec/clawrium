"""Cross-reference validation and secret preflight for ManifestDocuments."""
from __future__ import annotations

from .schema import ManifestDocument


def validate_refs(doc: ManifestDocument) -> list[str]:
    """Return a list of error strings for any unresolved cross-references."""
    errors: list[str] = []
    host_names = {h.metadata.name for h in doc.hosts()}
    provider_names = {p.metadata.name for p in doc.providers()}
    channel_names = {c.metadata.name for c in doc.channels()}
    integration_names = {i.metadata.name for i in doc.integrations()}

    for agent in doc.agents():
        n = agent.metadata.name
        if agent.spec.host and agent.spec.host not in host_names:
            errors.append(
                f"agent/{n}: references host {agent.spec.host!r} "
                f"which is not declared in the manifest"
            )
        if agent.spec.provider and agent.spec.provider not in provider_names:
            errors.append(
                f"agent/{n}: references provider {agent.spec.provider!r} "
                f"which is not declared in the manifest"
            )
        for ch in agent.spec.channels:
            if ch not in channel_names:
                errors.append(
                    f"agent/{n}: references channel {ch!r} "
                    f"which is not declared in the manifest"
                )
        for intg in agent.spec.integrations:
            if intg not in integration_names:
                errors.append(
                    f"agent/{n}: references integration {intg!r} "
                    f"which is not declared in the manifest"
                )
    return errors


def collect_secret_refs(doc: ManifestDocument) -> list[str]:
    """Return all secretRef paths declared across providers in the document."""
    refs: list[str] = []
    for provider in doc.providers():
        creds = provider.spec.credentials
        if creds and creds.apiKey and creds.apiKey.secretRef:
            refs.append(creds.apiKey.secretRef)
    return refs


def secret_preflight(secret_refs: list[str]) -> list[str]:
    """Return the subset of secret refs that are not yet stored locally."""
    from clawrium.core.providers.storage import get_provider_api_key

    missing: list[str] = []
    for ref in secret_refs:
        parts = ref.split("/")
        # Expected format: providers/<name>/apiKey
        if len(parts) == 3 and parts[0] == "providers":
            provider_name = parts[1]
            val = get_provider_api_key(provider_name)
            if not val:
                missing.append(ref)
    return missing

"""Provider management API routes.

CRUD operations for LLM providers. Wraps the existing
clawrium.core.providers.storage module.
"""

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from clawrium.core.hosts import update_host
from clawrium.core.provider_attachments import (
    AUXILIARY_SLOTS,
    PRIMARY_ROLE,
    VALID_ROLES,
    AttachmentError,
    normalize,
    supports_multi_provider,
    validate,
)
from clawrium.core.providers.models import (
    load_model_catalog,
    get_models_for_provider,
    search_models,
)
from clawrium.gui.routes._common import resolve_agent as _resolve_agent
from clawrium.core.providers.storage import (
    PROVIDER_MODELS,
    DuplicateProviderError,
    InvalidOllamaUrlError,
    InvalidProviderNameError,
    InvalidProviderTypeError,
    add_provider,
    get_provider,
    load_providers,
    remove_provider,
    update_provider,
    validate_ollama_url,
    validate_provider_name,
    validate_provider_type,
    get_provider_api_key,
    set_provider_api_key,
    remove_provider_api_key,
)

# Accelerator vendor is a UI-level hint for local-inference providers
# (ollama) so the topology view can render the right brand badge. Only
# "nvidia" / "amd" are accepted; ollama defaults to "nvidia" when omitted.
AcceleratorVendor = Literal["nvidia", "amd"]
LOCAL_INFERENCE_TYPES = frozenset({"ollama"})
DEFAULT_ACCELERATOR_VENDOR: AcceleratorVendor = "nvidia"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _resolve_accelerator_vendor(provider: dict) -> str | None:
    """Return the effective accelerator_vendor for a provider record.

    Local-inference providers (ollama) without an explicit value default
    to "nvidia" so the topology view always has a brand to render.
    """
    stored = provider.get("accelerator_vendor")
    if stored in ("nvidia", "amd"):
        return stored
    if provider.get("type") in LOCAL_INFERENCE_TYPES:
        return DEFAULT_ACCELERATOR_VENDOR
    return None


class ProviderCreate(BaseModel):
    """Request body for creating a provider."""

    name: str
    type: str
    endpoint: str | None = None
    default_model: str | None = None
    api_key: str | None = None
    accelerator_vendor: AcceleratorVendor | None = None


class ProviderUpdate(BaseModel):
    """Request body for updating a provider."""

    default_model: str | None = None
    endpoint: str | None = None
    api_key: str | None = None
    accelerator_vendor: AcceleratorVendor | None = None


@router.get("")
async def list_providers():
    """List all configured providers."""
    providers = await asyncio.to_thread(load_providers)
    # Mask API keys - just indicate if configured
    result = []
    for p in providers:
        has_key = False
        try:
            key = get_provider_api_key(p["name"])
            has_key = key is not None
        except Exception:
            pass

        result.append(
            {
                "name": p["name"],
                "type": p["type"],
                "endpoint": p.get("endpoint"),
                "default_model": p.get("default_model"),
                "available_models": p.get("available_models"),
                "has_api_key": has_key,
                "accelerator_vendor": _resolve_accelerator_vendor(p),
                "created_at": p.get("created_at"),
                "updated_at": p.get("updated_at"),
            }
        )
    return {"providers": result}


@router.get("/types")
async def provider_types():
    """Get available provider types with rich model metadata from the catalog.

    Ollama returns an empty model list — its models are populated per-instance
    from the host's Ollama daemon via `available_models`, not from the catalog.
    """
    catalog = load_model_catalog()
    types = {}
    for ptype, info in PROVIDER_MODELS.items():
        if ptype == "ollama":
            models: list[dict] = []
        else:
            models = list(catalog["providers"].get(ptype, {}).get("models", []))
        types[ptype] = {
            "endpoint": info.get("endpoint"),
            "models": models,
            "requires_api_key": info.get("requires_api_key", ptype != "ollama"),
            "requires_endpoint": info.get("requires_endpoint", ptype == "ollama"),
        }
    return {"types": types}


@router.get("/catalog")
async def model_catalog(
    provider: str | None = Query(None, description="Filter by provider type"),
    search: str | None = Query(None, description="Fuzzy search query"),
    limit: int = Query(100, ge=1, le=500),
):
    """Get the full model catalog with rich metadata.

    Optionally filter by provider or search by model name/ID.
    """
    if search:
        results = await asyncio.to_thread(search_models, search, provider, limit)
        # Add provider_type to each result
        catalog = load_model_catalog()
        provider_lookup: dict[str, str] = {}
        for ptype, pdata in catalog["providers"].items():
            for m in pdata["models"]:
                provider_lookup[m["id"]] = ptype

        return {
            "models": [
                {**m, "provider_type": provider_lookup.get(m["id"], "unknown")}
                for m in results
            ]
        }

    if provider:
        try:
            models = await asyncio.to_thread(get_models_for_provider, provider)
        except Exception:
            raise HTTPException(
                status_code=404, detail=f"Provider '{provider}' not in catalog"
            )
        return {"models": [{**m, "provider_type": provider} for m in models]}

    # Return all models from all providers
    catalog = load_model_catalog()
    all_models = []
    for ptype, pdata in catalog["providers"].items():
        for m in pdata["models"]:
            all_models.append({**m, "provider_type": ptype})

    return {"models": all_models[:limit]}


@router.get("/{name}")
async def get_provider_detail(name: str):
    """Get a single provider's details."""
    provider = await asyncio.to_thread(get_provider, name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    has_key = False
    try:
        key = get_provider_api_key(name)
        has_key = key is not None
    except Exception:
        pass

    return {
        "name": provider["name"],
        "type": provider["type"],
        "endpoint": provider.get("endpoint"),
        "default_model": provider.get("default_model"),
        "available_models": provider.get("available_models"),
        "has_api_key": has_key,
        "accelerator_vendor": _resolve_accelerator_vendor(provider),
        "created_at": provider.get("created_at"),
        "updated_at": provider.get("updated_at"),
    }


@router.post("")
async def create_provider(body: ProviderCreate):
    """Create a new provider."""
    try:
        validate_provider_name(body.name)
        validate_provider_type(body.type)
    except (InvalidProviderNameError, InvalidProviderTypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Determine endpoint
    endpoint = body.endpoint
    if not endpoint and body.type in PROVIDER_MODELS:
        endpoint = PROVIDER_MODELS[body.type].get("endpoint")

    # Apply the same SSRF guard the CLI uses for user-supplied Ollama
    # endpoints — without this, a client can store
    # http://169.254.169.254/... and exfiltrate cloud metadata via clm
    # provider sync. validate_ollama_url() blocks cloud metadata IPs and
    # rejects non-http(s) schemes.
    if body.type in LOCAL_INFERENCE_TYPES and endpoint:
        try:
            endpoint = validate_ollama_url(endpoint)
        except InvalidOllamaUrlError as e:
            raise HTTPException(status_code=400, detail=str(e))

    provider_record: dict[str, Any] = {
        "name": body.name,
        "type": body.type,
        "endpoint": endpoint,
        "default_model": body.default_model,
    }
    # Persist accelerator_vendor only for local-inference providers; storing
    # it on cloud providers would be misleading metadata.
    if body.type in LOCAL_INFERENCE_TYPES:
        provider_record["accelerator_vendor"] = (
            body.accelerator_vendor or DEFAULT_ACCELERATOR_VENDOR
        )

    try:
        await asyncio.to_thread(add_provider, provider_record)
    except DuplicateProviderError:
        raise HTTPException(
            status_code=409, detail=f"Provider '{body.name}' already exists"
        )

    # Store API key if provided
    if body.api_key:
        try:
            set_provider_api_key(body.name, body.api_key)
        except Exception as e:
            logger.warning("Failed to store API key for %s: %s", body.name, e)

    return {"success": True, "name": body.name}


@router.put("/{name}")
async def update_provider_endpoint(name: str, body: ProviderUpdate):
    """Update an existing provider."""
    provider = await asyncio.to_thread(get_provider, name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    updates: dict[str, Any] = {}
    if body.default_model is not None:
        updates["default_model"] = body.default_model
    if body.endpoint is not None:
        endpoint_value = body.endpoint
        # Same SSRF guard as the create path. Endpoint overrides on
        # cloud providers (bedrock/openai/etc.) are accepted here without
        # additional validation because the broader cloud-endpoint
        # validation is out of scope for this PR; we only enforce the
        # documented invariant for local-inference endpoints.
        if provider.get("type") in LOCAL_INFERENCE_TYPES and endpoint_value:
            try:
                endpoint_value = validate_ollama_url(endpoint_value)
            except InvalidOllamaUrlError as e:
                raise HTTPException(status_code=400, detail=str(e))
        updates["endpoint"] = endpoint_value
    if (
        body.accelerator_vendor is not None
        and provider.get("type") in LOCAL_INFERENCE_TYPES
    ):
        updates["accelerator_vendor"] = body.accelerator_vendor

    if updates:

        def _apply(existing: dict) -> dict:
            return {**existing, **updates}

        await asyncio.to_thread(update_provider, name, _apply)

    # Update API key if provided
    if body.api_key is not None:
        if body.api_key == "":
            remove_provider_api_key(name)
        else:
            set_provider_api_key(name, body.api_key)

    return {"success": True, "name": name}


@router.delete("/{name}")
async def delete_provider(name: str):
    """Remove a provider."""
    provider = await asyncio.to_thread(get_provider, name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    try:
        await asyncio.to_thread(remove_provider, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Also remove the API key
    try:
        remove_provider_api_key(name)
    except Exception:
        pass

    return {"success": True, "name": name}


# ─── Agent attachment endpoints ─────────────────────────────────────
#
# Mirror the CLI in `src/clawrium/cli/clawctl/agent/provider.py`:
# - hermes: `role` required on attach, exactly one `primary`, aux slots
#   from AUXILIARY_SLOTS are unique. Detaching primary while aux remain
#   is rejected.
# - non-hermes (zeroclaw/openclaw): `role` rejected; second attach is
#   rejected via the pinned `single-provider invariant` message from
#   `core.provider_attachments.validate()`.


class AttachmentRequest(BaseModel):
    """Body for POST /api/providers/{name}/attach."""

    agent: str
    role: str | None = None


def _resolve_agent_for_attach(agent: str) -> tuple[dict, str, str]:
    """Return (host, agent_key, agent_type) for an agent name.

    Raises HTTPException 404 if the agent cannot be resolved. Mirrors
    the CLI's `safe_resolve_agent` + `resolve_agent_key` combo without
    pulling in typer-only emit_error paths.
    """
    resolved = _resolve_agent(agent)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"agent '{agent}' not found")
    host, _agent_type_from_lookup, claw_record = resolved
    # Re-scan the host's agents map to find the canonical instance key —
    # `get_agent_by_name` returns the agent *type*, which is not the
    # mutation key on modern installs. Matches CLI behavior.
    agents = host.get("agents", {}) or {}
    agent_key: str | None = None
    for key, record in agents.items():
        if not isinstance(record, dict):
            continue
        if agent in (key, record.get("agent_name"), record.get("name")):
            agent_key = key
            break
    if agent_key is None:
        raise HTTPException(status_code=404, detail=f"agent '{agent}' not found")
    agent_type = str(claw_record.get("type") or "")
    return host, agent_key, agent_type


def _attachment_name(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        name = entry.get("name")
        if isinstance(name, str):
            return name
    return None


def _persist_attachments(
    hostname: str,
    agent_key: str,
    agent_type: str,
    attachments: list,
) -> None:
    """Validate then write the attachment list onto the agent record.

    `validate()` raises AttachmentError on invariant violations — the
    caller translates that into HTTP 400. Persistence failure (no rows
    written) surfaces as HTTP 500.
    """
    validate(attachments, agent_type)

    def updater(h: dict) -> dict:
        agents = h.get("agents", {})
        if agent_key not in agents:
            return h
        agent_data = agents[agent_key]
        if not isinstance(agent_data, dict):
            return h
        agent_data["providers"] = attachments
        return h

    if not update_host(hostname, updater):
        raise HTTPException(
            status_code=500,
            detail=f"failed to persist attachments for agent '{agent_key}'",
        )


def _available_roles(
    agent_type: str, attachments: list
) -> list[str]:
    """Return roles a fresh attach is currently allowed to use.

    For hermes:
    - if no primary yet → only ['primary']
    - otherwise → AUXILIARY_SLOTS minus already-filled aux roles
    For non-hermes → empty list (role is rejected entirely).
    """
    if not supports_multi_provider(agent_type):
        return []
    has_primary = any(
        isinstance(e, dict) and e.get("role") == PRIMARY_ROLE for e in attachments
    )
    if not has_primary:
        return [PRIMARY_ROLE]
    filled = {
        e.get("role")
        for e in attachments
        if isinstance(e, dict) and e.get("role") != PRIMARY_ROLE
    }
    return [r for r in AUXILIARY_SLOTS if r not in filled]


@router.get("/attachments/{agent}")
async def list_agent_attachments(agent: str):
    """Return current attachments + role availability for an agent.

    Drives the frontend's role dropdown: the modal shows `available_roles`
    for a fresh attach, and disables the primary-detach button when
    `aux_count > 0`.
    """
    host, agent_key, agent_type = _resolve_agent_for_attach(agent)
    raw = (host.get("agents", {}) or {}).get(agent_key, {}).get("providers", [])
    attachments = normalize(raw, agent_type)
    primary_entry = next(
        (e for e in attachments if isinstance(e, dict) and e.get("role") == PRIMARY_ROLE),
        None,
    )
    aux_count = sum(
        1 for e in attachments if isinstance(e, dict) and e.get("role") != PRIMARY_ROLE
    )
    return {
        "agent": agent,
        "agent_type": agent_type,
        "supports_multi": supports_multi_provider(agent_type),
        "attachments": attachments,
        "available_roles": _available_roles(agent_type, attachments),
        "primary_attached": primary_entry is not None,
        "aux_count": aux_count,
    }


@router.post("/{name}/attach")
async def attach_provider_to_agent(name: str, body: AttachmentRequest):
    """Attach a registered provider to an agent.

    Mirrors `clawctl agent provider attach`. On hermes, `role` is
    required; on non-hermes, `role` is rejected and the singleton
    invariant from `provider_attachments.validate()` still applies.
    """
    provider_record = await asyncio.to_thread(get_provider, name)
    if not provider_record:
        raise HTTPException(status_code=404, detail=f"provider '{name}' not found")

    host, agent_key, agent_type = _resolve_agent_for_attach(body.agent)
    hostname = host["hostname"]
    multi = supports_multi_provider(agent_type)

    # Role flag validity is agent-type-scoped — identical contract to
    # the CLI in cli/clawctl/agent/provider.py.
    if multi:
        if body.role is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"agent '{body.agent}' is a hermes agent; role is required"
                ),
            )
        if body.role not in VALID_ROLES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"invalid role {body.role!r}; expected one of "
                    f"{', '.join(sorted(VALID_ROLES))}"
                ),
            )
    else:
        if body.role is not None:
            raise HTTPException(
                status_code=400,
                detail=f"role is not supported on agent type {agent_type!r}",
            )

    raw = (host.get("agents", {}) or {}).get(agent_key, {}).get("providers", [])
    current = normalize(raw, agent_type)

    # Idempotent re-attach by name. For hermes, role must match the
    # already-attached entry's role — otherwise the operator's intent
    # is ambiguous (rebinding to a different slot) and we require a
    # detach first.
    existing = next((e for e in current if _attachment_name(e) == name), None)
    if existing is not None:
        if multi and isinstance(existing, dict):
            existing_role = existing.get("role")
            if body.role != existing_role:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"provider {name!r} already attached to agent "
                        f"{body.agent!r} with role {existing_role!r}; "
                        "detach first to rebind"
                    ),
                )
        return {
            "success": True,
            "agent": body.agent,
            "name": name,
            "already_attached": True,
        }

    if not multi and current:
        other = _attachment_name(current[0]) or ""
        raise HTTPException(
            status_code=409,
            detail=(
                f"agent '{body.agent}' already has provider {other!r} attached"
            ),
        )

    if multi:
        model = ""
        default_model = provider_record.get("default_model")
        if isinstance(default_model, str):
            model = default_model
        new_attachments = [
            *current,
            {"name": name, "role": body.role, "model": model},
        ]
    else:
        new_attachments = [*current, name]

    try:
        await asyncio.to_thread(
            _persist_attachments, hostname, agent_key, agent_type, new_attachments
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "agent": body.agent,
        "name": name,
        "role": body.role if multi else None,
    }


@router.delete("/{name}/attach")
async def detach_provider_from_agent(name: str, agent: str = Query(...)):
    """Detach a provider from an agent.

    Mirrors `clawctl agent provider detach`. On hermes, detaching the
    primary while auxiliary attachments remain is rejected — operators
    must detach aux entries first.
    """
    host, agent_key, agent_type = _resolve_agent_for_attach(agent)
    hostname = host["hostname"]
    multi = supports_multi_provider(agent_type)

    raw = (host.get("agents", {}) or {}).get(agent_key, {}).get("providers", [])
    current = normalize(raw, agent_type)
    target = next((e for e in current if _attachment_name(e) == name), None)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"provider {name!r} not attached to agent {agent!r}",
        )

    if (
        multi
        and isinstance(target, dict)
        and target.get("role") == PRIMARY_ROLE
        and len(current) > 1
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"cannot detach primary provider {name!r} from agent "
                f"{agent!r} while auxiliary attachments remain; "
                "detach auxiliary attachments first"
            ),
        )

    remaining = [e for e in current if e is not target]
    try:
        await asyncio.to_thread(
            _persist_attachments, hostname, agent_key, agent_type, remaining
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"success": True, "agent": agent, "name": name}

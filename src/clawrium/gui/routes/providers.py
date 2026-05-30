"""Provider management API routes.

CRUD operations for LLM providers. Wraps the existing
clawrium.core.providers.storage module.
"""

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from clawrium.core.providers.models import (
    load_model_catalog,
    get_models_for_provider,
    search_models,
)
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

"""Provider management API routes.

CRUD operations for LLM providers. Wraps the existing
clawrium.core.providers.storage module.
"""

import asyncio
import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
    get_provider_aws_credentials,
    set_provider_aws_credentials,
    remove_provider_aws_credentials,
)

# Default AWS region used by bedrock when the operator does not specify one.
# Matches the template-side default in the hermes/openclaw env templates.
DEFAULT_BEDROCK_REGION = "us-east-1"

# Bedrock region is interpolated into URL templates
# (e.g. `bedrock-runtime.<region>.amazonaws.com`). Constrain it to the
# AWS region character set so a crafted value can't redirect signed
# requests. Free text from the user perspective — they pick the region —
# but only [a-z0-9-] is accepted.
_REGION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


def _validate_region(region: str) -> str:
    """Normalize and validate a bedrock region string.

    Raises HTTPException(400) on empty or out-of-charset input.
    """
    cleaned = (region or "").strip().lower()
    if not cleaned or not _REGION_PATTERN.match(cleaned):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid region. Must be lowercase alphanumerics and "
                "hyphens (AWS region format, e.g. 'us-east-1')."
            ),
        )
    return cleaned

# Accelerator vendor is a UI-level hint for local-inference providers
# (ollama) so the topology view can render the right brand badge. Only
# "nvidia" / "amd" are accepted; ollama defaults to "nvidia" when omitted.
AcceleratorVendor = Literal["nvidia", "amd"]
LOCAL_INFERENCE_TYPES = frozenset({"ollama"})
DEFAULT_ACCELERATOR_VENDOR: AcceleratorVendor = "nvidia"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _serialize_provider(p: dict) -> dict:
    """Shape a stored provider record for the API response.

    Surfaces `has_api_key` for cloud providers and `has_aws_credentials` +
    `region` for bedrock providers so the GUI can render the right
    affordances without reaching into the secrets store.
    """
    name = p["name"]
    has_key = False
    try:
        has_key = get_provider_api_key(name) is not None
    except Exception:
        logger.warning("get_provider_api_key failed for %s", name, exc_info=True)

    has_aws = False
    if p.get("type") == "bedrock":
        try:
            access, secret = get_provider_aws_credentials(name)
            has_aws = access is not None and secret is not None
        except Exception:
            logger.warning(
                "get_provider_aws_credentials failed for %s", name, exc_info=True
            )

    return {
        "name": name,
        "type": p["type"],
        "endpoint": p.get("endpoint"),
        "default_model": p.get("default_model"),
        "available_models": p.get("available_models"),
        "has_api_key": has_key,
        "accelerator_vendor": _resolve_accelerator_vendor(p),
        "region": p.get("region"),
        "has_aws_credentials": has_aws,
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
    }


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


# Length caps prevent multi-MB credential payloads and bound any value
# that flows into rendered templates (env files, URL fragments).
_API_KEY_MAX = 512
_AWS_ACCESS_KEY_MAX = 128
_AWS_SECRET_KEY_MAX = 256
_REGION_MAX = 32
_ENDPOINT_MAX = 512
_DEFAULT_MODEL_MAX = 128

# `default_model` is interpolated verbatim into hermes / openclaw env
# templates; constrain it to a printable-ASCII subset that mirrors model
# IDs in the catalog. Catches bidi/control-character injection without
# rejecting legitimate model names.
_DEFAULT_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/+\- @]{1,128}$")


def _validate_default_model(value: str | None) -> str | None:
    if value is None:
        return None
    if not _DEFAULT_MODEL_PATTERN.match(value):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid default_model. Must be 1–128 printable ASCII "
                "characters (letters, digits, `._:/+- @`)."
            ),
        )
    return value


class ProviderCreate(BaseModel):
    """Request body for creating a provider."""

    name: str
    type: str
    endpoint: str | None = Field(default=None, max_length=_ENDPOINT_MAX)
    default_model: str | None = Field(default=None, max_length=_DEFAULT_MODEL_MAX)
    api_key: str | None = Field(default=None, max_length=_API_KEY_MAX)
    accelerator_vendor: AcceleratorVendor | None = None
    aws_access_key_id: str | None = Field(default=None, max_length=_AWS_ACCESS_KEY_MAX)
    aws_secret_access_key: str | None = Field(
        default=None, max_length=_AWS_SECRET_KEY_MAX
    )
    region: str | None = Field(default=None, max_length=_REGION_MAX)


class ProviderUpdate(BaseModel):
    """Request body for updating a provider."""

    default_model: str | None = Field(default=None, max_length=_DEFAULT_MODEL_MAX)
    endpoint: str | None = Field(default=None, max_length=_ENDPOINT_MAX)
    api_key: str | None = Field(default=None, max_length=_API_KEY_MAX)
    accelerator_vendor: AcceleratorVendor | None = None
    aws_access_key_id: str | None = Field(default=None, max_length=_AWS_ACCESS_KEY_MAX)
    aws_secret_access_key: str | None = Field(
        default=None, max_length=_AWS_SECRET_KEY_MAX
    )
    region: str | None = Field(default=None, max_length=_REGION_MAX)


@router.get("")
async def list_providers():
    """List all configured providers."""
    providers = await asyncio.to_thread(load_providers)
    # Mask API keys - just indicate if configured
    result = []
    for p in providers:
        result.append(_serialize_provider(p))
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
        is_bedrock = ptype == "bedrock"
        types[ptype] = {
            "endpoint": info.get("endpoint"),
            "models": models,
            "requires_api_key": (
                False if is_bedrock else info.get("requires_api_key", ptype != "ollama")
            ),
            "requires_endpoint": info.get("requires_endpoint", ptype == "ollama"),
            "requires_aws_credentials": is_bedrock,
            "default_region": DEFAULT_BEDROCK_REGION if is_bedrock else None,
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

    return _serialize_provider(provider)


@router.post("")
async def create_provider(body: ProviderCreate):
    """Create a new provider."""
    try:
        validate_provider_name(body.name)
        validate_provider_type(body.type)
    except (InvalidProviderNameError, InvalidProviderTypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    _validate_default_model(body.default_model)

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

    # Reject mismatched credential families up front rather than silently
    # discarding them.
    _aws_fields_present = (
        body.aws_access_key_id is not None
        or body.aws_secret_access_key is not None
        or body.region is not None
    )
    if body.type == "bedrock":
        if body.api_key:
            raise HTTPException(
                status_code=400,
                detail="Bedrock uses AWS credentials, not an API key.",
            )
        if not body.aws_access_key_id or not body.aws_secret_access_key:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Bedrock requires aws_access_key_id and "
                    "aws_secret_access_key."
                ),
            )
    elif _aws_fields_present:
        raise HTTPException(
            status_code=400,
            detail=(
                "aws_access_key_id, aws_secret_access_key, and region are "
                "only valid for bedrock providers."
            ),
        )

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
    if body.type == "bedrock":
        provider_record["region"] = _validate_region(
            body.region or DEFAULT_BEDROCK_REGION
        )

    try:
        await asyncio.to_thread(add_provider, provider_record)
    except DuplicateProviderError:
        raise HTTPException(
            status_code=409, detail=f"Provider '{body.name}' already exists"
        )

    # Store credentials. Bedrock writes AWS creds; everything else writes
    # the api_key (silently ignored for ollama which has neither).
    # Failures here are fatal — a provider record without its credentials
    # is broken on every downstream call. Roll back the record and
    # surface a 500 with a generic message.
    try:
        if body.type == "bedrock":
            set_provider_aws_credentials(
                body.name, body.aws_access_key_id, body.aws_secret_access_key
            )
        elif body.api_key:
            set_provider_api_key(body.name, body.api_key)
    except Exception:
        logger.exception("Failed to store credentials for %s", body.name)
        try:
            await asyncio.to_thread(remove_provider, body.name)
        except Exception:
            logger.exception("Rollback also failed for %s", body.name)
        raise HTTPException(
            status_code=500, detail="Failed to store provider credentials."
        )

    return {"success": True, "name": body.name}


@router.put("/{name}")
async def update_provider_endpoint(name: str, body: ProviderUpdate):
    """Update an existing provider."""
    provider = await asyncio.to_thread(get_provider, name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    # All schema validation runs before any write so a 400 on cross-field
    # checks cannot leave the provider record half-mutated.
    ptype = provider.get("type")
    _validate_default_model(body.default_model)

    # AWS fields are bedrock-only; reject up-front rather than silently
    # dropping them on a non-bedrock provider.
    if ptype != "bedrock" and (
        body.aws_access_key_id is not None
        or body.aws_secret_access_key is not None
        or body.region is not None
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "aws_access_key_id, aws_secret_access_key, and region are "
                "only valid for bedrock providers."
            ),
        )
    # Empty strings on AWS credential fields are rejected — distinct from
    # `api_key=""` which is the documented "clear stored key" sentinel for
    # cloud providers. Mixing the two semantics is a footgun.
    if (
        body.aws_access_key_id is not None and body.aws_access_key_id == ""
    ) or (
        body.aws_secret_access_key is not None and body.aws_secret_access_key == ""
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "aws_access_key_id and aws_secret_access_key must be "
                "non-empty when provided."
            ),
        )
    # Bedrock endpoint is derived from `region`; an endpoint override on
    # a bedrock provider would silently diverge from the credentials and
    # is rejected.
    if ptype == "bedrock" and body.endpoint is not None:
        raise HTTPException(
            status_code=400,
            detail="Bedrock endpoint is derived from `region`; pass `region` instead.",
        )
    # api_key is rejected on bedrock here (before write) so the same 400
    # doesn't fire after the non-credential updates have already landed.
    if ptype == "bedrock" and body.api_key is not None:
        raise HTTPException(
            status_code=400,
            detail="Bedrock uses AWS credentials, not an API key.",
        )

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
    if body.region is not None and provider.get("type") == "bedrock":
        updates["region"] = _validate_region(body.region)

    if updates:

        def _apply(existing: dict) -> dict:
            return {**existing, **updates}

        await asyncio.to_thread(update_provider, name, _apply)

    # Update credentials. For bedrock, allow rotating either AWS key
    # independently (paired with the existing counterpart); api_key on
    # bedrock and AWS fields on non-bedrock were already rejected above
    # before any write happened.
    if ptype == "bedrock":
        if body.aws_access_key_id or body.aws_secret_access_key:
            try:
                existing_access, existing_secret = get_provider_aws_credentials(
                    name
                )
            except Exception:
                logger.exception("Failed to read AWS credentials for %s", name)
                raise HTTPException(
                    status_code=500,
                    detail="Failed to read existing AWS credentials.",
                )
            new_access = body.aws_access_key_id or existing_access
            new_secret = body.aws_secret_access_key or existing_secret
            if not new_access or not new_secret:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Cannot rotate AWS credentials in isolation: provider "
                        "has no existing counterpart on file."
                    ),
                )
            try:
                set_provider_aws_credentials(name, new_access, new_secret)
            except Exception:
                logger.exception(
                    "Failed to store AWS credentials for %s", name
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to store AWS credentials.",
                )
    else:
        if body.api_key is not None:
            try:
                if body.api_key == "":
                    remove_provider_api_key(name)
                else:
                    set_provider_api_key(name, body.api_key)
            except Exception:
                logger.exception("Failed to update API key for %s", name)
                raise HTTPException(
                    status_code=500, detail="Failed to update API key."
                )

    return {"success": True, "name": name}


@router.delete("/{name}")
async def delete_provider(name: str):
    """Remove a provider."""
    provider = await asyncio.to_thread(get_provider, name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    try:
        await asyncio.to_thread(remove_provider, name)
    except Exception:
        # Don't leak filesystem paths or library internals from raised
        # exceptions back to the client. The exception is logged and a
        # generic 500 is returned.
        logger.exception("Failed to remove provider %s", name)
        raise HTTPException(
            status_code=500, detail="Failed to remove provider."
        )

    # Also remove credentials (api_key for cloud providers, AWS creds for
    # bedrock). Best-effort; storage cleanup must not fail the delete.
    try:
        remove_provider_api_key(name)
    except Exception:
        pass
    try:
        remove_provider_aws_credentials(name)
    except Exception:
        pass

    return {"success": True, "name": name}

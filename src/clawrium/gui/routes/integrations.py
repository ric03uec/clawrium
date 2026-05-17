"""Integration management API routes.

CRUD operations for external service integrations (GitHub, GitLab,
Atlassian, Linear, Notion). Wraps the existing
``clawrium.core.integrations`` module.

Credential values are NEVER returned by these endpoints — only the
credential keys and metadata. Mutations accept values via the request
body and persist them through ``set_integration_credential``.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from clawrium.core.integrations import (
    INTEGRATION_TYPES,
    DuplicateIntegrationError,
    IntegrationInUseError,
    IntegrationsFileCorruptedError,
    InvalidIntegrationNameError,
    InvalidIntegrationTypeError,
    add_integration,
    find_agents_using_integration,
    get_credentials_for_type,
    get_integration,
    get_integration_credentials,
    load_integrations,
    remove_integration,
    set_integration_credential,
    validate_integration_name,
    validate_integration_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class IntegrationCreate(BaseModel):
    """Request body for creating a new integration."""

    name: str
    type: str
    credentials: dict[str, str] = {}


class IntegrationCredentialsUpdate(BaseModel):
    """Request body for updating an integration's credentials."""

    credentials: dict[str, str]


def _credential_keys_for(integration_type: str | None) -> list[dict]:
    """Return credential definitions for a type, or empty list if unknown."""
    if not integration_type:
        return []
    spec = INTEGRATION_TYPES.get(integration_type)
    if not spec:
        return []
    return list(spec.get("credentials", []))


def _summarize_integration(record: dict, *, agent_count: int = 0) -> dict:
    """Public summary of an integration (no credential values).

    ``agent_count`` defaults to 0; list endpoints precompute usage in
    a single pass and pass it in to avoid an N+1 ``find_agents_using``
    fan-out per row.
    """
    name = record.get("name")
    integration_type = record.get("type")

    configured_keys: list[str] = []
    if name:
        try:
            stored = get_integration_credentials(name)
            configured_keys = sorted(stored.keys())
        except Exception as exc:  # noqa: BLE001 - secrets backend errors are non-fatal here
            logger.warning(
                "failed to read credentials for integration %s: %s", name, exc
            )

    return {
        "name": name,
        "type": integration_type,
        "credential_keys": [c["key"] for c in _credential_keys_for(integration_type)],
        "configured_credential_keys": configured_keys,
        "agent_count": agent_count,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _load_integrations_or_500() -> list[dict]:
    try:
        return load_integrations()
    except IntegrationsFileCorruptedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _get_integration_or_500(name: str) -> dict | None:
    """Wrap ``get_integration`` so that file corruption surfaces as 500.

    ``get_integration`` calls ``load_integrations`` internally; without
    this guard a corrupted file becomes an unhandled 500 in the three
    by-name handlers (detail, update, delete).
    """
    try:
        return get_integration(name)
    except IntegrationsFileCorruptedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("")
async def list_integrations():
    """List all configured integrations (credential values masked)."""
    records = await asyncio.to_thread(_load_integrations_or_500)

    # Build a single {integration_name: count} map by walking all hosts
    # once instead of calling find_agents_using_integration() per record.
    def _collect_usage() -> dict[str, int]:
        from clawrium.core.hosts import load_hosts

        counts: dict[str, int] = {}
        try:
            hosts = load_hosts()
        except Exception:  # noqa: BLE001 - hosts unavailable means 0 counts
            return counts
        for host in hosts:
            agents = host.get("agents", {}) if isinstance(host, dict) else {}
            for agent_data in agents.values():
                if not isinstance(agent_data, dict):
                    continue
                names = agent_data.get("integrations") or []
                if not isinstance(names, list):
                    continue
                for n in names:
                    if isinstance(n, str):
                        counts[n] = counts.get(n, 0) + 1
        return counts

    usage = await asyncio.to_thread(_collect_usage)
    return {
        "integrations": [
            _summarize_integration(r, agent_count=usage.get(r.get("name", ""), 0))
            for r in records
        ]
    }


@router.get("/types")
async def list_integration_types():
    """Return the supported integration types and their credential schemas.

    Frontend uses this to render dynamic credential fields per type.
    """
    types: dict[str, dict] = {}
    for type_key, spec in INTEGRATION_TYPES.items():
        types[type_key] = {
            "description": spec.get("description", ""),
            "credentials": list(spec.get("credentials", [])),
        }
    return {"types": types}


@router.get("/{name}")
async def get_integration_detail(name: str):
    """Get a single integration's details plus the agents that reference it."""
    record = await asyncio.to_thread(_get_integration_or_500, name)
    if not record:
        raise HTTPException(
            status_code=404, detail=f"Integration '{name}' not found"
        )

    agents_using_raw = await asyncio.to_thread(find_agents_using_integration, name)
    agents_using = [
        {"hostname": hostname, "agent_key": agent_key}
        for hostname, agent_key in agents_using_raw
    ]

    summary = _summarize_integration(record, agent_count=len(agents_using))
    summary["agents_using"] = agents_using
    return summary


@router.post("", status_code=201)
async def create_integration(body: IntegrationCreate):
    """Create an integration and store any provided credentials."""
    try:
        validate_integration_name(body.name)
        validate_integration_type(body.type)
    except InvalidIntegrationNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidIntegrationTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    valid_keys = {c["key"] for c in get_credentials_for_type(body.type)}
    unknown = sorted(k for k in body.credentials.keys() if k not in valid_keys)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown credential keys for type '{body.type}': "
                f"{', '.join(unknown)}"
            ),
        )

    record = {"name": body.name, "type": body.type}
    try:
        await asyncio.to_thread(add_integration, record)
    except DuplicateIntegrationError as exc:
        raise HTTPException(
            status_code=409, detail=f"Integration '{body.name}' already exists"
        ) from exc
    except (InvalidIntegrationNameError, InvalidIntegrationTypeError) as exc:
        # Validators ran above, but storage may re-check; surface as 400.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    failed_keys: list[str] = []
    for key, value in body.credentials.items():
        if not value:
            continue
        try:
            await asyncio.to_thread(
                set_integration_credential, body.name, key, value
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to store credential %s for integration %s: %s",
                key,
                body.name,
                exc,
            )
            failed_keys.append(key)

    response: dict = {"success": True, "name": body.name}
    if failed_keys:
        # Surface the partial-success so the client can prompt the user to
        # retry via PATCH instead of silently shipping a 201 with no secrets.
        response["warnings"] = {"failed_credential_keys": sorted(failed_keys)}
    return response


@router.patch("/{name}/credentials")
async def update_integration_credentials(
    name: str, body: IntegrationCredentialsUpdate
):
    """Update one or more credentials for an existing integration.

    Empty-string values are skipped (allows partial updates without
    clobbering existing secrets).
    """
    record = await asyncio.to_thread(_get_integration_or_500, name)
    if not record:
        raise HTTPException(
            status_code=404, detail=f"Integration '{name}' not found"
        )

    integration_type = record.get("type")
    valid_keys = {c["key"] for c in _credential_keys_for(integration_type)}
    unknown = sorted(k for k in body.credentials.keys() if k not in valid_keys)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown credential keys for type '{integration_type}': "
                f"{', '.join(unknown)}"
            ),
        )

    updated: list[str] = []
    for key, value in body.credentials.items():
        if not value:
            continue
        try:
            await asyncio.to_thread(set_integration_credential, name, key, value)
            updated.append(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to update credential %s for integration %s: %s",
                key,
                name,
                exc,
            )

    return {"success": True, "name": name, "updated_keys": updated}


@router.delete("/{name}")
async def delete_integration(name: str):
    """Delete an integration.

    Blocks deletion (409) when the integration is referenced by any
    agent and surfaces the referencing agents so the UI can guide the
    user to remove the assignments first.
    """
    record = await asyncio.to_thread(_get_integration_or_500, name)
    if not record:
        raise HTTPException(
            status_code=404, detail=f"Integration '{name}' not found"
        )

    try:
        removed = await asyncio.to_thread(remove_integration, name)
    except IntegrationInUseError as exc:
        agents_using_raw = await asyncio.to_thread(
            find_agents_using_integration, name
        )
        agents_using = [
            {"hostname": hostname, "agent_key": agent_key}
            for hostname, agent_key in agents_using_raw
        ]
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "agents_using": agents_using,
            },
        ) from exc

    if not removed:
        # Race: someone deleted it between our get + remove. Treat as 404.
        raise HTTPException(
            status_code=404, detail=f"Integration '{name}' not found"
        )

    return {"success": True, "name": name}

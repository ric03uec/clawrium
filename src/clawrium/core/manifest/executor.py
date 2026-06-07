"""Execute a ChangeSet against the live fleet (install, configure, start, delete)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .differ import ChangeSet
from .schema import ManifestDocument
from .state import ActualState


Emit = Callable[[str, str], None]


def _noop_emit(action: str, resource: str) -> None:
    pass


# ── apply ─────────────────────────────────────────────────────────────────────

def execute_apply(
    doc: ManifestDocument,
    cs: ChangeSet,
    actual: ActualState,
    emit: Emit = _noop_emit,
    dry_run: bool = False,
) -> list[str]:
    """Execute creates/attaches/starts from a ChangeSet. Returns list of error strings."""
    if dry_run:
        return []

    errors: list[str] = []

    # Index desired resources by name for quick lookup during execution
    host_by_name = {h.metadata.name: h for h in doc.hosts()}
    provider_by_name = {p.metadata.name: p for p in doc.providers()}
    agent_by_name = {a.metadata.name: a for a in doc.agents()}

    # 1. Create hosts
    for op in cs.creates:
        if op.kind != "host":
            continue
        host_res = host_by_name.get(op.name)
        if not host_res:
            continue
        emit("create", f"host/{op.name}")
        err = _create_host(host_res)
        if err:
            errors.append(f"host/{op.name}: {err}")

    # 2. Create providers
    for op in cs.creates:
        if op.kind != "provider":
            continue
        prov_res = provider_by_name.get(op.name)
        if not prov_res:
            continue
        emit("create", f"provider/{op.name}")
        err = _create_provider(prov_res)
        if err:
            errors.append(f"provider/{op.name}: {err}")

    # 3. Install agents
    for op in cs.creates:
        if op.kind != "agent":
            continue
        agent_res = agent_by_name.get(op.name)
        if not agent_res:
            continue
        emit("install", f"agent/{op.name}")
        err = _install_agent(agent_res, emit=emit)
        if err:
            errors.append(f"agent/{op.name}: {err}")

    # 4. Configure provider attachments (new and updated agents)
    provider_attaches = [a for a in cs.attaches if a.resource_kind == "provider"]
    for aop in provider_attaches:
        emit("configure", f"agent/{aop.agent}  provider {aop.resource_name!r}")
        err = _configure_provider(aop.agent, aop.resource_name)
        if err:
            errors.append(f"agent/{aop.agent}: {err}")

    # 5. Start agents
    for name in cs.starts:
        emit("start", f"agent/{name}")
        err = _start_agent(name)
        if err:
            errors.append(f"agent/{name}: {err}")

    return errors


# ── delete ────────────────────────────────────────────────────────────────────

def execute_delete(
    doc: ManifestDocument,
    cs: ChangeSet,
    actual: ActualState,
    emit: Emit = _noop_emit,
    cascade: bool = False,
) -> list[str]:
    """Stop and delete agents listed in cs.deletes. Returns list of error strings."""
    errors: list[str] = []

    for op in cs.deletes:
        if op.kind != "agent":
            continue
        emit("stop", f"agent/{op.name}")
        err = _stop_agent(op.name)
        if err:
            errors.append(f"agent/{op.name} (stop): {err}")

        emit("delete", f"agent/{op.name}")
        err = _remove_agent(op.name)
        if err:
            errors.append(f"agent/{op.name} (delete): {err}")

    if cascade:
        provider_names = {p.metadata.name for p in doc.providers()}
        for name in provider_names:
            emit("delete", f"provider/{name}")
            err = _remove_provider(name)
            if err:
                errors.append(f"provider/{name}: {err}")

    return errors


# ── internal: host ────────────────────────────────────────────────────────────

def _create_host(host_res) -> str | None:
    from clawrium.core.hosts import DuplicateHostError, add_host

    now = datetime.now(timezone.utc).isoformat()
    host_dict = {
        "hostname": host_res.spec.hostname,
        "key_id": host_res.spec.hostname,
        "port": host_res.spec.port,
        "user": host_res.spec.user,
        "auth_method": "key",
        "hardware": {},
        "metadata": {
            "added_at": now,
            "last_seen": None,
            "labels": dict(host_res.metadata.labels),
        },
        "addresses": [
            {
                "address": host_res.spec.hostname,
                "is_primary": True,
                "label": None,
                "added_at": now,
            }
        ],
        "agents": {},
    }
    alias = host_res.metadata.name
    if alias != host_res.spec.hostname:
        host_dict["alias"] = alias

    try:
        add_host(host_dict)
    except DuplicateHostError:
        pass  # idempotent
    except Exception as exc:
        return str(exc)
    return None


# ── internal: provider ────────────────────────────────────────────────────────

def _create_provider(prov_res) -> str | None:
    from clawrium.core.providers.storage import (
        DuplicateProviderError,
        add_provider,
    )

    prov_dict = {
        "name": prov_res.metadata.name,
        "type": prov_res.spec.type,
    }
    if prov_res.spec.config.defaultModel:
        prov_dict["model"] = prov_res.spec.config.defaultModel

    try:
        add_provider(prov_dict)
    except DuplicateProviderError:
        pass  # idempotent
    except Exception as exc:
        return str(exc)
    return None


def _remove_provider(name: str) -> str | None:
    from clawrium.core.providers.storage import remove_provider

    try:
        remove_provider(name)
    except Exception as exc:
        return str(exc)
    return None


# ── internal: agent ───────────────────────────────────────────────────────────

def _install_agent(agent_res, emit: Emit) -> str | None:
    from clawrium.core.install import InstallationError, run_installation

    host = agent_res.spec.host
    if not host:
        return "agent has no host specified"

    try:
        run_installation(
            claw_name=agent_res.spec.type,
            hostname=host,
            name=agent_res.metadata.name,
            on_event=lambda stage, msg: emit(stage, f"agent/{agent_res.metadata.name}: {msg}"),
            version_override=agent_res.spec.version,
        )
    except InstallationError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _configure_provider(agent_name: str, provider_name: str) -> str | None:
    from clawrium.core.lifecycle import LifecycleError, configure_agent

    try:
        configure_agent(agent_name, stage="providers", provider_name=provider_name)
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _start_agent(name: str) -> str | None:
    from clawrium.core.lifecycle import LifecycleError, start_agent

    try:
        start_agent(name)
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _stop_agent(name: str) -> str | None:
    from clawrium.core.lifecycle import LifecycleError, stop_agent

    try:
        stop_agent(name)
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _remove_agent(name: str) -> str | None:
    from clawrium.core.lifecycle import LifecycleError, remove_agent

    try:
        remove_agent(name)
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None

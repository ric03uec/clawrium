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

    # 3. Install new agents
    for op in cs.creates:
        if op.kind != "agent":
            continue
        agent_res = agent_by_name.get(op.name)
        if not agent_res:
            continue
        # Resolve spec.host alias to actual hostname via actual state
        hostname = _resolve_hostname(agent_res.spec.host, actual)
        emit("install", f"agent/{op.name}")
        err = _install_agent(agent_res, hostname=hostname, emit=emit)
        if err:
            errors.append(f"agent/{op.name}: {err}")

    # 3b. Upgrade existing agents (version change)
    for op in cs.updates:
        if op.kind != "agent":
            continue
        agent_res = agent_by_name.get(op.name)
        actual_agent = actual.agents.get(op.name)
        if not agent_res or not actual_agent:
            continue
        emit("upgrade", f"agent/{op.name}  ({op.details})")
        err = _upgrade_agent(agent_res, hostname=actual_agent.host, emit=emit)
        if err:
            errors.append(f"agent/{op.name}: {err}")

    # 4. Configure provider attachments (new and updated agents)
    provider_attaches = [a for a in cs.attaches if a.resource_kind == "provider"]
    for aop in provider_attaches:
        actual_agent = actual.agents.get(aop.agent)
        emit("configure", f"agent/{aop.agent}  provider {aop.resource_name!r}")
        err = _configure_provider(aop.agent, aop.resource_name, actual_agent)
        if err:
            errors.append(f"agent/{aop.agent}: {err}")

    # 5. Start new agents
    for name in cs.starts:
        actual_agent = actual.agents.get(name)
        emit("start", f"agent/{name}")
        err = _start_agent(name, actual_agent)
        if err:
            errors.append(f"agent/{name}: {err}")

    # 6. Restart agents after upgrade
    for name in cs.restarts:
        actual_agent = actual.agents.get(name)
        emit("restart", f"agent/{name}")
        err = _restart_agent(name, actual_agent)
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
        actual_agent = actual.agents.get(op.name)
        emit("stop", f"agent/{op.name}")
        err = _stop_agent(op.name, actual_agent)
        if err:
            errors.append(f"agent/{op.name} (stop): {err}")

        emit("delete", f"agent/{op.name}")
        err = _remove_agent(op.name, actual_agent)
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


# ── internal: helpers ─────────────────────────────────────────────────────────

def _resolve_hostname(spec_host: str, actual: ActualState) -> str:
    """Resolve a manifest host name/alias to the actual hostname stored in hosts.json."""
    host_record = actual.hosts.get(spec_host)
    if host_record:
        return host_record["hostname"]
    return spec_host  # may already be the real hostname/IP


# ── internal: agent ───────────────────────────────────────────────────────────

def _install_agent(agent_res, hostname: str, emit: Emit) -> str | None:
    from clawrium.core.install import InstallationError, run_installation

    if not hostname:
        return "agent has no host specified"

    try:
        run_installation(
            claw_name=agent_res.spec.type,
            hostname=hostname,
            name=agent_res.metadata.name,
            on_event=lambda stage, msg: emit(stage, f"agent/{agent_res.metadata.name}: {msg}"),
            version_override=agent_res.spec.version,
        )
    except InstallationError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _upgrade_agent(agent_res, hostname: str, emit: Emit) -> str | None:
    from clawrium.core.install import InstallationError, run_installation

    if not hostname:
        return "agent has no host specified"
    try:
        run_installation(
            claw_name=agent_res.spec.type,
            hostname=hostname,
            name=agent_res.metadata.name,
            on_event=lambda stage, msg: emit(stage, f"agent/{agent_res.metadata.name}: {msg}"),
            version_override=agent_res.spec.version,
            force=True,
        )
    except InstallationError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _restart_agent(name: str, actual_agent) -> str | None:
    from clawrium.core.lifecycle import LifecycleError, restart_agent

    if not actual_agent:
        return f"agent '{name}' not found in fleet state; cannot restart"
    try:
        result = restart_agent(
            hostname=actual_agent.host,
            claw_name=actual_agent.type,
            agent_name=name,
        )
        if not result["success"]:
            return result.get("error") or "unknown error"
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _configure_provider(agent_name: str, provider_name: str, actual_agent) -> str | None:
    """Attach a provider to an agent via configure playbook."""
    from clawrium.core.lifecycle import LifecycleError, configure_agent

    if not actual_agent:
        return f"agent '{agent_name}' not found in fleet state; cannot configure"
    try:
        ok, err = configure_agent(
            hostname=actual_agent.host,
            claw_name=actual_agent.type,
            config_data={"providers": [provider_name]},
            agent_name=agent_name,
        )
        if not ok:
            return err
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _start_agent(name: str, actual_agent) -> str | None:
    from clawrium.core.lifecycle import LifecycleError, start_agent

    if not actual_agent:
        return f"agent '{name}' not found in fleet state; cannot start"
    try:
        result = start_agent(
            hostname=actual_agent.host,
            claw_name=actual_agent.type,
            agent_name=name,
        )
        if not result["success"]:
            return result.get("error") or "unknown error"
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _stop_agent(name: str, actual_agent) -> str | None:
    from clawrium.core.lifecycle import LifecycleError, stop_agent

    if not actual_agent:
        return f"agent '{name}' not found in fleet state; cannot stop"
    try:
        result = stop_agent(
            hostname=actual_agent.host,
            claw_name=actual_agent.type,
            agent_name=name,
        )
        if not result["success"]:
            return result.get("error") or "unknown error"
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None


def _remove_agent(name: str, actual_agent) -> str | None:
    from clawrium.core.lifecycle import LifecycleError, remove_agent

    if not actual_agent:
        return f"agent '{name}' not found in fleet state; cannot remove"
    try:
        result = remove_agent(
            hostname=actual_agent.host,
            claw_name=actual_agent.type,
            agent_name=name,
        )
        if not result["success"]:
            return result.get("error") or "unknown error"
    except LifecycleError as exc:
        return str(exc)
    except Exception as exc:
        return str(exc)
    return None

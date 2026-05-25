"""`clawctl agent provider attach|detach|get` — Pattern A per-agent.

Stores attached provider names in `agent.providers` (a list of provider
names) on the agent record. The legacy `agent.config.providers` dict
(per-provider configuration written by `clm agent configure --stage
providers`) is left untouched — `attach`/`detach` add or remove the
provider's *name* from the dedicated attachments list, mirroring how
integrations track per-agent attachments (`agent.integrations`).

The provider record itself lives in `~/.config/clawrium/providers.json`
and is the source of truth for credentials, default model, etc.; the
agent record only tracks the *attachment*.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.core.hosts import update_host
from clawrium.core.providers.storage import (
    ProvidersFileCorruptedError,
    get_provider,
)

__all__ = ["provider_app"]


provider_app = typer.Typer(
    name="provider",
    help="Manage provider attachments on an agent.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


def _safe_get_provider(name: str) -> dict:
    try:
        record = get_provider(name)
    except ProvidersFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/providers.json")
    if not record:
        emit_error(
            f"provider {name!r} not found",
            hint="clawctl provider registry get",
        )
    return record  # type: ignore[return-value]


def _get_attached_providers(host: dict, agent_key: str) -> list[str]:
    agent_data = (host.get("agents", {}) or {}).get(agent_key, {})
    if not isinstance(agent_data, dict):
        return []
    providers = agent_data.get("providers", [])
    if not isinstance(providers, list):
        return []
    return list(providers)


def _set_attached_providers(
    hostname: str, agent_key: str, providers: list[str]
) -> bool:
    def updater(h: dict) -> dict:
        agents = h.get("agents", {})
        if agent_key not in agents:
            return h
        agent_data = agents[agent_key]
        if not isinstance(agent_data, dict):
            return h
        agent_data["providers"] = providers
        return h

    return update_host(hostname, updater)


@provider_app.command("attach")
def attach(
    name: str = typer.Argument(..., help="Provider name to attach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Attach a registered provider to an agent.

    The attachment is metadata only at this point — the provider config
    is materialized onto the remote agent on the next `clawctl agent
    sync`. Single-provider invariant: detach the current provider
    before attaching a different one. See #426.
    """
    _safe_get_provider(name)
    host, _agent_type, _claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)

    current = _get_attached_providers(host, agent_key)
    if name in current:
        typer.echo(f"agent/{agent}: provider {name!r} already attached")
        return
    # Issue #426: single-provider invariant. Once an agent has a
    # provider attached, refuse a second attachment with a clear
    # remediation pointer. `sync` materializes the attachment into
    # `config.provider`; multiple attachments would silently ambiguate
    # which one wins at reconcile time.
    if current:
        emit_error(
            f"agent '{agent}' already has provider {current[0]!r} attached",
            hint=(
                f"detach first: clawctl agent provider detach {current[0]} "
                f"--agent {agent}"
            ),
        )
    current.append(name)
    if not _set_attached_providers(hostname, agent_key, current):
        emit_error(f"failed to attach provider {name!r} to agent {agent!r}")
    typer.echo(f"agent/{agent}: attached provider {name!r}")


@provider_app.command("detach")
def detach(
    name: str = typer.Argument(..., help="Provider name to detach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Detach a provider from an agent.

    Note: the provider config previously materialized into the agent's
    `config.provider` block is preserved as last-known-good across
    syncs. To switch providers, attach a replacement and run
    `clawctl agent sync`; the new provider will overwrite the old.
    See #426.
    """
    host, _agent_type, _claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)

    current = _get_attached_providers(host, agent_key)
    if name not in current:
        emit_error(
            f"provider {name!r} not attached to agent {agent!r}",
            hint=f"clawctl agent provider get --agent {agent}",
        )
    current.remove(name)
    if not _set_attached_providers(hostname, agent_key, current):
        emit_error(f"failed to detach provider {name!r} from agent {agent!r}")
    # Issue #426 design decision: detach does NOT strip
    # `agent.config.provider`. The provider config persists across
    # sync runs as last-known-good so the remote keeps functioning
    # until the user explicitly attaches a replacement.
    typer.echo(f"agent/{agent}: detached provider {name!r}")


@provider_app.command("get")
def get(
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List providers attached to an agent."""
    host, _agent_type, _claw = safe_resolve_agent(agent)
    agent_key = resolve_agent_key(host, agent)
    names = _get_attached_providers(host, agent_key)

    rows = [{"kind": "provider", "name": n, "agent": agent} for n in names]

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return
    if output is OutputFormat.name:
        typer.echo(dump_name(rows), nl=False)
        return

    headers = ["NAME", "AGENT"]
    body = [[str(r["name"]), str(r["agent"])] for r in rows]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)

"""`clawctl agent integration attach|detach|get` — Pattern A per-agent.

Delegates to `clawrium.core.integrations` which already provides
`add_agent_integration`, `remove_agent_integration`, and
`get_agent_integrations`. Storage lives under
`agent.integrations` on the agent record (unchanged from legacy).
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
from clawrium.core.integrations import (
    IntegrationsFileCorruptedError,
    add_agent_integration,
    get_agent_integrations,
    get_integration,
    remove_agent_integration,
)
from clawrium.core.render import supported_integrations_for_agent_type

__all__ = ["integration_app"]


integration_app = typer.Typer(
    name="integration",
    help="Manage integration attachments on an agent.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


def _safe_get_integration(name: str) -> dict:
    try:
        record = get_integration(name)
    except IntegrationsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/integrations.json")
    if not record:
        emit_error(
            f"integration {name!r} not found",
            hint="clawctl integration registry get",
        )
    return record  # type: ignore[return-value]


@integration_app.command("attach")
def attach(
    name: str = typer.Argument(..., help="Integration name to attach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Attach a registered integration to an agent."""
    record = _safe_get_integration(name)
    host, atype, _claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)

    # #834 (B8): reject unsupported (agent-type, integration-type)
    # pairs at attach time. Without this, `add_agent_integration`
    # writes hosts.json unconditionally and the render layer is the
    # only guard — repeating the #555-class regression the
    # coming-soon contract in #499 is meant to prevent. `None` means
    # the renderer does not know this agent type, in which case we
    # fall through to the legacy render-time enforcement.
    # `_safe_get_integration` is NoReturn on failure, so `record` is
    # always a non-empty dict here.
    integration_type = record.get("type")
    supported = supported_integrations_for_agent_type(atype)
    if supported is not None and integration_type not in supported:
        emit_error(
            f"agent type {atype!r} does not support integration type "
            f"{integration_type!r} (integration {name!r})",
            hint=(
                "run `clawctl integration registry get --types` to list "
                "supported integration types — see #499"
            ),
            exit_code=2,
        )

    if add_agent_integration(hostname, agent_key, name):
        typer.echo(f"agent/{agent}: attached integration {name!r}")
    else:
        typer.echo(f"agent/{agent}: integration {name!r} already attached")


@integration_app.command("detach")
def detach(
    name: str = typer.Argument(..., help="Integration name to detach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Detach an integration from an agent."""
    host, _atype, _claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)

    if remove_agent_integration(hostname, agent_key, name):
        typer.echo(f"agent/{agent}: detached integration {name!r}")
    else:
        emit_error(
            f"integration {name!r} not attached to agent {agent!r}",
            hint=f"clawctl agent integration get --agent {agent}",
        )


@integration_app.command("get")
def get(
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List integrations attached to an agent."""
    host, _atype, _claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)
    names = get_agent_integrations(hostname, agent_key)

    rows = [{"kind": "integration", "name": n, "agent": agent} for n in names]

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

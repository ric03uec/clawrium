"""`clawctl agent channel attach|detach|get` — Pattern A per-agent.

Stores attached channel names in `agent.channels` (a list of channel
names) on the agent record. The channel record itself lives in
`~/.config/clawrium/channels.json`; the agent only tracks the
*attachment*.
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
from clawrium.core.channels import (
    ChannelsFileCorruptedError,
    add_agent_channel,
    get_agent_channels,
    get_channel,
    remove_agent_channel,
)

__all__ = ["channel_app"]


channel_app = typer.Typer(
    name="channel",
    help="Manage channel attachments on an agent.",
    no_args_is_help=True,
    add_completion=False,
)


def _safe_get_channel(name: str) -> dict:
    try:
        record = get_channel(name)
    except ChannelsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/channels.json")
    if not record:
        emit_error(
            f"channel {name!r} not found",
            hint="clawctl channel registry get",
        )
    return record  # type: ignore[return-value]


@channel_app.command("attach")
def attach(
    name: str = typer.Argument(..., help="Channel name to attach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Attach a registered channel to an agent."""
    _safe_get_channel(name)
    host, _atype, _claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)

    if add_agent_channel(hostname, agent_key, name):
        typer.echo(f"agent/{agent}: attached channel {name!r}")
    else:
        typer.echo(f"agent/{agent}: channel {name!r} already attached")


@channel_app.command("detach")
def detach(
    name: str = typer.Argument(..., help="Channel name to detach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Detach a channel from an agent."""
    host, _atype, _claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)

    if remove_agent_channel(hostname, agent_key, name):
        typer.echo(f"agent/{agent}: detached channel {name!r}")
    else:
        emit_error(
            f"channel {name!r} not attached to agent {agent!r}",
            hint=f"clawctl agent channel get --agent {agent}",
        )


@channel_app.command("get")
def get(
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List channels attached to an agent."""
    host, _atype, _claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)
    names = get_agent_channels(hostname, agent_key)

    rows = [{"kind": "channel", "name": n, "agent": agent} for n in names]

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

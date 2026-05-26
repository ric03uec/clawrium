"""`clawctl agent` — Pattern B target (AI assistant instances).

Plan §4 surface: create, get, describe, delete, edit, configure,
start, stop, restart, sync, logs, chat, open, port-forward, exec,
registry.

Per-verb modules under this package wire onto `agent_app`. The CLI
layer delegates all data-plane work to `clawrium.core.*` (untouched
per plan §2 guardrail).
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.agent import (
    chat as _chat,
    channel as _channel,
    configure as _configure,
    create as _create,
    delete as _delete,
    describe as _describe,
    edit as _edit,
    exec as _exec,
    get as _get,
    integration as _integration,
    logs as _logs,
    memory as _memory,
    open as _open,
    port_forward as _port_forward,
    provider as _provider,
    registry as _registry,
    restart as _restart,
    secret as _secret,
    skill as _skill,
    start as _start,
    stop as _stop,
    sync as _sync,
)

__all__ = ["agent_app"]


agent_app = typer.Typer(
    name="agent",
    help="Manage AI assistant instances (agents).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


# Verb registration. Order matches plan §4.
agent_app.command(name="create", help="Install an agent on a host.")(_create.create)
agent_app.command(name="get", help="List agents.")(_get.get)
agent_app.command(name="describe", help="Describe an agent.")(_describe.describe)
agent_app.command(name="delete", help="Delete an agent.")(_delete.delete)
agent_app.command(name="edit", help="Edit an agent record in $EDITOR.")(_edit.edit)
agent_app.command(name="configure", help="Configure an agent (per stage).")(
    _configure.configure
)
agent_app.command(name="start", help="Start an agent.")(_start.start)
agent_app.command(name="stop", help="Stop an agent.")(_stop.stop)
agent_app.command(name="restart", help="Restart an agent.")(_restart.restart)
agent_app.command(name="sync", help="Flush local control-plane state to the agent.")(
    _sync.sync
)
agent_app.command(name="logs", help="Stream agent logs.")(_logs.logs)
agent_app.command(name="chat", help="Chat with an agent.")(_chat.chat)
agent_app.command(name="open", help="Open the agent's web UI in a browser.")(_open.open)
agent_app.command(name="port-forward", help="Forward a local port to the agent.")(
    _port_forward.port_forward
)
agent_app.command(
    name="exec",
    help="Execute a command against the agent's native CLI on its host.",
    context_settings=_exec.EXEC_CONTEXT_SETTINGS,
)(_exec.exec_cmd)


# Sub-groups (Pattern A per-agent + agent-scoped sub-resources, plus
# the read-only types catalog).
agent_app.add_typer(_provider.provider_app, name="provider")
agent_app.add_typer(_channel.channel_app, name="channel")
agent_app.add_typer(_integration.integration_app, name="integration")
agent_app.add_typer(_skill.skill_app, name="skill")
agent_app.add_typer(_secret.secret_app, name="secret")
agent_app.add_typer(_memory.memory_app, name="memory")
agent_app.add_typer(_registry.registry_app, name="registry")

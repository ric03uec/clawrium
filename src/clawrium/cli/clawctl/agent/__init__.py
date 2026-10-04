"""`clawctl agent` — Pattern B target (AI assistant instances).

Plan §4 surface: create, get, describe, delete, edit, configure,
start, stop, restart, sync, logs, chat, open, port-forward, exec,
shell, registry.

Per-verb modules under this package wire onto `agent_app`. The CLI
layer delegates all data-plane work to `clawrium.core.*` (untouched
per plan §2 guardrail).
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.agent import (
    audit as _audit,
    chat as _chat,
    channel as _channel,
    configure as _configure,
    create as _create,
    delete as _delete,
    describe as _describe,
    doctor as _doctor,
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
    shell as _shell,
    skill as _skill,
    start as _start,
    status as _status,
    stop as _stop,
    sync as _sync,
    upgrade as _upgrade,
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
agent_app.command(
    name="create", help="Install an agent on a host (Claude Code is install-only)."
)(_create.create)
agent_app.command(name="get", help="List agents.")(_get.get)
agent_app.command(name="describe", help="Describe an agent.")(_describe.describe)
agent_app.command(name="delete", help="Delete an agent.")(_delete.delete)
agent_app.command(name="edit", help="Edit an agent record in $EDITOR.")(_edit.edit)
agent_app.command(
    name="configure",
    help="Configure an agent (Claude Code writes bounded global settings only).",
)(_configure.configure)
agent_app.command(name="start", help="Start a daemon-backed agent (not Claude Code).")(
    _start.start
)
agent_app.command(name="stop", help="Stop a daemon-backed agent (not Claude Code).")(
    _stop.stop
)
agent_app.command(
    name="status", help="Probe an agent runtime (use get for install-only Claude Code)."
)(_status.status)
agent_app.command(
    name="restart", help="Restart a daemon-backed agent (not Claude Code)."
)(_restart.restart)
agent_app.command(
    name="sync",
    help="Sync local state (Claude Code syncs settings only; no restart).",
)(_sync.sync)
agent_app.command(
    name="upgrade",
    help="Upgrade an agent to the manifest's max supported version.",
)(_upgrade.upgrade)
agent_app.command(
    name="doctor",
    help="Diagnose an agent's render bundle (attachments, secrets, files).",
)(_doctor.doctor)
agent_app.command(
    name="logs", help="Stream logs from a daemon-backed agent (not Claude Code)."
)(_logs.logs)
agent_app.command(
    name="chat", help="Chat with a chat-enabled agent (not Claude Code)."
)(_chat.chat)
agent_app.command(
    name="open", help="Open a native web UI (not available for Claude Code)."
)(_open.open)
agent_app.command(name="port-forward", help="Forward a local port to the agent.")(
    _port_forward.port_forward
)
agent_app.command(
    name="exec",
    context_settings=_exec.EXEC_CONTEXT_SETTINGS,
)(_exec.exec_cmd)
agent_app.command(
    name="shell",
    context_settings=_shell.SHELL_CONTEXT_SETTINGS,
)(_shell.shell)


# Sub-groups (Pattern A per-agent + agent-scoped sub-resources, plus
# the read-only types catalog).
agent_app.add_typer(_provider.provider_app, name="provider")
agent_app.add_typer(_channel.channel_app, name="channel")
agent_app.add_typer(_integration.integration_app, name="integration")
agent_app.add_typer(_skill.skill_app, name="skill")
agent_app.add_typer(_secret.secret_app, name="secret")
agent_app.add_typer(_memory.memory_app, name="memory")
agent_app.add_typer(_registry.registry_app, name="registry")
agent_app.command(
    name="audit",
    help="Show audit trail entries scoped to one agent.",
)(_audit.audit)

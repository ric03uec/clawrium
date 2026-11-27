"""`clawctl agent` — Pattern B target (AI assistant instances).

Surface: create, get, describe, delete, edit, configure, start, stop,
status, restart, sync, upgrade, doctor, logs, open, port-forward,
shell, registry (plus provider / channel / integration sub-groups).

Per-verb modules under this package wire onto `agent_app`. The CLI
layer delegates all data-plane work to `clawrium.core.*`.

`chat`, `exec`, `memory`, `audit`, and `secret` were removed in #1071.
Operators SSH to the host for one-off commands; `clawctl agent shell`
still wraps the SSH session.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.agent import (
    channel as _channel,
    configure as _configure,
    create as _create,
    delete as _delete,
    describe as _describe,
    doctor as _doctor,
    edit as _edit,
    get as _get,
    integration as _integration,
    logs as _logs,
    open as _open,
    port_forward as _port_forward,
    provider as _provider,
    registry as _registry,
    restart as _restart,
    shell as _shell,
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


# Verb registration.
agent_app.command(
    name="create", help="Install agent (Claude Code, Codex, and Pi are CLI-only)."
)(_create.create)
agent_app.command(name="get", help="List agents.")(_get.get)
agent_app.command(name="describe", help="Describe an agent.")(_describe.describe)
agent_app.command(name="delete", help="Delete an agent.")(_delete.delete)
agent_app.command(name="edit", help="Edit an agent record in $EDITOR.")(_edit.edit)
agent_app.command(
    name="configure",
    help=(
        "Configure an agent (Pi provider configuration is unavailable; "
        "daemonless CLIs manage no runtime service)."
    ),
)(_configure.configure)
agent_app.command(name="start", help="Start daemon agent (not CLI-only agents).")(
    _start.start
)
agent_app.command(name="stop", help="Stop daemon agent (not CLI-only agents).")(
    _stop.stop
)
agent_app.command(
    name="status", help="Probe an agent runtime (use get for install-only CLIs)."
)(_status.status)
agent_app.command(
    name="restart", help="Restart daemon agent (not CLI-only agents)."
)(_restart.restart)
agent_app.command(
    name="sync",
    help=(
        "Sync local state (Pi provider provisioning and sync are unsupported; "
        "daemonless CLIs do not restart)."
    ),
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
    name="logs", help="Stream agent logs (not CLI-only agents)."
)(_logs.logs)
agent_app.command(
    name="open", help="Open native UI (OpenClaw / Hermes / ZeroClaw only)."
)(_open.open)
agent_app.command(
    name="port-forward",
    help="Forward a local port to the agent (OpenClaw / Hermes / ZeroClaw only).",
)(_port_forward.port_forward)
agent_app.command(
    name="shell",
    context_settings=_shell.SHELL_CONTEXT_SETTINGS,
)(_shell.shell)


# Sub-groups.
agent_app.add_typer(_provider.provider_app, name="provider")
agent_app.add_typer(_channel.channel_app, name="channel")
agent_app.add_typer(_integration.integration_app, name="integration")
agent_app.add_typer(_registry.registry_app, name="registry")

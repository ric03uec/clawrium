"""`clawctl agent start <name>` — start an agent (with optional --force)."""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.lifecycle import LifecycleError, start_agent


def start(
    name: str = typer.Argument(..., help="Agent name."),
    force: bool = typer.Option(
        False, "--force", "-f", help="Bypass onboarding state check."
    ),
) -> None:
    """Start an agent unit on its host."""
    # Bug #516: see configure.py for full rationale.
    host, _agent_type, claw_record = safe_resolve_agent(name)
    agent_key = resolve_agent_key(host, name)
    hostname = host["hostname"]
    agent_type = claw_record.get("type", _agent_type)

    def on_event(stage: str, message: str) -> None:
        stream_action(resource=f"agent/{name}", message=f"[{stage}] {message}")

    try:
        result = start_agent(
            hostname=hostname,
            claw_name=agent_type,
            agent_name=agent_key,
            force=force,
            on_event=on_event,
        )
    except LifecycleError as exc:
        emit_error(f"start failed: {exc}")

    if not result.get("success"):
        emit_error(f"start failed: {result.get('error') or 'unknown error'}")
    stream_action(resource=f"agent/{name}", message="started")

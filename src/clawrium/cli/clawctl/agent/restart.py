"""`clawctl agent restart <name>` — restart an agent."""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.lifecycle import LifecycleError, restart_agent


def restart(
    name: str = typer.Argument(..., help="Agent name."),
) -> None:
    """Restart an agent unit on its host."""
    # Bug #516: see configure.py for full rationale.
    host, _agent_type, claw_record = safe_resolve_agent(name)
    agent_key = resolve_agent_key(host, name)
    hostname = host["hostname"]
    agent_type = claw_record.get("type", _agent_type)

    def on_event(stage: str, message: str) -> None:
        stream_action(resource=f"agent/{name}", message=f"[{stage}] {message}")

    try:
        result = restart_agent(
            hostname=hostname,
            claw_name=agent_type,
            agent_name=agent_key,
            on_event=on_event,
        )
    except LifecycleError as exc:
        emit_error(f"restart failed: {exc}")

    if not result.get("success"):
        emit_error(f"restart failed: {result.get('error') or 'unknown error'}")
    stream_action(resource=f"agent/{name}", message="restarted")

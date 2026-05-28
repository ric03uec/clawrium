"""`clawctl agent stop <name>` — stop an agent."""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.lifecycle import LifecycleError, stop_agent
from clawrium.core.playbook_resolver import resolve_lifecycle_backend


def stop(
    name: str = typer.Argument(..., help="Agent name."),
) -> None:
    """Stop an agent unit on its host."""
    # Bug #516: see configure.py for full rationale.
    host, _agent_type, claw_record = safe_resolve_agent(name)
    agent_key = resolve_agent_key(host, name)
    hostname = host["hostname"]
    agent_type = claw_record.get("type", _agent_type)

    def on_event(stage: str, message: str) -> None:
        stream_action(resource=f"agent/{name}", message=f"[{stage}] {message}")

    # OS-family dispatch (CLI layer). #469 step 1 invariant.
    os_family = host.get("os_family", "linux")
    if os_family == "linux":
        stop_fn = stop_agent
    else:
        stop_fn = resolve_lifecycle_backend(os_family).stop_agent

    try:
        result = stop_fn(
            hostname=hostname,
            claw_name=agent_type,
            agent_name=agent_key,
            on_event=on_event,
        )
    except LifecycleError as exc:
        emit_error(f"stop failed: {exc}")

    if not result.get("success"):
        emit_error(f"stop failed: {result.get('error') or 'unknown error'}")
    stream_action(resource=f"agent/{name}", message="stopped")

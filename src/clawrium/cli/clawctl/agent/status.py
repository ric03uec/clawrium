"""`clawctl agent status <name>` — probe an agent's runtime status."""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.agent_lifecycle import (
    has_completed_install,
    incomplete_install_message,
)


def status(
    name: str = typer.Argument(..., help="Agent name."),
) -> None:
    """Probe an agent runtime.

    Phase 3 of #11 delegates openclaw status to the backing NemoClaw
    sandbox. Other agent types still surface their persisted status via
    `clawctl agent get` / `describe` and are intentionally not given a
    systemd-specific status path here.
    """
    host, _agent_type, claw_record = safe_resolve_agent(name)
    agent_key = resolve_agent_key(host, name)
    agent_type = claw_record.get("type", _agent_type)
    if agent_type == "pi":
        if not has_completed_install(claw_record):
            emit_error(incomplete_install_message(agent_type, "status"))
        stream_action(
            resource=f"agent/{name}",
            message="Pi is install-only; no daemon status is available. Use agent get or describe.",
        )
        return
    if agent_type != "openclaw":
        if not has_completed_install(claw_record):
            emit_error(incomplete_install_message(agent_type, "status"))
        stream_action(
            resource=f"agent/{name}",
            message="status available via `clawctl agent get`",
        )
        return

    from clawrium.core.lifecycle import _run_lifecycle_playbook

    success, error = _run_lifecycle_playbook(
        agent_type="openclaw",
        agent_name=agent_key,
        hostname=host["hostname"],
        operation="status",
        host=host,
        timeout=60,
    )
    if not success:
        emit_error(f"status failed: {error or 'unknown error'}")
    stream_action(resource=f"agent/{name}", message="healthy (NemoClaw sandbox)")

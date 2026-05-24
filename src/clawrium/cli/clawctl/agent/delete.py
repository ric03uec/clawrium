"""`clawctl agent delete <name>` — remove an agent.

Runs the remote cleanup playbook via `core/lifecycle.py:remove_agent`
then prunes the local record via `core/hosts.py:remove_agent_from_host`.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl._common import confirm_destructive
from clawrium.cli.clawctl.agent._shared import safe_resolve_agent
from clawrium.cli.output import emit_error, stream_action
from clawrium.core.lifecycle import LifecycleError, remove_agent


def delete(
    name: str = typer.Argument(..., help="Agent name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirm prompt."),
) -> None:
    """Delete an agent (remote cleanup + local record removal)."""
    host, agent_key, claw_record = safe_resolve_agent(name)
    confirm_destructive(
        prompt=f"Delete agent '{name}'? Removes remote state and local record.",
        yes=yes,
    )

    hostname = host["hostname"]
    agent_type = claw_record.get("type", agent_key)

    def on_event(stage: str, message: str) -> None:
        stream_action(resource=f"agent/{name}", message=f"[{stage}] {message}")

    # ATX iter-1 B3: `remove_agent` can return `{"success": False}` without
    # raising when the Ansible playbook fails (host unreachable, non-zero
    # rc). Discarding the return value left orphaned remote agents while
    # silently deleting the local record. `remove_agent` also already
    # prunes the local record on success — the previous explicit second
    # call was redundant.
    # ATX iter-2 S7: pre-bind to silence UnboundLocalError if the except
    # falls through (currently safe because `emit_error` is NoReturn).
    result: dict = {}
    try:
        result = remove_agent(
            hostname=hostname,
            claw_name=agent_type,
            agent_name=agent_key,
            on_event=on_event,
        )
    except LifecycleError as exc:
        # ATX iter-2 W5: idempotent delete — re-running on an
        # already-removed agent should not fail fleet automation.
        # ATX iter-3 W5: narrow the match to "not installed" only.
        # `"not found"` also matches `lifecycle.py`'s `"Host 'X' not
        # found"` error, which is a genuine resolution failure and
        # MUST not be silently treated as a no-op success.
        if "not installed" in str(exc).lower():
            stream_action(resource=f"agent/{name}", message="already deleted (no-op)")
            return
        emit_error(f"remote cleanup failed: {exc}")

    if not result.get("success"):
        emit_error(
            f"remote cleanup failed: {result.get('error') or 'unknown error'}",
            hint=f"clawctl agent describe {name}",
        )
    stream_action(resource=f"agent/{name}", message="deleted")

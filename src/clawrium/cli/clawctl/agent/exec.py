"""`clawctl agent exec <name> <cmd...>` -- passthrough to the agent's
native CLI on the remote host.

The agent type's native binary path is hardcoded per claw type in the
matching `exec.yaml` playbook; remaining args are forwarded as argv to
that binary. stdout/stderr/exit-code are captured at command completion
and forwarded to the local terminal.

Unknown options pass through (Typer `ignore_unknown_options`), so
`clawctl agent exec myagent --version` works without a `--` separator;
`--` may still be used to disambiguate.
"""

from __future__ import annotations

import sys

import typer

from clawrium.cli.clawctl.agent._shared import safe_resolve_agent
from clawrium.cli.output._sanitize import sanitize_passthrough
from clawrium.cli.output.errors import emit_error
from clawrium.core.agent_exec import (
    SUPPORTED_CLAW_TYPES,
    AgentExecError,
    run_agent_exec,
)

EXEC_CONTEXT_SETTINGS = {
    "ignore_unknown_options": True,
    "allow_extra_args": True,
}


def exec_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(
        ..., help="Agent name (as shown by `clawctl agent get`)."
    ),
) -> None:
    """Execute a command against the agent's native CLI on its host.

    The command runs as the agent's user in the agent's workspace
    directory. Everything after the agent name is forwarded as argv to
    the agent's native binary:

        clawctl agent exec my-agent --version
        clawctl agent exec my-agent -- --some-flag

    Non-interactive only: no TTY is allocated, so commands that prompt
    for input or render TTY-only UI (progress bars, colors) will not
    work. stdout and stderr are returned to the local terminal when the
    remote command completes. The remote exit code is propagated.
    """
    cmd = list(ctx.args)
    if not cmd:
        emit_error(
            "no command provided",
            hint="clawctl agent exec <name> <args...>",
            exit_code=2,
        )

    host, agent_type, claw_record = safe_resolve_agent(name)
    claw_type = claw_record.get("type") or agent_type
    if claw_type not in SUPPORTED_CLAW_TYPES:
        emit_error(
            f"agent type '{claw_type}' does not support exec",
            hint="supported types: " + ", ".join(sorted(SUPPORTED_CLAW_TYPES)),
            exit_code=2,
        )

    unix_name = claw_record.get("agent_name") or name

    try:
        stdout, stderr, rc = run_agent_exec(
            hostname=host["hostname"],
            agent_name=unix_name,
            claw_type=claw_type,
            cmd_argv=cmd,
        )
    except AgentExecError as exc:
        emit_error(
            str(exc), hint="clawctl agent exec --help", exit_code=2
        )

    if stdout:
        clean = sanitize_passthrough(stdout)
        sys.stdout.write(clean)
        if not clean.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    if stderr:
        clean = sanitize_passthrough(stderr)
        sys.stderr.write(clean)
        if not clean.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()

    raise typer.Exit(code=rc)

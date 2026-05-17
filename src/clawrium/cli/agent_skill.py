"""`clm agent skill` — per-agent skill install/list/remove.

Wired into the existing `agent` sub-app via
`agent_app.add_typer(agent_skill_app, name="skill")` in
`clawrium/cli/agent.py`. Verb-first surface matches the rest of
`clm agent <verb> <agent-name>`:

  - `clm agent skill list    <agent>`
  - `clm agent skill install <agent> <registry>/<name>`
  - `clm agent skill remove  <agent> <registry>/<name>`

`install` and `remove` both mutate the desired-state file *first* and
then unconditionally invoke `apply_state(agent)`. That gives us:

  - **Idempotent installs** — re-running install on an already-installed
    skill is a no-op state mutation but still reconciles the host
    (drift recovery: re-run install after manual `rm -rf` on the
    agent's skill dir).
  - **Single chokepoint for I/O** — the per-claw playbook is the only
    code that touches the host.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from clawrium.core.skills import (
    ExternalSourceBlocked,
    IncompatibleSkillRegistry,
    InvalidSkillRef,
    MissingRegistryPrefix,
    SchemaValidationError,
    SkillError,
    SkillNotFound,
    parse_skill_ref,
)
from clawrium.core.skills_apply import (
    AgentNotFoundError,
    SkillApplyError,
    SkillApplyNotSupported,
    apply_state,
)
from clawrium.core.skills_state import (
    add_skill,
    read_state,
    remove_skill,
)

__all__ = ["agent_skill_app"]

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)


# Catch list: every SkillError subclass we expect to surface to the
# user. We list them explicitly (vs. catching `SkillError`) so a new
# subclass added later raises loudly until it's intentionally wired
# into the CLI — same pattern as `clm skill show` in cli/skill.py.
_USER_FACING_ERRORS: tuple[type[SkillError], ...] = (
    AgentNotFoundError,
    ExternalSourceBlocked,
    IncompatibleSkillRegistry,
    InvalidSkillRef,
    MissingRegistryPrefix,
    SchemaValidationError,
    SkillApplyError,
    SkillApplyNotSupported,
    SkillNotFound,
)


agent_skill_app = typer.Typer(
    name="skill",
    help="Manage skills installed on an agent.",
    no_args_is_help=True,
)


def _exit_with_error(error: SkillError) -> None:
    """Render a skill error to stderr and exit non-zero."""
    err_console.print(f"[red]Error:[/red] {escape(str(error))}")
    raise typer.Exit(code=1)


@agent_skill_app.command(name="list")
def list_command(
    agent_name: str = typer.Argument(
        ..., metavar="AGENT_NAME", help="Agent instance name."
    ),
) -> None:
    """List skills currently in the agent's desired state.

    Reads `${XDG_CONFIG_HOME:-~/.config}/clawrium/agents/<agent>/skills.json`.
    Does not query the remote host; for that, install/remove which run
    `apply_state` and reconcile.
    """
    try:
        refs = read_state(agent_name)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    if not refs:
        console.print(
            f"No skills installed on [cyan]{escape(agent_name)}[/cyan]. "
            f"Try [cyan]clm agent skill install {escape(agent_name)} "
            "clawrium/tdd[/cyan]."
        )
        return

    table = Table(title=f"Skills on {agent_name}")
    table.add_column("Ref", style="cyan", no_wrap=True)
    table.add_column("Registry", style="green")
    table.add_column("Name")
    for ref_str in refs:
        # Already-validated on write — but parse again so the table is
        # consistent if a Phase 3 change ever loosens the writer.
        ref = parse_skill_ref(ref_str)
        table.add_row(escape(ref_str), escape(ref.registry), escape(ref.name))
    console.print(table)


@agent_skill_app.command()
def install(
    agent_name: str = typer.Argument(
        ..., metavar="AGENT_NAME", help="Agent instance name."
    ),
    skill_ref: str = typer.Argument(
        ...,
        metavar="REGISTRY/NAME",
        help="Skill reference (e.g. `clawrium/tdd`). Bare names are rejected.",
    ),
) -> None:
    """Install `<registry>/<name>` on `<agent>`.

    Always re-runs the per-claw apply playbook even if the skill was
    already in the state file. Re-running is the documented way to
    recover from drift (e.g. someone manually removed the on-host
    SKILL.md).
    """
    try:
        new_state, added = add_skill(agent_name, skill_ref)
        result = apply_state(agent_name)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    if added:
        console.print(
            f"[green]Installed[/green] [cyan]{escape(skill_ref)}[/cyan] "
            f"on [cyan]{escape(agent_name)}[/cyan]."
        )
    else:
        # Re-applying an already-installed skill is the drift-recovery
        # path. Surface the no-op state mutation so the user understands
        # that the playbook ran anyway.
        console.print(
            f"[yellow]{escape(skill_ref)}[/yellow] was already in desired "
            f"state; reconciled host. Skills now installed: "
            f"{', '.join(escape(r) for r in result.applied_skills) or '(none)'}."
        )


@agent_skill_app.command()
def remove(
    agent_name: str = typer.Argument(
        ..., metavar="AGENT_NAME", help="Agent instance name."
    ),
    skill_ref: str = typer.Argument(
        ...,
        metavar="REGISTRY/NAME",
        help="Skill reference (e.g. `clawrium/tdd`).",
    ),
) -> None:
    """Remove `<registry>/<name>` from `<agent>`.

    Removing a skill that isn't currently in the state file is treated
    as idempotent — the playbook still runs and prunes any orphan
    directory on the host that matches the ref.
    """
    try:
        _new_state, removed = remove_skill(agent_name, skill_ref)
        _result = apply_state(agent_name)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    if removed:
        console.print(
            f"[green]Removed[/green] [cyan]{escape(skill_ref)}[/cyan] "
            f"from [cyan]{escape(agent_name)}[/cyan]."
        )
    else:
        console.print(
            f"[yellow]{escape(skill_ref)}[/yellow] was not in desired "
            f"state; host reconciled anyway (any orphan directory "
            "pruned)."
        )

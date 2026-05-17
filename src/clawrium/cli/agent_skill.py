"""`clm agent skill` — per-agent skill install/list/remove.

Wired into the existing `agent` sub-app via
`agent_app.add_typer(agent_skill_app, name="skill")` in
`clawrium/cli/agent.py`. Verb-first surface matches the rest of
`clm agent <verb> <agent-name>`:

  - `clm agent skill list    <agent>`
  - `clm agent skill install <agent> <registry>/<name>`
  - `clm agent skill remove  <agent> <registry>/<name>`

Install order is **preflight → mutate → apply**:

  1. Parse the ref, load+validate the skill, resolve the agent's claw
     type, and run `check_agent_compatibility`. All of this happens
     before `add_skill` mutates the desired-state file — so an
     incompatible install request cannot contaminate the state file.
  2. Mutate the state file.
  3. Run `apply_state` (which re-validates and reconciles the host).

Remove is symmetric: state is only mutated after the ref parses (it
does not require the skill to still exist in the catalog). If
`apply_state` fails mid-flight for either operation, the prior state
is restored so the user-visible state file matches what the host has.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from clawrium.cli.chat import _sanitize_exception_text
from clawrium.core.hosts import get_agent_by_name
from clawrium.core.skills import (
    ExternalSourceBlocked,
    IncompatibleSkillRegistry,
    InvalidSkillRef,
    MissingRegistryPrefix,
    SchemaValidationError,
    SkillError,
    SkillNotFound,
    check_agent_compatibility,
    load_skill,
    parse_skill_ref,
    validate_skill,
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
    write_state,
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
    """Render a skill error to stderr and exit non-zero.

    Routes the error text through `_sanitize_exception_text` (same
    helper used by `cli/chat.py` and `cli/tui/widgets/chat_panel.py`)
    so a remote-supplied playbook message containing U+202E (RTLO),
    other bidi-format codepoints, or C0/C1 control bytes cannot spoof
    terminal output via the `[red]Error: ...[/red]` channel.
    """
    err_console.print(
        f"[red]Error:[/red] {escape(_sanitize_exception_text(error))}"
    )
    raise typer.Exit(code=1)


def _resolve_agent_type(agent_name: str) -> str:
    """Resolve `agent_name` to its claw type for preflight checks.

    Raises:
        AgentNotFoundError: name does not match any installed agent,
            or matches more than one (ambiguous across hosts).
    """
    try:
        resolved = get_agent_by_name(agent_name)
    except ValueError as error:
        # Ambiguous name across hosts (see core.hosts.get_agent_by_name).
        raise AgentNotFoundError(str(error)) from error
    if resolved is None:
        raise AgentNotFoundError(
            f"Agent {agent_name!r} not found. Run `clm agent ps`."
        )
    _host, agent_type, _agent_record = resolved
    return agent_type


@agent_skill_app.command(name="list")
def list_command(
    agent_name: str = typer.Argument(
        ..., metavar="AGENT_NAME", help="Agent instance name."
    ),
) -> None:
    """List skills currently in the agent's desired state.

    Reads `${XDG_CONFIG_HOME:-~/.config}/clawrium/agents/<agent>/skills.json`.
    Does not query the remote host — run `install` or `remove` to
    reconcile on-host content with desired state.
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

    table = Table(title=f"Skills on {escape(agent_name)}")
    table.add_column("Ref", style="cyan", no_wrap=True)
    table.add_column("Registry", style="green")
    table.add_column("Name")
    for ref_str in refs:
        # Already-validated on write — but parse again so the table is
        # consistent if a future change ever loosens the writer.
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

    Preflight (parse + load + validate + compatibility) runs before
    the state file is touched so an incompatible install request never
    leaves the state file in a contaminated state. The per-claw apply
    playbook is then invoked unconditionally — re-running install on
    an already-installed skill is the documented drift-recovery path.
    """
    try:
        # Preflight — no state mutation yet.
        ref = parse_skill_ref(skill_ref)
        skill = load_skill(ref)
        validate_skill(skill)
        agent_type = _resolve_agent_type(agent_name)
        check_agent_compatibility(skill, agent_type)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    # Snapshot the prior state so we can roll back if `apply_state`
    # fails on the host. This is what keeps a transient SSH outage
    # from leaving the state file claiming a skill is installed when
    # it isn't.
    try:
        prior_state = read_state(agent_name)
        _new_state, added = add_skill(agent_name, ref)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    try:
        result = apply_state(agent_name)
    except _USER_FACING_ERRORS as error:
        # Roll back the state mutation; the host did not converge.
        try:
            write_state(agent_name, prior_state)
        except Exception as rollback_error:
            # Hard rollback failure is rare (the state file just got
            # written successfully one statement above) but it leaves
            # the file pointing at a host state that doesn't exist.
            # Surface that explicitly so the user knows to verify
            # rather than just seeing the original apply error.
            logger.warning(
                "Rollback of %s state failed: %s",
                agent_name,
                rollback_error,
            )
            err_console.print(
                "[yellow]Warning:[/yellow] State rollback failed. "
                f"Run [cyan]clm agent skill list {escape(agent_name)}"
                "[/cyan] to verify the desired state."
            )
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
        help="Skill reference (e.g. `clawrium/tdd`). Bare names are rejected.",
    ),
) -> None:
    """Remove `<registry>/<name>` from `<agent>`.

    Removing a skill that isn't currently in the state file is treated
    as idempotent — the playbook still runs and prunes any orphan
    directory on the host that matches the ref. If the playbook fails,
    the prior state is restored so the state file always tracks what
    the host has.
    """
    try:
        # Validate the ref *before* mutating state. We deliberately do
        # NOT call `load_skill` here — a remove should still work even
        # if the catalog entry has been deleted upstream (the on-host
        # SKILL.md may still exist and need pruning).
        ref = parse_skill_ref(skill_ref)
        prior_state = read_state(agent_name)
        _new_state, removed = remove_skill(agent_name, ref)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    try:
        _result = apply_state(agent_name)
    except _USER_FACING_ERRORS as error:
        try:
            write_state(agent_name, prior_state)
        except Exception as rollback_error:
            logger.warning(
                "Rollback of %s state failed: %s",
                agent_name,
                rollback_error,
            )
            err_console.print(
                "[yellow]Warning:[/yellow] State rollback failed. "
                f"Run [cyan]clm agent skill list {escape(agent_name)}"
                "[/cyan] to verify the desired state."
            )
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

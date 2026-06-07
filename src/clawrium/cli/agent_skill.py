"""`clm agent skill` — legacy entrypoint kept so cli/main.py keeps importing.

Active CLI is ``clawctl agent skill``. This wraps the new
``<source>/<name>`` grammar and the ``ClawNotSupported`` gate.
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
    ClawNotSupported,
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingSourcePrefix,
    SchemaValidationError,
    SkillError,
    SkillNotFound,
    check_claw_supported,
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


_USER_FACING_ERRORS: tuple[type[SkillError], ...] = (
    AgentNotFoundError,
    ClawNotSupported,
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingSourcePrefix,
    SchemaValidationError,
    SkillApplyError,
    SkillApplyNotSupported,
    SkillNotFound,
)


agent_skill_app = typer.Typer(
    name="skill",
    help="Manage skills installed on an agent.",
    no_args_is_help=True,
    rich_markup_mode=None,
)


def _exit_with_error(error: SkillError) -> None:
    err_console.print(f"[red]Error:[/red] {escape(_sanitize_exception_text(error))}")
    raise typer.Exit(code=1)


def _resolve_agent_type(agent_name: str) -> str:
    try:
        resolved = get_agent_by_name(agent_name)
    except ValueError as error:
        raise AgentNotFoundError(str(error)) from error
    if resolved is None:
        raise AgentNotFoundError(
            f"Agent {agent_name!r} not found. Run `clawctl agent ps`."
        )
    _host, agent_type, _agent_record = resolved
    return agent_type


@agent_skill_app.command(name="list")
def list_command(
    agent_name: str = typer.Argument(
        ..., metavar="AGENT_NAME", help="Agent instance name."
    ),
) -> None:
    """List skills currently in the agent's desired state."""
    try:
        refs = read_state(agent_name)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    if not refs:
        console.print(
            f"No skills installed on [cyan]{escape(agent_name)}[/cyan]. "
            f"Try [cyan]clawctl agent skill attach vetted/tdd --agent "
            f"{escape(agent_name)}[/cyan]."
        )
        return

    table = Table(title=f"Skills on {escape(agent_name)}")
    table.add_column("Ref", style="cyan", no_wrap=True)
    table.add_column("Source", style="green")
    table.add_column("Name")
    for ref_str in refs:
        ref = parse_skill_ref(ref_str)
        table.add_row(escape(ref_str), escape(ref.source), escape(ref.name))
    console.print(table)


@agent_skill_app.command()
def install(
    agent_name: str = typer.Argument(
        ..., metavar="AGENT_NAME", help="Agent instance name."
    ),
    skill_ref: str = typer.Argument(
        ...,
        metavar="SOURCE/NAME",
        help="Skill reference (e.g. `vetted/tdd`).",
    ),
) -> None:
    """Install `<source>/<name>` on `<agent>`."""
    try:
        ref = parse_skill_ref(skill_ref)
        skill = load_skill(ref)
        validate_skill(skill)
        agent_type = _resolve_agent_type(agent_name)
        check_claw_supported(agent_type)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    try:
        prior_state = read_state(agent_name)
        _new_state, added = add_skill(agent_name, ref)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    try:
        result = apply_state(agent_name)
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
                f"Run [cyan]clawctl agent skill list {escape(agent_name)}"
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
        metavar="SOURCE/NAME",
        help="Skill reference (e.g. `vetted/tdd`).",
    ),
) -> None:
    """Remove `<source>/<name>` from `<agent>`."""
    try:
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
                f"Run [cyan]clawctl agent skill list {escape(agent_name)}"
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

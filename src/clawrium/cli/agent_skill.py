"""`clawctl agent skill` — per-agent skill install/list/remove (legacy backend).

Wired into the existing `agent` sub-app via
`agent_app.add_typer(agent_skill_app, name="skill")` in
`clawrium/cli/agent.py`. Verb-first surface matches the rest of
`clawctl agent <verb> <agent-name>`:

  - `clawctl agent skill get    --agent <agent>`
  - `clawctl agent skill attach <registry>/<name> --agent <agent>`
  - `clawctl agent skill detach <registry>/<name> --agent <agent>`

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
import shutil

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
    materialize_skill_for_agent,
    parse_skill_ref,
    render_skill_md,
    validate_skill,
    with_source_ref,
)
from clawrium.core.skills_apply import (
    AgentNotFoundError,
    SkillApplyError,
    SkillApplyNotSupported,
    apply_state,
)
from clawrium.core.skills_state import (
    add_skill,
    agent_skills_dir,
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
# into the CLI.
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
    rich_markup_mode=None,
)


def _exit_with_error(error: SkillError) -> None:
    """Render a skill error to stderr and exit non-zero.

    Routes the error text through `_sanitize_exception_text` (same
    helper used by `cli/chat.py` and `cli/tui/widgets/chat_panel.py`)
    so a remote-supplied playbook message containing U+202E (RTLO),
    other bidi-format codepoints, or C0/C1 control bytes cannot spoof
    terminal output via the `[red]Error: ...[/red]` channel.
    """
    err_console.print(f"[red]Error:[/red] {escape(_sanitize_exception_text(error))}")
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
        raise AgentNotFoundError(f"Agent {agent_name!r} not found. Run `clawctl agent ps`.")
    _host, agent_type, _agent_record = resolved
    return agent_type


def _write_local_skill(agent_name: str, skill_name: str, skill) -> tuple[bool, object]:
    target = agent_skills_dir(agent_name) / skill_name
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    skill_file = target / "SKILL.md"
    prior_bytes = skill_file.read_bytes() if skill_file.exists() else None
    skill_file.write_text(render_skill_md(skill), encoding="utf-8")
    return existed, prior_bytes


def _restore_local_skill(agent_name: str, skill_name: str, existed: bool, prior_bytes) -> None:
    target = agent_skills_dir(agent_name) / skill_name
    if not existed:
        shutil.rmtree(target, ignore_errors=True)
        return
    target.mkdir(parents=True, exist_ok=True)
    if prior_bytes is None:
        try:
            (target / "SKILL.md").unlink()
        except FileNotFoundError:
            pass
        return
    (target / "SKILL.md").write_bytes(prior_bytes)


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
            f"Try [cyan]clawctl agent skill install {escape(agent_name)} "
            "clawrium/tdd[/cyan]."
        )
        return

    table = Table(title=f"Skills on {escape(agent_name)}")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Scope", style="green")
    table.add_column("Name")
    for name in refs:
        table.add_row(escape(name), "local", escape(name))
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
        agent_type = _resolve_agent_type(agent_name)
        skill = load_skill(ref)
        validate_skill(skill)
        check_agent_compatibility(skill, agent_type)
        local_skill = materialize_skill_for_agent(skill, agent_type)
        local_skill = with_source_ref(local_skill, str(ref))
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    # Snapshot the prior state so we can roll back if `apply_state`
    # fails on the host. This is what keeps a transient SSH outage
    # from leaving the state file claiming a skill is installed when
    # it isn't.
    try:
        prior_state = read_state(agent_name)
        existed, prior_bytes = _write_local_skill(agent_name, ref.name, local_skill)
        _new_state, added = add_skill(agent_name, ref.name)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return
    except Exception as error:
        _exit_with_error(SkillError(str(error)))
        return

    try:
        result = apply_state(agent_name)
    except _USER_FACING_ERRORS as error:
        # Roll back the state mutation; the host did not converge.
        try:
            write_state(agent_name, prior_state)
            _restore_local_skill(agent_name, ref.name, existed, prior_bytes)
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
        # Re-applying an already-installed skill is the drift-recovery
        # path. Surface the no-op state mutation so the user understands
        # that the playbook ran anyway.
        console.print(
            f"[yellow]{escape(skill_ref)}[/yellow] was already in desired "
            f"state; reconciled host. Skills now installed: "
            f"{', '.join(escape(r) for r in result.applied_skills) or '(none)'}.")


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
        target = agent_skills_dir(agent_name) / ref.name
        existed = target.exists()
        backup = target.with_name(f".{target.name}.clawctl-remove-backup")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if existed:
            target.rename(backup)
        _new_state, removed = remove_skill(agent_name, ref.name)
    except _USER_FACING_ERRORS as error:
        _exit_with_error(error)
        return

    try:
        _result = apply_state(agent_name)
    except _USER_FACING_ERRORS as error:
        try:
            write_state(agent_name, prior_state)
            if existed and backup.exists() and not target.exists():
                backup.rename(target)
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

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)

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

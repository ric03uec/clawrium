"""`clawctl agent skill attach|detach|get` — per-agent skill management (#411).

References use the unified ``<source>/<name>`` grammar
(``source ∈ {vetted, local}``). Attachment is gated on
``SUPPORTED_CLAWS_BY_DEFAULT`` — agents whose claw type is off in that
table reject ``attach`` with ``ClawNotSupported``.
"""

from __future__ import annotations

import logging

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl.agent._shared import safe_resolve_agent
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
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
from clawrium.core.skills_state import add_skill, read_state, remove_skill, write_state

__all__ = ["skill_app"]

logger = logging.getLogger(__name__)


skill_app = typer.Typer(
    name="skill",
    help="Manage skill attachments on an agent.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


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


def _exit_with_error(error: SkillError) -> None:
    emit_error(str(error))


@skill_app.command("attach")
def attach(
    skill_ref: str = typer.Argument(
        ..., metavar="SOURCE/NAME", help="Skill ref (e.g. `vetted/tdd`)."
    ),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Attach a skill to an agent (installs on host via Ansible)."""
    _host, agent_type, _claw = safe_resolve_agent(agent)
    try:
        check_claw_supported(agent_type)
        ref = parse_skill_ref(skill_ref)
        skill = load_skill(ref)
        validate_skill(skill)
    except _USER_FACING_ERRORS as exc:
        _exit_with_error(exc)
        return

    try:
        prior_state = read_state(agent)
        _new_state, added = add_skill(agent, ref)
    except _USER_FACING_ERRORS as exc:
        _exit_with_error(exc)
        return

    try:
        result = apply_state(agent)
    except _USER_FACING_ERRORS as exc:
        try:
            write_state(agent, prior_state)
        except Exception as rollback_exc:
            logger.warning("Rollback of %s state failed: %s", agent, rollback_exc)
        _exit_with_error(exc)
        return

    if added:
        typer.echo(f"agent/{agent}: attached skill {skill_ref!r}")
    else:
        applied = ", ".join(result.applied_skills) or "(none)"
        typer.echo(
            f"agent/{agent}: skill {skill_ref!r} already attached; "
            f"reconciled host (skills now: {applied})"
        )


@skill_app.command("detach")
def detach(
    skill_ref: str = typer.Argument(..., metavar="SOURCE/NAME", help="Skill ref."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Detach a skill from an agent (uninstalls on host via Ansible)."""
    _host, _agent_type, _claw = safe_resolve_agent(agent)
    try:
        ref = parse_skill_ref(skill_ref)
        prior_state = read_state(agent)
        _new_state, removed = remove_skill(agent, ref)
    except _USER_FACING_ERRORS as exc:
        _exit_with_error(exc)
        return

    try:
        _result = apply_state(agent)
    except _USER_FACING_ERRORS as exc:
        try:
            write_state(agent, prior_state)
        except Exception as rollback_exc:
            logger.warning("Rollback of %s state failed: %s", agent, rollback_exc)
        _exit_with_error(exc)
        return

    if removed:
        typer.echo(f"agent/{agent}: detached skill {skill_ref!r}")
    else:
        typer.echo(
            f"agent/{agent}: skill {skill_ref!r} was not in desired state; "
            "host reconciled anyway"
        )


@skill_app.command("get")
def get(
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List skills currently attached to an agent (desired state)."""
    safe_resolve_agent(agent)
    try:
        refs = read_state(agent)
    except _USER_FACING_ERRORS as exc:
        _exit_with_error(exc)
        return

    rows = []
    for ref_str in refs:
        try:
            ref = parse_skill_ref(ref_str)
            source = ref.source
        except _USER_FACING_ERRORS:
            source = ""
        rows.append(
            {
                "kind": "skill",
                "name": ref_str,
                "source": source,
                "agent": agent,
            }
        )

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return
    if output is OutputFormat.name:
        typer.echo(dump_name(rows), nl=False)
        return

    headers = ["NAME", "SOURCE", "AGENT"]
    body = [[str(r["name"]), str(r["source"] or "-"), str(r["agent"])] for r in rows]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)

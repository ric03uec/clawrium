"""`clawctl agent skill` — per-agent local skill lifecycle.

Issue #411 changes skills from registry-ref desired state to local,
agent-native skill files. Registry skills are templates only: `add`
materializes/copies them into
`~/.config/clawrium/agents/<agent>/skills/<name>/SKILL.md`; `sync`
later copies those local bytes to the host without transforming them.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional

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
    IncompatibleSkillRegistry,
    InvalidSkillRef,
    MissingRegistryPrefix,
    SchemaValidationError,
    Skill,
    SkillError,
    SkillNotFound,
    SkillRef,
    _NAME_RE,
    _load_skill_from_dir,
    _split_frontmatter,
    load_agent_skill,
    load_skill,
    materialize_skill_for_agent,
    parse_skill_ref,
    render_skill_md,
    validate_skill,
    with_source_ref,
)
from clawrium.core.skills_state import (
    add_skill,
    agent_skills_dir,
    read_state,
    remove_skill,
)

__all__ = ["skill_app"]


skill_app = typer.Typer(
    name="skill",
    help="Manage local skills on an agent.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


_USER_FACING_ERRORS: tuple[type[SkillError], ...] = (
    IncompatibleSkillRegistry,
    InvalidSkillRef,
    MissingRegistryPrefix,
    SchemaValidationError,
    SkillNotFound,
)


def _exit_with_error(error: Exception) -> None:
    emit_error(str(error))


def _validate_local_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise InvalidSkillRef(
            f"Invalid skill name {name!r}. Names must match ^[a-z0-9][a-z0-9_-]*$."
        )
    return name


def _persist_local_skill(agent: str, name: str, skill: Skill) -> None:
    target_dir = agent_skills_dir(agent) / name
    if target_dir.exists():
        raise InvalidSkillRef(
            f"Local skill {name!r} already exists for agent {agent!r}. "
            "Remove or rename the existing skill first."
        )
    if name in read_state(agent):
        raise InvalidSkillRef(
            f"Local skill {name!r} is already in desired state for agent {agent!r}. "
            "Remove or rename the existing skill first."
        )

    try:
        target_dir.mkdir(parents=True, exist_ok=False)
        (target_dir / "SKILL.md").write_text(render_skill_md(skill), encoding="utf-8")
        add_skill(agent, name)
    except FileExistsError as error:
        raise InvalidSkillRef(
            f"Local skill {name!r} already exists for agent {agent!r}. "
            "Remove or rename the existing skill first."
        ) from error
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise


def _with_name(skill: Skill, name: str) -> Skill:
    if skill.ref.name == name and skill.skill_md_frontmatter.get("name") == name:
        return skill
    frontmatter = dict(skill.skill_md_frontmatter)
    metadata = dict(skill.metadata)
    frontmatter["name"] = name
    metadata["name"] = name
    renamed = Skill(
        ref=SkillRef(skill.ref.registry, name),
        path=skill.path,
        metadata=metadata,
        body=skill.body,
        skill_md_frontmatter=frontmatter,
    )
    validate_skill(renamed)
    return renamed


def _name_from_skill(skill: Skill, explicit_name: Optional[str]) -> str:
    if explicit_name is not None:
        return _validate_local_name(explicit_name)
    raw = skill.skill_md_frontmatter.get("name") or skill.metadata.get("name")
    if not isinstance(raw, str):
        raise InvalidSkillRef("SKILL.md frontmatter must include a string `name` field.")
    return _validate_local_name(raw)


def _load_native_path(path: Path, agent_type: str) -> Skill:
    if path.is_dir():
        skill_dir = path
        skill_md = skill_dir / "SKILL.md"
    else:
        skill_dir = path.parent
        skill_md = path
    if not skill_md.is_file():
        raise SkillNotFound(f"Skill path {path} is missing SKILL.md.")
    body, frontmatter = _split_frontmatter(skill_md.read_text())
    name = frontmatter.get("name")
    if not isinstance(name, str):
        raise InvalidSkillRef("SKILL.md frontmatter must include a string `name` field.")
    skill = Skill(
        ref=SkillRef(agent_type, _validate_local_name(name)),
        path=skill_dir,
        metadata=dict(frontmatter),
        body=body,
        skill_md_frontmatter=dict(frontmatter),
    )
    validate_skill(skill)
    return skill


def _materialize_path_for_agent(path: Path, agent_type: str) -> Skill:
    if path.is_dir() and (path / "_meta.yaml").is_file():
        source = _load_skill_from_dir(SkillRef("clawrium", path.name), path)
        return materialize_skill_for_agent(source, agent_type)
    return _load_native_path(path, agent_type)


def _resolve_add_input(
    *,
    agent_type: str,
    path: Optional[Path],
    from_template: Optional[str],
    name: Optional[str],
) -> tuple[str, Skill]:
    if path is not None and from_template is not None:
        raise InvalidSkillRef("Pass either PATH or --from-template, not both.")
    if from_template is not None:
        source_ref = parse_skill_ref(from_template)
        source = load_skill(source_ref)
        skill = materialize_skill_for_agent(source, agent_type)
        skill = with_source_ref(skill, str(source_ref))
    elif path is not None:
        skill = _materialize_path_for_agent(path, agent_type)
    else:
        raise InvalidSkillRef("Pass PATH or --from-template. Interactive authoring is not implemented yet.")

    local_name = _name_from_skill(skill, name)
    skill = _with_name(skill, local_name)
    validate_skill(skill)
    return local_name, skill


def _editor_command(explicit: Optional[str]) -> list[str]:
    raw = explicit or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    return shlex.split(raw)


def _run_editor(path: Path, editor: Optional[str]) -> int:
    return subprocess.run([*_editor_command(editor), str(path)], check=False).returncode


@skill_app.command("list")
def list_agent_skill(
    agent: str = typer.Argument(..., help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List local skills in an agent's desired state."""
    safe_resolve_agent(agent)
    try:
        names = read_state(agent)
    except _USER_FACING_ERRORS as exc:
        _exit_with_error(exc)
        return

    rows = [
        {
            "kind": "skill",
            "name": name,
            "agent": agent,
            "path": str(agent_skills_dir(agent) / name / "SKILL.md"),
        }
        for name in names
    ]

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return
    if output is OutputFormat.name:
        typer.echo(dump_name(rows), nl=False)
        return

    headers = ["NAME", "AGENT", "PATH"]
    body = [[str(r["name"]), str(r["agent"]), str(r["path"])] for r in rows]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


@skill_app.command("add")
def add(
    agent: str = typer.Argument(..., help="Agent instance name."),
    path: Optional[Path] = typer.Argument(
        None, metavar="PATH", help="Path to SKILL.md or skill directory."
    ),
    from_template: Optional[str] = typer.Option(
        None,
        "--from-template",
        help="Registry template ref to copy, e.g. clawrium/tdd.",
    ),
    name: Optional[str] = typer.Option(None, "--name", help="Override local skill name."),
) -> None:
    """Add a local, agent-native skill without syncing the host."""
    _host, agent_type, _claw = safe_resolve_agent(agent)
    try:
        local_name, skill = _resolve_add_input(
            agent_type=agent_type, path=path, from_template=from_template, name=name
        )
        _persist_local_skill(agent, local_name, skill)
    except _USER_FACING_ERRORS as exc:
        _exit_with_error(exc)
        return

    typer.echo(
        f"agent/{agent}: added local skill {local_name!r}; run `clawctl agent sync {agent}` to apply"
    )


@skill_app.command("edit")
def edit(
    agent: str = typer.Argument(..., help="Agent instance name."),
    name: str = typer.Argument(..., help="Local skill name."),
    editor: Optional[str] = typer.Option(None, "--editor", help="Editor command."),
) -> None:
    """Edit a local skill and validate the native result."""
    _host, agent_type, _claw = safe_resolve_agent(agent)
    try:
        local_name = _validate_local_name(name)
        skill_dir = agent_skills_dir(agent) / local_name
        skill_md = skill_dir / "SKILL.md"
        before = skill_md.read_text()
    except (OSError, _USER_FACING_ERRORS) as exc:
        _exit_with_error(exc)
        return

    code = _run_editor(skill_md, editor)
    if code != 0:
        emit_error(f"editor exited with status {code}")

    try:
        load_agent_skill(agent, local_name, agent_type)
    except _USER_FACING_ERRORS as exc:
        skill_md.write_text(before)
        _exit_with_error(exc)
        return
    typer.echo(f"agent/{agent}: updated local skill {local_name!r}")


@skill_app.command("remove")
def remove(
    agent: str = typer.Argument(..., help="Agent instance name."),
    name: str = typer.Argument(..., help="Local skill name."),
) -> None:
    """Remove a local skill from desired state and disk."""
    safe_resolve_agent(agent)
    try:
        local_name = _validate_local_name(name)
        _new_state, removed = remove_skill(agent, local_name)
        shutil.rmtree(agent_skills_dir(agent) / local_name, ignore_errors=True)
    except _USER_FACING_ERRORS as exc:
        _exit_with_error(exc)
        return
    if removed:
        typer.echo(f"agent/{agent}: removed local skill {local_name!r}")
    else:
        typer.echo(f"agent/{agent}: local skill {local_name!r} was not present")


def _removed_verb(old: str, replacement: str) -> None:
    emit_error(
        f"`clawctl agent skill {old}` was removed.",
        hint=f"Use `{replacement}`.",
    )


@skill_app.command("attach", hidden=True)
def attach(
    skill_ref: str = typer.Argument(None),
    agent: Optional[str] = typer.Option(None, "--agent"),
) -> None:
    """Removed compatibility shim."""
    _removed_verb(
        "attach",
        "clawctl agent skill add <agent> --from-template <registry>/<name>",
    )


@skill_app.command("detach", hidden=True)
def detach(
    skill_ref: str = typer.Argument(None),
    agent: Optional[str] = typer.Option(None, "--agent"),
) -> None:
    """Removed compatibility shim."""
    _removed_verb("detach", "clawctl agent skill remove <agent> <skill-name>")


@skill_app.command("get", hidden=True)
def get(
    agent: Optional[str] = typer.Option(None, "--agent"),
) -> None:
    """Removed compatibility shim."""
    _removed_verb("get", "clawctl agent skill list <agent>")

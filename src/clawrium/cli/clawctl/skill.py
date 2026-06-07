"""`clawctl skill` — skill registry and user overlay management."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer
import yaml

from clawrium.cli.clawctl._common import OutputFormat, parse_kv_labels
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.core.skills import (
    InvalidSkillRef,
    MissingRegistryPrefix,
    REGISTRIES,
    SchemaValidationError,
    Skill,
    SkillError,
    SkillNotFound,
    SkillRef,
    _NAME_RE,
    _load_skill_from_dir,
    _overlay_root,
    _split_frontmatter,
    list_skills,
    load_skill,
    parse_skill_ref,
    validate_skill,
)

__all__ = ["skill_app"]


skill_app = typer.Typer(
    name="skill",
    help="Skills catalog and user overlay management.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)

skill_registry_app = typer.Typer(
    name="registry",
    help="Read-only entrypoint for the skill registry.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


def _skill_description(ref) -> str:
    """Best-effort: load the skill metadata and return its description.

    Falls back to an empty string for skills whose `_meta.yaml`
    cannot be loaded — list views should never crash on a single
    broken skill.
    """
    try:
        skill = load_skill(ref)
    except SkillError:
        return ""
    meta = skill.metadata or {}
    return str(meta.get("description") or "")


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise InvalidSkillRef(
            f"Invalid skill name {name!r}. Names must match ^[a-z0-9][a-z0-9_-]*$."
        )
    return name


def _render_skill_md(skill: Skill) -> str:
    frontmatter = yaml.safe_dump(
        dict(skill.skill_md_frontmatter), sort_keys=False, allow_unicode=False
    ).strip()
    return f"---\n{frontmatter}\n---\n{skill.body or ''}"


def _load_native_path(path: Path, registry: str) -> Skill:
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
        ref=SkillRef(registry, _validate_name(name)),
        path=skill_dir,
        metadata=dict(frontmatter),
        body=body,
        skill_md_frontmatter=dict(frontmatter),
    )
    validate_skill(skill)
    return skill


def _rename_skill(skill: Skill, name: str) -> Skill:
    if skill.ref.name == name and skill.metadata.get("name") == name:
        return skill
    metadata = dict(skill.metadata)
    frontmatter = dict(skill.skill_md_frontmatter)
    metadata["name"] = name
    if frontmatter:
        frontmatter["name"] = name
    renamed = Skill(
        ref=SkillRef(skill.ref.registry, name),
        path=skill.path,
        metadata=metadata,
        body=skill.body,
        skill_md_frontmatter=frontmatter,
    )
    validate_skill(renamed)
    return renamed


def _load_overlay_input(path: Path, registry: str, name: Optional[str]) -> tuple[str, Skill]:
    if registry not in REGISTRIES:
        raise InvalidSkillRef(
            f"Unknown registry {registry!r}. Allowed: {', '.join(REGISTRIES)}."
        )
    if registry == "clawrium":
        if not path.is_dir():
            raise InvalidSkillRef("clawrium registry skills must be provided as a directory.")
        skill = _load_skill_from_dir(SkillRef("clawrium", path.name), path)
        validate_skill(skill)
    else:
        skill = _load_native_path(path, registry)
    local_name = _validate_name(name) if name is not None else skill.ref.name
    skill = _rename_skill(skill, local_name)
    return local_name, skill


def _write_overlay_skill(registry: str, name: str, skill: Skill) -> None:
    target_dir = _overlay_root() / registry / name
    if target_dir.exists():
        raise InvalidSkillRef(
            f"Skill {registry}/{name} already exists in the user overlay. "
            "Remove or rename it before adding a replacement."
        )
    target_dir.mkdir(parents=True, exist_ok=False)
    try:
        (target_dir / "SKILL.md").write_text(_render_skill_md(skill))
        if registry == "clawrium":
            (target_dir / "_meta.yaml").write_text(
                yaml.safe_dump(dict(skill.metadata), sort_keys=False, allow_unicode=False)
            )
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise


@skill_app.command("add")
def add(
    path: Optional[Path] = typer.Argument(
        None, metavar="PATH", help="Path to SKILL.md or skill directory."
    ),
    registry: str = typer.Option(..., "--registry", help="Target skill registry."),
    name: Optional[str] = typer.Option(None, "--name", help="Override skill name."),
    interactive: bool = typer.Option(
        False, "--interactive", help="Open an editor for a new skill stub."
    ),
) -> None:
    """Add a skill to the user overlay catalog."""
    if interactive:
        emit_error("interactive skill authoring is not implemented yet")
    if path is None:
        emit_error("PATH is required unless --interactive is implemented")
    try:
        local_name, skill = _load_overlay_input(path, registry, name)
        _write_overlay_skill(registry, local_name, skill)
    except (InvalidSkillRef, SchemaValidationError, SkillNotFound) as exc:
        emit_error(str(exc))
    typer.echo(f"skill/{registry}/{local_name}: added to user overlay")


@skill_registry_app.command("get")
def get(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    selectors: Optional[list[str]] = typer.Option(
        None,
        "-l",
        "--selector",
        help="Label selector (registry=NAME). Repeatable.",
    ),
    registry_opt: Optional[str] = typer.Option(
        None, "--registry", "-r", help="Filter to a single registry (legacy form)."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List available skills (optionally filtered by registry)."""
    selector = parse_kv_labels(selectors)
    registry_filter = registry_opt or selector.get("registry")

    try:
        refs = list_skills(registry=registry_filter)
    except (InvalidSkillRef, SkillNotFound) as exc:
        emit_error(str(exc))

    rows = [
        {
            "kind": "skill",
            "name": str(ref),
            "registry": ref.registry,
            "description": _skill_description(ref),
        }
        for ref in refs
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

    headers = ["NAME", "REGISTRY", "DESCRIPTION"]
    body = [
        [str(r["name"]), str(r["registry"]), str(r["description"] or "-")] for r in rows
    ]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


@skill_registry_app.command("describe")
def describe(
    skill_ref: str = typer.Argument(..., metavar="REGISTRY/NAME", help="Skill ref."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table|json|yaml)."
    ),
) -> None:
    """Show full metadata + body for one skill."""
    try:
        ref = parse_skill_ref(skill_ref)
        skill = load_skill(ref)
        validate_skill(skill)
    except (
        InvalidSkillRef,
        MissingRegistryPrefix,
        SchemaValidationError,
        SkillNotFound,
    ) as exc:
        emit_error(str(exc))

    meta = skill.metadata or {}
    row = {
        "kind": "skill",
        "name": str(skill.ref),
        "registry": skill.ref.registry,
        "description": meta.get("description", ""),
        "metadata": dict(meta),
        "body_preview": skill.body[:200] if skill.body else "",
    }

    if output is OutputFormat.json:
        typer.echo(dump_json([row]), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml([row]), nl=False)
        return

    typer.echo(f"Name:         {row['name']}")
    typer.echo("Kind:         skill")
    typer.echo(f"Registry:     {row['registry']}")
    typer.echo(f"Description:  {row['description'] or '-'}")
    for key in sorted(meta.keys()):
        if key in ("name", "description"):
            continue
        value = meta[key]
        typer.echo(f"  {key}: {value}")
    if skill.body:
        typer.echo("")
        typer.echo("Body:")
        for line in skill.body.splitlines():
            typer.echo(f"  {line}")


# Register sub-group on the top-level `skill` app.
skill_app.add_typer(skill_registry_app, name="registry")

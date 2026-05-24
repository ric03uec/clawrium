"""`clawctl skill` — Pattern A attachable (READ-ONLY registry; #509).

Skills are repo-bundled — the catalog ships inside the wheel. `skill
registry` exposes `get` and `describe` only; there is no `create`
verb. Per-agent `attach/detach/get` lives under
`clawctl agent skill`.

Storage layer is `clawrium.core.skills` (untouched per plan §2).
"""

from __future__ import annotations

from typing import Optional

import typer

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
    SchemaValidationError,
    SkillError,
    SkillNotFound,
    list_skills,
    load_skill,
    parse_skill_ref,
    validate_skill,
)

__all__ = ["skill_app"]


skill_app = typer.Typer(
    name="skill",
    help="Skills catalog (Pattern A attachable, read-only).",
    no_args_is_help=True,
    add_completion=False,
)

skill_registry_app = typer.Typer(
    name="registry",
    help="Read-only entrypoint for the skill registry.",
    no_args_is_help=True,
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

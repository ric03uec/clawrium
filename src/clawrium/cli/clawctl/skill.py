"""`clawctl skill` — unified vetted+local skills catalog (#411).

Skills are referenced as ``<source>/<name>`` where
``source ∈ {vetted, local}``. Vetted skills ship in the wheel and are
read-only. Local skills live at ``~/.config/clawrium/skills/<name>/``
and are user-owned (create/edit/delete via ``add``/``edit``/``remove``).

Per-agent attach/detach lives under ``clawctl agent skill``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer
import yaml

from clawrium.cli.chat import _CONTROL_AND_BIDI_RE
from clawrium.cli.clawctl._common import OutputFormat, parse_kv_labels
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.core.skills import (
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingSourcePrefix,
    ReadOnlySource,
    SchemaValidationError,
    SkillError,
    SkillNameConflict,
    SkillNameImmutable,
    SkillNotFound,
    SOURCES,
    claws_support_map,
    list_skills,
    load_skill,
    parse_skill_ref,
    validate_skill,
)
from clawrium.core.skills_local import (
    create_local_skill,
    delete_local_skill,
    update_local_skill,
)

__all__ = ["skill_app"]


skill_app = typer.Typer(
    name="skill",
    help="Unified skills catalog (vetted + local).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)

skill_registry_app = typer.Typer(
    name="registry",
    help="Read-only entrypoint for the skill catalog (legacy alias).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


_USER_FACING_ERRORS: tuple[type[SkillError], ...] = (
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingSourcePrefix,
    ReadOnlySource,
    SchemaValidationError,
    SkillNameConflict,
    SkillNameImmutable,
    SkillNotFound,
)


def _skill_description(ref) -> str:
    try:
        skill = load_skill(ref)
    except SkillError:
        return ""
    meta = skill.metadata or {}
    return str(meta.get("description") or "")


def _supported_on_str() -> str:
    table = claws_support_map()
    return ", ".join(c for c, ok in table.items() if ok) or "(none)"


@skill_app.command("list")
def list_command(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    selectors: Optional[list[str]] = typer.Option(
        None,
        "-l",
        "--selector",
        help="Label selector (source=NAME). Repeatable.",
    ),
    source_opt: Optional[str] = typer.Option(
        None, "--source", "-s", help="Filter to a single source (vetted|local)."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List skills in the unified catalog."""
    selector = parse_kv_labels(selectors)
    source_filter = source_opt or selector.get("source")
    if source_filter is not None and source_filter not in SOURCES:
        emit_error(
            f"Unknown source {source_filter!r}. Allowed: {', '.join(SOURCES)}."
        )

    try:
        refs = list_skills(source=source_filter)
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    supported = _supported_on_str()
    rows = [
        {
            "kind": "skill",
            "name": str(ref),
            "source": ref.source,
            "supported_on": supported,
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

    headers = ["NAME", "SOURCE", "SUPPORTED ON", "DESCRIPTION"]
    body = [
        [
            str(r["name"]),
            str(r["source"]),
            str(r["supported_on"]),
            str(r["description"] or "-"),
        ]
        for r in rows
    ]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


@skill_app.command("show")
def show_command(
    skill_ref: str = typer.Argument(
        ..., metavar="SOURCE/NAME", help="Skill ref (e.g. `vetted/tdd`)."
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table|json|yaml)."
    ),
) -> None:
    """Show full metadata + body for one skill."""
    try:
        ref = parse_skill_ref(skill_ref)
        skill = load_skill(ref)
        validate_skill(skill)
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    meta = skill.metadata or {}
    supported = _supported_on_str()
    row = {
        "kind": "skill",
        "name": str(skill.ref),
        "source": skill.ref.source,
        "supported_on": supported,
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

    def _safe(value: object) -> str:
        return _CONTROL_AND_BIDI_RE.sub(" ", str(value))

    typer.echo(f"Name:         {_safe(row['name'])}")
    typer.echo("Kind:         skill")
    typer.echo(f"Source:       [{_safe(row['source'])}]")
    typer.echo(f"Supported on: {_safe(row['supported_on'])}")
    typer.echo(f"Description:  {_safe(row['description']) if row['description'] else '-'}")
    # Sanitize each metadata key + value: author/version/arbitrary
    # extension fields are catalog-author-supplied (ATX #411 New-B1b).
    for key in sorted(meta.keys()):
        if key in ("name", "description"):
            continue
        value = meta[key]
        typer.echo(f"  {_safe(key)}: {_safe(value)}")
    if skill.body:
        typer.echo("")
        typer.echo("Body:")
        # Sanitize each line: SKILL.md content is author-supplied and could
        # carry U+202E (RTLO) or other bidi/control codepoints that would
        # otherwise reach the terminal verbatim (ATX #411 B1).
        for line in skill.body.splitlines():
            safe = _CONTROL_AND_BIDI_RE.sub(" ", line)
            typer.echo(f"  {safe}")


def _parse_frontmatter_file(path: Path) -> tuple[dict[str, Any], str]:
    """Read a file as either a full SKILL.md (frontmatter + body) or a body-only markdown."""
    text = path.read_text()
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            yaml_block = text[4:end]
            body = text[end + len("\n---\n") :]
            try:
                fm = yaml.safe_load(yaml_block) or {}
            except yaml.YAMLError as error:
                raise SchemaValidationError(
                    f"Frontmatter is not valid YAML: {error}"
                ) from error
            if not isinstance(fm, dict):
                raise SchemaValidationError("Frontmatter must be a YAML mapping.")
            return fm, body
    return {}, text


def _local_ref_name(skill_ref: str, allow_bare: bool) -> str:
    """Return the local name from ``local/<name>`` or a bare ``<name>``."""
    if "/" in skill_ref:
        ref = parse_skill_ref(skill_ref)
        if ref.source != "local":
            raise ReadOnlySource(
                f"Cannot modify `{ref}`: only local/ skills are writable."
            )
        return ref.name
    if not allow_bare:
        raise MissingSourcePrefix(
            f"Skill reference {skill_ref!r} is missing a source prefix. "
            "Use `local/<name>` to disambiguate."
        )
    return skill_ref


@skill_app.command("add")
def add_command(
    skill_ref: str = typer.Argument(
        ..., metavar="LOCAL/NAME", help="Skill ref (e.g. `local/my-skill`)."
    ),
    description: Optional[str] = typer.Option(
        None, "--description", help="One-line description."
    ),
    body_file: Optional[Path] = typer.Option(
        None,
        "--body-file",
        help="Path to a markdown file containing the body (or full SKILL.md with frontmatter).",
        exists=True,
        readable=True,
    ),
    version: Optional[str] = typer.Option(None, "--version", help="Skill version."),
    author: Optional[str] = typer.Option(None, "--author", help="Skill author."),
) -> None:
    """Create a new local skill."""
    try:
        name = _local_ref_name(skill_ref, allow_bare=False)
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    fm: dict[str, Any] = {}
    body = ""
    if body_file is not None:
        try:
            fm, body = _parse_frontmatter_file(body_file)
        except _USER_FACING_ERRORS as exc:
            emit_error(str(exc))

    fm["name"] = name
    if description is not None:
        fm["description"] = description
    if version is not None:
        fm["version"] = version
    if author is not None:
        fm["author"] = author
    if not fm.get("description"):
        emit_error("`--description` is required (or include `description` in --body-file frontmatter).")

    try:
        ref = create_local_skill(name, fm, body)
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    typer.echo(f"skill/{ref}: created")


@skill_app.command("edit")
def edit_command(
    skill_ref: str = typer.Argument(
        ..., metavar="LOCAL/NAME", help="Skill ref (e.g. `local/my-skill`)."
    ),
    description: Optional[str] = typer.Option(
        None, "--description", help="Update description."
    ),
    body_file: Optional[Path] = typer.Option(
        None,
        "--body-file",
        help="Replace body (and optionally frontmatter) from this file.",
        exists=True,
        readable=True,
    ),
    version: Optional[str] = typer.Option(None, "--version", help="Update version."),
    author: Optional[str] = typer.Option(None, "--author", help="Update author."),
) -> None:
    """Edit an existing local skill. ``name`` is immutable."""
    try:
        name = _local_ref_name(skill_ref, allow_bare=False)
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    # Load current state.
    try:
        existing = load_skill(parse_skill_ref(f"local/{name}"))
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    fm: dict[str, Any] = dict(existing.metadata or {})
    body = existing.body
    if body_file is not None:
        try:
            file_fm, file_body = _parse_frontmatter_file(body_file)
        except _USER_FACING_ERRORS as exc:
            emit_error(str(exc))
        body = file_body
        if file_fm:
            # Merge file frontmatter, but `name` cannot change.
            if "name" in file_fm and file_fm["name"] != name:
                emit_error(
                    f"Cannot change skill name from {name!r} to {file_fm['name']!r}. "
                    "Names are immutable."
                )
            fm.update(file_fm)
    if description is not None:
        fm["description"] = description
    if version is not None:
        fm["version"] = version
    if author is not None:
        fm["author"] = author
    fm["name"] = name

    try:
        ref = update_local_skill(name, fm, body)
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    typer.echo(f"skill/{ref}: updated")


@skill_app.command("remove")
def remove_command(
    skill_ref: str = typer.Argument(
        ..., metavar="LOCAL/NAME", help="Skill ref (e.g. `local/my-skill`)."
    ),
) -> None:
    """Delete a local skill."""
    try:
        name = _local_ref_name(skill_ref, allow_bare=False)
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    try:
        removed = delete_local_skill(name)
    except _USER_FACING_ERRORS as exc:
        emit_error(str(exc))

    if removed:
        typer.echo(f"skill/local/{name}: removed")
    else:
        typer.echo(f"skill/local/{name}: not found (no-op)")


# Legacy `clawctl skill registry get|describe` aliases — kept so the
# existing test suite + docs keep working while Phase 7 rewrites tests.
@skill_registry_app.command("get")
def registry_get(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    selectors: Optional[list[str]] = typer.Option(
        None, "-l", "--selector", help="Label selector (source=NAME)."
    ),
    source_opt: Optional[str] = typer.Option(
        None, "--source", "-s", help="Filter to a single source."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """Alias for `skill list` (legacy)."""
    list_command(
        output=output,
        selectors=selectors,
        source_opt=source_opt,
        no_headers=no_headers,
    )


@skill_registry_app.command("describe")
def registry_describe(
    skill_ref: str = typer.Argument(..., metavar="SOURCE/NAME", help="Skill ref."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
) -> None:
    """Alias for `skill show` (legacy)."""
    show_command(skill_ref=skill_ref, output=output)


skill_app.add_typer(skill_registry_app, name="registry")

"""`clawctl skill registry` — browse the in-repo skills catalog (legacy backend).

Phase 1 surface: `get` (optionally filtered by `--registry`) and `describe`
(prints metadata + SKILL.md body). Per-agent install/remove lives under
`clawctl agent skill` and is wired up in Phase 2.

All errors raised by `clawrium.core.skills` are caught here and rendered
as a single-line `[red]Error:[/red] …` message with a non-zero exit code,
matching the existing `clawctl agent registry`/`clawctl agent` UX. The catch list is
explicit — we never swallow `Exception`.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from clawrium.core.skills import (
    REGISTRIES,
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingRegistryPrefix,
    SchemaValidationError,
    SkillError,
    SkillNotFound,
    SkillRef,
    list_skills,
    load_skill,
    parse_skill_ref,
    validate_skill,
)

__all__ = ["skill_app"]

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)


skill_app = typer.Typer(
    name="skill",
    help="Browse the clawrium-managed skills catalog.",
    no_args_is_help=True,
)


def _exit_with_error(error: SkillError) -> None:
    """Render a skill error to stderr and exit non-zero."""
    err_console.print(f"[red]Error:[/red] {escape(str(error))}")
    raise typer.Exit(code=1)


@skill_app.command(name="list")
def list_skills_command(
    registry: str | None = typer.Option(
        None,
        "--registry",
        "-r",
        help=(f"Filter to a single registry. Valid values: {', '.join(REGISTRIES)}."),
    ),
) -> None:
    """List skills in the catalog as a registry/name table."""
    try:
        refs = list_skills(registry=registry)
    except (InvalidSkillRef, SkillNotFound) as error:
        # SkillNotFound is raised by `_catalog_root` when neither the
        # bundled nor the dev catalog can be located — surface that as
        # an actionable CLI error rather than a raw traceback.
        _exit_with_error(error)
        return  # for type-checkers — typer.Exit raises

    if not refs:
        if registry:
            console.print(
                f"No skills registered under `{escape(registry)}/`. "
                "Add one under "
                f"[cyan]skills/{escape(registry)}/<name>/[/cyan]."
            )
        else:
            console.print(
                "No skills in the catalog. "
                "Add one under [cyan]skills/<registry>/<name>/[/cyan]."
            )
        return

    table = Table(title="Skills catalog")
    table.add_column("Ref", style="cyan", no_wrap=True)
    table.add_column("Registry", style="green")
    table.add_column("Description")

    for ref in refs:
        description = _short_description(ref)
        table.add_row(escape(str(ref)), escape(ref.registry), description)

    console.print(table)


@skill_app.command()
def show(
    skill_ref: str = typer.Argument(
        ...,
        metavar="REGISTRY/NAME",
        help="Skill reference (e.g. `clawrium/tdd`). Bare names are rejected.",
    ),
) -> None:
    """Show metadata + SKILL.md body for one skill."""
    try:
        ref = parse_skill_ref(skill_ref)
        skill = load_skill(ref)
        validate_skill(skill)
    except (
        MissingRegistryPrefix,
        InvalidSkillRef,
        ExternalSourceBlocked,
        SkillNotFound,
        SchemaValidationError,
    ) as error:
        _exit_with_error(error)
        return

    console.print(f"\n[bold cyan]{escape(str(skill.ref))}[/bold cyan]")
    description = skill.metadata.get("description", "")
    if isinstance(description, str) and description:
        console.print(escape(description.strip()))
    console.print()

    metadata_table = Table(title="Metadata", show_header=False, expand=False)
    metadata_table.add_column("Field", style="yellow", no_wrap=True)
    metadata_table.add_column("Value")
    metadata_table.add_row("registry", escape(skill.ref.registry))
    metadata_table.add_row("name", escape(skill.ref.name))
    for key in ("version", "license", "author"):
        value = skill.metadata.get(key)
        if value is not None:
            metadata_table.add_row(key, escape(str(value)))

    platforms = skill.metadata.get("platforms")
    if isinstance(platforms, list) and platforms:
        metadata_table.add_row(
            "platforms", escape(", ".join(str(p) for p in platforms))
        )

    compatibility = skill.metadata.get("compatibility")
    if isinstance(compatibility, dict):
        compat = ", ".join(
            f"{claw}={'yes' if flag else 'no'}" for claw, flag in compatibility.items()
        )
        metadata_table.add_row("compatibility", escape(compat))
    elif skill.ref.registry in {"openclaw", "hermes", "zeroclaw"}:
        metadata_table.add_row("compatibility", skill.ref.registry)

    console.print(metadata_table)

    if skill.body.strip():
        console.print(Panel(Markdown(skill.body), title="SKILL.md", expand=True))


def _short_description(ref: SkillRef) -> str:
    """Best-effort one-line description for the `list` table.

    Failures (parse errors, schema mismatches) are degraded to a static
    `?` so a single bad skill doesn't blow up the whole `list`. The
    detailed error is surfaced by `clm skill show <ref>`. An empty or
    missing description also renders as `?` — `?` and blank are
    visually identical otherwise, and `?` signals "look at me with
    show" more clearly.
    """
    try:
        skill = load_skill(ref)
    except SkillError as error:
        logger.debug("Skipping description for %s: %s", ref, error)
        return "?"

    description = skill.metadata.get("description", "")
    if not isinstance(description, str):
        return "?"
    one_line = " ".join(description.split())
    if not one_line:
        return "?"
    if len(one_line) > 80:
        one_line = one_line[:77] + "..."
    return escape(one_line)

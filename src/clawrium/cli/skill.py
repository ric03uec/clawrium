"""`clm skill` — legacy entrypoint (read-only catalog browse).

The active CLI is ``clawctl skill`` (``clawrium.cli.clawctl.skill``).
This module is preserved so ``clawrium.cli.main:app`` still imports
cleanly for the test suite. It now wraps the unified vetted+local
catalog with the new ref grammar.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from clawrium.cli.chat import _CONTROL_AND_BIDI_RE
from clawrium.core.skills import (
    SOURCES,
    ExternalSourceBlocked,
    InvalidSkillRef,
    MissingSourcePrefix,
    SchemaValidationError,
    SkillError,
    SkillNotFound,
    SkillRef,
    claws_support_map,
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
    rich_markup_mode=None,
)


def _exit_with_error(error: SkillError) -> None:
    err_console.print(f"[red]Error:[/red] {escape(str(error))}")
    raise typer.Exit(code=1)


@skill_app.command(name="list")
def list_skills_command(
    source: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help=f"Filter to a single source. Valid values: {', '.join(SOURCES)}.",
    ),
) -> None:
    """List skills in the catalog as a source/name table."""
    try:
        refs = list_skills(source=source)
    except (InvalidSkillRef, SkillNotFound) as error:
        _exit_with_error(error)
        return

    if not refs:
        console.print(
            "No skills in the catalog. "
            "Add one with [cyan]clawctl skill add local/<name>[/cyan]."
        )
        return

    supported = ", ".join(c for c, ok in claws_support_map().items() if ok) or "(none)"
    table = Table(title="Skills catalog")
    table.add_column("Ref", style="cyan", no_wrap=True)
    table.add_column("Source", style="green")
    table.add_column("Supported on", style="magenta")
    table.add_column("Description")

    for ref in refs:
        description = _short_description(ref)
        table.add_row(
            escape(str(ref)),
            escape(ref.source),
            escape(supported),
            description,
        )

    console.print(table)


@skill_app.command()
def show(
    skill_ref: str = typer.Argument(
        ...,
        metavar="SOURCE/NAME",
        help="Skill reference (e.g. `vetted/tdd`).",
    ),
) -> None:
    """Show metadata + SKILL.md body for one skill."""
    try:
        ref = parse_skill_ref(skill_ref)
        skill = load_skill(ref)
        validate_skill(skill)
    except (
        MissingSourcePrefix,
        InvalidSkillRef,
        ExternalSourceBlocked,
        SkillNotFound,
        SchemaValidationError,
    ) as error:
        _exit_with_error(error)
        return

    def _safe(value: object) -> str:
        return _CONTROL_AND_BIDI_RE.sub(" ", str(value))

    console.print(f"\n[bold cyan]{escape(str(skill.ref))}[/bold cyan]")
    description = skill.metadata.get("description", "")
    if isinstance(description, str) and description:
        console.print(escape(_safe(description.strip())))
    console.print()

    supported = ", ".join(c for c, ok in claws_support_map().items() if ok) or "(none)"
    metadata_table = Table(title="Metadata", show_header=False, expand=False)
    metadata_table.add_column("Field", style="yellow", no_wrap=True)
    metadata_table.add_column("Value")
    metadata_table.add_row("source", escape(skill.ref.source))
    metadata_table.add_row("name", escape(skill.ref.name))
    metadata_table.add_row("supported_on", escape(supported))
    for key in ("version", "license", "author"):
        value = skill.metadata.get(key)
        if value is not None:
            metadata_table.add_row(key, escape(_safe(value)))

    console.print(metadata_table)

    if skill.body.strip():
        # SKILL.md bodies are catalog-author-supplied; sanitize bidi /
        # control codepoints before handing the markdown to Rich.
        # (ATX #411 New-B1a.)
        safe_body = _CONTROL_AND_BIDI_RE.sub(" ", skill.body)
        console.print(Panel(Markdown(safe_body), title="SKILL.md", expand=True))


def _short_description(ref: SkillRef) -> str:
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

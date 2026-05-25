"""`clawctl agent registry get|describe` — read-only agent-types catalog.

Plan §"Specific Outcomes":
- `get` lists supported agent types (openclaw, zeroclaw, hermes).
- `describe <type>` shows the manifest's high-level info.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.output import (
    dump_json,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.cli.output._sanitize import sanitize
from clawrium.core.registry import (
    ManifestNotFoundError,
    get_claw_info,
    list_claws,
    load_manifest,
)


def _s(value: object) -> str:
    return sanitize(str(value))


__all__ = ["registry_app"]


registry_app = typer.Typer(
    name="registry",
    help="Read-only catalog of supported agent types.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


@registry_app.command("get")
def get(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
) -> None:
    """List supported agent types."""
    rows: list[dict] = []
    for claw in list_claws():
        try:
            info = get_claw_info(claw)
        except ManifestNotFoundError:
            continue
        rows.append(
            {
                "kind": "agent-type",
                "name": claw,
                "latest_version": info.get("latest_version", ""),
                "description": info.get("description", ""),
            }
        )

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return

    headers = ["NAME", "VERSION", "DESCRIPTION"]
    body = [
        [str(r["name"]), str(r["latest_version"]), str(r["description"])] for r in rows
    ]
    typer.echo(render_table(headers, body), nl=False)


@registry_app.command("describe")
def describe(
    agent_type: str = typer.Argument(..., help="Agent type to describe."),
) -> None:
    """Describe a single agent type."""
    try:
        manifest = load_manifest(agent_type)
    except ManifestNotFoundError:
        emit_error(
            f"unknown agent type {agent_type!r}",
            hint="clawctl agent registry get",
        )

    # ATX iter-1 B2: sanitize agent_type (raw user input) and manifest
    # fields (potentially attacker-controlled via third-party manifests)
    # before echoing to the terminal.
    agent = manifest.get("agent", {})
    typer.echo(f"Name:         {_s(agent_type)}")
    typer.echo(f"Description:  {_s(agent.get('description', '-'))}")
    platforms = manifest.get("platforms", []) or []
    typer.echo(f"Platforms:    {len(platforms)}")
    for platform in platforms:
        typer.echo(
            f"  - {_s(platform.get('version', '?'))}  "
            f"os={_s(platform.get('os', '?'))}  arch={_s(platform.get('arch', '?'))}"
        )
    features = manifest.get("features", {}) or {}
    if features.get("web_ui"):
        typer.echo("Web UI:       yes")
    if features.get("chat"):
        typer.echo("Chat:         yes")

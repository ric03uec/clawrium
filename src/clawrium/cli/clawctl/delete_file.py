"""`clawctl delete -f <file|dir>` — teardown resources declared in a manifest."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from clawrium.cli.clawctl._common import confirm_destructive
from clawrium.cli.output import emit_error, stream_action


def delete_file(
    file: Optional[Path] = typer.Option(
        None, "--file", "-f", help="Fleet manifest file or directory.",
    ),
    kustomize: Optional[Path] = typer.Option(
        None, "--kustomize", "-k", help="Directory of manifests (alias for --file with a directory).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    cascade: bool = typer.Option(
        False,
        "--cascade",
        help="Also delete providers, channels, integrations, and hosts.",
    ),
) -> None:
    """Teardown all resources declared in a manifest.

    By default stops and deletes agents only. Use --cascade to also remove
    providers, channels, integrations, and hosts.

    Examples:
        clawctl delete -f fleet.yaml
        clawctl delete -f fleet.yaml --yes
        clawctl delete -f fleet.yaml --cascade
    """
    target = file or kustomize
    if not target:
        emit_error("--file/-f is required", hint="clawctl delete -f fleet.yaml")

    target_path = Path(target)
    if not target_path.exists():
        emit_error(f"{target_path}: no such file or directory")

    from clawrium.core.manifest.differ import compute
    from clawrium.core.manifest.executor import execute_delete
    from clawrium.core.manifest.parser import parse_directory, parse_file
    from clawrium.core.manifest.state import ActualState

    try:
        doc = parse_directory(target_path) if target_path.is_dir() else parse_file(target_path)
    except ValueError as exc:
        emit_error(str(exc))

    actual = ActualState.from_disk()
    cs = compute(doc, actual, for_delete=True)

    agents_to_delete = [op.name for op in cs.deletes if op.kind == "agent"]
    if not agents_to_delete:
        typer.echo("Nothing to delete.")
        raise typer.Exit(code=0)

    cascade_note = (
        " and all associated providers/channels/integrations/hosts" if cascade else ""
    )
    confirm_destructive(
        prompt=f"Delete agents {agents_to_delete}{cascade_note}? This cannot be undone.",
        yes=yes,
    )

    def emit(action: str, resource: str) -> None:
        stream_action(resource=resource, message=action)

    errors = execute_delete(doc, cs, actual, emit=emit, cascade=cascade)

    if errors:
        typer.echo("\nErrors:", err=True)
        for e in errors:
            typer.echo(f"  {e}", err=True)
        raise typer.Exit(code=1)

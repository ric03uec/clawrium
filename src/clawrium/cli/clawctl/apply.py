"""`clawctl apply -f <file|dir>` — declarative fleet reconciliation."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from clawrium.cli.output import emit_error, stream_action


def apply(
    file: Optional[Path] = typer.Option(
        None, "--file", "-f", help="Fleet manifest file or directory.",
    ),
    kustomize: Optional[Path] = typer.Option(
        None, "--kustomize", "-k", help="Directory of manifests (alias for --file with a directory).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without applying."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation on destructive changes."),
) -> None:
    """Apply a fleet manifest — reconcile actual state toward desired state.

    Examples:
        clawctl apply -f fleet.yaml
        clawctl apply -f ./fleet/
        clawctl apply -f fleet.yaml --dry-run
    """
    target = file or kustomize
    if not target:
        emit_error("--file/-f is required", hint="clawctl apply -f fleet.yaml")

    target_path = Path(target)
    if not target_path.exists():
        emit_error(f"{target_path}: no such file or directory")

    from clawrium.core.manifest.differ import compute
    from clawrium.core.manifest.executor import execute_apply
    from clawrium.core.manifest.parser import parse_directory, parse_file
    from clawrium.core.manifest.state import ActualState
    from clawrium.core.manifest.validator import (
        collect_secret_refs,
        secret_preflight,
        validate_refs,
    )

    try:
        doc = parse_directory(target_path) if target_path.is_dir() else parse_file(target_path)
    except ValueError as exc:
        emit_error(str(exc))

    ref_errors = validate_refs(doc)
    if ref_errors:
        typer.echo("Error: manifest has unresolved references:", err=True)
        for e in ref_errors:
            typer.echo(f"  {e}", err=True)
        raise typer.Exit(code=1)

    secret_refs = collect_secret_refs(doc)
    missing_secrets = secret_preflight(secret_refs)
    if missing_secrets:
        typer.echo("Error: missing secrets required by manifest:", err=True)
        for s in missing_secrets:
            typer.echo(f"  {s}", err=True)
        typer.echo("\nSet them with:", err=True)
        for s in missing_secrets:
            parts = s.split("/")
            if len(parts) >= 2 and parts[0] == "providers":
                pname = parts[1]
                typer.echo(
                    f"  echo '<key>' | clawctl provider registry create {pname}"
                    f" --type <type> --api-key-stdin",
                    err=True,
                )
            else:
                typer.echo(f"  # set secret for: {s}", err=True)
        raise typer.Exit(code=1)

    actual = ActualState.from_disk()
    cs = compute(doc, actual)

    if cs.is_empty():
        typer.echo("Nothing to apply — all resources unchanged.")
        raise typer.Exit(code=0)

    _print_changeset(cs, dry_run=True)

    if dry_run:
        raise typer.Exit(code=0)

    def emit(action: str, resource: str) -> None:
        stream_action(resource=resource, message=action)

    errors = execute_apply(doc, cs, actual, emit=emit)

    for op in cs.noops:
        typer.echo(f"  {op.kind}/{op.name}  unchanged")

    if errors:
        typer.echo("\nErrors:", err=True)
        for e in errors:
            typer.echo(f"  {e}", err=True)
        raise typer.Exit(code=1)


def _print_changeset(cs, dry_run: bool = False) -> None:
    prefix = "~" if dry_run else " "
    for op in cs.creates:
        action = "would create" if dry_run else "create"
        typer.echo(f"{prefix} {op.kind}/{op.name}  {action}")
    for op in cs.updates:
        detail = f" ({op.details})" if op.details else ""
        action = f"would update{detail}" if dry_run else f"update{detail}"
        typer.echo(f"{prefix} {op.kind}/{op.name}  {action}")
    for aop in cs.attaches:
        action = "would attach" if dry_run else "attach"
        typer.echo(f"{prefix} agent/{aop.agent}  {action} {aop.resource_kind} {aop.resource_name!r}")
    for aop in cs.detaches:
        action = "would detach" if dry_run else "detach"
        typer.echo(f"{prefix} agent/{aop.agent}  {action} {aop.resource_kind} {aop.resource_name!r}")
    for name in cs.starts:
        action = "would start" if dry_run else "start"
        typer.echo(f"{prefix} agent/{name}  {action}")
    for name in cs.restarts:
        action = "would restart" if dry_run else "restart"
        typer.echo(f"{prefix} agent/{name}  {action}")
    for op in cs.noops:
        typer.echo(f"  {op.kind}/{op.name}  unchanged")

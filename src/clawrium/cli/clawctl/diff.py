"""`clawctl diff -f <file|dir>` — preview changes without applying."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from clawrium.cli.output import emit_error


def diff(
    file: Optional[Path] = typer.Option(
        None,
        "--file",
        "-f",
        help="Fleet manifest file or directory.",
    ),
    kustomize: Optional[Path] = typer.Option(
        None,
        "--kustomize",
        "-k",
        help="Directory of manifests (alias for --file with a directory).",
    ),
) -> None:
    """Preview what clawctl apply would change. Exits 1 if changes exist.

    Examples:
        clawctl diff -f fleet.yaml
        clawctl diff -f ./fleet/
    """
    target = file or kustomize
    if not target:
        emit_error("--file/-f is required", hint="clawctl diff -f fleet.yaml")

    target_path = Path(target)
    if not target_path.exists():
        emit_error(f"{target_path}: no such file or directory")

    from clawrium.core.manifest.differ import compute
    from clawrium.core.manifest.parser import parse_directory, parse_file
    from clawrium.core.manifest.state import ActualState
    from clawrium.core.manifest.validator import (
        collect_secret_refs,
        secret_preflight,
        validate_refs,
    )

    try:
        if target_path.is_dir():
            doc = parse_directory(target_path)
        else:
            doc = parse_file(target_path)
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
        typer.echo("Warning: missing secrets (apply would fail):", err=True)
        for s in missing_secrets:
            typer.echo(f"  {s}", err=True)

    actual = ActualState.from_disk()
    cs = compute(doc, actual)

    if cs.is_empty():
        typer.echo("No changes.")
        raise typer.Exit(code=0)

    # Print diff-style output
    for op in cs.creates:
        typer.echo(f"+ {op.kind}/{op.name}  (create)")
    for op in cs.updates:
        detail = f" — {op.details}" if op.details else ""
        typer.echo(f"~ {op.kind}/{op.name}  (update{detail})")
    for aop in cs.attaches:
        typer.echo(f"+ agent/{aop.agent}  {aop.resource_kind} attach {aop.resource_name!r}")
    for aop in cs.detaches:
        typer.echo(f"- agent/{aop.agent}  {aop.resource_kind} detach {aop.resource_name!r}")
    for name in cs.starts:
        typer.echo(f"+ agent/{name}  (start)")
    for name in cs.restarts:
        typer.echo(f"~ agent/{name}  (restart)")
    for op in cs.noops:
        typer.echo(f"  {op.kind}/{op.name}  (unchanged)")

    raise typer.Exit(code=1)  # changes exist → exit 1 (like `git diff`)

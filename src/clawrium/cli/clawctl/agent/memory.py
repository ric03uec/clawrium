"""`clawctl agent memory get|describe|edit|delete` — agent-scoped memory files.

Delegates to `clawrium.core.memory` which already provides the full
read/write/delete surface over Ansible. This module is the modern
flag-driven CLI wrapper.

Non-interactive contract (plan §7):

- `get` lists every memory file for the agent (no flag); `--file F`
  shows the content of a single file.
- `describe <file>` shows per-file metadata (size, relative path).
- `edit <file>` requires `--content "..."` OR `--from-file <path>`
  (the documented file-body exception).
- `delete <file>` requires `--yes` to skip the destructive prompt on
  non-TTY stdin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from clawrium.cli.clawctl._common import (
    OutputFormat,
    confirm_destructive,
    stdin_is_tty,
)
from clawrium.cli.clawctl.agent._shared import safe_resolve_agent
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.core.memory import (
    claw_supports_memory,
    delete_memory_files,
    get_memory_info,
    read_memory_file,
    write_memory_file,
)

__all__ = ["memory_app"]


memory_app = typer.Typer(
    name="memory",
    help="Manage per-agent memory files.",
    no_args_is_help=True,
    add_completion=False,
)


def _resolve_target(agent: str) -> tuple[str, str, str]:
    """Resolve agent name → (hostname, agent_name, claw_type).

    Aborts when the claw type doesn't support memory operations.
    """
    host, agent_type, claw_record = safe_resolve_agent(agent)
    hostname = host["hostname"]
    canonical = claw_record.get("agent_name") or claw_record.get("name") or agent
    if not claw_supports_memory(agent_type):
        emit_error(
            f"agent type {agent_type!r} does not support memory operations",
        )
    return hostname, canonical, agent_type


def _read_from_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError as exc:
        emit_error(f"cannot read --from-file {path!r}: {exc}")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@memory_app.command("get")
def get(
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    file: Optional[str] = typer.Option(
        None, "--file", help="Show content of a specific memory file."
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List memory files (default) or print one file's content (`--file`)."""
    hostname, canonical, _claw_type = _resolve_target(agent)

    if file:
        content = read_memory_file(hostname, canonical, file)
        if content is None:
            emit_error(
                f"memory file {file!r} unavailable on agent {agent!r}",
                hint="agent may be offline or file may not exist",
            )
        typer.echo(content, nl=False)
        return

    info = get_memory_info(hostname, canonical)
    if info is None:
        emit_error(
            f"could not load memory info for agent {agent!r}",
            hint="agent may be offline or memory ops unsupported",
        )

    files = info["files"]
    rows = [
        {
            "kind": "memory",
            "name": entry["name"],
            "size_bytes": entry["size_bytes"],
            "exists": entry["exists"],
            "relative_path": entry["relative_path"],
        }
        for entry in files
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

    headers = ["NAME", "SIZE", "EXISTS"]
    body = [
        [
            str(r["name"]),
            str(r["size_bytes"]) if r["exists"] else "-",
            "yes" if r["exists"] else "no",
        ]
        for r in rows
    ]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


@memory_app.command("describe")
def describe(
    file: str = typer.Argument(..., help="Memory file name."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table|json|yaml)."
    ),
) -> None:
    """Show metadata for a single memory file."""
    hostname, canonical, _claw_type = _resolve_target(agent)
    info = get_memory_info(hostname, canonical)
    if info is None:
        emit_error(
            f"could not load memory info for agent {agent!r}",
            hint="agent may be offline",
        )
    match = None
    for entry in info["files"]:
        if entry["name"] == file or entry["relative_path"] == file:
            match = entry
            break
    if match is None:
        emit_error(
            f"memory file {file!r} not found on agent {agent!r}",
            hint=f"clawctl agent memory get --agent {agent}",
        )
    row = {
        "kind": "memory",
        "name": match["name"],
        "size_bytes": match["size_bytes"],
        "exists": match["exists"],
        "relative_path": match["relative_path"],
        "workspace_path": info.get("workspace_path", ""),
    }
    if output is OutputFormat.json:
        typer.echo(dump_json([row]), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml([row]), nl=False)
        return

    typer.echo(f"Name:            {row['name']}")
    typer.echo("Kind:            memory")
    typer.echo(f"Relative path:   {row['relative_path']}")
    typer.echo(f"Workspace path:  {row['workspace_path'] or '-'}")
    typer.echo(f"Exists:          {'yes' if row['exists'] else 'no'}")
    typer.echo(
        f"Size:            {row['size_bytes']} bytes"
        if row["exists"]
        else "Size:            -"
    )


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@memory_app.command("edit")
def edit(
    file: str = typer.Argument(..., help="Memory file name."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    content: Optional[str] = typer.Option(
        None, "--content", help="Replace file content with this literal value."
    ),
    from_file: Optional[str] = typer.Option(
        None, "--from-file", help="Read replacement content from a file."
    ),
) -> None:
    """Overwrite a memory file's content (non-interactive)."""
    if content is None and from_file is None:
        if not stdin_is_tty():
            emit_error(
                "missing required flag --content or --from-file",
                hint="pass --content '<text>' or --from-file <path>",
            )
        content = typer.prompt(f"New content for {file}")
    if content is not None and from_file is not None:
        emit_error("pass exactly one of --content or --from-file")
    if from_file is not None:
        content = _read_from_file(from_file)
    if content is None:
        emit_error("no content supplied")

    hostname, canonical, _claw_type = _resolve_target(agent)
    success, error = write_memory_file(hostname, canonical, file, content)
    if not success:
        emit_error(f"failed to write memory file {file!r}: {error}")
    typer.echo(f"agent/{canonical}: memory file {file!r} updated")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@memory_app.command("delete")
def delete(
    file: str = typer.Argument(..., help="Memory file name."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a memory file on the agent."""
    confirm_destructive(
        prompt=f"Delete memory file {file!r} from agent {agent!r}?",
        yes=yes,
    )

    hostname, canonical, _claw_type = _resolve_target(agent)
    success, error = delete_memory_files(hostname, canonical, [file])
    if not success:
        emit_error(f"failed to delete memory file {file!r}: {error}")
    typer.echo(f"agent/{canonical}: memory file {file!r} deleted")

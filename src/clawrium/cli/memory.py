"""Memory management commands for memory-capable agents.

Surfaces ``clm agent memory show|delete|edit <name>`` (registered by
``clawrium.cli.agent``). Thin layer over ``clawrium.core.memory`` —
argument parsing, confirmation flows, and human-readable rendering.

Agent support is gated by each claw manifest's ``features.memory: true``
flag; unsupported types receive a friendly error before any Ansible
dispatch happens.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.table import Table

from clawrium.core.hosts import get_host
from clawrium.core.lifecycle import LifecycleError, restart_agent
from clawrium.core.memory import (
    MAX_MEMORY_CONTENT_BYTES,
    claw_supports_memory,
    delete_memory_files,
    get_memory_info,
    read_memory_file,
    write_memory_file,
)
from clawrium.core.secrets import (
    AgentNotFoundError,
    get_installed_claw,
)

__all__ = ["show_cmd", "delete_cmd", "edit_cmd"]

console = Console()


def _stdin_is_tty() -> bool:
    """Return True if stdin is connected to a terminal.

    Wrapped in a module-level helper so tests can monkey-patch the TTY
    check directly — CliRunner swaps ``sys.stdin`` per-invocation, so
    patching ``sys.stdin.isatty`` does not stick across runner.invoke().
    """
    return sys.stdin.isatty()


def _human_size(num_bytes: int) -> str:
    """Render an integer byte count as B / KB / MB. One decimal place."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _resolve_agent_for_memory_cli(claw_name: str) -> tuple[str, str, str]:
    """Resolve agent name to (hostname, unix_agent_name, claw_type) or exit 1.

    Gates memory operations by manifest ``features.memory: true``. Agents
    of types whose manifest does not advertise memory capability receive
    a friendly error before any Ansible dispatch.
    """
    try:
        hostname, claw_type, name = get_installed_claw(claw_name)
    except AgentNotFoundError as e:
        console.print(f"[red]Error:[/red] {rich_escape(str(e))}")
        raise typer.Exit(code=1)

    # `get_installed_claw` now returns the canonical claw type as the
    # second element (sourced from `claw_data["type"]` when present, or
    # the legacy dict key otherwise). `name` is the canonical agent
    # name, which equals the agents-dict key in both legacy and current
    # schemas — use it to look up the record.
    host = get_host(hostname)
    if host is None:
        console.print(
            f"[red]Error:[/red] host '{rich_escape(hostname)}' not found "
            f"in local config."
        )
        raise typer.Exit(code=1)

    # Try both schemas: current (dict keyed by agent name) and legacy
    # (dict keyed by claw type with a single instance per type).
    agents_dict = host.get("agents", {})
    record = agents_dict.get(name) or agents_dict.get(claw_type) or {}
    actual_type = record.get("type") if isinstance(record, dict) else claw_type

    if not isinstance(actual_type, str) or not actual_type:
        console.print(
            f"[red]Error:[/red] agent '{rich_escape(claw_name)}' has no "
            f"recorded type; cannot determine memory support."
        )
        raise typer.Exit(code=1)

    if not claw_supports_memory(actual_type):
        console.print(
            f"[red]Error:[/red] memory operations not supported for "
            f"agent type '{rich_escape(actual_type)}'."
        )
        raise typer.Exit(code=1)

    return hostname, name, actual_type


def show_cmd(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
) -> None:
    """Show memory file paths and sizes for a memory-capable agent."""
    hostname, agent_name, _claw_type = _resolve_agent_for_memory_cli(claw_name)
    safe_claw = rich_escape(claw_name)
    safe_host = rich_escape(hostname)

    info = get_memory_info(hostname, agent_name)
    if info is None:
        console.print(
            f"[yellow]Memory unavailable for '{safe_claw}' on '{safe_host}'.[/yellow]"
        )
        console.print(
            "[dim]The agent may be unreachable, still installing, or in a "
            "failed state. Run 'clm ps' to check status.[/dim]"
        )
        raise typer.Exit(code=1)

    console.print(f"\n[bold]Agent:[/bold] {safe_claw} ({safe_host})")
    console.print(f"[bold]Workspace:[/bold] {rich_escape(info['workspace_path'])}")
    console.print(f"[bold]Total size:[/bold] {_human_size(info['total_bytes'])}\n")

    table = Table(show_header=True, box=None)
    table.add_column("File", style="cyan")
    table.add_column("Status")
    table.add_column("Size", justify="right")

    if not info["files"]:
        console.print("  No memory files.")
        return

    for entry in info["files"]:
        if entry["exists"]:
            status = "[green]present[/green]"
            size = _human_size(entry["size_bytes"])
        else:
            status = "[dim]missing[/dim]"
            size = "-"
        table.add_row(rich_escape(entry["relative_path"]), status, size)

    console.print(table)


def _existing_files(hostname: str, agent_name: str) -> list[str] | None:
    """Return relative paths of all existing memory files, or None on miss."""
    info = get_memory_info(hostname, agent_name)
    if info is None:
        return None
    return [f["relative_path"] for f in info["files"] if f["exists"]]


def delete_cmd(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    file: Optional[str] = typer.Option(
        None,
        "--file",
        help="Single memory file to delete (e.g., SOUL.md or memory/2026-05-09.md).",
    ),
    all_files: bool = typer.Option(
        False,
        "--all",
        help="Delete every memory file. Requires --force and a typed confirmation.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip the per-file confirmation prompt; required gate for --all.",
    ),
) -> None:
    """Delete one memory file or every memory file for the agent.

    --all is gated by --force AND a typed agent-name confirmation. The
    typed confirmation is also TTY-gated so a piped 'yes <name>' cannot
    silently bypass the safeguard.
    """
    if not file and not all_files:
        console.print("[red]Error:[/red] specify either --file <name> or --all.")
        raise typer.Exit(code=1)
    if file and all_files:
        console.print("[red]Error:[/red] --file and --all are mutually exclusive.")
        raise typer.Exit(code=1)

    hostname, agent_name, _claw_type = _resolve_agent_for_memory_cli(claw_name)
    safe_claw = rich_escape(claw_name)

    if all_files:
        if not force:
            console.print(
                "[red]Error:[/red] --all requires --force to acknowledge "
                "the bulk delete."
            )
            raise typer.Exit(code=1)

        if not _stdin_is_tty():
            console.print(
                "[red]Error:[/red] --all --force requires an interactive "
                "TTY for the typed confirmation. Refusing to proceed with "
                "piped input."
            )
            raise typer.Exit(code=1)

        targets = _existing_files(hostname, agent_name)
        if targets is None:
            console.print(
                f"[yellow]Memory unavailable for '{safe_claw}'.[/yellow] "
                "Cannot enumerate files to delete."
            )
            raise typer.Exit(code=1)
        if not targets:
            console.print("No memory files to delete.")
            raise typer.Exit(code=0)

        console.print(
            f"[yellow]About to delete {len(targets)} memory file(s) "
            f"from '{safe_claw}'.[/yellow]"
        )
        for path in targets:
            console.print(f"  - {rich_escape(path)}")

        typed = typer.prompt(
            f"Type the agent name '{claw_name}' to confirm",
            default="",
            show_default=False,
        )
        if typed.strip() != claw_name:
            console.print("Cancelled.")
            raise typer.Exit(code=1)

        ok, err = delete_memory_files(hostname, agent_name, targets)
    else:
        if not force:
            confirmed = typer.confirm(
                f"Delete '{file}' from '{claw_name}'? This cannot be undone."
            )
            if not confirmed:
                console.print("Cancelled.")
                raise typer.Exit(code=0)

        ok, err = delete_memory_files(hostname, agent_name, [file])

    if not ok:
        console.print(f"[red]Error:[/red] {rich_escape(str(err))}")
        raise typer.Exit(code=1)

    if all_files:
        console.print(
            f"[green]Deleted {len(targets)} memory file(s) from '{safe_claw}'.[/green]"
        )
    else:
        console.print(
            f"[green]Deleted '{rich_escape(file)}' from '{safe_claw}'.[/green]"
        )


def _resolve_editor(explicit: str | None) -> list[str]:
    """Resolve editor command to argv list.

    Precedence: explicit (--editor) > $VISUAL > $EDITOR > 'vi'. Parsed
    via shlex.split so flags (e.g. 'code --wait') are preserved without
    invoking a shell.
    """
    raw = explicit or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    parts = shlex.split(raw)
    return parts or ["vi"]


def _run_editor(editor_argv: list[str], file_path: str) -> int:
    """Spawn editor as a child process. Returns exit code.

    Wrapped so tests can patch a single function rather than every
    subprocess.run call site. shell is left at the default (False).
    """
    return subprocess.run([*editor_argv, file_path], check=False).returncode


def _temp_file_dir() -> str | None:
    """Prefer XDG_RUNTIME_DIR when set and writable; else fall back to None.

    Returning None lets tempfile use its platform default.
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg and os.path.isdir(xdg) and os.access(xdg, os.W_OK):
        return xdg
    return None


def _agent_runtime_status(hostname: str, agent_name: str) -> str:
    """Return 'running' / 'stopped' / 'unknown' for an installed agent.

    Reads runtime.status from the local host record. The agents dict may
    be keyed by agent name OR by claw type depending on schema version,
    so fall back to scanning records by their agent_name field.
    """
    host = get_host(hostname)
    if not host:
        return "unknown"
    agents = host.get("agents", {})
    record = agents.get(agent_name)
    if not isinstance(record, dict) or not record:
        for r in agents.values():
            if isinstance(r, dict) and r.get("agent_name") == agent_name:
                record = r
                break
    if not isinstance(record, dict):
        return "unknown"
    runtime = record.get("runtime") or {}
    status = runtime.get("status")
    return status if isinstance(status, str) else "stopped"


def edit_cmd(
    claw_name: str = typer.Argument(..., help="Agent instance name"),
    file: str = typer.Argument(
        ...,
        help="Workspace-relative file (e.g., SOUL.md or memory/2026-05-09.md).",
    ),
    editor: Optional[str] = typer.Option(
        None,
        "--editor",
        help="Editor command. Defaults to $VISUAL, then $EDITOR, then 'vi'.",
    ),
    no_restart: bool = typer.Option(
        False,
        "--no-restart",
        help="Save the edit but skip restarting the agent.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip the restart confirmation prompt.",
    ),
) -> None:
    """Edit a memory file in $EDITOR; sync changes back and restart agent."""
    hostname, agent_name, claw_type = _resolve_agent_for_memory_cli(claw_name)
    safe_claw = rich_escape(claw_name)
    safe_host = rich_escape(hostname)
    safe_file = rich_escape(file)

    original = read_memory_file(hostname, agent_name, file)
    if original is None:
        console.print(
            f"[yellow]Memory unavailable for '{safe_claw}' on '{safe_host}'.[/yellow]"
        )
        console.print(
            "[dim]The agent may be unreachable, still installing, or in a "
            "failed state. Run 'clm ps' to check status.[/dim]"
        )
        raise typer.Exit(code=1)

    original_hash = hashlib.sha256(original.encode("utf-8")).digest()

    suffix = Path(file).suffix
    # mkstemp creates files with mode 0o600 by default on POSIX.
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, dir=_temp_file_dir())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(original)

        exit_code = _run_editor(_resolve_editor(editor), tmp_path)

        if exit_code != 0:
            console.print(f"Editor exited non-zero ({exit_code}). No changes.")
            return

        try:
            new_content = Path(tmp_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            console.print("Edit cancelled (temp file removed).")
            return

        if hashlib.sha256(new_content.encode("utf-8")).digest() == original_hash:
            console.print("No changes.")
            return

        encoded_size = len(new_content.encode("utf-8"))
        if encoded_size > MAX_MEMORY_CONTENT_BYTES:
            console.print(
                f"[red]Error:[/red] edit exceeds maximum size "
                f"({encoded_size} > {MAX_MEMORY_CONTENT_BYTES} bytes). "
                f"Aborted; remote file unchanged."
            )
            raise typer.Exit(code=1)

        ok, err = write_memory_file(hostname, agent_name, file, new_content)
        if not ok:
            console.print(f"[red]Error:[/red] {rich_escape(str(err))}")
            raise typer.Exit(code=1)

        if no_restart:
            console.print(
                f"[green]Saved '{safe_file}' to '{safe_claw}'. "
                f"Skipping restart (--no-restart).[/green]"
            )
            return

        # Skip restart if the agent isn't running. Calling restart_agent
        # here would unintentionally start a stopped agent, since
        # restart = stop (idempotent) + start.
        runtime_status = _agent_runtime_status(hostname, agent_name)
        if runtime_status != "running":
            console.print(
                f"[green]Saved '{safe_file}' to '{safe_claw}'.[/green] "
                f"Agent is {rich_escape(runtime_status)}; new memory takes "
                f"effect on next start."
            )
            return

        if not force:
            if not _stdin_is_tty():
                console.print(
                    "[red]Error:[/red] restart requires either --force or an "
                    "interactive TTY. File saved; agent NOT restarted."
                )
                raise typer.Exit(code=1)

            confirmed = typer.confirm(
                f"Restart agent '{safe_claw}' to apply changes?",
                default=False,
            )
            if not confirmed:
                console.print(
                    f"[green]Saved '{safe_file}' to '{safe_claw}'.[/green] "
                    "Agent not restarted; new memory takes effect on next restart."
                )
                return

        try:
            result = restart_agent(hostname, claw_type, agent_name=agent_name)
        except LifecycleError as e:
            console.print(f"[green]Saved '{safe_file}' to '{safe_claw}'.[/green]")
            console.print(
                f"[red]Error:[/red] restart failed: {rich_escape(str(e))}. "
                f"The agent may now be stopped. Run 'clm agent start "
                f"{safe_claw}' to bring it back up."
            )
            raise typer.Exit(code=1)

        if not result.get("success"):
            console.print(f"[green]Saved '{safe_file}' to '{safe_claw}'.[/green]")
            console.print(
                f"[red]Error:[/red] restart failed: "
                f"{rich_escape(str(result.get('error') or 'unknown'))}. "
                f"The agent may now be stopped. Run 'clm agent start "
                f"{safe_claw}' to bring it back up."
            )
            raise typer.Exit(code=1)

        console.print(
            f"[green]Saved '{safe_file}' to '{safe_claw}' and restarted agent.[/green]"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass

"""`clawctl audit` — operator audit trail for the /clawctl skill.

The audit trail is the operator-side record of every mutating clawctl
operation performed by a human operator or by an AI assistant using the
/clawctl skill. Logs live as one JSONL file per UTC day under
``$XDG_CONFIG_HOME/clawrium/changelog/`` (defaulting to
``~/.config/clawrium/changelog/``). The schema is documented at the top
of ``build_entry`` below.

This module replaces the prior standalone ``scripts/clawctl-audit.py``;
shipping the tool as a clawctl subcommand means anyone with clawctl on
PATH also has ``clawctl audit`` available — there is no separate PATH
plumbing for the /clawctl skill to depend on.
"""

from __future__ import annotations

import json
import os
import re
import uuid as uuidlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

import typer

from clawrium import __version__ as _clawctl_version

__all__ = ["audit_app", "audit_session_app"]


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

_VALID_ACTORS = ("user", "agent")
_VALID_RESULTS = ("success", "failure", "skipped")
_DEFAULT_TYPE = "clawctl_command"
_SCHEMA_VERSION = "1"
_SESSION_ENV_VAR = "CLAWCTL_AUDIT_SESSION_ID"


# ---------------------------------------------------------------------------
# Storage layout
# ---------------------------------------------------------------------------

def _config_root() -> Path:
    """Return the clawrium config root.

    Resolution order:
      1. ``$CLAWRIUM_CONFIG_HOME`` — test/override hook.
      2. ``$XDG_CONFIG_HOME/clawrium`` — Linux convention.
      3. ``~/.config/clawrium`` — default.
    """
    override = os.environ.get("CLAWRIUM_CONFIG_HOME")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "clawrium"


def _log_dir() -> Path:
    return _config_root() / "changelog"


def _log_path_for(dt: datetime) -> Path:
    return _log_dir() / f"{dt.strftime('%Y%m%d')}.jsonl"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso_ms() -> str:
    """ISO 8601 UTC with millisecond precision, e.g. ``2026-06-17T18:23:00.123Z``."""
    now = _utc_now()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Read / write primitives
# ---------------------------------------------------------------------------

def _build_entry(
    *,
    action: str,
    result: str,
    actor: str,
    notes: str = "",
    session_id: Optional[str] = None,
    parent_uuid: Optional[str] = None,
    entry_type: str = _DEFAULT_TYPE,
) -> dict:
    """Construct a schema-v1 entry.

    Required fields (every entry):
      type        -- discriminator; "clawctl_command" today
      uuid        -- uuid4, unique per entry
      parent_uuid -- causal parent's uuid (or None)
      session_id  -- workflow grouping id (or None)
      timestamp   -- ISO 8601 UTC with ms precision
      cwd         -- captured os.getcwd() at write time
      version     -- {"audit": "<schema>", "clawctl": "<clawctl>"}
      actor       -- "user" | "agent"
      action      -- short description / literal command
      result      -- "success" | "failure" | "skipped"
      notes       -- free text; "" allowed
    """
    return {
        "type": entry_type,
        "uuid": str(uuidlib.uuid4()),
        "parent_uuid": parent_uuid,
        "session_id": session_id,
        "timestamp": _utc_now_iso_ms(),
        "cwd": os.getcwd(),
        "version": {
            "audit": _SCHEMA_VERSION,
            "clawctl": _clawctl_version,
        },
        "actor": actor,
        "action": action,
        "result": result,
        "notes": notes or "",
    }


def _append_entry(entry: dict) -> Path:
    target = _log_path_for(_utc_now())
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return target


def _iter_entries(date: Optional[str] = None) -> Iterator[dict]:
    """Yield entries from one day's log, or from every log on disk.

    Malformed lines are silently skipped so a corrupt write never blocks
    reading the rest of the trail.
    """
    root = _log_dir()
    if not root.exists():
        return
    if date:
        files = [root / f"{date}.jsonl"]
    else:
        files = sorted(root.glob("*.jsonl"))
    for f in files:
        if not f.is_file():
            continue
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _format_entry(e: dict) -> str:
    notes = e.get("notes") or ""
    tail = f"  -- {notes}" if notes else ""
    sess = e.get("session_id")
    sess_tag = f" {sess[:8]}" if sess else ""
    return (
        f"{e.get('timestamp', '?'):24s}  "
        f"[{e.get('actor', '?'):5s}]  "
        f"{e.get('result', '?'):7s}  "
        f"{e.get('action', '?')}{sess_tag}{tail}"
    )


def _action_verb(action: str) -> str:
    """Coarse grouping for ``stats`` output.

    Almost every action will start with ``clawctl``, so the leading token
    alone is uninformative. When the action begins with ``clawctl`` we use
    the first two tokens (``clawctl agent``, ``clawctl host``) — the
    granularity an operator usually wants in a summary.
    """
    if not action:
        return "?"
    tokens = action.split()
    if tokens and tokens[0] == "clawctl" and len(tokens) >= 2:
        return f"clawctl {tokens[1]}"
    return tokens[0]


def _filter_entries(entries: Iterator[dict], *,
                    actor: Optional[str],
                    result: Optional[str],
                    session_id: Optional[str],
                    grep: Optional[str],
                    last: Optional[int]) -> List[dict]:
    out = list(entries)
    if actor:
        out = [e for e in out if e.get("actor") == actor]
    if result:
        out = [e for e in out if e.get("result") == result]
    if session_id:
        out = [e for e in out if e.get("session_id") == session_id]
    if grep:
        pat = re.compile(grep)
        def matches(e: dict) -> bool:
            haystack = " ".join([
                str(e.get("action", "")),
                str(e.get("notes", "")),
            ])
            return bool(pat.search(haystack))
        out = [e for e in out if matches(e)]
    if last:
        out = out[-last:]
    return out


# ---------------------------------------------------------------------------
# Typer apps
# ---------------------------------------------------------------------------

audit_app = typer.Typer(
    name="audit",
    help="Operator audit trail for the /clawctl skill.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)

audit_session_app = typer.Typer(
    name="session",
    help="Manage session ids for grouping a workflow's entries.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

@audit_app.command("log", help="Append an entry to today's audit log.")
def log(
    action: str = typer.Argument(..., help="What was done. Include the literal command when relevant."),
    result: str = typer.Option(..., "--result", help="success | failure | skipped", case_sensitive=False),
    actor: str = typer.Option("agent", "--actor", help="user (operator) or agent (you)", case_sensitive=False),
    notes: str = typer.Option("", "--notes", help="Free-text context: errors, prompts, confirmations."),
    session_id: Optional[str] = typer.Option(
        None,
        "--session-id",
        help=f"Group under a session id. Falls back to ${_SESSION_ENV_VAR} when unset.",
    ),
    parent_uuid: Optional[str] = typer.Option(
        None,
        "--parent-uuid",
        help="Causal parent entry's uuid (capture with --print-uuid on the previous log).",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress the 'logged -> path' line."),
    print_uuid: bool = typer.Option(
        False,
        "--print-uuid",
        help="On success print only the new entry's uuid (for chaining via --parent-uuid).",
    ),
) -> None:
    if result not in _VALID_RESULTS:
        typer.echo(f"--result must be one of {_VALID_RESULTS}", err=True)
        raise typer.Exit(code=2)
    if actor not in _VALID_ACTORS:
        typer.echo(f"--actor must be one of {_VALID_ACTORS}", err=True)
        raise typer.Exit(code=2)

    effective_session = session_id or os.environ.get(_SESSION_ENV_VAR) or None
    entry = _build_entry(
        action=action,
        result=result,
        actor=actor,
        notes=notes,
        session_id=effective_session,
        parent_uuid=parent_uuid,
    )
    path = _append_entry(entry)

    if print_uuid:
        typer.echo(entry["uuid"])
        return
    if quiet:
        return
    typer.echo(f"logged -> {path}  uuid={entry['uuid'][:8]}")


@audit_app.command("show", help="Show / filter audit entries.")
def show(
    date: Optional[str] = typer.Option(None, "--date", help="Restrict to a single UTC day (YYYYMMDD)."),
    actor: Optional[str] = typer.Option(None, "--actor", help="Filter by actor."),
    result: Optional[str] = typer.Option(None, "--result", help="Filter by result."),
    session_id: Optional[str] = typer.Option(None, "--session-id", help="Restrict to one session."),
    grep: Optional[str] = typer.Option(None, "--grep", help="Regex matched against action + notes."),
    last: Optional[int] = typer.Option(None, "--last", help="Only the last N matching entries."),
    as_json: bool = typer.Option(False, "--json", help="Emit raw JSONL instead of formatted lines."),
) -> None:
    if actor is not None and actor not in _VALID_ACTORS:
        typer.echo(f"--actor must be one of {_VALID_ACTORS}", err=True)
        raise typer.Exit(code=2)
    if result is not None and result not in _VALID_RESULTS:
        typer.echo(f"--result must be one of {_VALID_RESULTS}", err=True)
        raise typer.Exit(code=2)

    entries = _filter_entries(
        _iter_entries(date),
        actor=actor,
        result=result,
        session_id=session_id,
        grep=grep,
        last=last,
    )
    if as_json:
        for e in entries:
            typer.echo(json.dumps(e, ensure_ascii=False, separators=(",", ":")))
    else:
        for e in entries:
            typer.echo(_format_entry(e))


@audit_app.command("tail", help="Show the last N entries across all days.")
def tail(
    n: int = typer.Option(20, "-n", "--lines", help="Number of entries to show."),
) -> None:
    entries = list(_iter_entries(None))[-n:]
    for e in entries:
        typer.echo(_format_entry(e))


@audit_app.command("stats", help="Summary counts across the full audit history.")
def stats(
    top: int = typer.Option(10, "--top", help="Top N action groups by frequency."),
) -> None:
    actor_count: Counter = Counter()
    result_count: Counter = Counter()
    verb_count: Counter = Counter()
    days: set = set()
    sessions: set = set()
    total = 0
    for e in _iter_entries(None):
        total += 1
        actor_count[e.get("actor", "?")] += 1
        result_count[e.get("result", "?")] += 1
        verb_count[_action_verb(e.get("action", "") or "")] += 1
        ts = e.get("timestamp", "")
        if len(ts) >= 10:
            days.add(ts[:10])
        sid = e.get("session_id")
        if sid:
            sessions.add(sid)

    typer.echo(f"Total entries:     {total}")
    typer.echo(f"Distinct days:     {len(days)}")
    typer.echo(f"Distinct sessions: {len(sessions)}")
    typer.echo(f"By actor:          {dict(actor_count)}")
    typer.echo(f"By result:         {dict(result_count)}")
    if top and verb_count:
        typer.echo(f"Top {top} action groups:")
        for verb, n in verb_count.most_common(top):
            typer.echo(f"  {n:5d}  {verb}")


@audit_app.command("path", help="Print the log directory path.")
def path() -> None:
    typer.echo(str(_log_dir()))


@audit_session_app.command("new", help="Mint a new uuid4 session id and print it.")
def session_new() -> None:
    typer.echo(str(uuidlib.uuid4()))


audit_app.add_typer(audit_session_app, name="session")

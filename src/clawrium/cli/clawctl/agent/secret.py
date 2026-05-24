"""`clawctl agent secret create|get|describe|delete|import` — agent-scoped secrets.

Agent secrets live in `~/.config/clawrium/secrets.json` under the
instance key `host:claw_type:claw_name`, managed by
`clawrium.core.secrets`. This module is the modern flag-driven CLI
on top of those primitives.

Non-interactive contract (plan §7):

- `create` requires `--value`, `--value-stdin`, OR `--from-file <path>`.
- `import` requires `--from-file <path>` (a `KEY=VALUE` per line file).
- `get` lists keys for one agent (never prints values).
- `describe` shows metadata (description, timestamps) for one secret.
- `delete` requires `--yes` to skip the destructive-action prompt on
  non-TTY stdin.

The `--from-file` option is the documented exception to "no
`--from-file` for normal config" per plan §7.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from clawrium.cli.clawctl._common import (
    OutputFormat,
    confirm_destructive,
    stdin_is_tty,
)
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.core.secrets import (
    AgentNotFoundError,
    InvalidSecretKeyError,
    SecretsFileCorruptedError,
    get_installed_claw,
    get_instance_key,
    get_instance_secrets,
    remove_instance_secret,
    set_instance_secret,
)

__all__ = ["secret_app"]


secret_app = typer.Typer(
    name="secret",
    help="Manage per-agent secrets.",
    no_args_is_help=True,
    add_completion=False,
)


def _resolve_instance_key(agent: str) -> tuple[str, str]:
    """Resolve an agent name to (instance_key, canonical_name)."""
    try:
        hostname, claw_type, name = get_installed_claw(agent)
    except AgentNotFoundError as exc:
        emit_error(str(exc), hint="clawctl agent get")
    return get_instance_key(hostname, claw_type, name), name


def _read_value_from_stdin(flag: str) -> str:
    data = sys.stdin.read()
    if data == "":
        emit_error(
            f"empty stdin for {flag}",
            hint=f"pipe a value into {flag}",
        )
    # Preserve internal whitespace; only strip a trailing newline.
    if data.endswith("\n"):
        data = data[:-1]
    return data


def _read_from_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError as exc:
        emit_error(f"cannot read --from-file {path!r}: {exc}")


def _parse_env_file(text: str) -> dict[str, str]:
    """Parse a `.env`-style file body into a `KEY=VALUE` dict.

    Blank lines and `#` comment lines are skipped. Lines that don't
    contain `=` raise via `emit_error`.
    """
    out: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            emit_error(
                f"invalid env file line {lineno}: {raw!r}",
                hint="expected KEY=VALUE",
            )
        key, _, value = line.partition("=")
        key = key.strip()
        # Strip surrounding quotes from value (a courtesy that mirrors
        # most `.env` parsers).
        value = value.strip()
        if (value.startswith("'") and value.endswith("'")) or (
            value.startswith('"') and value.endswith('"')
        ):
            value = value[1:-1]
        if not key:
            emit_error(
                f"invalid env file line {lineno}: {raw!r}",
                hint="empty key",
            )
        out[key] = value
    return out


def _secret_to_row(entry: dict) -> dict:
    return {
        "kind": "secret",
        "name": entry.get("key", ""),
        "description": entry.get("description", ""),
        "created_at": entry.get("created_at"),
        "updated_at": entry.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@secret_app.command("create")
def create(
    key: str = typer.Argument(..., help="Secret key (e.g. OPENAI_API_KEY)."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    value: Optional[str] = typer.Option(None, "--value", help="Secret value."),
    value_stdin: bool = typer.Option(
        False, "--value-stdin", help="Read secret value from stdin."
    ),
    from_file: Optional[str] = typer.Option(
        None, "--from-file", help="Read secret value from a file."
    ),
    description: Optional[str] = typer.Option(
        None, "--description", help="Optional human-readable description."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip overwrite confirmation if key exists."
    ),
) -> None:
    """Create or overwrite a per-agent secret."""
    sources = [bool(value), value_stdin, bool(from_file)]
    chosen = sum(sources)
    if chosen > 1:
        emit_error(
            "pass exactly one of --value / --value-stdin / --from-file",
        )
    if chosen == 0:
        if not stdin_is_tty():
            emit_error(
                "missing required flag --value",
                hint="pass --value / --value-stdin / --from-file",
            )
        value = typer.prompt(f"Value for {key}", hide_input=True)

    if value_stdin:
        value = _read_value_from_stdin("--value-stdin")
    elif from_file:
        value = _read_from_file(from_file)

    if not value:
        emit_error("secret value cannot be empty")

    instance_key, canonical = _resolve_instance_key(agent)

    try:
        existing = get_instance_secrets(instance_key)
    except SecretsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/secrets.json")

    if key in existing and not yes:
        confirm_destructive(
            prompt=f"Secret {key!r} exists on agent {agent!r}. Overwrite?",
            yes=yes,
        )

    try:
        created = set_instance_secret(instance_key, key, value, description or "")
    except InvalidSecretKeyError as exc:
        emit_error(
            str(exc),
            hint="Keys must be uppercase letters, digits, and underscores",
        )

    action = "created" if created else "updated"
    typer.echo(f"agent/{canonical}: secret {key!r} {action}")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@secret_app.command("get")
def get(
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List secret keys for an agent. Values are NEVER displayed."""
    instance_key, _ = _resolve_instance_key(agent)

    try:
        entries = get_instance_secrets(instance_key)
    except SecretsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/secrets.json")

    rows = [_secret_to_row(entries[k]) for k in sorted(entries.keys())]

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return
    if output is OutputFormat.name:
        typer.echo(dump_name(rows), nl=False)
        return

    headers = ["KEY", "DESCRIPTION", "UPDATED"]
    body = [
        [
            str(r["name"]),
            str(r["description"] or "-"),
            (str(r["updated_at"] or "").split("T")[0] or "-"),
        ]
        for r in rows
    ]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


@secret_app.command("describe")
def describe(
    key: str = typer.Argument(..., help="Secret key."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table|json|yaml)."
    ),
) -> None:
    """Show metadata for one secret (value is never printed)."""
    instance_key, canonical = _resolve_instance_key(agent)
    try:
        entries = get_instance_secrets(instance_key)
    except SecretsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/secrets.json")
    if key not in entries:
        emit_error(
            f"secret {key!r} not found on agent {canonical!r}",
            hint=f"clawctl agent secret get --agent {agent}",
        )
    row = _secret_to_row(entries[key])

    if output is OutputFormat.json:
        typer.echo(dump_json([row]), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml([row]), nl=False)
        return

    typer.echo(f"Key:          {row['name']}")
    typer.echo("Kind:         secret")
    typer.echo(f"Description:  {row['description'] or '-'}")
    if row.get("created_at"):
        typer.echo(f"Created:      {row['created_at']}")
    if row.get("updated_at"):
        typer.echo(f"Updated:      {row['updated_at']}")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@secret_app.command("delete")
def delete(
    key: str = typer.Argument(..., help="Secret key."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a per-agent secret."""
    instance_key, canonical = _resolve_instance_key(agent)
    try:
        entries = get_instance_secrets(instance_key)
    except SecretsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/secrets.json")
    if key not in entries:
        emit_error(
            f"secret {key!r} not found on agent {canonical!r}",
            hint=f"clawctl agent secret get --agent {agent}",
        )

    confirm_destructive(
        prompt=f"Delete secret {key!r} on agent {agent!r}?",
        yes=yes,
    )

    try:
        removed = remove_instance_secret(instance_key, key)
    except InvalidSecretKeyError as exc:
        emit_error(str(exc))
    if not removed:
        emit_error(f"failed to delete secret {key!r}")
    typer.echo(f"agent/{canonical}: secret {key!r} deleted")


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


@secret_app.command("import")
def import_cmd(
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    from_file: str = typer.Option(
        ..., "--from-file", help="Path to a KEY=VALUE-per-line file (.env)."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip overwrite confirmation for existing keys."
    ),
) -> None:
    """Bulk-import secrets from a .env-style file."""
    text = _read_from_file(from_file)
    pairs = _parse_env_file(text)
    if not pairs:
        emit_error(
            f"no KEY=VALUE pairs found in {from_file!r}",
            hint="file must contain at least one non-empty, non-comment line",
        )

    instance_key, canonical = _resolve_instance_key(agent)
    try:
        existing = get_instance_secrets(instance_key)
    except SecretsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/secrets.json")
    overlap = sorted(set(existing.keys()) & set(pairs.keys()))
    if overlap and not yes:
        confirm_destructive(
            prompt=(
                f"Overwrite {len(overlap)} existing secret(s) on {agent!r}: "
                f"{', '.join(overlap[:5])}"
                + (f" and {len(overlap) - 5} more" if len(overlap) > 5 else "")
                + "?"
            ),
            yes=yes,
        )

    created = 0
    updated = 0
    for key, value in pairs.items():
        try:
            was_new = set_instance_secret(instance_key, key, value, "")
        except InvalidSecretKeyError as exc:
            emit_error(
                f"invalid secret key {key!r}: {exc}",
                hint="Keys must be uppercase letters, digits, and underscores",
            )
        if was_new:
            created += 1
        else:
            updated += 1
    typer.echo(
        f"agent/{canonical}: imported secrets (created={created} updated={updated})"
    )

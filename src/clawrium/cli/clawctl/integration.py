"""`clawctl integration` — Pattern A attachable (Bundle 4 / #509).

`integration registry` is the ONLY CRUD entrypoint for external-service
integrations (GitHub, Atlassian, Linear, …). Per-agent
`attach/detach/get` lives under `clawctl agent integration`.

Storage layer is `clawrium.core.integrations` (untouched per plan §2
guardrail).

Non-interactive contract (plan §7):

- `--type` is always required.
- Credentials are provided as repeated `--credential KEY=VALUE`
  pairs, OR via `--credential-stdin` (one `KEY=VALUE` per line).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Optional

import typer

from clawrium.cli.clawctl._common import (
    OutputFormat,
    confirm_destructive,
    now_seconds_since,
)
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.core.integrations import (
    DuplicateIntegrationError,
    INTEGRATION_TYPES,
    IntegrationInUseError,
    IntegrationsFileCorruptedError,
    InvalidIntegrationNameError,
    InvalidIntegrationTypeError,
    add_integration,
    get_credentials_for_type,
    get_integration,
    get_integration_credentials,
    load_integrations,
    remove_integration,
    remove_integration_credentials,
    set_integration_credential,
    update_integration,
    validate_integration_name,
    validate_integration_type,
)

__all__ = ["integration_app"]


integration_app = typer.Typer(
    name="integration",
    help="External service integrations (Pattern A attachable).",
    no_args_is_help=True,
    add_completion=False,
)

integration_registry_app = typer.Typer(
    name="registry",
    help="CRUD entrypoint for the integration registry.",
    no_args_is_help=True,
    add_completion=False,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_load_integrations() -> list[dict]:
    try:
        return load_integrations()
    except IntegrationsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/integrations.json")


def _safe_get_integration(name: str) -> dict:
    try:
        record = get_integration(name)
    except IntegrationsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/integrations.json")
    if not record:
        emit_error(
            f"integration {name!r} not found",
            hint="clawctl integration registry get",
        )
    return record  # type: ignore[return-value]


def _parse_credential_pairs(items: list[str], *, source: str) -> dict[str, str]:
    """Parse KEY=VALUE entries from CLI flags or stdin.

    ATX iter-2 W-NEW-2: error messages must never echo the raw entry
    once it has been split, because the VALUE half is the credential.
    Empty-key entries (`=VALUE`) previously surfaced `repr(raw)` to
    stderr — which lands in shell logs, CI logs, and crash reporters
    verbatim. We now report the malformed structure without
    interpolating the secret.
    """
    out: dict[str, str] = {}
    for raw in items:
        if "=" not in raw:
            emit_error(
                f"invalid credential from {source}: missing '='",
                hint="expected KEY=VALUE",
            )
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            emit_error(
                f"invalid credential from {source}: key is empty",
                hint="expected KEY=VALUE",
            )
        out[key] = value
    return out


def _resolve_credentials(
    credentials: Optional[list[str]],
    credential_stdin: bool,
) -> dict[str, str]:
    if credentials and credential_stdin:
        emit_error(
            "cannot combine --credential with --credential-stdin",
            hint="pass exactly one",
        )
    if credentials:
        return _parse_credential_pairs(credentials, source="--credential")
    if credential_stdin:
        lines = [line for line in sys.stdin.read().splitlines() if line.strip()]
        if not lines:
            emit_error(
                "empty stdin for --credential-stdin",
                hint="provide one KEY=VALUE per line",
            )
        return _parse_credential_pairs(lines, source="stdin")
    return {}


def _integration_to_row(record: dict) -> dict:
    name = record.get("name", "")
    itype = record.get("type", "")
    stored = get_integration_credentials(name)
    required = {
        c["key"]
        for c in (INTEGRATION_TYPES.get(itype, {}).get("credentials") or [])
        if c.get("required")
    }
    missing = sorted(required - set(stored.keys()))
    creds_status = "configured" if not missing else f"missing: {','.join(missing)}"
    return {
        "kind": "integration",
        "name": name,
        "type": itype,
        "credentials": creds_status,
        "credential_keys": sorted(stored.keys()),
        "age_seconds": now_seconds_since(record.get("created_at")),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@integration_registry_app.command("create")
def create(
    name: str = typer.Argument(..., help="Unique integration name."),
    integration_type: str = typer.Option(
        ..., "--type", "-t", help="Integration type (github, atlassian, ...)."
    ),
    credentials: Optional[list[str]] = typer.Option(
        None,
        "--credential",
        help="Credential as KEY=VALUE. Repeatable.",
    ),
    credential_stdin: bool = typer.Option(
        False, "--credential-stdin", help="Read KEY=VALUE per line from stdin."
    ),
) -> None:
    """Register an integration non-interactively when flags are supplied."""
    try:
        validate_integration_name(name)
    except InvalidIntegrationNameError as exc:
        emit_error(str(exc))
    try:
        validate_integration_type(integration_type)
    except InvalidIntegrationTypeError as exc:
        emit_error(str(exc))

    try:
        if get_integration(name):
            emit_error(
                f"integration {name!r} already exists",
                hint="clawctl integration registry describe " + name,
            )
    except IntegrationsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/integrations.json")

    creds = _resolve_credentials(credentials, credential_stdin)

    # ATX iter-2 W5: required-credential enforcement now applies on
    # both TTY and non-TTY paths. The previous gate was non-TTY-only,
    # which let an interactive user create a github integration with
    # zero credentials and exit 0 — leaving a broken record behind.
    required_keys = [
        c["key"]
        for c in get_credentials_for_type(integration_type)
        if c.get("required")
    ]
    missing = [k for k in required_keys if k not in creds]
    if missing:
        emit_error(
            f"missing required credential keys for {integration_type!r}: {', '.join(missing)}",
            hint="pass --credential KEY=VALUE for each missing key",
        )

    record = {
        "name": name,
        "type": integration_type,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    try:
        add_integration(record)
    except DuplicateIntegrationError as exc:
        emit_error(str(exc))
    except (InvalidIntegrationNameError, InvalidIntegrationTypeError) as exc:
        emit_error(str(exc))

    for key, value in creds.items():
        set_integration_credential(name, key, value)

    typer.echo(f"integration/{name}: created (type={integration_type})")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@integration_registry_app.command("get")
def get(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    types: bool = typer.Option(
        False, "--types", help="List supported integration types (catalog)."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List registered integrations (or supported types with `--types`)."""
    if types:
        _emit_types(output, no_headers=no_headers)
        return

    rows = [_integration_to_row(i) for i in _safe_load_integrations()]

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return
    if output is OutputFormat.name:
        typer.echo(dump_name(rows), nl=False)
        return

    headers = ["NAME", "TYPE", "CREDENTIALS"]
    body = [[str(r["name"]), str(r["type"]), str(r["credentials"])] for r in rows]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


def _emit_types(output: OutputFormat, *, no_headers: bool) -> None:
    rows = [
        {
            "kind": "integration-type",
            "name": itype,
            "description": cfg.get("description", ""),
            "credentials": [c["key"] for c in cfg.get("credentials", [])],
        }
        for itype, cfg in sorted(INTEGRATION_TYPES.items())
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
    headers = ["NAME", "DESCRIPTION", "CREDENTIAL-KEYS"]
    body = [
        [
            str(r["name"]),
            str(r["description"] or "-"),
            ",".join(r["credentials"]) or "-",
        ]
        for r in rows
    ]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


@integration_registry_app.command("describe")
def describe(
    name: str = typer.Argument(..., help="Integration name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table|json|yaml)."
    ),
) -> None:
    """Show full details of a registered integration."""
    record = _safe_get_integration(name)
    row = _integration_to_row(record)

    if output is OutputFormat.json:
        typer.echo(dump_json([row]), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml([row]), nl=False)
        return

    typer.echo(f"Name:            {row['name']}")
    typer.echo("Kind:            integration")
    typer.echo(f"Type:            {row['type']}")
    typer.echo(f"Credentials:     {row['credentials']}")
    if row["credential_keys"]:
        typer.echo(f"Credential keys: {', '.join(row['credential_keys'])}")
    if row.get("created_at"):
        typer.echo(f"Created:         {row['created_at']}")
    if row.get("updated_at"):
        typer.echo(f"Updated:         {row['updated_at']}")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@integration_registry_app.command("delete")
def delete(
    name: str = typer.Argument(..., help="Integration name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    force: bool = typer.Option(
        False, "--force", help="Delete even if attached to agents."
    ),
) -> None:
    """Delete an integration and its stored credentials."""
    _safe_get_integration(name)
    confirm_destructive(prompt=f"Delete integration {name!r}?", yes=yes)
    try:
        removed = remove_integration(name, force=force)
    except IntegrationInUseError as exc:
        emit_error(str(exc), hint="--force to delete anyway")
    if not removed:
        emit_error(f"failed to delete integration {name!r}")
    # remove_integration already clears credentials on success, but if
    # the caller used force=True past in-use detection, ensure cleanup.
    remove_integration_credentials(name)
    typer.echo(f"integration/{name}: deleted")


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@integration_registry_app.command("edit")
def edit(
    name: str = typer.Argument(..., help="Integration name."),
    credentials: Optional[list[str]] = typer.Option(
        None,
        "--credential",
        help="Set credential KEY=VALUE. Repeatable.",
    ),
    credential_stdin: bool = typer.Option(
        False, "--credential-stdin", help="Read KEY=VALUE per line from stdin."
    ),
) -> None:
    """Edit credentials on an existing integration."""
    _safe_get_integration(name)
    creds = _resolve_credentials(credentials, credential_stdin)
    if not creds:
        emit_error(
            "no changes specified",
            hint="pass --credential KEY=VALUE or --credential-stdin",
        )

    def apply(rec: dict) -> dict:
        rec["updated_at"] = _now_iso()
        return rec

    if not update_integration(name, apply):
        emit_error(f"failed to update integration {name!r}")

    for key, value in creds.items():
        set_integration_credential(name, key, value)

    typer.echo(f"integration/{name}: updated ({len(creds)} credential(s) set)")


# Register sub-group on the top-level `integration` app.
integration_app.add_typer(integration_registry_app, name="registry")

"""`clawctl channel` — Pattern A attachable (NEW noun; Bundle 4 / #509).

`channel registry` is the ONLY CRUD entrypoint for chat-surface
records (Discord, Slack). Per-agent `attach/detach/get` lives under
`clawctl agent channel`.

Storage layer is `clawrium.core.channels` — the one deliberate
`clawrium.core.*` addition introduced by this bundle (see plan §8 and
the PR description for the Risk R1 disclosure).

Non-interactive contract (plan §7):

- `--type` is always required (`discord` or `slack`).
- `--token` OR `--token-stdin` is required.
- All other flags (`--allowed-user`, `--allowed-channel`,
  `--allowed-guild`, `--home-channel`, `--require-mention`,
  `--stream-mode`, `--stream-delay`) are optional.
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
    stdin_is_tty,
)
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.core.channels import (
    ChannelInUseError,
    ChannelsFileCorruptedError,
    DuplicateChannelError,
    InvalidChannelNameError,
    InvalidChannelTypeError,
    InvalidStreamModeError,
    add_channel,
    get_channel,
    get_channel_token,
    load_channels,
    remove_channel,
    set_channel_token,
    update_channel,
    validate_channel_name,
    validate_channel_type,
    validate_stream_mode,
)

__all__ = ["channel_app"]


channel_app = typer.Typer(
    name="channel",
    help="Chat surfaces (Discord, Slack) (Pattern A attachable).",
    no_args_is_help=True,
    add_completion=False,
)

channel_registry_app = typer.Typer(
    name="registry",
    help="CRUD entrypoint for the channel registry.",
    no_args_is_help=True,
    add_completion=False,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_load_channels() -> list[dict]:
    try:
        return load_channels()
    except ChannelsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/channels.json")


def _safe_get_channel(name: str) -> dict:
    try:
        record = get_channel(name)
    except ChannelsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/channels.json")
    if not record:
        emit_error(
            f"channel {name!r} not found",
            hint="clawctl channel registry get",
        )
    return record  # type: ignore[return-value]


def _read_token_from_stdin(flag: str) -> str:
    data = sys.stdin.read()
    value = data.strip("\n").rstrip("\r")
    if not value:
        emit_error(
            f"empty value on stdin for {flag}",
            hint=f"pipe a non-empty value into {flag}",
        )
    return value


def _resolve_token(
    token: Optional[str],
    token_stdin: bool,
    *,
    flag: str = "--token",
    stdin_flag: str = "--token-stdin",
    required: bool = True,
) -> Optional[str]:
    if token and token_stdin:
        emit_error(
            f"cannot combine {flag} with {stdin_flag}",
            hint="pass exactly one",
        )
    if token_stdin:
        return _read_token_from_stdin(stdin_flag)
    if token:
        return token
    if not required:
        return None
    if not stdin_is_tty():
        emit_error(
            f"missing required flag {flag}",
            hint=f"pass {flag} or {stdin_flag}",
        )
    return typer.prompt(flag.lstrip("-").replace("-", " "), hide_input=True)


def _channel_to_row(record: dict) -> dict:
    cfg = record.get("config", {}) or {}
    name = record.get("name", "")
    has_token = get_channel_token(name, "BOT_TOKEN") is not None
    has_app_token = get_channel_token(name, "APP_TOKEN") is not None
    return {
        "kind": "channel",
        "name": name,
        "type": record.get("type", ""),
        "allowed_users": cfg.get("allowed_users", []) or [],
        "allowed_channels": cfg.get("allowed_channels", []) or [],
        "allowed_guilds": cfg.get("allowed_guilds", []) or [],
        "home_channel": cfg.get("home_channel"),
        "require_mention": cfg.get("require_mention"),
        "stream_mode": cfg.get("stream_mode"),
        "stream_delay_ms": cfg.get("stream_delay_ms"),
        "credentials": "set" if has_token else "unset",
        "app_token": "set" if has_app_token else "unset",
        "age_seconds": now_seconds_since(record.get("created_at")),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _build_config(
    *,
    channel_type: str,
    allowed_users: Optional[list[str]],
    allowed_channels: Optional[list[str]],
    allowed_guilds: Optional[list[str]],
    home_channel: Optional[str],
    require_mention: Optional[bool],
    stream_mode: Optional[str],
    stream_delay: Optional[int],
) -> dict:
    cfg: dict = {}
    if allowed_users:
        cfg["allowed_users"] = list(allowed_users)
    if allowed_channels:
        cfg["allowed_channels"] = list(allowed_channels)
    if allowed_guilds:
        if channel_type != "discord":
            emit_error(
                f"--allowed-guild only valid for discord channels (got {channel_type!r})"
            )
        cfg["allowed_guilds"] = list(allowed_guilds)
    if home_channel is not None:
        cfg["home_channel"] = home_channel
    if require_mention is not None:
        cfg["require_mention"] = require_mention
    if stream_mode is not None:
        try:
            validate_stream_mode(stream_mode)
        except InvalidStreamModeError as exc:
            emit_error(str(exc))
        cfg["stream_mode"] = stream_mode
    if stream_delay is not None:
        if stream_delay < 0:
            emit_error("--stream-delay must be >= 0")
        cfg["stream_delay_ms"] = stream_delay
    return cfg


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@channel_registry_app.command("create")
def create(
    name: str = typer.Argument(..., help="Unique channel name."),
    channel_type: str = typer.Option(
        ..., "--type", "-t", help="Channel type: discord | slack."
    ),
    token: Optional[str] = typer.Option(None, "--token", help="Bot token."),
    token_stdin: bool = typer.Option(
        False, "--token-stdin", help="Read bot token from stdin."
    ),
    app_token: Optional[str] = typer.Option(
        None, "--app-token", help="Slack app-level token (Slack only)."
    ),
    allowed_users: Optional[list[str]] = typer.Option(
        None, "--allowed-user", help="Allowed user ID. Repeatable."
    ),
    allowed_channels: Optional[list[str]] = typer.Option(
        None, "--allowed-channel", help="Allowed channel ID. Repeatable."
    ),
    allowed_guilds: Optional[list[str]] = typer.Option(
        None, "--allowed-guild", help="Allowed guild ID (Discord). Repeatable."
    ),
    home_channel: Optional[str] = typer.Option(
        None, "--home-channel", help="Default channel ID (Slack)."
    ),
    require_mention: Optional[bool] = typer.Option(
        None,
        "--require-mention/--no-require-mention",
        help="Only reply when mentioned.",
    ),
    stream_mode: Optional[str] = typer.Option(
        None, "--stream-mode", help="Streaming mode: replace | append."
    ),
    stream_delay: Optional[int] = typer.Option(
        None, "--stream-delay", help="Streaming delay in milliseconds."
    ),
) -> None:
    """Register a new chat channel non-interactively when flags are supplied."""
    try:
        validate_channel_name(name)
    except InvalidChannelNameError as exc:
        emit_error(str(exc))
    try:
        validate_channel_type(channel_type)
    except InvalidChannelTypeError as exc:
        emit_error(str(exc))

    try:
        if get_channel(name):
            emit_error(
                f"channel {name!r} already exists",
                hint="clawctl channel registry describe " + name,
            )
    except ChannelsFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/channels.json")

    # `_resolve_token` does the non-interactive-contract check itself
    # (fails fast on non-TTY when neither --token nor --token-stdin is
    # supplied). A redundant `require_flag` here would emit the wrong
    # hint, so we trust `_resolve_token` to surface the missing-flag
    # error.
    bot_token = _resolve_token(token, token_stdin)

    if app_token and channel_type != "slack":
        emit_error(f"--app-token only valid for slack channels (got {channel_type!r})")

    if home_channel and channel_type != "slack":
        emit_error(
            f"--home-channel only valid for slack channels (got {channel_type!r})"
        )

    cfg = _build_config(
        channel_type=channel_type,
        allowed_users=allowed_users,
        allowed_channels=allowed_channels,
        allowed_guilds=allowed_guilds,
        home_channel=home_channel,
        require_mention=require_mention,
        stream_mode=stream_mode,
        stream_delay=stream_delay,
    )

    record = {
        "name": name,
        "type": channel_type,
        "config": cfg,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    try:
        add_channel(record)
    except DuplicateChannelError as exc:
        emit_error(str(exc))
    except (
        InvalidChannelNameError,
        InvalidChannelTypeError,
        InvalidStreamModeError,
    ) as exc:
        emit_error(str(exc))

    # Credentials are written *after* the record so a duplicate-name
    # collision earlier cannot orphan a secret in the secrets store.
    if bot_token:
        set_channel_token(name, "BOT_TOKEN", bot_token)
    if app_token:
        set_channel_token(name, "APP_TOKEN", app_token)

    typer.echo(f"channel/{name}: created (type={channel_type})")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@channel_registry_app.command("get")
def get(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List registered channels."""
    rows = [_channel_to_row(c) for c in _safe_load_channels()]

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return
    if output is OutputFormat.name:
        typer.echo(dump_name(rows), nl=False)
        return

    if output is OutputFormat.wide:
        headers = [
            "NAME",
            "TYPE",
            "CREDENTIALS",
            "ALLOWED-USERS",
            "ALLOWED-CHANNELS",
            "STREAM-MODE",
        ]
        body = [
            [
                str(r["name"]),
                str(r["type"]),
                str(r["credentials"]),
                str(len(r["allowed_users"]) or "-"),
                str(len(r["allowed_channels"]) or "-"),
                str(r["stream_mode"] or "-"),
            ]
            for r in rows
        ]
    else:
        headers = ["NAME", "TYPE", "CREDENTIALS"]
        body = [[str(r["name"]), str(r["type"]), str(r["credentials"])] for r in rows]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


@channel_registry_app.command("describe")
def describe(
    name: str = typer.Argument(..., help="Channel name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table|json|yaml)."
    ),
) -> None:
    """Show full details of a registered channel."""
    record = _safe_get_channel(name)
    row = _channel_to_row(record)

    if output is OutputFormat.json:
        typer.echo(dump_json([row]), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml([row]), nl=False)
        return

    typer.echo(f"Name:             {row['name']}")
    typer.echo("Kind:             channel")
    typer.echo(f"Type:             {row['type']}")
    typer.echo(f"Credentials:      {row['credentials']}")
    if row["type"] == "slack":
        typer.echo(f"App token:        {row['app_token']}")
    if row["allowed_users"]:
        typer.echo(f"Allowed users:    {', '.join(row['allowed_users'])}")
    if row["allowed_channels"]:
        typer.echo(f"Allowed channels: {', '.join(row['allowed_channels'])}")
    if row["allowed_guilds"]:
        typer.echo(f"Allowed guilds:   {', '.join(row['allowed_guilds'])}")
    if row.get("home_channel"):
        typer.echo(f"Home channel:     {row['home_channel']}")
    if row.get("require_mention") is not None:
        typer.echo(f"Require mention:  {row['require_mention']}")
    if row.get("stream_mode"):
        typer.echo(f"Stream mode:      {row['stream_mode']}")
    if row.get("stream_delay_ms") is not None:
        typer.echo(f"Stream delay ms:  {row['stream_delay_ms']}")
    if row.get("created_at"):
        typer.echo(f"Created:          {row['created_at']}")
    if row.get("updated_at"):
        typer.echo(f"Updated:          {row['updated_at']}")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@channel_registry_app.command("delete")
def delete(
    name: str = typer.Argument(..., help="Channel name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    force: bool = typer.Option(
        False, "--force", help="Delete even if still attached to agents."
    ),
) -> None:
    """Delete a channel record and its stored token(s)."""
    _safe_get_channel(name)
    confirm_destructive(prompt=f"Delete channel {name!r}?", yes=yes)
    try:
        removed = remove_channel(name, force=force)
    except ChannelInUseError as exc:
        emit_error(str(exc), hint="--force to delete anyway")
    except OSError as exc:
        # ATX iter-2 W-NEW-3: `remove_channel` clears credentials
        # *before* the atomic channels.json write. An OSError there
        # (disk full, EROFS, EACCES) leaves the channel record
        # present but with credentials gone — a zombie record. Catch
        # the OSError here so the user sees an actionable error
        # rather than a raw Python traceback; the only safe recovery
        # is `delete --force` which skips the in-use re-check.
        emit_error(
            (
                f"failed to delete channel {name!r}: {exc}. The channel "
                "is now in a zombie state (record present, credentials "
                "gone) — re-run with --force to complete removal."
            ),
            hint=f"clawctl channel registry delete {name} --yes --force",
        )
    if not removed:
        emit_error(f"failed to delete channel {name!r}")
    typer.echo(f"channel/{name}: deleted")


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@channel_registry_app.command("edit")
def edit(
    name: str = typer.Argument(..., help="Channel name."),
    token: Optional[str] = typer.Option(None, "--token", help="New bot token."),
    token_stdin: bool = typer.Option(
        False, "--token-stdin", help="Read new bot token from stdin."
    ),
    app_token: Optional[str] = typer.Option(
        None, "--app-token", help="New Slack app token (Slack only)."
    ),
    allowed_users: Optional[list[str]] = typer.Option(
        None, "--allowed-user", help="Replace allowed user IDs. Repeatable."
    ),
    allowed_channels: Optional[list[str]] = typer.Option(
        None, "--allowed-channel", help="Replace allowed channel IDs. Repeatable."
    ),
    allowed_guilds: Optional[list[str]] = typer.Option(
        None, "--allowed-guild", help="Replace allowed guild IDs (Discord). Repeatable."
    ),
    home_channel: Optional[str] = typer.Option(
        None, "--home-channel", help="New default channel (Slack)."
    ),
    require_mention: Optional[bool] = typer.Option(
        None,
        "--require-mention/--no-require-mention",
        help="Toggle require-mention.",
    ),
    stream_mode: Optional[str] = typer.Option(
        None, "--stream-mode", help="Streaming mode: replace | append."
    ),
    stream_delay: Optional[int] = typer.Option(
        None, "--stream-delay", help="Streaming delay in milliseconds."
    ),
) -> None:
    """Edit an existing channel record (any subset of fields)."""
    record = _safe_get_channel(name)
    ctype = record.get("type", "")

    if not any(
        [
            token,
            token_stdin,
            app_token,
            allowed_users,
            allowed_channels,
            allowed_guilds,
            home_channel,
            require_mention is not None,
            stream_mode,
            stream_delay is not None,
        ]
    ):
        emit_error(
            "no changes specified",
            hint="pass at least one of --token / --allowed-user / --stream-mode / etc.",
        )

    new_token: Optional[str] = None
    if token or token_stdin:
        new_token = _resolve_token(token, token_stdin, required=True)

    if app_token and ctype != "slack":
        emit_error(f"--app-token only valid for slack channels (got {ctype!r})")
    if home_channel and ctype != "slack":
        emit_error(f"--home-channel only valid for slack channels (got {ctype!r})")
    if allowed_guilds and ctype != "discord":
        emit_error(f"--allowed-guild only valid for discord channels (got {ctype!r})")

    if stream_mode is not None:
        try:
            validate_stream_mode(stream_mode)
        except InvalidStreamModeError as exc:
            emit_error(str(exc))
    if stream_delay is not None and stream_delay < 0:
        emit_error("--stream-delay must be >= 0")

    def apply(c: dict) -> dict:
        cfg = c.get("config", {}) or {}
        if allowed_users is not None:
            cfg["allowed_users"] = list(allowed_users)
        if allowed_channels is not None:
            cfg["allowed_channels"] = list(allowed_channels)
        if allowed_guilds is not None:
            cfg["allowed_guilds"] = list(allowed_guilds)
        if home_channel is not None:
            cfg["home_channel"] = home_channel
        if require_mention is not None:
            cfg["require_mention"] = require_mention
        if stream_mode is not None:
            cfg["stream_mode"] = stream_mode
        if stream_delay is not None:
            cfg["stream_delay_ms"] = stream_delay
        c["config"] = cfg
        c["updated_at"] = _now_iso()
        return c

    if not update_channel(name, apply):
        emit_error(f"failed to update channel {name!r}")

    if new_token is not None:
        set_channel_token(name, "BOT_TOKEN", new_token)
    if app_token:
        set_channel_token(name, "APP_TOKEN", app_token)

    typer.echo(f"channel/{name}: updated")


# Register sub-group on the top-level `channel` app.
channel_app.add_typer(channel_registry_app, name="registry")

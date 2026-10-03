"""`clawctl agent provider attach|detach|get` — Pattern A per-agent.

Stores attached provider names in `agent.providers` on the agent record.
The shape depends on agent type — see `core/provider_attachments.py`:

- `hermes` (multi-provider) — list of `{name, role, model}` dicts.
  `--role` is required at attach time; exactly one `primary` plus
  optional auxiliary slots (#612 / parent #589).
- `openclaw` / `zeroclaw` (singleton) — list of provider-name strings.
  Second attach is rejected with the pinned `single-provider invariant`
  message that callers + docs depend on (#426).
- `claude` (singleton) — accepts only a registered `claude-oauth` provider;
  attach imports OAuth through the local Claude Code reader into the selected
  agent's per-instance secret scope before the next normal sync.

The provider record itself lives in `~/.config/clawrium/providers.json`
and is the source of truth for ordinary backend credentials and default model;
Claude OAuth records are selection-only, while the agent record tracks the
non-secret attachment and its OAuth token stays in per-instance secrets.
"""

from __future__ import annotations

from typing import Optional

import typer

from clawrium.cli.clawctl._common import OutputFormat
from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
    stream_action,
)
from clawrium.core.hosts import update_host
from clawrium.core.claude_credentials import (
    ClaudeCredentialError,
    import_claude_oauth_from_local_reader,
)
from clawrium.core.provider_attachments import (
    AUXILIARY_SLOTS,
    PRIMARY_ROLE,
    VALID_ROLES,
    AttachmentError,
    normalize,
    supports_multi_provider,
    validate,
)
from clawrium.core.providers.storage import (
    CLAUDE_OAUTH_PROVIDER_TYPE,
    ProvidersFileCorruptedError,
    get_provider,
)

__all__ = ["provider_app"]


provider_app = typer.Typer(
    name="provider",
    help="Manage provider attachments on an agent.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


def _safe_get_provider(name: str) -> dict:
    try:
        record = get_provider(name)
    except ProvidersFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/providers.json")
    if not record:
        emit_error(
            f"provider {name!r} not found",
            hint="clawctl provider registry get",
        )
    return record  # type: ignore[return-value]


def _agent_type(claw_record: dict) -> str:
    return str(claw_record.get("type") or "")


def _get_attachments(
    host: dict, agent_key: str, agent_type: str
) -> list:
    """Read the normalized attachment list for an agent.

    Returns list-of-dicts for hermes (per provider_attachments.normalize)
    and list-of-strings for singleton agent types.
    """
    agent_data = (host.get("agents", {}) or {}).get(agent_key, {})
    if not isinstance(agent_data, dict):
        return []
    raw = agent_data.get("providers", [])
    return normalize(raw, agent_type)


def _set_attachments(
    hostname: str, agent_key: str, agent_type: str, attachments: list
) -> bool:
    """Validate then persist the attachment list onto the agent record."""
    try:
        validate(attachments, agent_type)
    except AttachmentError as exc:
        # ATX iter-1 B4: explicit early return after emit_error so the
        # validation gate still keeps `update_host` from running even if
        # tests (or future callers) patch `emit_error` to a no-op.
        emit_error(str(exc))
        return False

    def updater(h: dict) -> dict:
        agents = h.get("agents", {})
        if agent_key not in agents:
            return h
        agent_data = agents[agent_key]
        if not isinstance(agent_data, dict):
            return h
        agent_data["providers"] = attachments
        return h

    return update_host(hostname, updater)


def _attachment_name(entry: object) -> Optional[str]:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        name = entry.get("name")
        if isinstance(name, str):
            return name
    return None


def _find_attachment(attachments: list, name: str) -> Optional[object]:
    for entry in attachments:
        if _attachment_name(entry) == name:
            return entry
    return None


def _restore_claude_attachment(
    hostname: str,
    agent_key: str,
    *,
    had_providers: bool,
    raw_providers: object,
    expected_providers: list[str],
) -> bool:
    """Restore this operation's unchanged attachment metadata only.

    The reader can be interactive. A concurrent attach or detach must win over
    this operation's failed import, so do not restore the pre-import snapshot
    unless the record still has exactly the list this operation wrote.
    """
    restored = False

    def updater(host: dict) -> dict:
        nonlocal restored
        agents = host.get("agents", {})
        record = agents.get(agent_key)
        if (
            not isinstance(record, dict)
            or record.get("providers") != expected_providers
        ):
            return host
        if had_providers:
            record["providers"] = raw_providers
        else:
            record.pop("providers", None)
        restored = True
        return host

    try:
        return update_host(hostname, updater) and restored
    except Exception:
        # The public reader failure remains fixed and secret-free even if a
        # concurrent host-record change prevents metadata rollback.
        return False


def _attach_claude_oauth_provider(
    *,
    provider_record: dict,
    host: dict,
    agent: str,
    hostname: str,
    agent_key: str,
) -> None:
    """Attach Claude OAuth metadata and import one per-instance credential.

    Provider metadata contains only the selected provider name. The token is
    read through the local-reader seam and stored by the credential module in
    the selected Claude agent's secret scope; it never enters hosts.json. On a
    reader failure, restore the pre-attach metadata so an unusable OAuth
    selection cannot be left behind.
    """
    if provider_record.get("type") != CLAUDE_OAUTH_PROVIDER_TYPE:
        emit_error(
            "Claude agents require a claude-oauth provider",
            hint=(
                "create one with: clawctl provider registry create <name> "
                "--type claude-oauth"
            ),
        )

    provider_name = str(provider_record.get("name") or "")
    agent_data = (host.get("agents", {}) or {}).get(agent_key, {})
    had_providers = isinstance(agent_data, dict) and "providers" in agent_data
    raw_providers = (
        agent_data.get("providers") if isinstance(agent_data, dict) else None
    )
    current = _get_attachments(host, agent_key, "claude")
    existing = _find_attachment(current, provider_name)
    if existing is None and current:
        other = _attachment_name(current[0]) or ""
        emit_error(
            f"agent '{agent}' already has provider {other!r} attached",
            hint=(
                f"detach first: clawctl agent provider detach {other} --agent {agent}"
            ),
        )

    attached_now = existing is None
    if attached_now and not _set_attachments(
        hostname, agent_key, "claude", [provider_name]
    ):
        emit_error(f"failed to attach provider {provider_name!r} to agent {agent!r}")

    try:
        import_claude_oauth_from_local_reader(agent)
    except ClaudeCredentialError as exc:
        credential_hint = str(exc)
    except Exception:
        # A secret-store or resolution failure must not leave newly written
        # attachment metadata behind or produce an unredacted traceback.
        credential_hint = "local Claude OAuth credential import failed"
    except BaseException:
        # Do not leave a selected provider behind if browser authorization is
        # cancelled or the process exits while the local reader is running.
        rollback_succeeded = not attached_now or _restore_claude_attachment(
            hostname,
            agent_key,
            had_providers=had_providers,
            raw_providers=raw_providers,
            expected_providers=[provider_name],
        )
        if not rollback_succeeded:
            stream_action(
                resource=f"agent/{agent}",
                message=(
                    "provider attachment rollback could not be confirmed; "
                    f"detach {provider_name!r} before retrying"
                ),
            )
        raise
    else:
        credential_hint = None

    if credential_hint is not None:
        rollback_succeeded = not attached_now or _restore_claude_attachment(
            hostname,
            agent_key,
            had_providers=had_providers,
            raw_providers=raw_providers,
            expected_providers=[provider_name],
        )
        if not rollback_succeeded:
            credential_hint += (
                "; provider attachment rollback could not be confirmed. "
                f"Detach {provider_name!r} from agent {agent!r} before retrying"
            )
        emit_error(
            "could not import the local Claude OAuth credential",
            hint=credential_hint,
        )

    if attached_now:
        stream_action(
            resource=f"agent/{agent}",
            message=f"attached provider {provider_name!r}",
        )
    else:
        stream_action(
            resource=f"agent/{agent}",
            message=(
                f"provider {provider_name!r} already attached; refreshed local OAuth credential"
            ),
        )


@provider_app.command("attach")
def attach(
    name: str = typer.Argument(..., help="Provider name to attach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    role: Optional[str] = typer.Option(
        None,
        "--role",
        help=(
            "Attachment role (hermes only). Required on hermes: 'primary' "
            f"or one of {', '.join(sorted(AUXILIARY_SLOTS))}. Rejected on non-hermes."
        ),
    ),
) -> None:
    """Attach a registered provider to an agent.

    Ordinary provider attachments are metadata only until the next `clawctl
    agent sync`. A Claude `claude-oauth` attachment additionally imports the
    local OAuth token into that selected agent's private secret scope; the
    next sync uses the existing credential activation path.

    On hermes, `--role` is required: pass `--role primary` for the
    primary attachment and one of the auxiliary slot names for any
    subsequent attachment. On non-hermes (zeroclaw, openclaw) the
    singleton invariant from #426 still applies — the second attach
    is rejected with the pinned `single-provider invariant` message.
    """
    provider_record = _safe_get_provider(name)
    host, _agent_key_unused, claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)
    agent_type = _agent_type(claw)
    if (
        provider_record.get("type") == CLAUDE_OAUTH_PROVIDER_TYPE
        and agent_type != "claude"
    ):
        emit_error(
            "claude-oauth providers can only be attached to Claude agents",
            hint="select a provider type supported by this agent",
        )
    if agent_type == "claude":
        if role is not None:
            emit_error(
                "--role is not supported on agent type 'claude'",
                hint="Claude OAuth uses the single-provider selection",
            )
        _attach_claude_oauth_provider(
            provider_record=provider_record,
            host=host,
            agent=agent,
            hostname=hostname,
            agent_key=agent_key,
        )
        return

    multi = supports_multi_provider(agent_type)

    # Role flag validity is agent-type-scoped.
    if multi:
        if role is None:
            emit_error(
                f"agent '{agent}' is a hermes agent; --role is required",
                hint=(
                    "pass --role primary for the first attachment, "
                    f"or one of {', '.join(sorted(AUXILIARY_SLOTS))} for an auxiliary slot"
                ),
            )
        if role not in VALID_ROLES:
            emit_error(
                f"invalid --role {role!r}",
                hint=f"expected one of {', '.join(sorted(VALID_ROLES))}",
            )
    else:
        if role is not None:
            emit_error(
                f"--role is not supported on agent type {agent_type!r}",
                hint="--role applies to hermes agents only",
            )

    current = _get_attachments(host, agent_key, agent_type)

    # Idempotent re-attach by name. For hermes, role must match the
    # already-attached entry's role — otherwise the operator's intent
    # (rebinding to a different slot) is ambiguous and we make them
    # detach first.
    existing = _find_attachment(current, name)
    if existing is not None:
        if multi and isinstance(existing, dict):
            existing_role = existing.get("role")
            if role != existing_role:
                emit_error(
                    f"provider {name!r} already attached to agent {agent!r} "
                    f"with role {existing_role!r}",
                    hint=(
                        f"detach first: clawctl agent provider detach {name} "
                        f"--agent {agent}"
                    ),
                )
        typer.echo(f"agent/{agent}: provider {name!r} already attached")
        return

    if not multi:
        # Issue #426 singleton invariant. The verbatim phrase
        # "single-provider invariant" comes from
        # `provider_attachments.validate()` and is pinned by tests +
        # docs; let `validate()` raise it via `_set_attachments` instead
        # of duplicating the string here. Same UX as before via the
        # `already has provider` hint.
        if current:
            other = _attachment_name(current[0]) or ""
            emit_error(
                f"agent '{agent}' already has provider {other!r} attached",
                hint=(
                    f"detach first: clawctl agent provider detach {other} "
                    f"--agent {agent}"
                ),
            )
        new_attachments = [*current, name]
    else:
        # Hermes multi-attach. Determine model from the provider record's
        # default_model when available so the rendered hermes config has
        # a model to point at; empty string is acceptable and lets the
        # template fall back to `auto` per upstream.
        model = ""
        default_model = provider_record.get("default_model")
        if isinstance(default_model, str):
            model = default_model
        new_attachments = [
            *current,
            {"name": name, "role": role, "model": model},
        ]

    if not _set_attachments(hostname, agent_key, agent_type, new_attachments):
        emit_error(f"failed to attach provider {name!r} to agent {agent!r}")

    if multi:
        typer.echo(
            f"agent/{agent}: attached provider {name!r} with role {role!r}"
        )
    else:
        typer.echo(f"agent/{agent}: attached provider {name!r}")


@provider_app.command("detach")
def detach(
    name: str = typer.Argument(..., help="Provider name to detach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
) -> None:
    """Detach a provider from an agent.

    To switch providers, attach a replacement and run
    `clawctl agent sync`. See #426.

    On hermes, detaching the primary while auxiliary attachments remain
    is rejected — promotion is out of scope (#612). Detach the aux
    attachments first.
    """
    host, _agent_key_unused, claw = safe_resolve_agent(agent)
    hostname = host["hostname"]
    agent_key = resolve_agent_key(host, agent)
    agent_type = _agent_type(claw)
    multi = supports_multi_provider(agent_type)

    current = _get_attachments(host, agent_key, agent_type)
    target = _find_attachment(current, name)
    if target is None:
        emit_error(
            f"provider {name!r} not attached to agent {agent!r}",
            hint=f"clawctl agent provider get --agent {agent}",
        )

    # Primary-detach guard on hermes: refuse when aux slots are filled.
    if multi and isinstance(target, dict) and target.get("role") == PRIMARY_ROLE:
        if len(current) > 1:
            aux_names = [
                _attachment_name(e) or ""
                for e in current
                if e is not target
            ]
            aux_hint = ", ".join(
                f"clawctl agent provider detach {n} --agent {agent}"
                for n in aux_names
                if n
            )
            emit_error(
                f"cannot detach primary provider {name!r} from agent "
                f"{agent!r} while auxiliary attachments remain",
                hint=(
                    f"detach auxiliary attachments first: {aux_hint}"
                    if aux_hint
                    else "detach auxiliary attachments first"
                ),
            )

    remaining = [e for e in current if e is not target]
    if not _set_attachments(hostname, agent_key, agent_type, remaining):
        emit_error(f"failed to detach provider {name!r} from agent {agent!r}")
    typer.echo(f"agent/{agent}: detached provider {name!r}")


@provider_app.command("get")
def get(
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    no_headers: bool = typer.Option(False, "--no-headers", help="Skip header row."),
) -> None:
    """List providers attached to an agent.

    For multi-provider agent types (hermes) the table renders
    `name`, `role`, `model` columns; for singleton agent types only
    `name` is meaningful and the table stays flat for back-compat.
    """
    host, _agent_key_unused, claw = safe_resolve_agent(agent)
    agent_key = resolve_agent_key(host, agent)
    agent_type = _agent_type(claw)
    multi = supports_multi_provider(agent_type)
    attachments = _get_attachments(host, agent_key, agent_type)

    rows: list[dict] = []
    for entry in attachments:
        if multi and isinstance(entry, dict):
            rows.append(
                {
                    "kind": "provider",
                    "name": entry.get("name", ""),
                    "agent": agent,
                    "role": entry.get("role", ""),
                    "model": entry.get("model", ""),
                }
            )
        else:
            n = _attachment_name(entry) or ""
            rows.append({"kind": "provider", "name": n, "agent": agent})

    if output is OutputFormat.json:
        typer.echo(dump_json(rows), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml(rows), nl=False)
        return
    if output is OutputFormat.name:
        typer.echo(dump_name(rows), nl=False)
        return

    if multi:
        headers = ["NAME", "ROLE", "MODEL", "AGENT"]
        body = [
            [str(r["name"]), str(r["role"]), str(r["model"]), str(r["agent"])]
            for r in rows
        ]
    else:
        headers = ["NAME", "AGENT"]
        body = [[str(r["name"]), str(r["agent"])] for r in rows]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


# Used by tests + neighboring modules that previously imported the
# original helpers. The shape they expected (list of strings) only
# matched the singleton path; new callers should prefer
# `_get_attachments` directly with an explicit agent_type.
def _get_attached_providers(host: dict, agent_key: str) -> list[str]:
    agent_data = (host.get("agents", {}) or {}).get(agent_key, {})
    if not isinstance(agent_data, dict):
        return []
    providers = agent_data.get("providers", [])
    if not isinstance(providers, list):
        return []
    out: list[str] = []
    for entry in providers:
        n = _attachment_name(entry)
        if n is not None:
            out.append(n)
    return out

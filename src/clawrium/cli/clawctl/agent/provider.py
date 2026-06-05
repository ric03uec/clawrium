"""`clawctl agent provider attach|detach|get` — Pattern A per-agent.

Stores attached provider names in `agent.providers` on the agent record.
The shape depends on agent type — see `core/provider_attachments.py`:

- `hermes` (multi-provider) — list of `{name, role, model}` dicts.
  `--role` is required at attach time; exactly one `primary` plus
  optional auxiliary slots (#612 / parent #589).
- `openclaw` / `zeroclaw` (singleton) — list of provider-name strings.
  Second attach is rejected with the pinned `single-provider invariant`
  message that callers + docs depend on (#426).

The provider record itself lives in `~/.config/clawrium/providers.json`
and is the source of truth for credentials, default model, etc.; the
agent record only tracks the *attachment*.
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
)
from clawrium.core.hosts import update_host
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

    The attachment is metadata only at this point — the provider config
    is materialized onto the remote agent on the next `clawctl agent
    sync`.

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

    Note: the provider config previously materialized into the agent's
    `config.provider` block is preserved as last-known-good across
    syncs. To switch providers, attach a replacement and run
    `clawctl agent sync`; the new provider will overwrite the old.
    See #426.

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
    # Issue #426 design decision: detach does NOT strip
    # `agent.config.provider`. The provider config persists across
    # sync runs as last-known-good so the remote keeps functioning
    # until the user explicitly attaches a replacement.
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

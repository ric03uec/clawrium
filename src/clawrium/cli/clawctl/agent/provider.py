"""`clawctl agent provider attach|detach|get` — Pattern A per-agent.

Stores attached provider names in `agent.providers` on the agent record.
The shape depends on agent type — see `core/provider_attachments.py`:

- `hermes` (multi-provider) — list of `{name, role, model}` dicts.
  `--role` is required at attach time; exactly one `primary` plus
  optional auxiliary slots (#612 / parent #589).
- `openclaw` / `zeroclaw` (singleton) — list of provider-name strings.
  Second attach is rejected with the pinned `single-provider invariant`
  message that callers + docs depend on (#426).
- `claude` / `codex` (singleton) — each accepts only its matching selection-
  only OAuth provider; attach imports the native local credential document into
  the selected agent's per-instance secret scope before the next normal sync.

The provider record itself lives in `~/.config/clawrium/providers.json`
and is the source of truth for ordinary backend credentials and default model;
Claude OAuth records are selection-only, while the agent record tracks the
non-secret attachment and its OAuth token stays in per-instance secrets.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import uuid
from typing import Optional

import paramiko
import typer

from clawrium.cli.clawctl._common import OutputFormat, confirm_destructive
from clawrium.cli.clawctl.agent._shared import resolve_agent_key, safe_resolve_agent
from clawrium.cli.output._sanitize import sanitize, sanitize_passthrough
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
    stream_action,
)
from clawrium.core.hosts import update_host
from clawrium.core.keys import get_host_private_key
from clawrium.core import codex_credentials
from clawrium.core.claude_credentials import (
    ClaudeCredentialError,
    import_claude_oauth_from_local_reader,
)
from clawrium.core.codex_credentials import (
    CODEX_OAUTH_DOCUMENT,
    CODEX_OAUTH_PENDING_ACTIVATION,
    CodexCredentialError,
    codex_oauth_operation_lock,
    get_codex_oauth_instance_key,
    normalize_codex_oauth_document,
)
from clawrium.core.secrets import (
    get_instance_secrets,
    replace_instance_secrets,
    remove_instance_secret_if_matches,
    replace_instance_secret_if_matches,
    restore_instance_secret_if_absent,
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
    CODEX_OAUTH_PROVIDER_TYPE,
    ProvidersFileCorruptedError,
    get_provider,
)
from clawrium.core.pi import (
    PI_CODEX_PROVIDER_TYPE,
    PiProvisioningError,
    validate_pi_provider,
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


def _get_attachments(host: dict, agent_key: str, agent_type: str) -> list:
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
                "use a claude-oauth provider, or set an API key with: "
                "clawctl agent secret create ANTHROPIC_API_KEY --agent <name> "
                "--value-stdin"
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


def _attach_codex_oauth_provider(
    *, provider_record: dict, host: dict, agent: str, hostname: str, agent_key: str
) -> None:
    """Serialize attach/refresh with detach before touching either store."""
    with codex_oauth_operation_lock(agent):
        # Resolve after acquiring the canonical per-instance lock so a failed
        # import cannot roll back metadata read before a concurrent lifecycle
        # operation completed.
        locked_host, _unused, _locked_claw = safe_resolve_agent(agent)
        _attach_codex_oauth_provider_locked(
            provider_record=provider_record,
            host=locked_host,
            agent=agent,
            hostname=locked_host["hostname"],
            agent_key=resolve_agent_key(locked_host, agent),
        )


CODEX_OAUTH_PENDING_TRANSACTION = "CODEX_OAUTH_PENDING_TRANSACTION"


def _after_codex_oauth_durable_step(_step: str) -> None:
    """Test seam for interruption immediately after each durable boundary."""


def _pending_transaction(
    operation: str, provider_name: str, previous_document: str | None, document: str
) -> str:
    return json.dumps(
        {
            "document": document,
            "operation": operation,
            "previous_document": previous_document,
            "provider_name": provider_name,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _load_codex_pending_transaction(secret_key: str) -> tuple[str, dict] | None:
    entry = get_instance_secrets(secret_key).get(CODEX_OAUTH_PENDING_TRANSACTION)
    value = entry.get("value") if isinstance(entry, dict) else None
    if not isinstance(value, str):
        return None
    try:
        transaction = json.loads(value)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(transaction, dict)
        or transaction.get("operation") not in {"attach", "detach"}
        or not isinstance(transaction.get("provider_name"), str)
        or not isinstance(transaction.get("document"), str)
        or transaction.get("previous_document") is not None
        and not isinstance(transaction.get("previous_document"), str)
    ):
        return None
    return value, transaction


def _clear_codex_pending_transaction(secret_key: str, serialized: str) -> None:
    # Compare-and-delete avoids erasing a future transaction if a caller that
    # does not use the per-agent operation lock writes one concurrently.
    remove_instance_secret_if_matches(
        secret_key, CODEX_OAUTH_PENDING_TRANSACTION, serialized
    )


def _set_document_if_prior_matches(
    secret_key: str, previous_document: str | None, document: str
) -> None:
    if previous_document is None:
        restore_instance_secret_if_absent(
            secret_key,
            CODEX_OAUTH_DOCUMENT,
            document,
            description="Codex OAuth credential document",
        )
    elif previous_document != document:
        replace_instance_secret_if_matches(
            secret_key,
            CODEX_OAUTH_DOCUMENT,
            previous_document,
            document,
            description="Codex OAuth credential document",
        )


def _restore_document_if_operation_matches(
    secret_key: str, previous_document: str | None, document: str
) -> None:
    replace_instance_secret_if_matches(
        secret_key,
        CODEX_OAUTH_DOCUMENT,
        document,
        previous_document,
        description="Codex OAuth credential document",
    )


def _reconcile_codex_oauth_transaction(
    *, host: dict, agent_key: str, agent: str
) -> None:
    """Resolve an interrupted credential operation without exposing its document.

    The journal and credential mutation share one atomic secrets-file write.
    Hosts metadata is a distinct file, so recovery uses its observed selection:
    selected means complete the intent; unselected means restore the prior
    credential.  All document writes are compare-and-swap/absent-only, so a
    newer credential always wins over stale recovery.
    """
    secret_key = get_codex_oauth_instance_key(agent)
    pending = _load_codex_pending_transaction(secret_key)
    if pending is None:
        return
    serialized, transaction = pending
    provider_name = transaction["provider_name"]
    document = transaction["document"]
    previous_document = transaction["previous_document"]
    selected = _find_attachment(
        _get_attachments(host, agent_key, "codex"), provider_name
    ) is not None
    if transaction["operation"] == "attach":
        if selected:
            _set_document_if_prior_matches(secret_key, previous_document, document)
        else:
            _restore_document_if_operation_matches(
                secret_key, previous_document, document
            )
            # A replacement marker only authorizes activation for a selected
            # attachment. The same durable write installed it alongside this
            # attach transaction, so an unselected rollback must remove it
            # before a later sync can mistake the rolled-back import for an
            # explicit activation request.
            activation = get_instance_secrets(secret_key).get(
                CODEX_OAUTH_PENDING_ACTIVATION
            )
            activation_value = (
                activation.get("value") if isinstance(activation, dict) else None
            )
            if isinstance(activation_value, str):
                remove_instance_secret_if_matches(
                    secret_key, CODEX_OAUTH_PENDING_ACTIVATION, activation_value
                )
    elif selected:
        if previous_document is not None:
            restore_instance_secret_if_absent(
                secret_key,
                CODEX_OAUTH_DOCUMENT,
                previous_document,
                description="Codex OAuth credential document",
            )
    else:
        remove_instance_secret_if_matches(secret_key, CODEX_OAUTH_DOCUMENT, document)
    _clear_codex_pending_transaction(secret_key, serialized)


def _attach_codex_oauth_provider_locked(
    *, provider_record: dict, host: dict, agent: str, hostname: str, agent_key: str
) -> None:
    """Attach Codex OAuth metadata and import its private native snapshot."""
    _reconcile_codex_oauth_transaction(host=host, agent_key=agent_key, agent=agent)
    if provider_record.get("type") != CODEX_OAUTH_PROVIDER_TYPE:
        emit_error(
            "Codex agents require a codex-oauth provider",
            hint="use a codex-oauth provider; API-key mode is not supported by this attachment",
        )
    provider_name = str(provider_record.get("name") or "")
    current = _get_attachments(host, agent_key, "codex")
    existing = _find_attachment(current, provider_name)
    if existing is None and current:
        other = _attachment_name(current[0]) or ""
        emit_error(
            f"agent '{agent}' already has provider {other!r} attached",
            hint=f"detach first: clawctl agent provider detach {other} --agent {agent}",
        )
    attached_now = existing is None
    secret_key = get_codex_oauth_instance_key(agent)
    old_entry = get_instance_secrets(secret_key).get(CODEX_OAUTH_DOCUMENT)
    previous_document = old_entry.get("value") if isinstance(old_entry, dict) else None
    if not isinstance(previous_document, str):
        previous_document = None
    try:
        document = normalize_codex_oauth_document(
            codex_credentials.read_local_codex_oauth_document()
        )
    except CodexCredentialError as exc:
        emit_error("could not import the local Codex OAuth credential", hint=str(exc))
        return
    except Exception:
        emit_error(
            "could not import the local Codex OAuth credential",
            hint="local Codex OAuth credential import failed",
        )
        return
    transaction = _pending_transaction(
        "attach", provider_name, previous_document, document
    )
    try:
        replace_instance_secrets(
            secret_key,
            {
                CODEX_OAUTH_PENDING_TRANSACTION: transaction,
                CODEX_OAUTH_DOCUMENT: document,
                CODEX_OAUTH_PENDING_ACTIVATION: f"pending:{uuid.uuid4().hex}",
            },
            descriptions={
                CODEX_OAUTH_PENDING_TRANSACTION: "Codex OAuth operation journal",
                CODEX_OAUTH_DOCUMENT: "Codex OAuth credential document",
                CODEX_OAUTH_PENDING_ACTIVATION: "Codex OAuth activation request",
            },
        )
    except Exception:
        emit_error(
            "could not import the local Codex OAuth credential",
            hint="local Codex OAuth credential import failed",
        )
        return
    _after_codex_oauth_durable_step("attach_secret")
    try:
        metadata_written = not attached_now or _set_attachments(
            hostname, agent_key, "codex", [provider_name]
        )
    except BaseException:
        _reconcile_codex_oauth_transaction(host=host, agent_key=agent_key, agent=agent)
        raise
    _after_codex_oauth_durable_step("attach_metadata")
    if not metadata_written:
        _reconcile_codex_oauth_transaction(host=host, agent_key=agent_key, agent=agent)
        emit_error(f"failed to attach provider {provider_name!r} to agent {agent!r}")
    _clear_codex_pending_transaction(secret_key, transaction)
    if attached_now:
        stream_action(resource=f"agent/{agent}", message=f"attached provider {provider_name!r}")
    else:
        stream_action(
            resource=f"agent/{agent}",
            message=f"provider {provider_name!r} already attached; refreshed local OAuth credential",
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
    agent sync`. Matching Claude `claude-oauth` and Codex `codex-oauth`
    attachments additionally import their local native OAuth credential into
    that selected agent's private secret scope; the next sync uses the
    existing credential activation path.

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
    if agent_type == "pi":
        try:
            validate_pi_provider(provider_record)
        except PiProvisioningError as exc:
            emit_error(
                str(exc),
                hint="select an OpenRouter or AWS SSO-backed Bedrock provider with a supported default model",
            )
    if (
        provider_record.get("type") == CLAUDE_OAUTH_PROVIDER_TYPE
        and agent_type != "claude"
    ):
        emit_error(
            "claude-oauth providers can only be attached to Claude agents",
            hint="select a provider type supported by this agent",
        )
    if (
        provider_record.get("type") == CODEX_OAUTH_PROVIDER_TYPE
        and agent_type != "codex"
    ):
        emit_error(
            "codex-oauth providers can only be attached to Codex agents",
            hint="select a provider type supported by this agent",
        )
    if agent_type in {"claude", "codex"}:
        if role is not None:
            emit_error(
                f"--role is not supported on agent type {agent_type!r}",
                hint="OAuth uses the single-provider selection",
            )
        attach_oauth = (
            _attach_claude_oauth_provider
            if agent_type == "claude"
            else _attach_codex_oauth_provider
        )
        attach_oauth(
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
        stream_action(
            resource=f"agent/{agent}", message=f"provider {name!r} already attached"
        )
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

    message = f"attached provider {name!r}"
    if multi:
        message += f" with role {role!r}"
    stream_action(resource=f"agent/{agent}", message=message)


def _detach_codex_oauth_provider(*, agent: str, name: str) -> None:
    """Detach Codex selection and credential under one per-agent lock."""
    with codex_oauth_operation_lock(agent):
        host, _unused, claw = safe_resolve_agent(agent)
        hostname = host["hostname"]
        agent_key = resolve_agent_key(host, agent)
        _reconcile_codex_oauth_transaction(host=host, agent_key=agent_key, agent=agent)
        current = _get_attachments(host, agent_key, _agent_type(claw))
        target = _find_attachment(current, name)
        if target is None:
            emit_error(
                f"provider {name!r} not attached to agent {agent!r}",
                hint=f"clawctl agent provider get --agent {agent}",
            )
        remaining = [entry for entry in current if entry is not target]
        secret_key = get_codex_oauth_instance_key(agent)
        entry = get_instance_secrets(secret_key).get(CODEX_OAUTH_DOCUMENT)
        document = entry.get("value") if isinstance(entry, dict) else None
        if not isinstance(document, str):
            emit_error(
                f"could not remove Codex OAuth credential for agent {agent!r} "
                f"and provider {name!r}: secret removal was not confirmed"
            )
            return
        transaction = _pending_transaction("detach", name, document, document)
        try:
            replace_instance_secrets(
                secret_key,
                {
                    CODEX_OAUTH_PENDING_TRANSACTION: transaction,
                    CODEX_OAUTH_DOCUMENT: None,
                    CODEX_OAUTH_PENDING_ACTIVATION: None,
                },
                descriptions={CODEX_OAUTH_PENDING_TRANSACTION: "Codex OAuth operation journal"},
            )
        except Exception:
            emit_error(
                f"could not remove Codex OAuth credential for agent {agent!r} "
                f"and provider {name!r}: secret removal was not confirmed"
            )
            return
        _after_codex_oauth_durable_step("detach_secret")
        try:
            metadata_written = _set_attachments(hostname, agent_key, "codex", remaining)
        except BaseException:
            _reconcile_codex_oauth_transaction(host=host, agent_key=agent_key, agent=agent)
            raise
        _after_codex_oauth_durable_step("detach_metadata")
        if not metadata_written:
            _reconcile_codex_oauth_transaction(host=host, agent_key=agent_key, agent=agent)
            emit_error(f"failed to detach provider {name!r} from agent {agent!r}")
        _clear_codex_pending_transaction(secret_key, transaction)
        stream_action(
            resource=f"agent/{agent}",
            message=f"detached provider {name!r} and removed imported Codex OAuth credential",
        )


@provider_app.command("login")
def login(
    name: str = typer.Argument(..., help="Attached provider name."),
    agent: str = typer.Option(..., "--agent", help="Pi agent instance name."),
) -> None:
    """Open Pi-native OAuth in the dedicated account; no credential crosses Clawrium."""
    record = _safe_get_provider(name)
    host, _unused, claw = safe_resolve_agent(agent)
    if _agent_type(claw) != "pi" or record.get("type") != PI_CODEX_PROVIDER_TYPE:
        emit_error("Pi native login is available only for an attached openai-codex provider")
    agent_key = resolve_agent_key(host, agent)
    if name not in _get_attachments(host, agent_key, "pi"):
        emit_error(f"provider {name!r} is not attached to agent {agent!r}")
    try:
        selection = validate_pi_provider(record)
    except PiProvisioningError as exc:
        emit_error(str(exc))
    agent_unix = claw.get("agent_name") or agent
    key_id = host.get("key_id") or host.get("hostname")
    key = get_host_private_key(key_id)
    hostname, user = host.get("hostname"), host.get("user", "xclm")
    if not key or not isinstance(hostname, str) or not isinstance(user, str):
        emit_error("Pi host is missing its managed SSH identity")
    root = "/Users" if str(host.get("os_family", "")).lower() in {"darwin", "macos", "osx"} else "/home"
    home = f"{root}/{agent_unix}"
    remote = (
        "unset OPENAI_API_KEY OPENROUTER_API_KEY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_BEARER_TOKEN_BEDROCK; "
        f"exec sudo -n -H -u {shlex.quote(str(agent_unix))} env HOME={shlex.quote(home)} "
        f"PATH={shlex.quote(home + '/.local/pi/bin')}:/usr/local/bin:/usr/bin:/bin PI_DISABLE_AUTOUPDATE=1 "
        f"pi --provider {shlex.quote(selection.provider)} --model {shlex.quote(selection.model)}"
    )
    typer.echo("Opening Pi native login in the dedicated account. Enter /login, select openai-codex, complete the browser/device flow, then exit Pi.")
    result = subprocess.run(["ssh", "-tt", "-i", str(key), "-p", str(host.get("port", 22)), f"{user}@{hostname}", remote], check=False)
    if result.returncode:
        raise typer.Exit(code=result.returncode)


@provider_app.command("detach")
def detach(
    name: str = typer.Argument(..., help="Provider name to detach."),
    agent: str = typer.Option(..., "--agent", help="Agent instance name."),
    yes: bool = typer.Option(
        False, "--yes", help="Confirm Codex OAuth credential removal."
    ),
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
    if agent_type == "codex":
        provider_record = _safe_get_provider(name)
        if provider_record.get("type") != CODEX_OAUTH_PROVIDER_TYPE:
            emit_error(
                "Codex OAuth credential can only be removed with a codex-oauth provider",
                hint="repair the provider attachment metadata before detaching",
            )
        confirm_destructive(
            prompt=(
                f"Detach provider {sanitize_passthrough(name)!r} and delete the imported "
                f"Codex OAuth credential for agent {sanitize_passthrough(agent)!r}?"
            ),
            yes=yes,
        )
        _detach_codex_oauth_provider(agent=agent, name=name)
        return
    target = _find_attachment(current, name)
    if target is None:
        emit_error(
            f"provider {name!r} not attached to agent {agent!r}",
            hint=f"clawctl agent provider get --agent {agent}",
        )

    # Primary-detach guard on hermes: refuse when aux slots are filled.
    if multi and isinstance(target, dict) and target.get("role") == PRIMARY_ROLE:
        if len(current) > 1:
            aux_names = [_attachment_name(e) or "" for e in current if e is not target]
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

    if agent_type == "pi":
        # Serialize from the fresh attachment read through remote revocation
        # and hosts.json persistence; a concurrent sync re-resolves under the
        # same lock and therefore cannot resurrect a detached credential.
        from clawrium.core.lifecycle_canonical import (
            CanonicalSyncError,
            revoke_pi_codex,
            revoke_pi_openrouter,
        )
        from clawrium.core.pi import pi_credential_lock

        with pi_credential_lock(agent):
            # Re-read hosts.json after acquiring the lock; the earlier object
            # may predate a concurrent attach/detach in another process.
            locked_host, _locked_type, locked_record = safe_resolve_agent(agent)
            locked_key = resolve_agent_key(locked_host, agent)
            if (
                locked_host.get("hostname") != hostname
                or locked_key != agent_key
                or _agent_type(locked_record) != "pi"
            ):
                emit_error(
                    "Pi agent changed while detaching provider; retry the command"
                )
            host = locked_host
            current = _get_attachments(host, locked_key, agent_type)
            target = _find_attachment(current, name)
            if target is None:
                emit_error(f"provider {name!r} not attached to agent {agent!r}")
            remaining = [entry for entry in current if entry is not target]
            if not remaining:
                try:
                    detached = _safe_get_provider(name)
                    if detached.get("type") == PI_CODEX_PROVIDER_TYPE:
                        revoke_pi_codex(agent_name=agent, host=host)
                    else:
                        revoke_pi_openrouter(agent_name=agent, host=host)
                except (CanonicalSyncError, paramiko.SSHException, OSError):
                    emit_error(
                        "failed to revoke Pi provider credential; detach did not finish",
                        hint=f"retry: clawctl agent provider detach {name} --agent {agent}",
                    )
            try:
                metadata_persisted = _set_attachments(
                    hostname, agent_key, agent_type, remaining
                )
            except Exception:
                metadata_persisted = False
            if not metadata_persisted:
                # Do not recreate credentials after a failed local commit.
                # Keep the durable attachment unchanged so this idempotent
                # detach can be retried; remote rm -f remains safe.
                emit_error(
                    f"failed to persist Pi provider detach for {name!r}; detach did not finish",
                    hint=f"retry: clawctl agent provider detach {name} --agent {agent}",
                )
        typer.echo(f"agent/{sanitize(agent)}: detached provider {sanitize(name)!r}")
        return

    remaining = [e for e in current if e is not target]
    provider_record = _safe_get_provider(name)
    if not _set_attachments(hostname, agent_key, agent_type, remaining):
        emit_error(f"failed to detach provider {name!r} from agent {agent!r}")
    stream_action(resource=f"agent/{agent}", message=f"detached provider {name!r}")


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

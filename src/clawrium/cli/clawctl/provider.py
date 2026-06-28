"""`clawctl provider` — Pattern A attachable (Bundle 4 / #509).

`provider registry` is the ONLY CRUD entrypoint for inference-backend
providers per plan §3 / §4. Per-agent `attach/detach/get` lives under
`clawctl agent provider`.

The CLI layer delegates every storage operation to
`clawrium.core.providers.storage` (untouched per plan §2 guardrail).

Non-interactive contract (plan §7):

- `--type` is always required.
- For Ollama: `--ollama-url` is required.
- For AWS Bedrock: `--access-key` and `--secret-key` are required;
  `--region` is optional.
- For every other (cloud) provider: `--api-key` OR `--api-key-stdin`
  is required.
- If a mandatory flag is missing AND stdin is not a TTY: fail fast.
- If a mandatory flag is missing AND stdin IS a TTY: the verb may
  prompt (`--api-key`/`--access-key`/etc. fall back to `typer.prompt`
  with `hide_input=True`).
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
    require_flag,
    stdin_is_tty,
)
from clawrium.cli.output import (
    dump_json,
    dump_name,
    dump_yaml,
    emit_error,
    render_table,
)
from clawrium.core.providers.storage import (
    DuplicateProviderError,
    InvalidLiteLLMUrlError,
    InvalidOllamaUrlError,
    InvalidProviderNameError,
    InvalidProviderTypeError,
    LiteLLMConnectionError,
    OllamaConnectionError,
    ProvidersFileCorruptedError,
    PROVIDER_MODELS,
    add_provider,
    fetch_litellm_models,
    fetch_ollama_models,
    get_provider,
    get_provider_api_key,
    get_provider_aws_credentials,
    load_providers,
    remove_provider,
    remove_provider_api_key,
    remove_provider_aws_credentials,
    set_provider_api_key,
    set_provider_aws_credentials,
    update_provider,
    validate_litellm_url,
    validate_ollama_url,
    validate_provider_name,
    validate_provider_type,
)

__all__ = ["provider_app"]


provider_app = typer.Typer(
    name="provider",
    help="Inference backend providers (Pattern A attachable).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)

provider_registry_app = typer.Typer(
    name="registry",
    help="CRUD entrypoint for the provider registry.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_load_providers() -> list[dict]:
    try:
        return load_providers()
    except ProvidersFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/providers.json")


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


def _provider_to_row(record: dict) -> dict:
    """Render a provider record as a serializable row (plan §6.5 shape).

    Credentials are summarized — never exported in plaintext. The
    `credentials_status` field is `set`/`unset`/`partial` so `get -o
    json` consumers can see whether the provider is usable without
    leaking the secret values.
    """
    name = record.get("name", "")
    ptype = record.get("type", "")
    creds_status = _credentials_status(name, ptype)
    return {
        "kind": "provider",
        "name": name,
        "type": ptype,
        "model": record.get("default_model") or "",
        "endpoint": record.get("endpoint") or "",
        "credentials": creds_status,
        "age_seconds": now_seconds_since(record.get("created_at")),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _credentials_status(name: str, ptype: str) -> str:
    if ptype == "ollama":
        return "n/a"
    if ptype == "bedrock":
        access, secret = get_provider_aws_credentials(name)
        if access and secret:
            return "set"
        if access or secret:
            return "partial"
        return "unset"
    api_key = get_provider_api_key(name)
    return "set" if api_key else "unset"


def _read_secret_from_stdin(flag: str) -> str:
    data = sys.stdin.read()
    value = data.strip("\n").rstrip("\r")
    if not value:
        emit_error(
            f"empty value on stdin for {flag}",
            hint=f"pipe a non-empty value into {flag}",
        )
    return value


def _resolve_api_key(
    api_key: Optional[str],
    api_key_stdin: bool,
    *,
    required: bool = True,
) -> Optional[str]:
    if api_key_stdin and api_key:
        emit_error(
            "cannot combine --api-key with --api-key-stdin",
            hint="pass exactly one",
        )
    if api_key_stdin:
        return _read_secret_from_stdin("--api-key-stdin")
    if api_key:
        return api_key
    if not required:
        return None
    if not stdin_is_tty():
        emit_error(
            "missing required flag --api-key",
            hint="pass --api-key or --api-key-stdin",
        )
    return typer.prompt("API key", hide_input=True)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@provider_registry_app.command("create")
def create(
    name: str = typer.Argument(..., help="Unique provider name."),
    provider_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Provider type (anthropic, openai, bedrock, opencode, opencode-go, ollama, ...).",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Default model id."
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="API key for cloud providers."
    ),
    api_key_stdin: bool = typer.Option(
        False, "--api-key-stdin", help="Read API key from stdin."
    ),
    access_key: Optional[str] = typer.Option(
        None, "--access-key", help="AWS access key id (Bedrock)."
    ),
    secret_key: Optional[str] = typer.Option(
        None, "--secret-key", help="AWS secret access key (Bedrock)."
    ),
    region: Optional[str] = typer.Option(
        None, "--region", help="AWS region (Bedrock)."
    ),
    ollama_url: Optional[str] = typer.Option(
        None, "--ollama-url", help="Ollama server URL (Ollama)."
    ),
    litellm_url: Optional[str] = typer.Option(
        None,
        "--litellm-url",
        help="LiteLLM (OpenAI-compatible) proxy URL (LiteLLM).",
    ),
    context_window: Optional[int] = typer.Option(
        None,
        "--context-window",
        help=(
            "Model context window in tokens (LiteLLM only). Honoured by "
            "hermes and openclaw renderers; both fall back to ~65k (65536) "
            "when unset."
        ),
    ),
) -> None:
    """Register a provider non-interactively when flags are supplied."""
    try:
        validate_provider_name(name)
    except InvalidProviderNameError as exc:
        emit_error(str(exc))
    try:
        validate_provider_type(provider_type)
    except InvalidProviderTypeError as exc:
        emit_error(str(exc))

    # #831: --context-window is litellm-only (same pattern as
    # --litellm-url / --ollama-url). Reject upfront so the operator
    # doesn't silently get an ignored value persisted on, e.g., a
    # bedrock record.
    if context_window is not None and provider_type != "litellm":
        emit_error(
            "--context-window only valid for litellm providers",
            hint="omit --context-window for this provider type",
        )
    if context_window is not None and context_window <= 0:
        emit_error(
            "--context-window must be a positive integer",
            hint="pin to the model's actual context window (e.g. 131072)",
        )

    try:
        if get_provider(name):
            emit_error(
                f"provider {name!r} already exists",
                hint="clawctl provider registry describe " + name,
            )
    except ProvidersFileCorruptedError as exc:
        emit_error(str(exc), hint="check ~/.config/clawrium/providers.json")

    now = _now_iso()

    if provider_type == "ollama":
        require_flag(ollama_url, flag="--ollama-url")
        if not ollama_url and stdin_is_tty():
            ollama_url = typer.prompt(
                "Ollama server URL", default="http://localhost:11434"
            )
        try:
            ollama_url = validate_ollama_url(ollama_url or "")
        except InvalidOllamaUrlError as exc:
            emit_error(str(exc))
        try:
            available = fetch_ollama_models(ollama_url)
        except OllamaConnectionError as exc:
            emit_error(str(exc))
        record = {
            "name": name,
            "type": provider_type,
            "endpoint": ollama_url,
            "default_model": model or (available[0] if available else None),
            "available_models": available,
            "created_at": now,
            "updated_at": now,
        }
        try:
            add_provider(record)
        except DuplicateProviderError as exc:
            emit_error(str(exc))
        typer.echo(f"provider/{name}: created (type={provider_type})")
        return

    if provider_type == "litellm":
        require_flag(litellm_url, flag="--litellm-url")
        if not model:
            emit_error(
                "missing required flag --model",
                hint="LiteLLM providers require an explicit model id",
            )
        try:
            litellm_url = validate_litellm_url(litellm_url or "")
        except InvalidLiteLLMUrlError as exc:
            emit_error(str(exc))
        resolved_key = _resolve_api_key(api_key, api_key_stdin)
        if not resolved_key:
            emit_error("API key is required")
        # Probe /v1/models. Failure is non-fatal: the proxy may be off
        # at create-time; operators can rerun `provider registry
        # refresh` once it's up.
        try:
            available = fetch_litellm_models(litellm_url, resolved_key)
        except LiteLLMConnectionError as exc:
            typer.echo(
                f"warning: could not list models from proxy: {exc}",
                err=True,
            )
            available = []
        record = {
            "name": name,
            "type": provider_type,
            "endpoint": litellm_url,
            "default_model": model,
            "available_models": available,
            "created_at": now,
            "updated_at": now,
        }
        # #831: persist operator-supplied context_window so render_hermes
        # / render_openclaw emit it on the next configure / sync. Same
        # field is shared by both render paths.
        if context_window is not None:
            record["context_window"] = context_window
        try:
            add_provider(record)
        except DuplicateProviderError as exc:
            emit_error(str(exc))
        set_provider_api_key(name, resolved_key)
        typer.echo(f"provider/{name}: created (type={provider_type})")
        return

    if provider_type == "bedrock":
        require_flag(access_key, flag="--access-key")
        require_flag(secret_key, flag="--secret-key")
        if not access_key and stdin_is_tty():
            access_key = typer.prompt("AWS Access Key ID", hide_input=True)
        if not secret_key and stdin_is_tty():
            secret_key = typer.prompt("AWS Secret Access Key", hide_input=True)
        if not access_key or not secret_key:
            emit_error("AWS access key and secret key are required for Bedrock")
        record = {
            "name": name,
            "type": provider_type,
            "default_model": model,
            "created_at": now,
            "updated_at": now,
        }
        if region:
            record["region"] = region
        try:
            add_provider(record)
        except DuplicateProviderError as exc:
            emit_error(str(exc))
        set_provider_aws_credentials(name, access_key, secret_key)
        typer.echo(f"provider/{name}: created (type={provider_type})")
        return

    # OpenCode hosted providers: default endpoint is part of the provider
    # contract; persist it so renderers don't have to re-derive it from
    # PROVIDER_MODELS on every configure/sync.
    if provider_type in ("opencode", "opencode-go"):
        resolved_key = _resolve_api_key(api_key, api_key_stdin)
        if not resolved_key:
            emit_error("API key is required")
        endpoint = PROVIDER_MODELS.get(provider_type, {}).get("endpoint", "")
        record = {
            "name": name,
            "type": provider_type,
            "endpoint": endpoint,
            "default_model": model,
            "created_at": now,
            "updated_at": now,
        }
        try:
            add_provider(record)
        except DuplicateProviderError as exc:
            emit_error(str(exc))
        set_provider_api_key(name, resolved_key)
        typer.echo(f"provider/{name}: created (type={provider_type})")
        return

    # Cloud provider with API key.
    resolved_key = _resolve_api_key(api_key, api_key_stdin)
    if not resolved_key:
        emit_error("API key is required")
    record = {
        "name": name,
        "type": provider_type,
        "default_model": model,
        "created_at": now,
        "updated_at": now,
    }
    try:
        add_provider(record)
    except DuplicateProviderError as exc:
        emit_error(str(exc))
    set_provider_api_key(name, resolved_key)
    typer.echo(f"provider/{name}: created (type={provider_type})")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@provider_registry_app.command("get")
def get(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format."
    ),
    types: bool = typer.Option(
        False,
        "--types",
        help="List supported provider types (catalog) instead of records.",
    ),
    no_headers: bool = typer.Option(
        False, "--no-headers", help="Skip the header row (table modes)."
    ),
) -> None:
    """List providers (default) or supported provider types (`--types`)."""
    if types:
        _emit_types(output, no_headers=no_headers)
        return

    rows = [_provider_to_row(p) for p in _safe_load_providers()]

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
        headers = ["NAME", "TYPE", "MODEL", "ENDPOINT", "CREDENTIALS"]
        body = [
            [
                str(r["name"]),
                str(r["type"]),
                str(r["model"] or "-"),
                str(r["endpoint"] or "-"),
                str(r["credentials"]),
            ]
            for r in rows
        ]
    else:
        headers = ["NAME", "TYPE", "MODEL", "CREDENTIALS"]
        body = [
            [
                str(r["name"]),
                str(r["type"]),
                str(r["model"] or "-"),
                str(r["credentials"]),
            ]
            for r in rows
        ]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


def _emit_types(output: OutputFormat, *, no_headers: bool) -> None:
    from clawrium.core.providers.models import get_model_count

    rows = [
        {
            "kind": "provider-type",
            "name": ptype,
            "endpoint": (cfg.get("endpoint") or ""),
            "model_count": (
                0 if ptype == "ollama" else get_model_count(ptype)
            ),
        }
        for ptype, cfg in sorted(PROVIDER_MODELS.items())
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
    headers = ["NAME", "ENDPOINT", "MODELS"]
    body = [
        [str(r["name"]), str(r["endpoint"] or "-"), str(r["model_count"] or "-")]
        for r in rows
    ]
    typer.echo(render_table(headers, body, no_headers=no_headers), nl=False)


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


@provider_registry_app.command("describe")
def describe(
    name: str = typer.Argument(..., help="Provider name."),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format (table|json|yaml)."
    ),
) -> None:
    """Show full details of a provider."""
    record = _safe_get_provider(name)
    row = _provider_to_row(record)

    if output is OutputFormat.json:
        typer.echo(dump_json([row]), nl=False)
        return
    if output is OutputFormat.yaml:
        typer.echo(dump_yaml([row]), nl=False)
        return

    typer.echo(f"Name:         {row['name']}")
    typer.echo("Kind:         provider")
    typer.echo(f"Type:         {row['type']}")
    typer.echo(f"Model:        {row['model'] or '-'}")
    if row["endpoint"]:
        typer.echo(f"Endpoint:     {row['endpoint']}")
    typer.echo(f"Credentials:  {row['credentials']}")
    if row.get("created_at"):
        typer.echo(f"Created:      {row['created_at']}")
    if row.get("updated_at"):
        typer.echo(f"Updated:      {row['updated_at']}")
    available = record.get("available_models") or []
    if available:
        typer.echo(f"Models ({len(available)}):")
        for m in available:
            typer.echo(f"  - {m}")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@provider_registry_app.command("delete")
def delete(
    name: str = typer.Argument(..., help="Provider name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a provider record and its stored credentials."""
    record = _safe_get_provider(name)
    confirm_destructive(prompt=f"Delete provider {name!r}?", yes=yes)
    ptype = record.get("type")
    if not remove_provider(name):
        emit_error(f"failed to delete provider {name!r}")
    if ptype == "bedrock":
        remove_provider_aws_credentials(name)
    elif ptype != "ollama":
        remove_provider_api_key(name)
    typer.echo(f"provider/{name}: deleted")


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@provider_registry_app.command("edit")
def edit(
    name: str = typer.Argument(..., help="Provider name."),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="New default model id."
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="New API key (cloud provider)."
    ),
    api_key_stdin: bool = typer.Option(
        False, "--api-key-stdin", help="Read new API key from stdin."
    ),
    access_key: Optional[str] = typer.Option(
        None, "--access-key", help="New AWS access key id (Bedrock)."
    ),
    secret_key: Optional[str] = typer.Option(
        None, "--secret-key", help="New AWS secret access key (Bedrock)."
    ),
    region: Optional[str] = typer.Option(
        None, "--region", help="New AWS region (Bedrock)."
    ),
    ollama_url: Optional[str] = typer.Option(
        None, "--ollama-url", help="New Ollama server URL (Ollama)."
    ),
    litellm_url: Optional[str] = typer.Option(
        None,
        "--litellm-url",
        help="New LiteLLM proxy URL (LiteLLM).",
    ),
    context_window: Optional[int] = typer.Option(
        None,
        "--context-window",
        help=(
            "Model context window in tokens (LiteLLM only). Honoured by "
            "hermes and openclaw renderers; re-render with `clawctl agent "
            "sync` to push the new value to the agent host."
        ),
    ),
) -> None:
    """Edit an existing provider record."""
    record = _safe_get_provider(name)
    ptype = record.get("type")

    if not any(
        [
            model,
            api_key,
            api_key_stdin,
            access_key,
            secret_key,
            region,
            ollama_url,
            litellm_url,
            context_window is not None,
        ]
    ):
        emit_error(
            "no changes specified",
            hint=(
                "pass --model / --api-key / --access-key / --secret-key / "
                "--region / --ollama-url / --litellm-url / --context-window"
            ),
        )

    # #831: --context-window is litellm-only. Reject upfront on the
    # existing record's type (mirrors --litellm-url gating below).
    if context_window is not None:
        if ptype != "litellm":
            emit_error(
                "--context-window only valid for litellm providers",
                hint=f"provider {name!r} is type {ptype!r}",
            )
        if context_window <= 0:
            emit_error(
                "--context-window must be a positive integer",
                hint="pin to the model's actual context window (e.g. 131072)",
            )

    available: Optional[list[str]] = None
    if ollama_url is not None:
        if ptype != "ollama":
            emit_error("--ollama-url only valid for ollama providers")
        try:
            ollama_url = validate_ollama_url(ollama_url)
        except InvalidOllamaUrlError as exc:
            emit_error(str(exc))
        try:
            available = fetch_ollama_models(ollama_url)
        except OllamaConnectionError as exc:
            emit_error(str(exc))

    if litellm_url is not None:
        if ptype != "litellm":
            emit_error("--litellm-url only valid for litellm providers")
        try:
            litellm_url = validate_litellm_url(litellm_url)
        except InvalidLiteLLMUrlError as exc:
            emit_error(str(exc))
        # Re-probe /v1/models using the new key (if supplied) or the
        # currently-stored one. Probe failure surfaces as a warning so
        # an `edit` doesn't fail just because the proxy is offline.
        probe_key = (
            api_key if api_key else (None if api_key_stdin else get_provider_api_key(name))
        )
        if probe_key:
            try:
                available = fetch_litellm_models(litellm_url, probe_key)
            except LiteLLMConnectionError as exc:
                typer.echo(
                    f"warning: could not list models from proxy: {exc}",
                    err=True,
                )
                available = None

    new_api_key: Optional[str] = None
    if api_key or api_key_stdin:
        if ptype in ("ollama", "bedrock"):
            emit_error(f"--api-key is not valid for {ptype} providers")
        new_api_key = _resolve_api_key(api_key, api_key_stdin, required=True)

    if access_key or secret_key:
        if ptype != "bedrock":
            emit_error("--access-key/--secret-key only valid for bedrock providers")
        if not (access_key and secret_key):
            emit_error(
                "both --access-key and --secret-key are required when updating AWS creds"
            )

    if region and ptype != "bedrock":
        emit_error("--region only valid for bedrock providers")

    def apply(p: dict) -> dict:
        if model is not None:
            p["default_model"] = model
        if ollama_url is not None:
            p["endpoint"] = ollama_url
            if available is not None:
                p["available_models"] = available
        if litellm_url is not None:
            p["endpoint"] = litellm_url
            if available is not None:
                p["available_models"] = available
        if region:
            p["region"] = region
        # #831: persist litellm context_window override. The next
        # `clawctl agent sync` for any hermes/openclaw agent attached
        # to this provider will re-render with the new value.
        if context_window is not None:
            p["context_window"] = context_window
        p["updated_at"] = _now_iso()
        return p

    if not update_provider(name, apply):
        emit_error(f"failed to update provider {name!r}")

    if new_api_key is not None:
        set_provider_api_key(name, new_api_key)
    if access_key and secret_key:
        set_provider_aws_credentials(name, access_key, secret_key)

    typer.echo(f"provider/{name}: updated")


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


@provider_registry_app.command("refresh")
def refresh(
    name: str = typer.Argument(
        ..., help="Endpoint-backed provider name (ollama or litellm) to refresh."
    ),
) -> None:
    """Refresh available models from an endpoint-backed provider.

    Works for Ollama (hits /api/tags) and LiteLLM (hits /v1/models with
    the stored bearer key).
    """
    record = _safe_get_provider(name)
    ptype = record.get("type")
    if ptype not in ("ollama", "litellm"):
        emit_error(
            f"refresh only applies to ollama/litellm providers (got {ptype!r})",
            hint="this is a no-op for cloud providers",
        )
    endpoint = record.get("endpoint")
    if not endpoint:
        emit_error(f"provider {name!r} has no endpoint configured")

    if ptype == "ollama":
        try:
            available = fetch_ollama_models(endpoint)
        except OllamaConnectionError as exc:
            emit_error(str(exc))
    else:  # litellm
        stored_key = get_provider_api_key(name)
        if not stored_key:
            emit_error(
                f"provider {name!r} has no stored API key",
                hint=f"clawctl provider registry edit {name} --api-key …",
            )
        try:
            available = fetch_litellm_models(endpoint, stored_key)
        except LiteLLMConnectionError as exc:
            emit_error(str(exc))

    def apply(p: dict) -> dict:
        p["available_models"] = available
        p["updated_at"] = _now_iso()
        return p

    if not update_provider(name, apply):
        emit_error(f"failed to refresh provider {name!r}")
    typer.echo(f"provider/{name}: refreshed ({len(available)} models)")


# Register sub-group.
provider_app.add_typer(provider_registry_app, name="registry")

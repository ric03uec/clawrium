"""Deterministic render-input assembly and pure rendering for agent configs.

This module is the F1+F2 scaffolding for parent issue #555. It is the
single source of truth for the canonical agent-config bundle:

1. `build_render_inputs(agent_name)` assembles `RenderInputs` from
   clawctl's own stores (providers.json + channels.json +
   integrations.json + secrets.json + hosts.json attachment lists).
   Any unresolved attachment raises `AgentConfigError` — there is no
   "skip on missing" branch. This is the rule restated by #555's TL;DR.

2. `render_hermes` / `render_zeroclaw` / `render_openclaw` are pure
   functions of `RenderInputs` returning `RenderedFiles`. Templates
   branch ONLY on `provider.type` (the value that comes from the
   registry). They DO NOT branch on "is field X populated" — every
   declared input flows to exactly one declared output. The functions
   are also byte-deterministic: same inputs → byte-identical bytes.

The module is intentionally NOT wired into `lifecycle.py` yet (see
#555 plan F3+); that wiring lands in a follow-up. The contract here
must stand alone so it can be exercised by unit + property tests
before any production code paths depend on it.
"""

from __future__ import annotations

import functools as _functools
import re
from dataclasses import dataclass, field

__all__ = [
    "AgentConfigError",
    "ProviderInputs",
    "ChannelInputs",
    "IntegrationInputs",
    "APIServerInputs",
    "GatewayInputs",
    "RenderInputs",
    "RenderedFiles",
    "build_render_inputs",
    "render_hermes",
    "render_zeroclaw",
    "render_openclaw",
]


# Provider types whose API key is stored as a single bearer secret in
# secrets.json. Each one MUST also appear in the per-renderer support
# table below so a successful `build_render_inputs` cannot hand the
# renderer a provider it does not know how to emit. The renderers
# enforce this with explicit raises.
#
# `vertex` is intentionally absent: GCP service-account auth uses a
# filesystem path (`GOOGLE_APPLICATION_CREDENTIALS=/path/to.json`),
# not a bearer string. Conflating the two would silently produce a
# broken on-host config. Vertex support belongs in a follow-up that
# extends the schema with a credential-kind field.
_BEARER_API_KEY_TYPES = frozenset({"openrouter", "anthropic", "openai", "zai"})
_LOCAL_ENDPOINT_TYPES = frozenset({"ollama"})

# Per-agent-type supported provider sets. `build_render_inputs` checks
# this so a hermes agent attached to a zai-only provider fails up-front
# instead of crashing later inside `render_hermes`. The membership
# matches the renderer dispatch tables further below.
_AGENT_TYPE_PROVIDER_SUPPORT: dict[str, frozenset[str]] = {
    "hermes": frozenset({"openrouter", "anthropic", "openai", "bedrock", "ollama"}),
    "zeroclaw": frozenset({"openrouter", "anthropic", "openai", "ollama"}),
    "openclaw": frozenset(
        {"openrouter", "anthropic", "openai", "bedrock", "ollama", "zai"}
    ),
}


def _clean_secret(value: str | None) -> str:
    """Strip NUL/CR/LF from a secret before any truthiness check.

    A NUL-only string (`'\\x00'`) is truthy in Python but causes
    systemd's `EnvironmentFile` reader to silently truncate at the
    NUL — every subsequent var is dropped from the unit's environment
    with no error. CR/LF can split the value across lines and inject
    arbitrary keys. Sanitize before guarding so a degenerate secret is
    treated as missing, not "present but corrupt".
    """
    if not value:
        return ""
    return value.replace("\x00", "").replace("\r", "").replace("\n", "")


class AgentConfigError(Exception):
    """Raised when a declared attachment cannot be resolved.

    `build_render_inputs` raises this on any missing provider record,
    missing secret, missing channel record, or missing integration —
    never silently skips. The message names the failed lookup so the
    operator can fix the underlying record (provider attach, channel
    create, secret set, etc.) and re-run.
    """


# ---------------------------------------------------------------------------
# Typed inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderInputs:
    name: str
    type: str
    endpoint: str = ""
    default_model: str = ""
    region: str = ""
    api_key: str = ""
    aws_access_key: str = ""
    aws_secret_key: str = ""


@dataclass(frozen=True)
class AuxiliaryProviderInputs:
    """One non-primary provider attachment on a hermes agent (#614).

    `role` is one of `provider_attachments.AUXILIARY_SLOTS` (e.g.
    `vision`, `title_generation`). `model` is the per-attachment
    override; the renderer reads exactly this field so attachment-time
    `--model X` reaches the rendered config without further fallback
    logic at template time.

    Credential fields mirror `ProviderInputs` so a bedrock auxiliary
    carrying its own AWS triplet is representable. For dedup at env-var
    emission time the type field is the join key.
    """

    name: str
    type: str
    role: str
    model: str = ""
    api_key: str = ""
    aws_access_key: str = ""
    aws_secret_key: str = ""
    region: str = ""


@dataclass(frozen=True)
class ChannelInputs:
    name: str
    type: str
    bot_token: str = ""
    app_token: str = ""
    allowed_users: tuple[str, ...] = ()
    allowed_guilds: tuple[str, ...] = ()
    allowed_channels: tuple[str, ...] = ()
    require_mention: bool = True
    allow_all_users: bool = False
    stream_mode: str = ""
    home_channel: str = ""
    home_channel_name: str = ""
    home_channel_thread_id: str = ""


@dataclass(frozen=True)
class IntegrationInputs:
    name: str
    type: str
    # Sorted tuple of (key, value) for deterministic iteration.
    credentials: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class APIServerInputs:
    host: str
    port: int
    key: str


@dataclass(frozen=True)
class GatewayInputs:
    host: str = ""
    port: int = 0
    auth: str = ""
    bind: str = ""
    allow_public_bind: bool = True


@dataclass(frozen=True)
class RenderInputs:
    agent_name: str
    agent_type: str
    provider: ProviderInputs
    channels: tuple[ChannelInputs, ...] = ()
    integrations: tuple[IntegrationInputs, ...] = ()
    api_server: APIServerInputs | None = None
    gateway: GatewayInputs | None = None
    # #614: non-primary provider attachments on multi-provider agent
    # types (hermes only today). Empty tuple for singleton agent types
    # and for hermes agents with only a primary attached — the renderer
    # falls through to the existing single-provider path.
    auxiliary_providers: tuple[AuxiliaryProviderInputs, ...] = ()


@dataclass(frozen=True)
class RenderedFiles:
    """Bytes-equivalent string contents of every on-host config file.

    Files are addressed by their relative path under the agent's home
    directory on the host (e.g. `.hermes/.env`, `.hermes/config.yaml`).
    """

    files: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Keys must be deterministically ordered; coerce to a sorted
        # dict so callers comparing `rendered.files == rendered.files`
        # across two invocations don't accidentally pass on dict-order
        # differences before Python 3.7's insertion-order guarantee
        # would otherwise mask a real drift.
        object.__setattr__(
            self,
            "files",
            dict(sorted(self.files.items())),
        )


# ---------------------------------------------------------------------------
# Assembly: build_render_inputs
# ---------------------------------------------------------------------------


def build_render_inputs(agent_name: str) -> RenderInputs:
    """Assemble the canonical render bundle for one agent.

    Resolves the agent via `hosts.json`, then loads the full provider /
    channel / integration / secret records from clawctl's own stores.
    Any missing attachment raises `AgentConfigError`.

    No "if attached then include" branches: this function iterates the
    declared attachment lists and raises on any unresolved name.
    """
    # Imports are deferred so the module is import-cheap for tests that
    # patch the data-layer functions.
    from clawrium.core.channels import (
        get_agent_channels,
        get_channel,
        get_channel_token,
    )
    from clawrium.core.hosts import get_agent_by_name
    from clawrium.core.integrations import (
        INTEGRATION_TYPES,
        get_agent_integrations,
        get_integration,
        get_integration_credentials,
    )
    from clawrium.core.provider_attachments import (
        normalize as normalize_attachments,
    )
    from clawrium.core.providers import (
        get_provider,
        get_provider_api_key,
        get_provider_aws_credentials,
    )

    resolved = get_agent_by_name(agent_name)
    if resolved is None:
        raise AgentConfigError(
            f"agent {agent_name!r} not found in any host record"
        )
    host_record, agent_type, agent_record = resolved
    hostname = host_record.get("hostname") or ""
    # `get_agent_by_name` returns the dict-key match; the canonical
    # agent_key used by channel / integration lookups is the same value
    # the caller passed in (an agent is uniquely keyed by name in
    # `host["agents"]`).
    agent_key = agent_record.get("agent_name") or agent_name

    # --- Provider ----------------------------------------------------------
    raw_attachments = agent_record.get("providers") or []
    attachments = normalize_attachments(raw_attachments, agent_type)
    if not attachments:
        raise AgentConfigError(
            f"agent {agent_name!r} has no provider attached; "
            f"run `clawctl agent provider attach <provider> --agent {agent_name}` first"
        )

    # Pick the primary attachment. For hermes this is the entry whose
    # role == 'primary'; for single-provider agent types it's the only
    # entry. Either way the result is a single provider name.
    primary_name: str | None = None
    for entry in attachments:
        if isinstance(entry, dict):
            if entry.get("role") == "primary":
                primary_name = entry.get("name")
                break
        elif isinstance(entry, str):
            primary_name = entry
            break
    if not primary_name:
        raise AgentConfigError(
            f"agent {agent_name!r} attachments do not yield a primary provider"
        )

    provider_record = get_provider(primary_name)
    if provider_record is None:
        raise AgentConfigError(
            f"provider {primary_name!r} attached to agent {agent_name!r} "
            f"is not registered in providers.json"
        )
    raw_type = provider_record.get("type")
    provider_type = (raw_type or "").strip() if isinstance(raw_type, str) else ""
    if not provider_type:
        raise AgentConfigError(
            f"provider {primary_name!r} has no type field"
        )

    # Per-agent-type provider compatibility gate. Catches misconfigurations
    # like a hermes agent attached to a zai provider (which only openclaw
    # renders) BEFORE the renderer fails with a less-actionable message.
    supported = _AGENT_TYPE_PROVIDER_SUPPORT.get(agent_type, frozenset())
    if provider_type not in supported:
        raise AgentConfigError(
            f"agent {agent_name!r} (type {agent_type}) does not support "
            f"provider type {provider_type!r}. "
            f"Supported types for {agent_type}: {sorted(supported)}"
        )

    api_key = ""
    aws_access_key = ""
    aws_secret_key = ""
    if provider_type == "bedrock":
        ak, sk = get_provider_aws_credentials(primary_name)
        ak = _clean_secret(ak)
        sk = _clean_secret(sk)
        if not ak or not sk:
            raise AgentConfigError(
                f"bedrock provider {primary_name!r} is missing AWS credentials "
                f"in secrets.json (expected AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY)"
            )
        aws_access_key = ak
        aws_secret_key = sk
    elif provider_type in _BEARER_API_KEY_TYPES:
        key = _clean_secret(get_provider_api_key(primary_name))
        if not key:
            raise AgentConfigError(
                f"provider {primary_name!r} (type {provider_type}) is missing "
                f"API key in secrets.json"
            )
        api_key = key
    elif provider_type in _LOCAL_ENDPOINT_TYPES:
        # Local providers (ollama) need an endpoint, not an API key.
        if not provider_record.get("endpoint"):
            raise AgentConfigError(
                f"provider {primary_name!r} (type {provider_type}) is missing "
                f"endpoint in providers.json"
            )
    else:
        # _AGENT_TYPE_PROVIDER_SUPPORT already filtered unsupported types
        # for the requested agent type. A miss here means a supported
        # type was added to the per-agent table without wiring its
        # credential fetch — fail loudly so the next reviewer notices.
        raise AgentConfigError(
            f"provider {primary_name!r} has type {provider_type!r} which is "
            f"declared supported for agent {agent_type} but has no credential "
            f"fetch wired in build_render_inputs"
        )

    provider = ProviderInputs(
        name=primary_name,
        type=provider_type,
        endpoint=provider_record.get("endpoint", "") or "",
        default_model=provider_record.get("default_model", "") or "",
        region=provider_record.get("region", "") or "",
        api_key=api_key,
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key,
    )

    # --- Auxiliary providers (#614) ---------------------------------------
    # Non-primary attachments on multi-provider agent types (hermes only
    # today). Each gets its own credential fetch so the env template can
    # emit one *_API_KEY per unique type and the YAML template can emit a
    # per-attachment `auxiliary.<role>:` block.
    # ATX iter-1 B1: validate role against the canonical AUXILIARY_SLOTS
    # tuple. The canonical `agent sync` caller does NOT first call
    # `provider_attachments.validate()`, so without this check a
    # hand-edited hosts.json with `"role": "vision:\n  malicious_key"`
    # would flow straight into a bare YAML key in `auxiliary.<role>:`
    # and inject arbitrary structure into the rendered config. The
    # legacy ansible path is already gated by `_pa.validate()` upstream.
    from clawrium.core.provider_attachments import AUXILIARY_SLOTS

    auxiliary_provider_inputs: list[AuxiliaryProviderInputs] = []
    seen_aux_roles: set[str] = set()
    for entry in attachments:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role", "")
        if not role or role == "primary":
            continue
        if role not in AUXILIARY_SLOTS:
            raise AgentConfigError(
                f"auxiliary attachment on agent {agent_name!r} has invalid "
                f"role {role!r}; expected one of {sorted(AUXILIARY_SLOTS)}"
            )
        # Uniqueness gate. `_pa.validate()` enforces this on the legacy
        # path; mirror it here so a duplicate-role hosts.json does not
        # render two `auxiliary.<role>:` keys (PyYAML silently
        # last-wins) on the canonical sync path.
        if role in seen_aux_roles:
            raise AgentConfigError(
                f"auxiliary attachments on agent {agent_name!r} reuse role "
                f"{role!r}; each auxiliary slot must appear at most once"
            )
        seen_aux_roles.add(role)
        aux_name = entry.get("name") or ""
        if not aux_name:
            continue
        aux_record = get_provider(aux_name)
        if aux_record is None:
            raise AgentConfigError(
                f"auxiliary provider {aux_name!r} (role {role!r}) attached to "
                f"agent {agent_name!r} is not registered in providers.json"
            )
        raw_aux_type = aux_record.get("type")
        aux_type = (
            (raw_aux_type or "").strip() if isinstance(raw_aux_type, str) else ""
        )
        if not aux_type:
            raise AgentConfigError(
                f"auxiliary provider {aux_name!r} has no type field"
            )
        if aux_type not in supported:
            raise AgentConfigError(
                f"agent {agent_name!r} (type {agent_type}) does not support "
                f"auxiliary provider type {aux_type!r}. "
                f"Supported types for {agent_type}: {sorted(supported)}"
            )
        aux_api_key = ""
        aux_aws_access = ""
        aux_aws_secret = ""
        if aux_type == "bedrock":
            ak, sk = get_provider_aws_credentials(aux_name)
            ak = _clean_secret(ak)
            sk = _clean_secret(sk)
            if not ak or not sk:
                raise AgentConfigError(
                    f"bedrock auxiliary provider {aux_name!r} (role {role!r}) is "
                    f"missing AWS credentials in secrets.json"
                )
            aux_aws_access = ak
            aux_aws_secret = sk
        elif aux_type in _BEARER_API_KEY_TYPES:
            key = _clean_secret(get_provider_api_key(aux_name))
            if not key:
                raise AgentConfigError(
                    f"auxiliary provider {aux_name!r} (role {role!r}, type "
                    f"{aux_type}) is missing API key in secrets.json"
                )
            aux_api_key = key
        elif aux_type in _LOCAL_ENDPOINT_TYPES:
            if not aux_record.get("endpoint"):
                raise AgentConfigError(
                    f"auxiliary provider {aux_name!r} (type {aux_type}) is "
                    f"missing endpoint in providers.json"
                )
        attachment_model = entry.get("model") or aux_record.get("default_model", "")
        auxiliary_provider_inputs.append(
            AuxiliaryProviderInputs(
                name=aux_name,
                type=aux_type,
                role=role,
                model=attachment_model or "",
                api_key=aux_api_key,
                aws_access_key=aux_aws_access,
                aws_secret_key=aux_aws_secret,
                region=aux_record.get("region", "") or "",
            )
        )
    # Sort by role for byte-determinism. Roles are unique per validate().
    auxiliary_provider_inputs.sort(key=lambda p: p.role)

    # --- Channels ----------------------------------------------------------
    channel_inputs: list[ChannelInputs] = []
    for channel_name in get_agent_channels(hostname, agent_key):
        record = get_channel(channel_name)
        if record is None:
            raise AgentConfigError(
                f"channel {channel_name!r} attached to agent {agent_name!r} "
                f"is not registered in channels.json"
            )
        channel_type = record.get("type") or ""
        bot_token = _clean_secret(get_channel_token(channel_name, "BOT_TOKEN"))
        if not bot_token:
            raise AgentConfigError(
                f"channel {channel_name!r} (type {channel_type}) is missing BOT_TOKEN in secrets.json"
            )
        app_token = ""
        if channel_type == "slack":
            app_token = _clean_secret(get_channel_token(channel_name, "APP_TOKEN"))
            if not app_token:
                raise AgentConfigError(
                    f"slack channel {channel_name!r} is missing APP_TOKEN in secrets.json"
                )
        cfg = record.get("config") or {}
        channel_inputs.append(
            ChannelInputs(
                name=channel_name,
                type=channel_type,
                bot_token=bot_token,
                app_token=app_token,
                allowed_users=tuple(cfg.get("allowed_users", []) or []),
                allowed_guilds=tuple(cfg.get("allowed_guilds", []) or []),
                allowed_channels=tuple(cfg.get("allowed_channels", []) or []),
                require_mention=bool(cfg.get("require_mention", True)),
                allow_all_users=bool(cfg.get("allow_all_users", False)),
                stream_mode=str(cfg.get("stream_mode", "") or ""),
                home_channel=str(cfg.get("home_channel", "") or ""),
                home_channel_name=str(cfg.get("home_channel_name", "") or ""),
                home_channel_thread_id=str(
                    cfg.get("home_channel_thread_id", "") or ""
                ),
            )
        )
    # Sort by name for byte-determinism.
    channel_inputs.sort(key=lambda c: c.name)

    # --- Integrations ------------------------------------------------------
    integration_inputs: list[IntegrationInputs] = []
    for integration_name in get_agent_integrations(hostname, agent_key):
        record = get_integration(integration_name)
        if record is None:
            raise AgentConfigError(
                f"integration {integration_name!r} attached to agent {agent_name!r} "
                f"is not registered in integrations.json"
            )
        integration_type = record.get("type") or ""
        raw_creds = get_integration_credentials(integration_name)
        # Apply NUL/CR/LF sanitization before the required-field truthiness
        # gate so a degenerate secret reads as missing, not present-but-corrupt.
        creds_map = {k: _clean_secret(v) for k, v in raw_creds.items()}
        # Verify every REQUIRED credential is present (and non-degenerate).
        type_spec = INTEGRATION_TYPES.get(integration_type, {}) or {}
        for cred_spec in type_spec.get("credentials", []) or []:
            if cred_spec.get("required") and not creds_map.get(cred_spec["key"]):
                raise AgentConfigError(
                    f"integration {integration_name!r} (type {integration_type}) "
                    f"is missing required credential {cred_spec['key']!r} in secrets.json"
                )
        integration_inputs.append(
            IntegrationInputs(
                name=integration_name,
                type=integration_type,
                credentials=tuple(sorted(creds_map.items())),
            )
        )
    integration_inputs.sort(key=lambda i: i.name)

    # --- API server / gateway (per-instance config knobs) -----------------
    config_blob = agent_record.get("config") or {}
    api_server_input: APIServerInputs | None = None
    api_server_blob = config_blob.get("api_server")
    if isinstance(api_server_blob, dict):
        # Hermes API_SERVER_KEY lives in secrets.json (install.py:1138-1145
        # writes only the non-sensitive shape to hosts.json by design). The
        # legacy configure_agent path hydrates it at lifecycle.py:1695; the
        # canonical render path must do the same or every `agent sync`
        # writes `API_SERVER_KEY=''` into ~/.hermes/.env and the gateway
        # refuses to bind a wildcard interface without a key (#582).
        key_value = _clean_secret(api_server_blob.get("key"))
        if not key_value and agent_type == "hermes":
            from clawrium.core.install import _is_valid_hermes_api_server_key
            from clawrium.core.secrets import (
                get_instance_key,
                get_instance_secrets,
            )

            instance_key = get_instance_key(
                host_record.get("key_id") or hostname,
                "hermes",
                agent_key,
            )
            entry = get_instance_secrets(instance_key).get(
                "HERMES_API_SERVER_KEY"
            )
            candidate = entry.get("value") if entry else None
            if _is_valid_hermes_api_server_key(candidate):
                key_value = _clean_secret(candidate)
        api_server_input = APIServerInputs(
            host=str(api_server_blob.get("host", "")),
            port=int(api_server_blob.get("port", 0) or 0),
            # `key` is the bearer the gateway enforces; a NUL byte would
            # silently truncate the systemd EnvironmentFile after
            # API_SERVER_KEY=, dropping every var below it. Sanitize at
            # assembly time, same as provider/channel/integration secrets.
            key=key_value,
        )

    gateway_input: GatewayInputs | None = None
    gateway_blob = config_blob.get("gateway")
    if isinstance(gateway_blob, dict):
        # #576: zeroclaw's daemon refuses an empty `gateway.host`
        # (`required_field_empty: gateway.host must not be empty`), so a
        # missing/empty/whitespace-only value here would render
        # `host = ""` (or `host = "   "`) in config.toml and brick
        # `clawctl agent configure` on every fresh install. Default to
        # `0.0.0.0` per the documented `features.web_ui.bind: wildcard`
        # contract in AGENTS.md.
        #
        # `.strip()` catches whitespace-only values that `_clean_secret`
        # does not (it strips NUL/CR/LF only). The default only fires
        # for zeroclaw in practice — `render_hermes` and the openclaw
        # renderer never read `inputs.gateway.host`, so applying the
        # default unconditionally here is safe and keeps the assembler
        # agent-type-agnostic.
        host_raw = _clean_secret(gateway_blob.get("host")).strip()
        gateway_input = GatewayInputs(
            # W6 (ATX #555 polish): NUL in host value would silently
            # truncate the TOML at parse time. Sanitize at assembly
            # time, same as every other secret/identity string from
            # hosts.json.
            host=host_raw or "0.0.0.0",
            port=int(gateway_blob.get("port", 0) or 0),
            # Same systemd-truncation hazard as api_server.key above.
            auth=_clean_secret(gateway_blob.get("auth")),
            bind=str(gateway_blob.get("bind", "")),
            allow_public_bind=bool(gateway_blob.get("allow_public_bind", True)),
        )

    return RenderInputs(
        agent_name=agent_name,
        agent_type=agent_type,
        provider=provider,
        channels=tuple(channel_inputs),
        integrations=tuple(integration_inputs),
        api_server=api_server_input,
        gateway=gateway_input,
        auxiliary_providers=tuple(auxiliary_provider_inputs),
    )


# ---------------------------------------------------------------------------
# Pure renderers
# ---------------------------------------------------------------------------


def _shell_quote(value: str) -> str:
    """POSIX single-quote shell escape. Matches the .env.j2 macro.

    Embeds a single quote in a single-quoted string as: 'val'"'"'ue'.
    Used for systemd EnvironmentFile values so `#` mid-value isn't
    parsed as a comment and arbitrary content can't break the line.

    Strips NUL/CR/LF unconditionally:
    * NUL — silently truncates the systemd EnvironmentFile at the NUL
      byte, dropping every var below it (silent-wipe class, parent
      #555).
    * CR/LF — a single-quoted POSIX string CAN span lines, but systemd
      EnvironmentFile parses one assignment per line; a literal newline
      in any value breaks the assignment grammar (W7 / round-2 B2).
    """
    cleaned = value.replace("\x00", "").replace("\r", "").replace("\n", "")
    return "'" + cleaned.replace("'", "'\"'\"'") + "'"


def _systemd_quote(value: str) -> str:
    """Double-quote escape for systemd Environment= drop-ins.

    Strips NUL (round-2 B3) for the same EnvironmentFile-truncation
    reason as `_shell_quote`. Escapes `$` → `$$` (round-2 W2) because
    systemd performs variable substitution in double-quoted
    `Environment=` values BEFORE handing them to the process — a token
    like `ghp_$SOMETHING` would otherwise be silently corrupted to
    `ghp_` at unit load. Escapes `%` → `%%` (round-3 W2) because
    systemd also performs specifier expansion (`%h`, `%n`, `%u`, etc.)
    in the same pass — a credential containing `%n` would otherwise be
    silently rewritten to the unit name.
    """
    cleaned = value.replace("\x00", "").replace("\r", "").replace("\n", "")
    cleaned = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    cleaned = cleaned.replace("%", "%%").replace("$", "$$")
    return f'"{cleaned}"'


# W4 (ATX #555 polish round 3): the bare `{{ agent_name }}` Jinja
# interpolation is used by the hermes mcp_servers.command path and the
# `# Re-render with `clawctl agent configure {{ agent_name }}`` header
# comment present in every canonical template. Validate at the entry
# point of every renderer (not just hermes) so a future template that
# starts interpolating the name into a sensitive position cannot be
# fed a malicious value via the pure-function API.
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _validate_agent_name(value: object) -> str:
    """Return `value` if it matches the agent_name grammar, else raise.

    Accepts `object` rather than `str` so the round-3 W6 hazard
    (passing `None`) raises `AgentConfigError` instead of `TypeError`
    inside the regex engine.
    """
    if not isinstance(value, str) or not _AGENT_NAME_RE.match(value):
        raise AgentConfigError(
            f"agent_name must match ^[a-z][a-z0-9_-]{{0,31}}$; got "
            f"{value!r}"
        )
    return value


def _toml_escape(value: str) -> str:
    """Escape a value for use inside a TOML basic string.

    Strips NUL (round-2 B1): the TOML spec rejects NUL in basic
    strings and some parsers truncate the string at NUL silently
    rather than erroring. `gateway.host` and `provider.endpoint`
    both flow through this filter, so a NUL anywhere upstream in
    hosts.json would otherwise corrupt the rendered config.toml.
    """
    return (
        value.replace("\x00", "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _yaml_quote(value: str) -> str:
    """Single-quote escape for a YAML scalar.

    Strips NUL / CR / LF first — YAML 1.1/1.2 prohibits NUL inside
    scalars and most parsers silently truncate; CR/LF inside a
    single-quoted scalar produces line-broken output that downstream
    YAML readers (esp. PyYAML's C loader) handle inconsistently.
    """
    cleaned = value.replace("\x00", "").replace("\r", "").replace("\n", "")
    return "'" + cleaned.replace("'", "''") + "'"


def _integration_slug(name: str) -> str:
    """Slug used in per-integration env var names (`GITHUB_TOKEN_<NAME>`)."""
    upper = name.upper().replace("-", "_")
    return "".join(c for c in upper if c.isalnum() or c == "_")


# W4 (ATX round 3): the legacy `_HERMES_PROVIDER_ENV` dispatch table was
# removed in this commit. The Jinja template `hermes-env.canonical.j2`
# is now the only source of truth for provider.type → env-var mapping
# for hermes. The bedrock/ollama branches that previously lived next to
# this table moved into the template alongside their main-bearer peers
# so all five hermes providers share one branching surface.


_HERMES_SUPPORTED_PROVIDERS = frozenset(
    {"openrouter", "anthropic", "openai", "bedrock", "ollama"}
)
_HERMES_SUPPORTED_CHANNELS = frozenset({"discord", "slack"})
_HERMES_SUPPORTED_INTEGRATIONS = frozenset(
    {"github", "atlassian", "linear", "notion", "gitlab", "git"}
)
# Lockstep with hermes' configure.yaml playbook
# (`mcp_atlassian_version: "0.21.1"`). Without this pin in the rendered
# `mcp_servers.<slug>.args` line the daemon's uvx launcher would resolve
# `mcp-atlassian` to latest — divergent from the version `uv tool install`
# installed onto the host, so a fresh tool venv would silently get a
# different MCP build than the one tested.
_HERMES_MCP_ATLASSIAN_VERSION = "0.21.1"


# Per-primary-type default `auxiliary.title_generation.model`. Ollama is
# intentionally absent: the local model is already cheap, so no remote
# aux pin (mirrors the legacy template and the prior canonical branch).
_HERMES_DEFAULT_TITLE_GEN_MODEL: dict[str, str] = {
    "openrouter": "anthropic/claude-haiku-4.5",
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5-nano",
    "bedrock": "anthropic.claude-haiku-4-5-20251001-v1:0",
}


def _build_provider_env_views(
    primary: ProviderInputs,
    auxiliary: tuple[AuxiliaryProviderInputs, ...],
) -> tuple[list[dict], list[dict]]:
    """Return (per-type env views, conflict notices) for hermes-env.canonical.j2.

    One view per unique provider type across primary + auxiliaries.
    Primary wins on same-type-different-key collisions; the collision is
    surfaced as a `# WARNING` line via the conflicts list rather than
    silently dropped (#614 acceptance criterion).

    Bedrock env-var triplet (access/secret/region) ships in `aws_*`
    keys so the template can branch the same way it branches today on
    `provider.type == 'bedrock'`.
    """
    views: list[dict] = []
    seen_type_keys: dict[str, str] = {}
    conflicts: list[dict] = []

    def _add_view(ptype: str, view: dict, key_for_compare: str) -> None:
        prior = seen_type_keys.get(ptype)
        if prior is None:
            seen_type_keys[ptype] = key_for_compare
            views.append(view)
        elif prior != key_for_compare:
            conflicts.append({"type": ptype})

    if primary.type == "bedrock":
        _add_view(
            "bedrock",
            {
                "type": "bedrock",
                "aws_access_key": primary.aws_access_key,
                "aws_secret_key": primary.aws_secret_key,
                "region": primary.region or "us-east-1",
            },
            primary.aws_access_key + "|" + primary.aws_secret_key,
        )
    elif primary.type in _BEARER_API_KEY_TYPES:
        _add_view(
            primary.type,
            {"type": primary.type, "api_key": primary.api_key},
            primary.api_key,
        )
    # ollama: no key emission; HERMES_INFERENCE_PROVIDER='custom' is emitted
    # by the template branch on provider.type directly.

    for aux in auxiliary:
        if aux.type == "bedrock":
            _add_view(
                "bedrock",
                {
                    "type": "bedrock",
                    "aws_access_key": aux.aws_access_key,
                    "aws_secret_key": aux.aws_secret_key,
                    "region": aux.region or "us-east-1",
                },
                aux.aws_access_key + "|" + aux.aws_secret_key,
            )
        elif aux.type in _BEARER_API_KEY_TYPES:
            _add_view(
                aux.type,
                {"type": aux.type, "api_key": aux.api_key},
                aux.api_key,
            )

    return views, conflicts


def _build_aux_yaml_views(
    auxiliary: tuple[AuxiliaryProviderInputs, ...],
) -> list[dict]:
    """Return one dict per non-primary attachment for the YAML template."""
    return [
        {
            "role": aux.role,
            "type": aux.type,
            "model": aux.model,
        }
        for aux in auxiliary
    ]


def render_hermes(inputs: RenderInputs) -> RenderedFiles:
    """Render hermes' on-host config files from canonical inputs.

    Produces:
      - `.hermes/.env`: systemd EnvironmentFile body.
      - `.hermes/config.yaml`: model + auxiliary config.

    Both files are rendered from canonical Jinja templates loaded via
    `importlib.resources` so the wheel ships them. Branches only on
    `inputs.provider.type`. Every field declared on `inputs` flows into
    exactly one output line; the function does NOT conditionally emit a
    section based on whether a hosts.json field happened to be populated.
    """
    _validate_agent_name(inputs.agent_name)

    ptype = inputs.provider.type
    if ptype not in _HERMES_SUPPORTED_PROVIDERS:
        raise AgentConfigError(
            f"render_hermes does not support provider type {ptype!r}. "
            f"Supported: {sorted(_HERMES_SUPPORTED_PROVIDERS)}"
        )

    # B2 (ATX round 4): duplicate-discord/duplicate-slack guard. The
    # hermes daemon reads DISCORD_BOT_TOKEN / SLACK_BOT_TOKEN as scalar
    # env vars — two attached channels of the same type would render
    # two `DISCORD_BOT_TOKEN=` lines into the EnvironmentFile and
    # systemd's last-wins parse semantics would silently keep one.
    # Mirror the zeroclaw guard added in ATX round 3.
    seen_channel_types: dict[str, str] = {}
    for channel in inputs.channels:
        if channel.type not in _HERMES_SUPPORTED_CHANNELS:
            raise AgentConfigError(
                f"render_hermes: unsupported channel type {channel.type!r}. "
                f"Supported: {sorted(_HERMES_SUPPORTED_CHANNELS)}"
            )
        prior = seen_channel_types.get(channel.type)
        if prior is not None:
            raise AgentConfigError(
                f"render_hermes: agent {inputs.agent_name!r} has "
                f"multiple {channel.type} channels attached "
                f"({prior!r}, {channel.name!r}); hermes emits one "
                f"{channel.type.upper()}_BOT_TOKEN env var and "
                f"systemd's last-wins parse would silently keep one. "
                f"Detach one with `clawctl channel detach`."
            )
        seen_channel_types[channel.type] = channel.name

    for integration in inputs.integrations:
        if integration.type not in _HERMES_SUPPORTED_INTEGRATIONS:
            # W2 (ATX round 1): same listing rule.
            raise AgentConfigError(
                f"render_hermes: unsupported integration type {integration.type!r}. "
                f"Supported: {sorted(_HERMES_SUPPORTED_INTEGRATIONS)}"
            )

    integration_views: list[dict] = []
    atlassian_views: list[dict] = []
    seen_atlassian_slugs: set[str] = set()
    last_github_token = ""
    for integration in inputs.integrations:
        creds = dict(integration.credentials)
        slug = _integration_slug(integration.name)
        if integration.type == "github":
            last_github_token = creds.get("GITHUB_TOKEN", "")
        if integration.type == "atlassian":
            lo_slug = slug.lower()
            if not lo_slug:
                raise AgentConfigError(
                    f"render_hermes: integration name {integration.name!r} "
                    f"slugifies to empty — refusing to emit an unnamed YAML key"
                )
            if lo_slug in seen_atlassian_slugs:
                raise AgentConfigError(
                    f"render_hermes: atlassian integration names collide on "
                    f"YAML key {lo_slug!r}; rename one of the integrations to "
                    f"differentiate after slugification"
                )
            seen_atlassian_slugs.add(lo_slug)
            url = creds.get("ATLASSIAN_URL", "").rstrip("/")
            atlassian_views.append(
                {
                    "slug": lo_slug,
                    "url": url,
                    "email": creds.get("ATLASSIAN_EMAIL", ""),
                    "token": creds.get("ATLASSIAN_API_TOKEN", ""),
                    "confluence_url": url + "/wiki",
                }
            )
        integration_views.append(
            {"type": integration.type, "slug": slug, "creds": creds}
        )

    ollama_base_url = ""
    if ptype == "ollama":
        endpoint = inputs.provider.endpoint.rstrip("/")
        if not endpoint.endswith("/v1"):
            endpoint = endpoint + "/v1"
        ollama_base_url = endpoint

    # #614: build per-type env-var view for hermes-env.canonical.j2 so the
    # template emits one `*_API_KEY` line per unique provider type across
    # primary + auxiliaries. Same-type duplicate keys are not silently
    # collapsed — the primary's value wins and a `# WARNING` line is
    # emitted so operators see the upstream one-key-per-type limitation.
    provider_env_views, env_conflicts = _build_provider_env_views(
        inputs.provider, inputs.auxiliary_providers
    )
    # #614: build per-aux view for the YAML template (one `auxiliary.<role>:`
    # block per non-primary attachment). An explicit `title_generation`
    # attachment shadows the per-primary-type default model.
    aux_yaml_views = _build_aux_yaml_views(inputs.auxiliary_providers)
    explicit_title_gen = any(
        v["role"] == "title_generation" for v in aux_yaml_views
    )

    env_body = _render_hermes_template(
        "hermes-env.canonical.j2",
        agent_name=inputs.agent_name,
        provider=inputs.provider,
        api_server=inputs.api_server,
        channels=inputs.channels,
        integrations=integration_views,
        last_github_token=last_github_token,
        provider_env_views=provider_env_views,
        env_conflicts=env_conflicts,
    )
    yaml_body = _render_hermes_template(
        "hermes-config.canonical.yaml.j2",
        agent_name=inputs.agent_name,
        provider=inputs.provider,
        ollama_base_url=ollama_base_url,
        atlassian_integrations=atlassian_views,
        mcp_atlassian_version=_HERMES_MCP_ATLASSIAN_VERSION,
        aux_providers=aux_yaml_views,
        explicit_title_gen=explicit_title_gen,
        # ATX iter-1 W1: single source of truth — pass the Python map
        # through to the template rather than maintaining an inline
        # copy in Jinja.
        default_title_gen_map=_HERMES_DEFAULT_TITLE_GEN_MODEL,
    )

    return RenderedFiles(
        files={
            ".hermes/.env": env_body,
            ".hermes/config.yaml": yaml_body,
        }
    )


@_functools.lru_cache(maxsize=8)
def _hermes_template(template_name: str):
    """Load + compile a hermes canonical template once per process.

    Memoized so `render_hermes`' two template renders per invocation do not
    re-read the wheel resource or re-compile the Jinja AST. The cache is
    keyed on filename; identity of returned template is stable.
    """
    from importlib.resources import files

    from jinja2 import Environment, StrictUndefined

    template_path = files("clawrium.platform.registry.hermes.templates").joinpath(
        template_name
    )
    template_source = template_path.read_text(encoding="utf-8")

    # autoescape=False is INTENTIONAL: shq/yq filters handle all shell and
    # YAML quoting already, and the output files are shell EnvironmentFile
    # bodies / YAML — not HTML. Flipping autoescape to True would
    # double-encode every shq/yq-quoted value (e.g. `'sk-or-1'` →
    # `&#x27;sk-or-1&#x27;`) and corrupt the on-host files silently.
    env = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    env.filters["shq"] = lambda v: _shell_quote(str(v))
    env.filters["yq"] = lambda v: _yaml_quote(str(v))
    return env.from_string(template_source)


def _render_hermes_template(template_name: str, **context) -> str:
    """Render a hermes canonical template under
    `clawrium.platform.registry.hermes.templates` via importlib.resources.

    StrictUndefined so any missing context variable raises at render time
    rather than silently producing an empty string. `shq` / `yq` filters
    mirror `_shell_quote` / `_yaml_quote` exactly.
    """
    return _hermes_template(template_name).render(**context)


# Zeroclaw provider section table. Each entry: (kind_string,)
_ZEROCLAW_PROVIDER_KINDS = frozenset(
    {"anthropic", "openai", "ollama", "openrouter"}
)
_ZEROCLAW_SUPPORTED_INTEGRATIONS = frozenset({"github", "git"})


def render_zeroclaw(inputs: RenderInputs) -> RenderedFiles:
    """Render zeroclaw's config.toml + systemd env drop-in.

    The config.toml is rendered from a Jinja2 template that is a FULL copy
    of the canonical zeroclaw config — every section the daemon expects is
    preserved verbatim. Only clawctl-managed values are templated. This
    prevents the silent-wipe bug where rendering only what clawctl knows
    about destroys daemon-managed sections (gateway pairing state, security
    knobs, memory backends, cost.prices, hooks, etc.).
    """
    _validate_agent_name(inputs.agent_name)

    ptype = inputs.provider.type

    if ptype not in _ZEROCLAW_PROVIDER_KINDS:
        raise AgentConfigError(
            f"render_zeroclaw does not support provider type {ptype!r}. "
            f"Supported: {sorted(_ZEROCLAW_PROVIDER_KINDS)}"
        )
    if inputs.gateway is None:
        raise AgentConfigError(
            f"render_zeroclaw requires gateway config for agent "
            f"{inputs.agent_name!r} (port + host); none supplied"
        )

    # --- shell_env_passthrough entries (autonomy block in template) -------
    # `[autonomy] shell_env_passthrough` is a MANDATORY block: the configure
    # playbook asserts its presence with `grep -qE '^shell_env_passthrough\s*='`
    # and fails the deploy if missing. Without listing GITHUB_TOKEN_<NAME>
    # here, the zeroclaw sandbox strips integration tokens from the shell
    # tool's environment even though the systemd drop-in injected them.
    passthrough = ["PATH", "HOME", "USER", "LANG"]
    any_github = False
    for integration in inputs.integrations:
        if integration.type == "github":
            slug = _integration_slug(integration.name)
            passthrough.append(f"GITHUB_TOKEN_{slug}")
            any_github = True
    if any_github:
        passthrough.append("GITHUB_TOKEN")

    # --- discord channel (zeroclaw supports discord only today) -----------
    # B8: surface unsupported channel types up-front. Silently dropping a
    # non-discord channel (slack, etc.) here meant operators who attached
    # the wrong channel type would see a successful render with no Discord
    # output — the daemon would then run without channel access and the
    # mistake would only show up on first @mention.
    # W1 (ATX round 3): a second `discord` channel is ALSO a silent-drop
    # surface (zeroclaw daemon emits one [channels.discord] block, so two
    # attached discord channels means the second is invisible). Raise so
    # the operator detaches one rather than getting nondeterministic
    # "which one won?" behavior.
    discord_channel = None
    for channel in inputs.channels:
        if channel.type == "discord":
            if discord_channel is not None:
                raise AgentConfigError(
                    f"render_zeroclaw: agent {inputs.agent_name!r} has "
                    f"multiple discord channels attached "
                    f"({discord_channel.name!r}, {channel.name!r}); "
                    f"zeroclaw renders exactly one [channels.discord] block. "
                    f"Detach one with `clawctl channel detach`."
                )
            discord_channel = channel
            continue
        raise AgentConfigError(
            f"render_zeroclaw: unsupported channel type {channel.type!r} "
            f"(zeroclaw supports 'discord' only)"
        )

    # --- render the full canonical template -------------------------------
    toml_body = _render_zeroclaw_config_template(
        agent_name=inputs.agent_name,
        gateway=inputs.gateway,
        provider=inputs.provider,
        discord_channel=discord_channel,
        shell_env_passthrough=passthrough,
    )

    # --- systemd env drop-in (integrations) -------------------------------
    env_lines: list[str] = []
    env_lines.append(
        f"# Managed by clawrium (clawctl). Re-render with "
        f"`clawctl agent configure {inputs.agent_name}`."
    )
    env_lines.append("[Service]")
    last_github_token = ""
    # B9: silently skipping non-github integrations here (the previous
    # `continue`) meant an operator attaching a gitlab/atlassian/linear
    # integration to zeroclaw would see a successful render with no
    # corresponding env var on disk. Mirror render_hermes's explicit
    # whitelist and raise AgentConfigError on anything zeroclaw can't
    # express today. `git` is a clientside-only identity integration
    # (~/.gitconfig render lives elsewhere) so it is explicitly skipped.
    # W5: defined as module constant for consistency with other
    # supported-set tables in this module.
    for integration in inputs.integrations:
        if integration.type not in _ZEROCLAW_SUPPORTED_INTEGRATIONS:
            raise AgentConfigError(
                f"render_zeroclaw: unsupported integration type "
                f"{integration.type!r} (zeroclaw supports: "
                f"{sorted(_ZEROCLAW_SUPPORTED_INTEGRATIONS)})"
            )
        if integration.type != "github":
            continue
        creds = dict(integration.credentials)
        token = creds.get("GITHUB_TOKEN", "")
        slug = _integration_slug(integration.name)
        env_lines.append(
            f"Environment=GITHUB_TOKEN_{slug}={_systemd_quote(token)}"
        )
        last_github_token = token
    if last_github_token:
        env_lines.append(
            f"Environment=GITHUB_TOKEN={_systemd_quote(last_github_token)}"
        )
    env_body = "\n".join(env_lines) + "\n"

    return RenderedFiles(
        files={
            ".zeroclaw/config.toml": toml_body,
            ".zeroclaw/zeroclaw-env.conf": env_body,
        }
    )


@_functools.lru_cache(maxsize=1)
def _zeroclaw_template():
    """Load + compile the zeroclaw canonical config.toml template once.

    W2 (ATX #555 polish): the 1027-line zeroclaw template was previously
    re-read from disk and re-compiled on every render call. Hermes and
    openclaw both cache theirs — mirror that for consistency and to keep
    fan-out render benchmarks fast on multi-agent hosts.
    """
    from importlib.resources import files

    from jinja2 import Environment, StrictUndefined

    template_path = files("clawrium.platform.registry.zeroclaw.templates").joinpath(
        "zeroclaw-config.toml.j2"
    )
    template_source = template_path.read_text(encoding="utf-8")

    # `StrictUndefined` so a missing context var raises rather than rendering
    # an empty string — same fail-loudly contract as build_render_inputs.
    env = Environment(
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,  # TOML is not HTML
    )
    # `toq` filter — applied to every {{ ... }} that renders into a TOML
    # double-quoted string. Closes B3 (ATX round on #555 polish): without
    # this an API key containing `"` would terminate the TOML string
    # early and could inject arbitrary keys (e.g. silently disable
    # `require_pairing` on the gateway). `\` in any field would produce
    # an invalid escape and brick TOML parse.
    env.filters["toq"] = lambda v: _toml_escape(str(v))
    return env.from_string(template_source)


def _render_zeroclaw_config_template(
    *,
    agent_name: str,
    gateway: "GatewayInputs",
    provider: "ProviderInputs",
    discord_channel: "ChannelInputs | None",
    shell_env_passthrough: list[str],
) -> str:
    """Render the full-canonical zeroclaw config.toml Jinja template.

    The template lives at
    `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`
    and is a verbatim copy of the canonical zeroclaw config with only
    clawctl-managed values templated. Loaded via importlib.resources so it
    ships with the wheel.
    """
    template = _zeroclaw_template()
    return template.render(
        agent_name=agent_name,
        gateway=gateway,
        provider=provider,
        discord_channel=discord_channel,
        shell_env_passthrough=shell_env_passthrough,
    )


# Openclaw provider env-var table. `vertex` is intentionally absent:
# `GOOGLE_APPLICATION_CREDENTIALS` is a path to an ADC JSON file, not a
# bearer string. Emitting `inputs.provider.api_key` into it would
# silently produce a broken config — GCP client libs reject token
# strings. Vertex support belongs in a follow-up that extends the
# credential schema with a credential-kind field (path vs bearer).
_OPENCLAW_SUPPORTED_PROVIDERS = frozenset(
    {"openrouter", "anthropic", "openai", "bedrock", "ollama", "zai"}
)
_OPENCLAW_SUPPORTED_CHANNELS = frozenset({"discord", "slack"})
_OPENCLAW_SUPPORTED_INTEGRATIONS = frozenset(
    {"github", "atlassian", "linear", "notion", "gitlab", "git"}
)
_OPENCLAW_MODEL_PREFIX = {
    "openrouter": "openrouter/",
    "bedrock": "bedrock/",
}

# Single source of truth for the openclaw gateway port fallback. Used by
# BOTH the env template (`default_gateway_port` context var) AND
# `_render_openclaw_json` so the env file and openclaw.json cannot
# disagree on which port the daemon listens on. install.py always
# provides a real port; this fallback only matters if `gateway` is
# supplied without a port (defense in depth).
_OPENCLAW_DEFAULT_GATEWAY_PORT = 40000


def render_openclaw(inputs: RenderInputs) -> RenderedFiles:
    """Render openclaw's `.openclaw/env` (Jinja) + `.openclaw/openclaw.json`
    (JSON baseline deep-update).

    Both files are loaded as canonical resources via `importlib.resources` so
    the wheel ships them. Env is rendered from
    `openclaw-env.canonical.j2`; JSON is loaded from `openclaw.json` baseline
    and the five clawctl-managed paths are deep-updated from `inputs`:

      - `channels.discord.enabled`
      - `channels.discord.allowFrom` (from inputs.channels[discord].allowed_users)
      - `channels.discord.guilds`    (nested reshape from allowed_guilds + allowed_channels)
      - `gateway.port` + `gateway.bind`
      - `agents.defaults.model.primary` (from inputs.provider.default_model + type prefix)

    Every other key in the baseline is preserved byte-identically (modulo
    `json.dumps` formatting), matching the silent-wipe-prevention contract
    introduced for zeroclaw in #565.
    """
    _validate_agent_name(inputs.agent_name)
    ptype = inputs.provider.type
    if ptype not in _OPENCLAW_SUPPORTED_PROVIDERS:
        raise AgentConfigError(
            f"render_openclaw does not support provider type {ptype!r}. "
            f"Supported: {sorted(_OPENCLAW_SUPPORTED_PROVIDERS)}"
        )

    # Up-front validation: channel + integration types, dual-discord +
    # dual-slack guards (matches hermes/zeroclaw patterns from Phases 1+2).
    seen_channel_types: dict[str, str] = {}
    discord_channel: ChannelInputs | None = None
    for channel in inputs.channels:
        if channel.type not in _OPENCLAW_SUPPORTED_CHANNELS:
            raise AgentConfigError(
                f"render_openclaw: unsupported channel type {channel.type!r}. "
                f"Supported: {sorted(_OPENCLAW_SUPPORTED_CHANNELS)}"
            )
        prior = seen_channel_types.get(channel.type)
        if prior is not None:
            raise AgentConfigError(
                f"render_openclaw: agent {inputs.agent_name!r} has "
                f"multiple {channel.type} channels attached "
                f"({prior!r}, {channel.name!r}); openclaw emits one "
                f"{channel.type.upper()}_BOT_TOKEN env var and the "
                f"`channels.{channel.type}` block in openclaw.json holds "
                f"one allowlist — detach one with `clawctl channel detach`."
            )
        seen_channel_types[channel.type] = channel.name
        if channel.type == "discord":
            discord_channel = channel

    for integration in inputs.integrations:
        if integration.type not in _OPENCLAW_SUPPORTED_INTEGRATIONS:
            raise AgentConfigError(
                f"render_openclaw: unsupported integration type "
                f"{integration.type!r}. "
                f"Supported: {sorted(_OPENCLAW_SUPPORTED_INTEGRATIONS)}"
            )

    # --- Build prefixed model id (used by both env + openclaw.json) -------
    model_id = inputs.provider.default_model
    prefix = _OPENCLAW_MODEL_PREFIX.get(ptype, "")
    if prefix and not model_id.startswith(prefix):
        model_id = prefix + model_id

    # --- Integration views for the env template ---------------------------
    integration_views: list[dict] = []
    last_github_token = ""
    for integration in inputs.integrations:
        if integration.type == "git":
            # `git` is a clientside-only identity integration; no env var.
            continue
        creds = dict(integration.credentials)
        view: dict = {"type": integration.type}
        if integration.type == "github":
            slug = _integration_slug(integration.name)
            token = creds.get("GITHUB_TOKEN", "")
            view["slug"] = slug
            view["token"] = token
            last_github_token = token
        elif integration.type == "gitlab":
            view["gitlab_token"] = creds.get("GITLAB_TOKEN", "")
            view["has_gitlab_url"] = "GITLAB_URL" in creds
            view["gitlab_url"] = creds.get("GITLAB_URL", "")
        elif integration.type == "atlassian":
            url = creds.get("ATLASSIAN_URL", "").rstrip("/")
            view["atlassian_url"] = url
            view["confluence_url"] = url + "/wiki"
            view["atlassian_email"] = creds.get("ATLASSIAN_EMAIL", "")
            view["atlassian_api_token"] = creds.get("ATLASSIAN_API_TOKEN", "")
        elif integration.type == "linear":
            view["linear_api_key"] = creds.get("LINEAR_API_KEY", "")
        elif integration.type == "notion":
            view["notion_api_key"] = creds.get("NOTION_API_KEY", "")
        integration_views.append(view)

    env_body = _render_openclaw_template(
        "openclaw-env.canonical.j2",
        agent_name=inputs.agent_name,
        provider=inputs.provider,
        gateway=inputs.gateway,
        default_gateway_port=_OPENCLAW_DEFAULT_GATEWAY_PORT,
        default_model_id=model_id,
        channels=inputs.channels,
        integrations=integration_views,
        last_github_token=last_github_token,
    )

    # --- openclaw.json: load baseline + deep-update managed paths ---------
    json_body = _render_openclaw_json(
        provider_default_model=model_id,
        gateway=inputs.gateway,
        discord_channel=discord_channel,
    )

    return RenderedFiles(
        files={
            ".openclaw/env": env_body,
            ".openclaw/openclaw.json": json_body,
        }
    )


@_functools.lru_cache(maxsize=4)
def _openclaw_template(template_name: str):
    """Load + compile an openclaw canonical template once per process."""
    from importlib.resources import files

    from jinja2 import Environment, StrictUndefined

    template_path = files(
        "clawrium.platform.registry.openclaw.templates"
    ).joinpath(template_name)
    template_source = template_path.read_text(encoding="utf-8")

    env = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    env.filters["shq"] = lambda v: _shell_quote(str(v))
    return env.from_string(template_source)


def _render_openclaw_template(template_name: str, **context) -> str:
    """Render an openclaw canonical template via importlib.resources."""
    return _openclaw_template(template_name).render(**context)


@_functools.lru_cache(maxsize=1)
def _openclaw_json_baseline() -> str:
    """Load the openclaw.json baseline text once per process.

    Returns the raw text; `_render_openclaw_json` re-parses on every call so
    deep-updates don't mutate the shared baseline dict.

    Baseline schema provenance: the structure mirrors the legacy
    `openclaw.json.j2` Ansible template at
    `src/clawrium/platform/registry/openclaw/templates/openclaw.json.j2`,
    which is the existing source of truth for the on-host file shape
    (consumed by `install.yaml` and `configure.yaml`). Field names
    (`agents.defaults.{workspace,model,sandbox,heartbeat}`, `gateway.{mode,
    port,bind,reload,auth}`, `session.{dmScope,threadBindings,reset}`,
    `tools.{exec,deny}`, `channels.discord.{enabled,allowFrom,guilds}`,
    `browser.enabled`, `env.shellEnv.{enabled,timeoutMs}`) are copied
    verbatim from that template's defaults. 00_PLAN.md Phase 4 closes
    the schema verification loop with a live dry-run against wolf-i's
    `~/.openclaw/openclaw.json`; if any key name diverges, the captured
    live file replaces this synthesized baseline. Until Phase 4 runs,
    treat the baseline as "best-effort match to the legacy Ansible
    template" — silent no-op risk on unknown keys is non-zero.
    """
    from importlib.resources import files

    return (
        files("clawrium.platform.registry.openclaw.templates")
        .joinpath("openclaw.json")
        .read_text(encoding="utf-8")
    )


def _render_openclaw_json(
    *,
    provider_default_model: str,
    gateway: "GatewayInputs | None",
    discord_channel: "ChannelInputs | None",
) -> str:
    """Deep-update the openclaw.json baseline with the 5 clawctl-managed paths.

    Every other key in the baseline is preserved byte-for-byte (modulo
    json.dumps formatting). Output uses `indent=2, sort_keys=False` to keep
    section order stable for diffability.
    """
    import json

    baseline = json.loads(_openclaw_json_baseline())

    # 1. agents.defaults.model.primary
    agents = baseline.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    model = defaults.setdefault("model", {})
    model["primary"] = provider_default_model

    # 2. gateway.port + 3. gateway.bind + gateway.auth (managed bearer)
    #
    # Round 3 B1: `gateway.auth` MUST flow into the JSON. The legacy
    # `openclaw.json.j2` writes the bearer to `gateway.auth.{mode,token}`
    # via `install.yaml`; if F3 sync emitted the baseline verbatim
    # (without auth), it would silently wipe the on-host bearer on every
    # sync — exactly the silent-wipe class of bug #560 was opened to fix.
    if gateway is not None:
        gw = baseline.setdefault("gateway", {})
        gw["port"] = int(gateway.port or _OPENCLAW_DEFAULT_GATEWAY_PORT)
        gw["bind"] = gateway.bind or "lan"
        if gateway.auth:
            gw["auth"] = {"mode": "token", "token": gateway.auth}
        else:
            # Drop any stale auth block from the baseline (which has none)
            # to keep the state explicit: no auth → no `gateway.auth` key.
            gw.pop("auth", None)

    # 4. channels.discord.enabled + 5. channels.discord.allowFrom + guilds.
    channels = baseline.setdefault("channels", {})
    discord = channels.setdefault(
        "discord", {"enabled": False, "allowFrom": [], "guilds": {}}
    )
    if discord_channel is not None:
        discord["enabled"] = True
        discord["allowFrom"] = list(discord_channel.allowed_users)
        # Reshape flat allowed_guilds[] + allowed_channels[] into the
        # nested {<guild>: {users: [...], channels: {<chan>: {allow: true}}}}
        # structure openclaw's daemon expects.
        guilds_block: dict = {}
        for guild_id in discord_channel.allowed_guilds:
            guilds_block[guild_id] = {
                "users": list(discord_channel.allowed_users),
                "channels": {
                    chan_id: {"allow": True}
                    for chan_id in discord_channel.allowed_channels
                },
            }
        discord["guilds"] = guilds_block
    else:
        # No discord channel attached → leave defaults (`enabled: false`,
        # empty allowFrom, empty guilds). Baseline already has this shape;
        # explicit reset prevents stale values surviving across renders.
        discord["enabled"] = False
        discord["allowFrom"] = []
        discord["guilds"] = {}

    return json.dumps(baseline, indent=2, sort_keys=False) + "\n"

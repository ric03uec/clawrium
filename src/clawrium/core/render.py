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
from dataclasses import dataclass, field, replace

__all__ = [
    "AgentConfigError",
    "ProviderInputs",
    "AttachedProviderInputs",
    "HermesProviderBundle",
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
_BEARER_API_KEY_TYPES = frozenset({"openrouter", "anthropic", "openai", "zai", "opencode", "opencode-go"})
_LOCAL_ENDPOINT_TYPES = frozenset({"ollama"})
# Providers that require BOTH a free-form endpoint AND a bearer API key.
# LiteLLM is the canonical case: an OpenAI-compatible proxy whose URL is
# operator-supplied (like ollama) and whose master key is required for
# every /v1 call (like openrouter/openai). Keeping these distinct from
# `_BEARER_API_KEY_TYPES` lets `build_render_inputs` raise on both a
# missing key and a missing endpoint with a single targeted message.
_BEARER_API_KEY_WITH_ENDPOINT_TYPES = frozenset({"litellm"})

# Per-agent-type supported provider sets. `build_render_inputs` checks
# this so a hermes agent attached to a zai-only provider fails up-front
# instead of crashing later inside `render_hermes`. The membership
# matches the renderer dispatch tables further below.
#
# `litellm` on zeroclaw is still deferred — the zeroclaw renderer has no
# `models.providers.<id>` writer and no env-var path for a free-form
# OpenAI-compatible base_url + bearer pair. Openclaw gained litellm
# support in #723: the renderer writes a `models.providers.<provider-name>`
# block into `openclaw.json` with `api: "openai-completions"`, matching
# upstream openclaw's custom-provider shape.
_AGENT_TYPE_PROVIDER_SUPPORT: dict[str, frozenset[str]] = {
    "hermes": frozenset(
        {"openrouter", "anthropic", "openai", "bedrock", "ollama", "litellm", "opencode", "opencode-go"}
    ),
    "zeroclaw": frozenset({"openrouter", "anthropic", "openai", "ollama", "opencode", "opencode-go"}),
    "openclaw": frozenset(
        {"openrouter", "anthropic", "openai", "bedrock", "ollama", "zai", "litellm", "opencode", "opencode-go"}
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
    # Secret fields use `repr=False` so an exception traceback / pytest
    # --showlocals / logging.debug(provider) never echoes the bearer.
    # `FileDiff.remote_body` in core/render_diff.py uses the same
    # hardening for the same reason. #723 ATX W5.
    api_key: str = field(default="", repr=False)
    aws_access_key: str = field(default="", repr=False)
    aws_secret_key: str = field(default="", repr=False)
    # Optional model-shape overrides used by the litellm branch of
    # `_render_openclaw_json` (#723 ATX W2). Operator-supplied via
    # provider record (`context_window` / `max_tokens` fields in
    # providers.json). 0 means "renderer picks default". LiteLLM proxies
    # front everything from 4K-context models to 256K — hard-coding any
    # single value silently truncates or wastes capacity for whichever
    # operator's model doesn't match.
    context_window: int = 0
    max_tokens: int = 0


@dataclass(frozen=True)
class AttachedProviderInputs:
    """One provider attachment in a hermes multi-provider bundle.

    Carries the per-attachment role + model so the canonical template can
    iterate a uniform list across primary and auxiliary slots.

    `api_key` and `base_url` are populated for `litellm` aux attachments
    (every litellm proxy can have a distinct URL + key, so per-type
    dedup as used for openrouter/anthropic/openai/zai doesn't fit).
    Both stay empty for every other type — the template branches on
    `entry.type` and only reads them in the litellm branch.
    """

    name: str
    type: str
    role: str
    model: str
    endpoint: str = ""
    region: str = ""
    # See ProviderInputs.api_key — same repr-leak rationale.
    api_key: str = field(default="", repr=False)
    base_url: str = ""


@dataclass(frozen=True)
class HermesProviderBundle:
    """Hermes-only multi-provider bundle.

    Populated by `build_render_inputs` when `agent_type == "hermes"`.
    `None` for zeroclaw/openclaw — their renderers never read this field.

    `api_keys` is keyed by provider type (hermes' env-var contract is one
    `<TYPE>_API_KEY=` per process; same-type collision raises).
    `aws_credentials` is keyed by provider name. Multiple bedrock
    attachments are allowed only when their full (access_key, secret_key,
    region) triples match — hermes emits one AWS_* triple and one
    `bedrock.region` per process, so any divergence is rejected upfront.
    """

    attachments: tuple[AttachedProviderInputs, ...]
    api_keys: tuple[tuple[str, str], ...] = ()
    aws_credentials: tuple[tuple[str, tuple[str, str, str]], ...] = ()


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
    # Populated only when agent_type == "hermes". `None` for
    # zeroclaw/openclaw — their renderers do not read this field, and
    # `build_render_inputs` skips the multi-provider walk for them.
    hermes: HermesProviderBundle | None = None


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
    elif provider_type in _BEARER_API_KEY_WITH_ENDPOINT_TYPES:
        # litellm: free-form proxy URL + bearer master key. Both are
        # required; neither has a sensible default.
        if not provider_record.get("endpoint"):
            raise AgentConfigError(
                f"provider {primary_name!r} (type {provider_type}) is missing "
                f"endpoint in providers.json"
            )
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
        # Optional model-shape overrides (#723 ATX W2). Mirrors what the
        # legacy ollama playbook template already accepted at
        # `openclaw.json.j2:132-133`; surfaced through ProviderInputs so
        # `_render_openclaw_json`'s litellm branch can honor them.
        context_window=int(provider_record.get("context_window") or 0),
        max_tokens=int(provider_record.get("max_tokens") or 0),
    )

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

    # --- Hermes multi-provider bundle (hermes-only) ------------------------
    # Issue #621: the canonical render path was picking only the primary
    # attachment and dropping every auxiliary slot. Build a per-attachment
    # view (primary + non-primary) plus deduped credential dicts so the
    # canonical templates can render `auxiliary.<role>:` blocks and emit
    # per-aux env vars.
    #
    # Gated on `agent_type == "hermes"` — zeroclaw / openclaw enforce a
    # singleton attachment and their renderers never read `inputs.hermes`.
    # Bundle stays `None` for those types so the data shape they consume
    # is unchanged.
    hermes_bundle: HermesProviderBundle | None = None
    if agent_type == "hermes":
        attached: list[AttachedProviderInputs] = []
        api_keys: dict[str, str] = {}
        aws_creds: dict[str, tuple[str, str, str]] = {}
        bedrock_attachment_name: str | None = None
        for entry in attachments:
            if not isinstance(entry, dict):
                # Hermes attachments are list-of-dicts post-normalize;
                # a non-dict here means provider_attachments.normalize()
                # regressed. Fail loud rather than silently skipping —
                # silent skip would render an incomplete hermes config.
                raise AgentConfigError(
                    f"agent {agent_name!r} has non-dict provider attachment "
                    f"{entry!r} after normalization"
                )
            entry_name = entry.get("name")
            if not isinstance(entry_name, str) or not entry_name:
                raise AgentConfigError(
                    f"agent {agent_name!r} has a provider attachment with "
                    f"no name: {entry!r}"
                )
            entry_record = get_provider(entry_name)
            if entry_record is None:
                raise AgentConfigError(
                    f"provider {entry_name!r} attached to agent {agent_name!r} "
                    f"is not registered in providers.json"
                )
            entry_type_raw = entry_record.get("type")
            entry_type = (
                entry_type_raw.strip()
                if isinstance(entry_type_raw, str)
                else ""
            )
            if entry_type not in supported:
                raise AgentConfigError(
                    f"agent {agent_name!r} (type {agent_type}) does not "
                    f"support provider type {entry_type!r} (attachment "
                    f"{entry_name!r}). Supported: {sorted(supported)}"
                )
            entry_role = entry.get("role") or ""
            entry_model = (
                entry.get("model")
                or entry_record.get("default_model")
                or ""
            )
            entry_region = entry_record.get("region", "") or ""
            entry_endpoint = entry_record.get("endpoint", "") or ""
            entry_api_key = ""
            entry_base_url = ""
            if entry_type == "bedrock":
                ak, sk = get_provider_aws_credentials(entry_name)
                ak = _clean_secret(ak)
                sk = _clean_secret(sk)
                if not ak or not sk:
                    raise AgentConfigError(
                        f"bedrock provider {entry_name!r} attached to agent "
                        f"{agent_name!r} is missing AWS credentials in "
                        f"secrets.json"
                    )
                # Hermes emits one AWS_* triple and one bedrock.region per
                # process. Multiple bedrock attachments are fine when their
                # full (ak, sk, region) triples match; any divergence would
                # silently overwrite and is rejected.
                prior_creds = (
                    aws_creds[bedrock_attachment_name]
                    if bedrock_attachment_name is not None
                    else None
                )
                new_creds = (ak, sk, entry_region or "us-east-1")
                if prior_creds is not None and prior_creds != new_creds:
                    raise AgentConfigError(
                        f"agent {agent_name!r} has two bedrock provider "
                        f"attachments ({bedrock_attachment_name!r}, "
                        f"{entry_name!r}) with different AWS credentials "
                        f"or region; hermes emits one AWS_* triple and one "
                        f"bedrock.region per process. Detach one or unify "
                        f"the secret and region."
                    )
                bedrock_attachment_name = entry_name
                aws_creds[entry_name] = new_creds
            elif entry_type in _BEARER_API_KEY_TYPES:
                key = _clean_secret(get_provider_api_key(entry_name))
                if not key:
                    raise AgentConfigError(
                        f"provider {entry_name!r} (type {entry_type}) "
                        f"attached to agent {agent_name!r} is missing API "
                        f"key in secrets.json"
                    )
                prior = api_keys.get(entry_type)
                if prior is not None and prior != key:
                    raise AgentConfigError(
                        f"agent {agent_name!r} has two providers of type "
                        f"{entry_type!r} with different API keys; hermes "
                        f"emits one {entry_type.upper()}_API_KEY env var "
                        f"per process and would silently keep one. "
                        f"Detach one or unify the secret."
                    )
                api_keys[entry_type] = key
            elif entry_type in _BEARER_API_KEY_WITH_ENDPOINT_TYPES:
                # litellm aux: per-attachment URL AND per-attachment key.
                # Two litellm providers attached at different roles can
                # point at different proxies, so dedup-by-type would lose
                # information. The per-attachment api_key rides on
                # `AttachedProviderInputs.api_key` and is emitted as
                # `LITELLM_<ROLE_UPPER>_API_KEY` by the env template.
                if not entry_endpoint:
                    raise AgentConfigError(
                        f"provider {entry_name!r} (type {entry_type}) "
                        f"attached to agent {agent_name!r} is missing "
                        f"endpoint in providers.json"
                    )
                entry_api_key = _clean_secret(get_provider_api_key(entry_name))
                if not entry_api_key:
                    raise AgentConfigError(
                        f"provider {entry_name!r} (type {entry_type}) "
                        f"attached to agent {agent_name!r} is missing API "
                        f"key in secrets.json"
                    )
                # Normalize the proxy URL to its /v1 suffix once at
                # assembly time so the template never touches strings.
                stripped = entry_endpoint.rstrip("/")
                entry_base_url = (
                    stripped if stripped.endswith("/v1") else stripped + "/v1"
                )
            elif entry_type in _LOCAL_ENDPOINT_TYPES:
                if not entry_endpoint:
                    raise AgentConfigError(
                        f"provider {entry_name!r} (type {entry_type}) "
                        f"attached to agent {agent_name!r} is missing "
                        f"endpoint in providers.json"
                    )
            else:
                raise AgentConfigError(
                    f"provider {entry_name!r} has type {entry_type!r} which "
                    f"is declared supported for agent {agent_type} but has "
                    f"no credential fetch wired in build_render_inputs"
                )
            attached.append(
                AttachedProviderInputs(
                    name=entry_name,
                    type=entry_type,
                    role=entry_role,
                    model=entry_model,
                    endpoint=entry_endpoint,
                    region=entry_region,
                    api_key=entry_api_key,
                    base_url=entry_base_url,
                )
            )
        hermes_bundle = HermesProviderBundle(
            attachments=tuple(attached),
            api_keys=tuple(sorted(api_keys.items())),
            aws_credentials=tuple(sorted(aws_creds.items())),
        )

    return RenderInputs(
        agent_name=agent_name,
        agent_type=agent_type,
        provider=provider,
        channels=tuple(channel_inputs),
        integrations=tuple(integration_inputs),
        api_server=api_server_input,
        gateway=gateway_input,
        hermes=hermes_bundle,
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
    {"openrouter", "anthropic", "openai", "bedrock", "ollama", "litellm", "opencode", "opencode-go"}
)
_HERMES_SUPPORTED_CHANNELS = frozenset({"discord", "slack"})
_HERMES_SUPPORTED_INTEGRATIONS = frozenset(
    {"github", "atlassian", "linear", "notion", "gitlab", "git", "brave"}
)
# Lockstep with hermes' configure.yaml playbook
# (`mcp_atlassian_version: "0.21.1"`). Without this pin in the rendered
# `mcp_servers.<slug>.args` line the daemon's uvx launcher would resolve
# `mcp-atlassian` to latest — divergent from the version `uv tool install`
# installed onto the host, so a fresh tool venv would silently get a
# different MCP build than the one tested.
_HERMES_MCP_ATLASSIAN_VERSION = "0.21.1"


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
        if integration.type == "brave":
            # #734: hermes upstream (PR #21337) reads
            # `BRAVE_SEARCH_API_KEY` from the env, but the operator-facing
            # credential is `BRAVE_API_KEY` (single key name across all
            # three agent types). Mirror the value under the hermes-
            # specific name — in the Python view builder, NOT in the
            # Jinja template — so the template stays a dumb formatter
            # and the rename is unit-testable in isolation from Jinja.
            # Do NOT pop the source key (ATX iter 1 render-engine
            # suggestion): a future consumer needing the operator name
            # downstream would silently see an empty string.
            if "BRAVE_API_KEY" in creds:
                creds["BRAVE_SEARCH_API_KEY"] = creds["BRAVE_API_KEY"]
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

    # LiteLLM uses the same hermes `provider: "custom"` render shape as
    # ollama (OpenAI-compatible /v1 endpoint) but additionally carries a
    # bearer API key. The base_url normalization is identical: ensure the
    # trailing `/v1` so the daemon hits `/v1/chat/completions`.
    litellm_base_url = ""
    if ptype == "litellm":
        endpoint = inputs.provider.endpoint.rstrip("/")
        if not endpoint.endswith("/v1"):
            endpoint = endpoint + "/v1"
        litellm_base_url = endpoint

    # OpenCode (Zen / Go) is an OpenAI-compatible hosted gateway. The
    # default endpoint already ends in `/v1`; normalize defensively so a
    # user-supplied override still works.
    opencode_base_url = ""
    if ptype in ("opencode", "opencode-go"):
        endpoint = inputs.provider.endpoint.rstrip("/")
        if not endpoint.endswith("/v1"):
            endpoint = endpoint + "/v1"
        opencode_base_url = endpoint

    # Issue #621: hermes multi-provider context. When the caller built
    # `RenderInputs` via `build_render_inputs`, `inputs.hermes` carries
    # the full attachment list + per-aux credential dicts. When a test
    # or legacy caller built `RenderInputs` by hand without populating
    # `hermes`, synthesize a single-provider bundle from `inputs.provider`
    # so the templates can always iterate one uniform list. This keeps
    # single-provider rendering byte-identical to pre-#621.
    if inputs.hermes is not None:
        aux_attachments = tuple(
            a for a in inputs.hermes.attachments if a.role != "primary"
        )
        aux_api_keys = {
            t: k
            for t, k in dict(inputs.hermes.api_keys).items()
            if t != ptype
        }
        # Primary's bedrock triple already covers all aux bedrock slots
        # (build_render_inputs guarantees shared creds + region).
        aux_aws_credentials = {
            n: t
            for n, t in dict(inputs.hermes.aws_credentials).items()
            if ptype != "bedrock"
        }
    else:
        aux_attachments = ()
        aux_api_keys = {}
        aux_aws_credentials = {}

    env_body = _render_hermes_template(
        "hermes-env.canonical.j2",
        agent_name=inputs.agent_name,
        provider=inputs.provider,
        aux_api_keys=aux_api_keys,
        aux_aws_credentials=aux_aws_credentials,
        api_server=inputs.api_server,
        channels=inputs.channels,
        integrations=integration_views,
        last_github_token=last_github_token,
    )
    yaml_body = _render_hermes_template(
        "hermes-config.canonical.yaml.j2",
        agent_name=inputs.agent_name,
        provider=inputs.provider,
        aux_attachments=aux_attachments,
        ollama_base_url=ollama_base_url,
        litellm_base_url=litellm_base_url,
        opencode_base_url=opencode_base_url,
        atlassian_integrations=atlassian_views,
        mcp_atlassian_version=_HERMES_MCP_ATLASSIAN_VERSION,
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
    {"anthropic", "openai", "ollama", "openrouter", "opencode", "opencode-go"}
)
_ZEROCLAW_SUPPORTED_INTEGRATIONS = frozenset({"github", "git", "brave"})


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

    # --- normalize provider endpoint for OpenAI-compatible gateways ------
    # zeroclaw's config.toml uses the endpoint verbatim as base_url. For
    # opencode/opencode-go (and litellm/ollama), ensure the trailing `/v1`
    # is present so the daemon hits the correct OpenAI-compatible path.
    provider = inputs.provider
    if provider.type in ("opencode", "opencode-go"):
        endpoint = provider.endpoint.rstrip("/")
        if endpoint and not endpoint.endswith("/v1"):
            endpoint = endpoint + "/v1"
        provider = replace(provider, endpoint=endpoint)

    # --- render the full canonical template -------------------------------
    toml_body = _render_zeroclaw_config_template(
        agent_name=inputs.agent_name,
        gateway=inputs.gateway,
        provider=provider,
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
        if integration.type == "github":
            creds = dict(integration.credentials)
            token = creds.get("GITHUB_TOKEN", "")
            slug = _integration_slug(integration.name)
            env_lines.append(
                f"Environment=GITHUB_TOKEN_{slug}={_systemd_quote(token)}"
            )
            last_github_token = token
        elif integration.type == "brave":
            # #734: brave web-search routing. Both lines are required —
            # `BRAVE_API_KEY` alone leaves the search provider on its
            # duckduckgo default. The `ZEROCLAW_web_search__search_provider`
            # env-prefix override flips the router (zeroclaw-tools'
            # `web_search_provider_routing.rs:33`). Mirror of the j2
            # template branch so canonical + Ansible paths stay in lockstep.
            creds = dict(integration.credentials)
            key = creds.get("BRAVE_API_KEY", "")
            env_lines.append(
                f"Environment=BRAVE_API_KEY={_systemd_quote(key)}"
            )
            env_lines.append(
                'Environment=ZEROCLAW_web_search__search_provider="brave"'
            )
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
    {"openrouter", "anthropic", "openai", "bedrock", "ollama", "zai", "litellm", "opencode", "opencode-go"}
)
_OPENCLAW_SUPPORTED_CHANNELS = frozenset({"discord", "slack"})
_OPENCLAW_SUPPORTED_INTEGRATIONS = frozenset(
    {"github", "atlassian", "linear", "notion", "gitlab", "git", "brave"}
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
    and the clawctl-managed paths are deep-updated from `inputs`:

      - `channels.discord.enabled`
      - `channels.discord.allowFrom` (from inputs.channels[discord].allowed_users)
      - `channels.discord.guilds`    (nested reshape from allowed_guilds + allowed_channels)
      - `gateway.port` + `gateway.bind`
      - `agents.defaults.model.primary` (from inputs.provider.default_model + type prefix)
      - `models.providers.<provider-name>` — litellm only (#723); writes a
        custom OpenAI-compatible provider block so openclaw routes via the
        operator-supplied proxy (LiteLLM, vLLM, etc.).

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
    if ptype == "litellm":
        # The litellm prefix is the clawctl provider name, not a static
        # type-keyed string — every litellm proxy is its own custom
        # provider in `models.providers.<name>`, so the daemon picks the
        # right block via `<provider-name>/<model>`.
        prefix = f"{inputs.provider.name}/"
    else:
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
        elif integration.type == "brave":
            view["brave_api_key"] = creds.get("BRAVE_API_KEY", "")
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
        provider=inputs.provider,
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
    provider: "ProviderInputs",
    provider_default_model: str,
    gateway: "GatewayInputs | None",
    discord_channel: "ChannelInputs | None",
) -> str:
    """Deep-update the openclaw.json baseline with the clawctl-managed paths.

    Managed paths:
      1. `agents.defaults.model.primary`
      2. `gateway.port`
      3. `gateway.bind` (+ `gateway.auth` when present)
      4. `channels.discord.enabled` / `allowFrom` / `guilds`
      5. (litellm only) `models.providers.<provider-name>` — a custom
         OpenAI-compatible provider block matching upstream openclaw's
         `models.providers` schema (see
         `docs.openclaw.ai/gateway/config-tools#custom-providers-and-base-urls`).
         The block sets `api: "openai-completions"`, `baseUrl` from the
         provider's `endpoint` (`/v1` appended if missing), `apiKey` from
         the provider's bearer, and one `models[]` entry built from
         `default_model`. Non-litellm provider types do NOT write this
         path — for them, model selection flows through `OPENCLAW_DEFAULT_MODEL`
         in `.openclaw/env` only.

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

    # 5. models.providers.<provider-name> — litellm only.
    if provider.type == "litellm":
        # W3 (#723 ATX): the provider name is used both as a JSON key in
        # `models.providers.<name>` AND as a routing prefix in
        # `<name>/<model>`. A name containing `/`, whitespace, control
        # chars, or backslash would silently corrupt the daemon's
        # routing tokenizer or produce malformed JSON keys. Reject
        # early; the message points at the canonical fix surface.
        # Iteration 3 follow-up (ATX): the iter-2 check only covered
        # `/`; whitespace and control chars also break tokenization.
        bad_chars = [
            c
            for c in provider.name
            if c == "/" or c == "\\" or c.isspace() or ord(c) < 0x20
        ]
        if bad_chars:
            raise AgentConfigError(
                f"render_openclaw: litellm provider name "
                f"{provider.name!r} must not contain '/', '\\\\', "
                f"whitespace, or control characters "
                f"(used as a routing prefix in "
                f"agents.defaults.model.primary). "
                f"Recreate with `clawctl provider registry create "
                f"<safe-name> --type litellm`."
            )
        # W1 + W4 (#723 ATX): normalization first, guard second. The
        # iter-2 fix added `.strip()` here to defend against newlines
        # surviving from providers.json — that extends hermes' simpler
        # `rstrip('/')` normalization at render.py:985-987 with an
        # additional whitespace defence rather than literal byte-for-byte
        # parity (an iter-2 reviewer flagged the parity claim was
        # false; corrected here). The empty-endpoint guard sits BELOW
        # normalization so whitespace-only / bare-slash inputs ('   ',
        # '/', '\\n') are caught — the iter-2 implementation checked
        # `if not provider.endpoint` before strip+rstrip and let those
        # cases through with `baseUrl: "/v1"`.
        base_url = provider.endpoint.strip().rstrip("/")
        if not base_url:
            raise AgentConfigError(
                f"render_openclaw: litellm provider {provider.name!r} "
                f"requires a non-empty endpoint "
                f"(got {provider.endpoint!r})"
            )
        if not base_url.endswith("/v1"):
            base_url = base_url + "/v1"
        model_name = provider.default_model
        # W2 (#723 ATX): operator-overridable context_window / max_tokens.
        # Defaults match the issue spec (65536 / 16384) — tuned for
        # vLLM's Qwen3-Next default `--max-model-len`. Operators with
        # smaller (4K/8K) or larger (200K+) models override via
        # `providers.json.context_window` / `.max_tokens`.
        context_window = provider.context_window or 65536
        max_tokens = provider.max_tokens or 16384
        models_block = baseline.setdefault("models", {})
        providers_block = models_block.setdefault("providers", {})
        # S1 (#723 ATX): apiKey is written inline (no env-var hop). This
        # is the upstream openclaw custom-provider contract — the
        # daemon reads it from openclaw.json directly. The file is
        # written atomically with mode 0600; any GUI/CLI dumper that
        # emits the rendered JSON verbatim MUST redact this path.
        providers_block[provider.name] = {
            "baseUrl": base_url,
            "apiKey": provider.api_key,
            "api": "openai-completions",
            "models": [
                {
                    "id": model_name,
                    "name": model_name,
                    "reasoning": False,
                    "input": ["text"],
                    "cost": {
                        "input": 0,
                        "output": 0,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                    },
                    "contextWindow": context_window,
                    "maxTokens": max_tokens,
                }
            ],
        }

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
        # Pin `groupPolicy: "allowlist"` explicitly so the channel-presence
        # invariant below does not depend on openclaw's implicit default.
        # The legacy `clm` wizard at `cli/agent.py` writes the same value
        # when it constructs `channels_config["discord"]`; emitting it here
        # keeps the canonical render path semantically aligned.
        discord["groupPolicy"] = "allowlist"
        # Reshape flat allowed_guilds[] + allowed_channels[] into the
        # nested {<guild>: {users: [...], channels: {<chan>: {}}}} structure
        # openclaw's daemon expects. Under `groupPolicy: "allowlist"`, mere
        # presence in `channels` permits the channel — `{"allow": true}` was
        # accepted by older openclaw but rejected as an additional property
        # by 2026.5.28+ (`channels.discord.guilds.<id>.channels.<id>: must
        # not have additional properties: "allow"`).
        guilds_block: dict = {}
        for guild_id in discord_channel.allowed_guilds:
            guilds_block[guild_id] = {
                "users": list(discord_channel.allowed_users),
                "channels": {
                    chan_id: {} for chan_id in discord_channel.allowed_channels
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

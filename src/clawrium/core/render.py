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
        api_server_input = APIServerInputs(
            host=str(api_server_blob.get("host", "")),
            port=int(api_server_blob.get("port", 0) or 0),
            # `key` is the bearer the gateway enforces; a NUL byte would
            # silently truncate the systemd EnvironmentFile after
            # API_SERVER_KEY=, dropping every var below it. Sanitize at
            # assembly time, same as provider/channel/integration secrets.
            key=_clean_secret(api_server_blob.get("key")),
        )

    gateway_input: GatewayInputs | None = None
    gateway_blob = config_blob.get("gateway")
    if isinstance(gateway_blob, dict):
        gateway_input = GatewayInputs(
            host=str(gateway_blob.get("host", "")),
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
    )


# ---------------------------------------------------------------------------
# Pure renderers
# ---------------------------------------------------------------------------


def _shell_quote(value: str) -> str:
    """POSIX single-quote shell escape. Matches the .env.j2 macro.

    Embeds a single quote in a single-quoted string as: 'val'"'"'ue'.
    Used for systemd EnvironmentFile values so `#` mid-value isn't
    parsed as a comment and arbitrary content can't break the line.
    """
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _systemd_quote(value: str) -> str:
    """Double-quote escape for systemd Environment= drop-ins."""
    cleaned = value.replace("\r", "").replace("\n", "")
    cleaned = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{cleaned}"'


def _toml_escape(value: str) -> str:
    """Escape a value for use inside a TOML basic string."""
    return (
        value.replace("\\", "\\\\")
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


# Provider env-var-name table, keyed on provider.type. Each entry is a
# tuple of (env_var_name_for_api_key, inference_provider_value). The
# table is the ONLY place provider.type matters at render time.
_HERMES_PROVIDER_ENV = {
    "openrouter": ("OPENROUTER_API_KEY", "openrouter"),
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic"),
    "openai": ("OPENAI_API_KEY", "openai"),
}


def render_hermes(inputs: RenderInputs) -> RenderedFiles:
    """Render hermes' on-host config files from canonical inputs.

    Produces:
      - `.hermes/.env`: systemd EnvironmentFile body.
      - `.hermes/config.yaml`: model + auxiliary config.

    Branches only on `inputs.provider.type`. Every field declared on
    `inputs` flows into exactly one output line; the function does NOT
    conditionally emit a section based on whether a hosts.json field
    happened to be populated.
    """
    env_lines: list[str] = []
    env_lines.append(
        f"# Managed by clawrium (clawctl). Re-render with "
        f"`clawctl agent configure {inputs.agent_name}`."
    )

    # --- Provider credentials (branch on provider.type only) -----------
    ptype = inputs.provider.type
    if ptype in _HERMES_PROVIDER_ENV:
        env_var, inference_name = _HERMES_PROVIDER_ENV[ptype]
        env_lines.append(f"{env_var}={_shell_quote(inputs.provider.api_key)}")
        env_lines.append(f"HERMES_INFERENCE_PROVIDER={_shell_quote(inference_name)}")
    elif ptype == "bedrock":
        env_lines.append(f"AWS_ACCESS_KEY_ID={_shell_quote(inputs.provider.aws_access_key)}")
        env_lines.append(f"AWS_SECRET_ACCESS_KEY={_shell_quote(inputs.provider.aws_secret_key)}")
        env_lines.append(
            f"AWS_DEFAULT_REGION={_shell_quote(inputs.provider.region or 'us-east-1')}"
        )
        env_lines.append("HERMES_INFERENCE_PROVIDER='bedrock'")
    elif ptype == "ollama":
        env_lines.append("HERMES_INFERENCE_PROVIDER='custom'")
    else:
        # `build_render_inputs` filters via _AGENT_TYPE_PROVIDER_SUPPORT,
        # but callers may construct `RenderInputs` directly (tests,
        # future programmatic configure flows). Raise loudly here so an
        # unsupported provider type can never silently produce an
        # incomplete on-host config.
        raise AgentConfigError(
            f"render_hermes does not support provider type {ptype!r}. "
            f"Supported: {sorted(_HERMES_PROVIDER_ENV) + ['bedrock', 'ollama']}"
        )

    # --- API server block --------------------------------------------------
    if inputs.api_server is not None:
        env_lines.append("API_SERVER_ENABLED=1")
        env_lines.append(f"API_SERVER_HOST={_shell_quote(inputs.api_server.host)}")
        env_lines.append(f"API_SERVER_PORT={int(inputs.api_server.port)}")
        env_lines.append(f"API_SERVER_KEY={_shell_quote(inputs.api_server.key)}")

    # --- Channels (every attached channel renders all its tokens) ---------
    for channel in inputs.channels:
        if channel.type == "discord":
            env_lines.append(f"DISCORD_BOT_TOKEN={_shell_quote(channel.bot_token)}")
            env_lines.append(
                f"DISCORD_ALLOWED_USERS={_shell_quote(','.join(channel.allowed_users))}"
            )
            env_lines.append(
                f"DISCORD_ALLOWED_CHANNELS={_shell_quote(','.join(channel.allowed_channels))}"
            )
            env_lines.append(
                f"DISCORD_REQUIRE_MENTION={_shell_quote(str(channel.require_mention).lower())}"
            )
            # CRITICAL: only emit `DISCORD_ALLOW_ALL_USERS` when the
            # operator explicitly set it. The hermes daemon parses this
            # var as a presence flag (Python `bool(os.environ.get(...))`
            # treats any non-empty string — including `'false'` — as
            # truthy), so unconditionally emitting `'false'` would
            # silently open public Discord access on every agent on
            # first configure. Mirrors the j2 template's
            # `{% if discord.get('allow_all_users') %}` guard at
            # hermes.env.j2:58. This is a real-world regression we
            # cannot risk.
            if channel.allow_all_users:
                env_lines.append("DISCORD_ALLOW_ALL_USERS=true")
            env_lines.append(f"DISCORD_HOME_CHANNEL={_shell_quote(channel.home_channel)}")
            env_lines.append(
                f"DISCORD_HOME_CHANNEL_NAME={_shell_quote(channel.home_channel_name)}"
            )
            env_lines.append(
                f"DISCORD_HOME_CHANNEL_THREAD_ID={_shell_quote(channel.home_channel_thread_id)}"
            )
        elif channel.type == "slack":
            env_lines.append(f"SLACK_BOT_TOKEN={_shell_quote(channel.bot_token)}")
            env_lines.append(f"SLACK_APP_TOKEN={_shell_quote(channel.app_token)}")
            env_lines.append(
                f"SLACK_ALLOWED_USERS={_shell_quote(','.join(channel.allowed_users))}"
            )
            env_lines.append(f"SLACK_HOME_CHANNEL={_shell_quote(channel.home_channel)}")
            env_lines.append(
                f"SLACK_HOME_CHANNEL_NAME={_shell_quote(channel.home_channel_name)}"
            )
        else:
            raise AgentConfigError(
                f"render_hermes: unsupported channel type {channel.type!r}"
            )

    # --- Integrations (per-name and bare GITHUB_TOKEN fallback) -----------
    last_github_token = ""
    for integration in inputs.integrations:
        creds = dict(integration.credentials)
        if integration.type == "github":
            token = creds.get("GITHUB_TOKEN", "")
            slug = _integration_slug(integration.name)
            env_lines.append(f"GITHUB_TOKEN_{slug}={_shell_quote(token)}")
            last_github_token = token
        elif integration.type == "atlassian":
            # Atlassian creds are emitted in config.yaml's mcp_servers block,
            # not the env file. Skip here.
            continue
        elif integration.type == "linear":
            env_lines.append(f"LINEAR_API_KEY={_shell_quote(creds.get('LINEAR_API_KEY', ''))}")
        elif integration.type == "notion":
            env_lines.append(f"NOTION_API_KEY={_shell_quote(creds.get('NOTION_API_KEY', ''))}")
        elif integration.type == "gitlab":
            env_lines.append(f"GITLAB_TOKEN={_shell_quote(creds.get('GITLAB_TOKEN', ''))}")
            if "GITLAB_URL" in creds:
                env_lines.append(f"GITLAB_URL={_shell_quote(creds['GITLAB_URL'])}")
        elif integration.type == "git":
            # git-identity creds go into ~/.gitconfig via a separate render;
            # nothing for the env file.
            continue
        else:
            raise AgentConfigError(
                f"render_hermes: unsupported integration type {integration.type!r}"
            )
    if last_github_token:
        env_lines.append(f"GITHUB_TOKEN={_shell_quote(last_github_token)}")

    env_body = "\n".join(env_lines) + "\n"

    # --- config.yaml -------------------------------------------------------
    yaml_lines: list[str] = []
    yaml_lines.append(
        f"# Managed by clawrium (clawctl). Re-render with "
        f"`clawctl agent configure {inputs.agent_name}`."
    )
    if ptype == "openrouter":
        yaml_lines.append("model:")
        yaml_lines.append('  provider: "openrouter"')
        yaml_lines.append('  base_url: "https://openrouter.ai/api/v1"')
        yaml_lines.append(f"  default: {_yaml_quote(inputs.provider.default_model)}")
        yaml_lines.append("auxiliary:")
        yaml_lines.append("  title_generation:")
        yaml_lines.append('    model: "anthropic/claude-haiku-4.5"')
    elif ptype == "anthropic":
        yaml_lines.append("model:")
        yaml_lines.append('  provider: "anthropic"')
        yaml_lines.append(f"  default: {_yaml_quote(inputs.provider.default_model)}")
        yaml_lines.append("auxiliary:")
        yaml_lines.append("  title_generation:")
        yaml_lines.append('    model: "claude-haiku-4-5-20251001"')
    elif ptype == "openai":
        yaml_lines.append("model:")
        yaml_lines.append('  provider: "openai"')
        yaml_lines.append(f"  default: {_yaml_quote(inputs.provider.default_model)}")
        yaml_lines.append("auxiliary:")
        yaml_lines.append("  title_generation:")
        yaml_lines.append('    model: "gpt-5-nano"')
    elif ptype == "bedrock":
        yaml_lines.append("model:")
        yaml_lines.append('  provider: "bedrock"')
        yaml_lines.append(f"  default: {_yaml_quote(inputs.provider.default_model)}")
        yaml_lines.append("bedrock:")
        yaml_lines.append(f"  region: {_yaml_quote(inputs.provider.region or 'us-east-1')}")
        yaml_lines.append("auxiliary:")
        yaml_lines.append("  title_generation:")
        yaml_lines.append('    model: "anthropic.claude-haiku-4-5-20251001-v1:0"')
    elif ptype == "ollama":
        endpoint = inputs.provider.endpoint.rstrip("/")
        if not endpoint.endswith("/v1"):
            endpoint = endpoint + "/v1"
        yaml_lines.append("model:")
        yaml_lines.append('  provider: "custom"')
        yaml_lines.append(f"  base_url: {_yaml_quote(endpoint)}")
        yaml_lines.append(f"  default: {_yaml_quote(inputs.provider.default_model)}")

    # Atlassian integrations → mcp_servers entries (sorted by name).
    atlassian = [i for i in inputs.integrations if i.type == "atlassian"]
    if atlassian:
        yaml_lines.append("mcp_servers:")
        seen_slugs: set[str] = set()
        for integration in atlassian:
            creds = dict(integration.credentials)
            url = creds.get("ATLASSIAN_URL", "").rstrip("/")
            email = creds.get("ATLASSIAN_EMAIL", "")
            token = creds.get("ATLASSIAN_API_TOKEN", "")
            # Use the env-var slug (alnum + underscore only). A naive
            # `.replace('-', '_')` leaves CR/LF/colon/etc. in the key,
            # enabling YAML key injection from a malicious or
            # malformed integration name. The slug strips everything
            # outside `[A-Z0-9_]`; lowercase here so YAML keys stay
            # idiomatic snake_case.
            slug = _integration_slug(integration.name).lower()
            if not slug:
                raise AgentConfigError(
                    f"render_hermes: integration name {integration.name!r} "
                    f"slugifies to empty — refusing to emit an unnamed YAML key"
                )
            # Distinct integration names can slugify to the same YAML
            # key (e.g. `my-atlassian` and `my_atlassian` both produce
            # `my_atlassian`). PyYAML's last-wins semantics would
            # silently drop one set of credentials. Fail loud instead.
            if slug in seen_slugs:
                raise AgentConfigError(
                    f"render_hermes: atlassian integration names collide on "
                    f"YAML key {slug!r}; rename one of the integrations to "
                    f"differentiate after slugification"
                )
            seen_slugs.add(slug)
            yaml_lines.append(f"  {slug}:")
            yaml_lines.append("    env:")
            yaml_lines.append(f"      JIRA_URL: {_yaml_quote(url)}")
            yaml_lines.append(f"      JIRA_USERNAME: {_yaml_quote(email)}")
            yaml_lines.append(f"      JIRA_API_TOKEN: {_yaml_quote(token)}")
            yaml_lines.append(f"      CONFLUENCE_URL: {_yaml_quote(url + '/wiki')}")
            yaml_lines.append(f"      CONFLUENCE_USERNAME: {_yaml_quote(email)}")
            yaml_lines.append(f"      CONFLUENCE_API_TOKEN: {_yaml_quote(token)}")

    yaml_body = "\n".join(yaml_lines) + "\n"

    return RenderedFiles(
        files={
            ".hermes/.env": env_body,
            ".hermes/config.yaml": yaml_body,
        }
    )


# Zeroclaw provider section table. Each entry: (kind_string,)
_ZEROCLAW_PROVIDER_KINDS = frozenset(
    {"anthropic", "openai", "ollama", "openrouter"}
)


def render_zeroclaw(inputs: RenderInputs) -> RenderedFiles:
    """Render zeroclaw's config.toml + systemd env drop-in."""
    ptype = inputs.provider.type

    # --- config.toml -------------------------------------------------------
    toml_lines: list[str] = []
    toml_lines.append(
        f"# Managed by clawrium (clawctl). Re-render with "
        f"`clawctl agent configure {inputs.agent_name}`."
    )
    if ptype not in _ZEROCLAW_PROVIDER_KINDS:
        raise AgentConfigError(
            f"render_zeroclaw does not support provider type {ptype!r}. "
            f"Supported: {sorted(_ZEROCLAW_PROVIDER_KINDS)}"
        )
    toml_lines.append(f'default_provider = "{_toml_escape(ptype)}"')
    toml_lines.append(
        f'default_model = "{_toml_escape(inputs.provider.default_model)}"'
    )

    toml_lines.append("")
    toml_lines.append("[gateway]")
    if inputs.gateway is None:
        raise AgentConfigError(
            f"render_zeroclaw requires gateway config for agent "
            f"{inputs.agent_name!r} (port + host); none supplied"
        )
    toml_lines.append(f'host = "{_toml_escape(inputs.gateway.host)}"')
    toml_lines.append(f"port = {int(inputs.gateway.port)}")
    toml_lines.append(
        f"allow_public_bind = {str(inputs.gateway.allow_public_bind).lower()}"
    )
    toml_lines.append("require_pairing = true")

    toml_lines.append("")
    toml_lines.append(f"[providers.models.{ptype}]")
    toml_lines.append(f'kind = "{_toml_escape(ptype)}"')
    toml_lines.append(f'model = "{_toml_escape(inputs.provider.default_model)}"')
    if ptype == "ollama":
        toml_lines.append(f'base_url = "{_toml_escape(inputs.provider.endpoint)}"')
    else:
        toml_lines.append(f'api_key = "{_toml_escape(inputs.provider.api_key)}"')

    # Channels (discord only for zeroclaw today; slack is hermes-side).
    for channel in inputs.channels:
        if channel.type != "discord":
            continue
        toml_lines.append("")
        toml_lines.append("[channels.discord]")
        toml_lines.append("enabled = true")
        toml_lines.append(f'bot_token = "{_toml_escape(channel.bot_token)}"')
        guilds = ", ".join(f'"{_toml_escape(g)}"' for g in channel.allowed_guilds)
        toml_lines.append(f"allowed_guilds = [{guilds}]")
        users = ", ".join(f'"{_toml_escape(u)}"' for u in channel.allowed_users)
        toml_lines.append(f"allowed_users = [{users}]")
        toml_lines.append(f"mention_only = {str(channel.require_mention).lower()}")
        # Only emit stream_mode when explicitly set; an empty string
        # preserves the daemon's compiled "off" default. Defaulting to
        # "partial" here would flip every legacy agent into streaming
        # mode on first configure — a behavior change, not a render.
        if channel.stream_mode:
            toml_lines.append(
                f'stream_mode = "{_toml_escape(channel.stream_mode)}"'
            )

    # `[autonomy] shell_env_passthrough` is a MANDATORY block: the
    # configure playbook asserts its presence with `grep -qE
    # '^shell_env_passthrough\\s*='` and fails the deploy if missing.
    # Without listing GITHUB_TOKEN_<NAME> here, the zeroclaw sandbox
    # strips integration tokens from the shell tool's environment even
    # though the systemd drop-in injected them correctly.
    passthrough = ["PATH", "HOME", "USER", "LANG"]
    any_github = False
    for integration in inputs.integrations:
        if integration.type == "github":
            slug = _integration_slug(integration.name)
            passthrough.append(f"GITHUB_TOKEN_{slug}")
            any_github = True
    if any_github:
        passthrough.append("GITHUB_TOKEN")
    toml_lines.append("")
    toml_lines.append("[autonomy]")
    toml_lines.append(
        "shell_env_passthrough = ["
        + ", ".join(f'"{entry}"' for entry in passthrough)
        + "]"
    )

    toml_body = "\n".join(toml_lines) + "\n"

    # --- systemd env drop-in (integrations) -------------------------------
    env_lines: list[str] = []
    env_lines.append(
        f"# Managed by clawrium (clawctl). Re-render with "
        f"`clawctl agent configure {inputs.agent_name}`."
    )
    env_lines.append("[Service]")
    last_github_token = ""
    for integration in inputs.integrations:
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


# Openclaw provider env-var table. `vertex` is intentionally absent:
# `GOOGLE_APPLICATION_CREDENTIALS` is a path to an ADC JSON file, not a
# bearer string. Emitting `inputs.provider.api_key` into it would
# silently produce a broken config — GCP client libs reject token
# strings. Vertex support belongs in a follow-up that extends the
# credential schema with a credential-kind field (path vs bearer).
_OPENCLAW_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "zai": "ZAI_API_KEY",
}
_OPENCLAW_MODEL_PREFIX = {
    "openrouter": "openrouter/",
    "bedrock": "bedrock/",
}


def render_openclaw(inputs: RenderInputs) -> RenderedFiles:
    """Render openclaw's `.env`."""
    ptype = inputs.provider.type
    env_lines: list[str] = []
    env_lines.append(
        f"# Managed by clawrium (clawctl). Re-render with "
        f"`clawctl agent configure {inputs.agent_name}`."
    )
    if inputs.gateway is not None:
        # Shell-quote `bind` so a CRLF-injected value can't smuggle an
        # extra `KEY=VALUE` line into the EnvironmentFile.
        env_lines.append(
            f"OPENCLAW_GATEWAY_BIND={_shell_quote(inputs.gateway.bind or 'lan')}"
        )
        env_lines.append(f"OPENCLAW_GATEWAY_PORT={int(inputs.gateway.port or 40000)}")
        env_lines.append(
            f"OPENCLAW_GATEWAY_AUTH_MODE={'token' if inputs.gateway.auth else 'none'}"
        )
        env_lines.append(
            f"OPENCLAW_GATEWAY_AUTH_TOKEN={_shell_quote(inputs.gateway.auth)}"
        )

    model_id = inputs.provider.default_model
    prefix = _OPENCLAW_MODEL_PREFIX.get(ptype, "")
    if prefix and not model_id.startswith(prefix):
        model_id = prefix + model_id
    env_lines.append(f"OPENCLAW_DEFAULT_MODEL={_shell_quote(model_id)}")

    if ptype in _OPENCLAW_PROVIDER_ENV:
        env_lines.append(
            f"{_OPENCLAW_PROVIDER_ENV[ptype]}={_shell_quote(inputs.provider.api_key)}"
        )
    elif ptype == "bedrock":
        env_lines.append(f"AWS_ACCESS_KEY_ID={_shell_quote(inputs.provider.aws_access_key)}")
        env_lines.append(f"AWS_SECRET_ACCESS_KEY={_shell_quote(inputs.provider.aws_secret_key)}")
    elif ptype == "ollama":
        env_lines.append(f"OPENCLAW_OLLAMA_URL={_shell_quote(inputs.provider.endpoint)}")
    else:
        raise AgentConfigError(
            f"render_openclaw does not support provider type {ptype!r}. "
            f"Supported: {sorted(_OPENCLAW_PROVIDER_ENV) + ['bedrock', 'ollama']}"
        )

    for channel in inputs.channels:
        if channel.type == "discord":
            env_lines.append(f"DISCORD_BOT_TOKEN={_shell_quote(channel.bot_token)}")
        elif channel.type == "slack":
            env_lines.append(f"SLACK_BOT_TOKEN={_shell_quote(channel.bot_token)}")
            env_lines.append(f"SLACK_APP_TOKEN={_shell_quote(channel.app_token)}")
        else:
            raise AgentConfigError(
                f"render_openclaw: unsupported channel type {channel.type!r}"
            )

    last_github_token = ""
    for integration in inputs.integrations:
        creds = dict(integration.credentials)
        if integration.type == "github":
            token = creds.get("GITHUB_TOKEN", "")
            slug = _integration_slug(integration.name)
            env_lines.append(f"GITHUB_TOKEN_{slug}={_shell_quote(token)}")
            last_github_token = token
        elif integration.type == "gitlab":
            env_lines.append(f"GITLAB_TOKEN={_shell_quote(creds.get('GITLAB_TOKEN', ''))}")
            if "GITLAB_URL" in creds:
                env_lines.append(f"GITLAB_URL={_shell_quote(creds['GITLAB_URL'])}")
        elif integration.type == "atlassian":
            url = creds.get("ATLASSIAN_URL", "").rstrip("/")
            email = creds.get("ATLASSIAN_EMAIL", "")
            token = creds.get("ATLASSIAN_API_TOKEN", "")
            env_lines.append(f"JIRA_URL={_shell_quote(url)}")
            env_lines.append(f"CONFLUENCE_URL={_shell_quote(url + '/wiki')}")
            env_lines.append(f"JIRA_EMAIL={_shell_quote(email)}")
            env_lines.append(f"CONFLUENCE_EMAIL={_shell_quote(email)}")
            env_lines.append(f"JIRA_API_TOKEN={_shell_quote(token)}")
            env_lines.append(f"CONFLUENCE_API_TOKEN={_shell_quote(token)}")
        elif integration.type == "linear":
            env_lines.append(
                f"LINEAR_API_KEY={_shell_quote(creds.get('LINEAR_API_KEY', ''))}"
            )
        elif integration.type == "notion":
            env_lines.append(
                f"NOTION_API_KEY={_shell_quote(creds.get('NOTION_API_KEY', ''))}"
            )
        elif integration.type == "git":
            continue
        else:
            raise AgentConfigError(
                f"render_openclaw: unsupported integration type {integration.type!r}"
            )
    if last_github_token:
        env_lines.append(f"GITHUB_TOKEN={_shell_quote(last_github_token)}")

    env_body = "\n".join(env_lines) + "\n"
    # Path is `.openclaw/env` (no leading dot on the filename) to match
    # the configure playbook's lineinfile target. A dot-prefixed name
    # would silently render to a file the playbook never reads.
    return RenderedFiles(files={".openclaw/env": env_body})

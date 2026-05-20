"""Rendering tests for the v0.7.5 zeroclaw config.toml.j2 template.

Covers issue #357 (Subtask B):
- gateway block: host, port, allow_public_bind, require_pairing
- top-level default_provider + default_model
- per-provider [providers.models.<name>] sub-table with `kind` discriminator
- api_key for anthropic/openai/openrouter; base_url for ollama
- TOML escape correctness on api_key (containing quotes / backslashes)

Provider scope is intentionally limited to the four #112 providers:
anthropic, openai, ollama, openrouter. The legacy integrations block
(github, gitlab, atlassian, linear, notion) is removed from this
template by #357 and tracked as a follow-up outside #112.
"""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader


ZEROCLAW_TEMPLATES = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "zeroclaw"
    / "templates"
)

_GATEWAY_DEFAULTS = {
    "host": "0.0.0.0",
    "port": 4080,
    "allow_public_bind": True,
    "require_pairing": True,
}


def _ansible_bool(v):
    """Mirror Ansible's string coercion in the `bool` filter."""
    if isinstance(v, str):
        return v.lower() not in ("no", "false", "0", "")
    return bool(v)


def _ansible_regex_replace_top(value, pattern, replacement=""):
    """Module-level mirror of ansible.builtin.filter.regex_replace, used by
    `_render()`. The #422 section below defines an identical helper for the
    bigger renderers — both registered with the same filter name in their
    respective env instances so the test renderer matches production."""
    import re as _re_mod

    return _re_mod.sub(pattern, replacement, str(value))


def _render(
    provider: dict | None,
    provider_api_key: str = "",
    personality: dict | None = None,
    agent_name: str | None = None,
) -> str:
    """Render `config.toml.j2` with the given provider block."""
    env = Environment(loader=FileSystemLoader(str(ZEROCLAW_TEMPLATES)))
    env.filters["bool"] = _ansible_bool
    # ATX Round 5 W2: register regex_replace here too. The template's
    # [autonomy] block calls regex_replace inside the integrations loop.
    # _render() never passes integrations today so it's not exercised, but
    # keeping the test-renderer's filter set in sync with the production
    # ansible env avoids a future opaque TemplateAssertionError. Mirrors
    # _render_with_channels_and_integrations() at line ~376.
    env.filters["regex_replace"] = _ansible_regex_replace_top
    template = env.get_template("config.toml.j2")
    config = {"gateway": dict(_GATEWAY_DEFAULTS)}
    if provider is not None:
        config["provider"] = provider
    if personality is not None:
        config["personality"] = personality
    ctx = {"config": config, "provider_api_key": provider_api_key}
    if agent_name is not None:
        ctx["agent_name"] = agent_name
    return template.render(**ctx)


class TestGatewayBlock:
    """The [gateway] header lands the security defaults from issue #357."""

    def test_gateway_block_emits_security_defaults(self):
        rendered = _render(
            provider={"type": "anthropic", "default_model": "claude-sonnet-4-5"},
            provider_api_key="sk-test",
        )
        assert "[gateway]" in rendered
        assert 'host = "0.0.0.0"' in rendered
        assert "port = 4080" in rendered
        assert "allow_public_bind = true" in rendered
        assert "require_pairing = true" in rendered

    def test_gateway_require_pairing_defaults_to_true_when_unset(self):
        """`require_pairing` MUST default to true when the caller doesn't pass
        it. A silent false default would let the daemon accept unauthenticated
        requests — the threat model in .itx/357/01_EXECUTION.md rules that
        out."""
        env = Environment(loader=FileSystemLoader(str(ZEROCLAW_TEMPLATES)))
        env.filters["bool"] = _ansible_bool
        template = env.get_template("config.toml.j2")
        # Build the config without require_pairing to force the default.
        config = {
            "gateway": {"host": "0.0.0.0", "port": 4080, "allow_public_bind": True},
            "provider": {"type": "anthropic"},
        }
        rendered = template.render(config=config, provider_api_key="sk-test")
        assert "require_pairing = true" in rendered


class TestProviderRenderingAnthropic:
    def test_anthropic_renders_sub_table_with_api_key(self):
        rendered = _render(
            provider={"type": "anthropic", "default_model": "claude-sonnet-4-5"},
            provider_api_key="sk-ant-test",
        )
        assert 'default_provider = "anthropic"' in rendered
        assert 'default_model = "claude-sonnet-4-5"' in rendered
        assert "[providers.models.anthropic]" in rendered
        assert 'kind = "anthropic"' in rendered
        assert 'model = "claude-sonnet-4-5"' in rendered
        assert 'api_key = "sk-ant-test"' in rendered
        # Anthropic must NOT emit base_url (that's ollama only).
        assert "base_url" not in rendered

    def test_anthropic_api_key_toml_escaped(self):
        """A key with embedded quotes / backslashes must be TOML-escaped."""
        key = 'sk"with"quote\\and\\bs'
        rendered = _render(
            provider={"type": "anthropic", "default_model": "claude-sonnet-4-5"},
            provider_api_key=key,
        )
        # Per TOML basic-string rules: \\ for backslash, \" for quote.
        assert 'api_key = "sk\\"with\\"quote\\\\and\\\\bs"' in rendered

    def test_api_key_with_control_chars_is_escaped(self):
        """ATX Round 1 B1: an api_key containing CR/LF/TAB must NOT be
        able to break out of the TOML basic string and inject keys. The
        escape macro must encode \\r, \\n, \\t as TOML escape sequences."""
        key = "leading\ninjected_key = \"evil\"\nokay"
        rendered = _render(
            provider={"type": "anthropic", "default_model": "claude-sonnet-4-5"},
            provider_api_key=key,
        )
        # The literal newline must be encoded; the rendered file must
        # have api_key on exactly one line (no break-out).
        assert 'api_key = "leading\\ninjected_key = \\"evil\\"\\nokay"' in rendered
        # And no injected `injected_key = "evil"` TOML statement.
        for line in rendered.splitlines():
            stripped = line.strip()
            if stripped.startswith("injected_key"):
                raise AssertionError(
                    f"TOML injection succeeded — got bare key line: {stripped!r}"
                )

    def test_api_key_with_carriage_return_is_escaped(self):
        """`\\r` alone also splits TOML lines on some parsers; escape it."""
        key = "abc\rdef"
        rendered = _render(
            provider={"type": "anthropic", "default_model": "x"},
            provider_api_key=key,
        )
        assert 'api_key = "abc\\rdef"' in rendered

    def test_api_key_with_tab_is_escaped(self):
        """ATX Round 2 W6: a raw `\\t` in a TOML basic string is
        permitted by spec but parsed inconsistently across implementations;
        toml_escape must encode it. This pins the escape behavior so a
        future refactor can't drop the `\\t` branch from the macro."""
        key = "abc\tdef"
        rendered = _render(
            provider={"type": "anthropic", "default_model": "x"},
            provider_api_key=key,
        )
        assert 'api_key = "abc\\tdef"' in rendered


class TestProviderRenderingOpenAI:
    def test_openai_renders_sub_table_with_api_key(self):
        rendered = _render(
            provider={"type": "openai", "default_model": "gpt-4o"},
            provider_api_key="sk-oa-test",
        )
        assert 'default_provider = "openai"' in rendered
        assert 'default_model = "gpt-4o"' in rendered
        assert "[providers.models.openai]" in rendered
        assert 'kind = "openai"' in rendered
        assert 'model = "gpt-4o"' in rendered
        assert 'api_key = "sk-oa-test"' in rendered
        assert "base_url" not in rendered


class TestProviderRenderingOpenRouter:
    def test_openrouter_renders_sub_table_with_api_key(self):
        rendered = _render(
            provider={
                "type": "openrouter",
                "default_model": "anthropic/claude-3.5-sonnet",
            },
            provider_api_key="sk-or-test",
        )
        assert 'default_provider = "openrouter"' in rendered
        assert 'default_model = "anthropic/claude-3.5-sonnet"' in rendered
        assert "[providers.models.openrouter]" in rendered
        assert 'kind = "openrouter"' in rendered
        assert 'model = "anthropic/claude-3.5-sonnet"' in rendered
        assert 'api_key = "sk-or-test"' in rendered
        assert "base_url" not in rendered


class TestProviderRenderingOllama:
    def test_ollama_renders_sub_table_with_base_url(self):
        rendered = _render(
            provider={
                "type": "ollama",
                "default_model": "llama3",
                "endpoint": "http://192.168.1.50:11434",
            },
            # provider_api_key is intentionally NOT used for ollama; pass
            # something non-empty to verify it does not leak through.
            provider_api_key="should-not-render-for-ollama",
        )
        assert 'default_provider = "ollama"' in rendered
        assert 'default_model = "llama3"' in rendered
        assert "[providers.models.ollama]" in rendered
        assert 'kind = "ollama"' in rendered
        assert 'model = "llama3"' in rendered
        assert 'base_url = "http://192.168.1.50:11434"' in rendered
        # Ollama is unauthenticated; api_key must NEVER render for it.
        assert "api_key" not in rendered
        assert "should-not-render-for-ollama" not in rendered

    def test_ollama_base_url_toml_escaped(self):
        endpoint = 'http://host:11434/v1"path'
        rendered = _render(
            provider={
                "type": "ollama",
                "default_model": "llama3",
                "endpoint": endpoint,
            },
        )
        assert 'base_url = "http://host:11434/v1\\"path"' in rendered


class TestProviderRenderingUnsupportedProvider:
    """Unsupported provider types must NOT emit a providers.models block.

    The configure playbook fails-fast on these via its `Validate provider
    configuration is present` task, so the template's tolerant behavior
    (render gateway, skip provider) keeps the playbook's failure message
    as the user-facing error rather than producing malformed TOML.
    """

    def test_unknown_provider_type_skips_provider_block(self):
        rendered = _render(
            provider={"type": "bedrock", "default_model": "anthropic.claude-3"},
            provider_api_key="aws-sig",
        )
        # gateway block is still emitted.
        assert "[gateway]" in rendered
        # providers.models block is NOT emitted for unknown types.
        assert "[providers.models" not in rendered
        assert "default_provider" not in rendered

    def test_no_provider_dict_skips_provider_block(self):
        rendered = _render(provider=None)
        assert "[gateway]" in rendered
        assert "[providers.models" not in rendered
        assert "default_provider" not in rendered


class TestIntegrationsRemoved:
    """The legacy `[integrations]` block must NOT render in v0.7.5.

    Integrations (github/gitlab/atlassian/linear/notion) are explicitly
    out of scope for #112 and will land in a follow-up issue. A regression
    that re-introduces them would silently leak integration credentials
    into config.toml on every configure run.
    """

    def test_no_integrations_block_rendered_for_any_provider(self):
        for provider_type in ("anthropic", "openai", "openrouter", "ollama"):
            kwargs = {"type": provider_type, "default_model": "m"}
            if provider_type == "ollama":
                kwargs["endpoint"] = "http://localhost:11434"
            rendered = _render(provider=kwargs, provider_api_key="k")
            assert "[integrations]" not in rendered, (
                f"integrations block leaked for provider {provider_type}"
            )
            for token_name in (
                "github_token",
                "gitlab_token",
                "jira_url",
                "jira_api_token",
                "confluence_url",
                "linear_api_key",
                "notion_api_key",
            ):
                assert token_name not in rendered, (
                    f"{token_name} leaked for provider {provider_type}"
                )


class TestPersonalityBlock:
    """The [personality] block (#358) seeds the daemon with name/timezone/style."""

    def test_personality_block_defaults_when_unspecified(self):
        rendered = _render(
            provider={"type": "anthropic", "default_model": "m"},
            provider_api_key="k",
        )
        assert "[personality]" in rendered
        # No agent_name passed, no personality dict → falls back to 'zeroclaw'.
        assert 'name = "zeroclaw"' in rendered
        assert 'timezone = "UTC"' in rendered
        assert 'communication_style = "direct, concise"' in rendered

    def test_personality_block_uses_agent_name_fallback(self):
        rendered = _render(
            provider={"type": "anthropic", "default_model": "m"},
            provider_api_key="k",
            agent_name="zc-edge",
        )
        # name should fall back to agent_name when personality.name is unset.
        assert 'name = "zc-edge"' in rendered

    def test_personality_overrides_apply(self):
        rendered = _render(
            provider={"type": "anthropic", "default_model": "m"},
            provider_api_key="k",
            personality={
                "name": "lighthouse",
                "timezone": "America/Los_Angeles",
                "communication_style": "verbose",
            },
        )
        assert 'name = "lighthouse"' in rendered
        assert 'timezone = "America/Los_Angeles"' in rendered
        assert 'communication_style = "verbose"' in rendered

    @pytest.mark.parametrize(
        "field",
        ["name", "timezone", "communication_style"],
    )
    def test_personality_values_are_toml_escaped(self, field: str):
        # ATX iter 1 W8: each personality field must independently pass
        # through toml_escape. A regression that drops the macro from a
        # single field would otherwise slip past a name-only test (the
        # same shape of bug ATX flagged for `api_key` in earlier rounds).
        payload = (
            'evil"\n[providers.models.injected]\nkind = "anthropic'
        )
        personality = {
            "name": "ok-name",
            "timezone": "UTC",
            "communication_style": "concise",
        }
        personality[field] = payload
        rendered = _render(
            provider={"type": "anthropic", "default_model": "m"},
            provider_api_key="k",
            personality=personality,
        )
        # The injected text must appear as escape sequences INSIDE the
        # basic string. What must NOT happen: a line that begins a new
        # TOML section header.
        for line in rendered.splitlines():
            assert line.strip() != "[providers.models.injected]", (
                f"TOML injection succeeded via personality.{field} — "
                f"payload broke out of basic string: {line!r}"
            )


# ---------------------------------------------------------------------------
# #422 — [channels.discord], [autonomy], and clm-env.conf.j2 rendering
# ---------------------------------------------------------------------------


import re as _re422  # noqa: E402  (test-section import, kept local)


def _ansible_regex_replace(value, pattern, replacement=""):
    """Ansible's `regex_replace` filter, reimplemented for the bare-Jinja
    test renderer (same pattern as tests/test_hermes_configure.py:23-29)."""
    return _re422.sub(pattern, replacement, str(value))


def _render_with_channels_and_integrations(
    *,
    channels: dict | None = None,
    integrations: dict | None = None,
    provider: dict | None = None,
    provider_api_key: str = "sk-test",
) -> str:
    """Render config.toml.j2 with the #422 extensions wired in.

    Mirrors the production Ansible env: registers `bool` + `regex_replace`
    filters so the [autonomy] block's per-integration env-var name
    construction matches what the configure playbook actually produces.
    """
    env = Environment(loader=FileSystemLoader(str(ZEROCLAW_TEMPLATES)))
    env.filters["bool"] = _ansible_bool
    env.filters["regex_replace"] = _ansible_regex_replace
    template = env.get_template("config.toml.j2")
    config = {"gateway": dict(_GATEWAY_DEFAULTS)}
    if provider is not None:
        config["provider"] = provider
    if channels is not None:
        config["channels"] = channels
    return template.render(
        config=config,
        provider_api_key=provider_api_key,
        integrations=integrations or {},
    )


def _render_systemd_dropin(integrations: dict | None) -> str:
    """Render the clm-env.conf.j2 drop-in with the supplied integrations dict."""
    env = Environment(
        loader=FileSystemLoader(str(ZEROCLAW_TEMPLATES)),
        keep_trailing_newline=True,
    )
    env.filters["regex_replace"] = _ansible_regex_replace
    template = env.get_template("clm-env.conf.j2")
    return template.render(integrations=integrations or {}, agent_name="zc1")


class TestChannelsDiscordBlock:
    """[channels.discord] is the upstream-documented v0.7.5 schema —
    docs/book/src/channels/chat-others.md. Only keys listed in that doc
    may appear in the rendered TOML.
    """

    def test_no_discord_block_when_disabled(self):
        rendered = _render_with_channels_and_integrations(
            channels={"discord": {"enabled": False}},
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "[channels.discord]" not in rendered

    def test_no_discord_block_when_token_missing(self):
        """`enabled = true` without a hydrated bot_token must not render —
        the playbook's verify_bot_token grep would fail, but the template
        is the first defense."""
        rendered = _render_with_channels_and_integrations(
            channels={"discord": {"enabled": True}},
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "[channels.discord]" not in rendered

    def test_discord_block_emits_upstream_fields(self):
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": "DUMMY_BOT_TOKEN_VALUE",
                    "allowed_users": ["123456789012345678"],
                    "allowed_guilds": ["987654321098765432"],
                    "require_mention": True,
                    "draft_update_interval_ms": 750,
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "[channels.discord]" in rendered
        assert "enabled = true" in rendered
        assert 'bot_token = "DUMMY_BOT_TOKEN_VALUE"' in rendered
        assert 'allowed_users = ["123456789012345678"]' in rendered
        assert 'allowed_guilds = ["987654321098765432"]' in rendered
        # require_mention (hermes naming) → reply_to_mentions_only (upstream).
        assert "reply_to_mentions_only = true" in rendered
        assert "draft_update_interval_ms = 750" in rendered

    def test_discord_block_drops_hermes_only_fields(self):
        """home_channel, home_channel_name, allow_all_users, allowed_channels
        have no zeroclaw upstream equivalent and must NOT leak into the
        rendered TOML — the daemon would reject the file or silently ignore."""
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": "DUMMY",
                    "home_channel": "111",
                    "home_channel_name": "general",
                    "home_channel_thread_id": "222",
                    "allow_all_users": True,
                    "allowed_channels": ["333"],
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "home_channel" not in rendered
        assert "allow_all_users" not in rendered
        assert "allowed_channels" not in rendered

    def test_discord_legacy_record_defaults_reply_to_mentions_to_true(self):
        """ATX Round 4 B1-R4: a hosts.json record predating the
        require_mention field (the dict has `enabled` + `bot_token` but no
        require_mention) MUST render `reply_to_mentions_only = true`.

        The fragile form `_discord.get('require_mention') | default(true)`
        silently rendered `false` because dict.get returns None for missing
        keys and Jinja's default() only fires on Undefined. dict.get(key,
        default) applies the default at the Python level, bypassing the
        filter entirely."""
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": "DUMMY_LEGACY_TOKEN_VALUE",
                    # NB: require_mention deliberately absent — simulating a
                    # legacy hosts.json record written before the field was
                    # added in #422.
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "reply_to_mentions_only = true" in rendered, (
            "Legacy hosts.json record rendered reply_to_mentions_only=false "
            "— this is the ATX Round 4 B1-R4 safety regression. The CLI "
            "default is True; the template must match."
        )

    def test_discord_bot_token_newline_toml_injection_blocked(self):
        """ATX Round 5 W1: parallel to the api_key control-char test. A
        bot_token containing `\\n` + a fake TOML statement must NOT break
        out of the basic string into the next [section]. The toml_escape
        macro encodes \\r/\\n/\\t today, but without an explicit test a
        future macro refactor could drop a branch and leave bot_token
        injectable while the api_key test still passes."""
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": 'tok\ninjected_key = "evil"\nok',
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        # The encoded payload must appear inside the bot_token line, not
        # as a top-level injected TOML statement.
        assert (
            'bot_token = "tok\\ninjected_key = \\"evil\\"\\nok"' in rendered
        )
        # No injected top-level key.
        for line in rendered.splitlines():
            assert not line.strip().startswith("injected_key"), (
                f"TOML injection succeeded via bot_token newline payload: "
                f"{line!r}"
            )

    def test_discord_allowed_users_array_elements_toml_escaped(self):
        """ATX Round 5 W6: array elements must also pass through
        toml_escape. A regression dropping the macro on the loop body
        would let a quote-bearing ID break out of the array."""
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": "DUMMY",
                    "allowed_users": ['98765"evil', "740723459344302120"],
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        # Escaped quote inside the array element.
        assert '"98765\\"evil"' in rendered
        # No raw injection landing outside the string.
        for line in rendered.splitlines():
            assert not line.strip().startswith("evil"), (
                f"allowed_users element broke out of TOML basic string: "
                f"{line!r}"
            )

    def test_discord_allowed_guilds_array_elements_toml_escaped(self):
        """ATX Round 5 W6 (symmetric to allowed_users)."""
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": "DUMMY",
                    "allowed_guilds": ['11111"evil', "987654321098765432"],
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert '"11111\\"evil"' in rendered
        for line in rendered.splitlines():
            assert not line.strip().startswith("evil"), (
                f"allowed_guilds element broke out of TOML basic string: "
                f"{line!r}"
            )

    def test_discord_draft_update_interval_zero_omitted(self):
        """ATX Round 5 W5: integer `0` is falsy in Jinja2/Python so the
        current `{% if _discord.get('draft_update_interval_ms') %}` guard
        silently drops a zero value. This test pins that behavior so any
        future change to treat `0` as a real value (e.g., real-time
        updates) is a conscious decision, not a silent semantic flip.
        Operators relying on this should be aware: zeroclaw's daemon
        applies its compiled-in default when the key is absent."""
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": "DUMMY",
                    "draft_update_interval_ms": 0,
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "draft_update_interval_ms" not in rendered, (
            "Zero value for draft_update_interval_ms is currently dropped "
            "by the falsy-check; if intentional, document. If not, treat "
            "0 as a valid configured value."
        )

    def test_discord_explicit_false_require_mention_renders_false(self):
        """Counterpart to the legacy-default test: an explicit `False` value
        must NOT be overridden to `True`. This catches the alternative
        `| default(true, boolean=True)` form, which would clobber explicit
        opt-outs."""
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": "DUMMY",
                    "require_mention": False,
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "reply_to_mentions_only = false" in rendered

    def test_discord_bot_token_toml_escaped(self):
        """Tokens with embedded quotes/backslashes must be escaped so they
        cannot break out of the TOML basic string and inject `[autonomy]`
        overrides below."""
        rendered = _render_with_channels_and_integrations(
            channels={
                "discord": {
                    "enabled": True,
                    "bot_token": 'tok"with"quote\\and\\bs',
                }
            },
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert 'bot_token = "tok\\"with\\"quote\\\\and\\\\bs"' in rendered


class TestAgentBlock:
    """[agent] pins the daemon's tool-loop + context budgets above their
    too-tight defaults (10 iterations / 32k tokens), which were causing
    multi-step PR workflows to hit `Max iterations reached` and poison
    the conversation history with phantom-block hallucinations."""

    def test_agent_block_pins_iteration_and_context_budgets(self):
        rendered = _render_with_channels_and_integrations(
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "[agent]" in rendered
        assert "max_tool_iterations = 30" in rendered
        assert "max_context_tokens = 100000" in rendered


class TestAutonomyBlock:
    """[autonomy] is always rendered (no gate). The default block mirrors
    docs/book/src/security/autonomy.md verbatim. shell_env_passthrough is
    extended when github integrations are assigned."""

    def test_autonomy_block_always_renders(self):
        rendered = _render_with_channels_and_integrations(
            provider={"type": "anthropic", "default_model": "m"},
        )
        assert "[autonomy]" in rendered
        assert 'level = "supervised"' in rendered
        assert "approval_timeout_secs = 300" in rendered
        assert "workspace_only = true" in rendered
        # Explicit broad developer allowlist. v0.7.5 treats `[]` as
        # deny-all (vs. the doc's implied permissive), so we enumerate.
        # Spot-check representative entries from each category — the
        # exhaustive list lives in the template and changes more often
        # than the categories.
        assert '"git"' in rendered
        assert '"gh"' in rendered
        assert '"make"' in rendered
        assert '"curl"' in rendered
        assert '"bash"' in rendered
        assert '"rm"' in rendered
        assert '"jq"' in rendered
        # block_high_risk_commands is intentionally OFF — the pattern
        # matcher was blocking `git push` / `git branch <new>` as
        # high-risk; the supervised approval flow now arbitrates.
        assert "block_high_risk_commands = false" in rendered
        # System-wrecker denylist + escalation guards.
        assert '"shutdown"' in rendered
        assert '"mkfs"' in rendered
        assert '"dd"' in rendered
        assert '"sudo"' in rendered
        # forbidden_paths covers system + secret-bearing dotdirs.
        assert '"/etc"' in rendered
        assert '"/proc"' in rendered
        assert '"~/.ssh"' in rendered
        assert '"~/.config/clawrium"' in rendered

    def test_shell_env_passthrough_defaults_to_upstream_four(self):
        rendered = _render_with_channels_and_integrations(
            provider={"type": "anthropic", "default_model": "m"},
        )
        # Without github integrations, only the 4 upstream-default vars.
        assert (
            'shell_env_passthrough = ["PATH", "HOME", "USER", "LANG"]' in rendered
        )

    def test_shell_env_passthrough_appends_github_token_names(self):
        rendered = _render_with_channels_and_integrations(
            provider={"type": "anthropic", "default_model": "m"},
            integrations={
                "work-gh": {"type": "github", "GITHUB_TOKEN": "ghp_DUMMY1"},
                "personal-gh": {"type": "github", "GITHUB_TOKEN": "ghp_DUMMY2"},
            },
        )
        # Defaults still present + per-name + canonical at the end (so the
        # bare GITHUB_TOKEN tracks the last integration alphabetically:
        # `work-gh` > `personal-gh` → bare entry follows GITHUB_TOKEN_WORK_GH).
        assert "PATH" in rendered
        assert "GITHUB_TOKEN_PERSONAL_GH" in rendered
        assert "GITHUB_TOKEN_WORK_GH" in rendered
        # The canonical GITHUB_TOKEN entry must be present (after the per-name
        # entries per template construction).
        assert _re422.search(
            r'shell_env_passthrough\s*=\s*\[[^\]]*"GITHUB_TOKEN"', rendered
        ), f"GITHUB_TOKEN missing from shell_env_passthrough: {rendered}"

    def test_shell_env_passthrough_excludes_non_github_integrations(self):
        """An assigned atlassian integration must NOT add its credential
        names to the autonomy allowlist — that table is GitHub-specific."""
        rendered = _render_with_channels_and_integrations(
            provider={"type": "anthropic", "default_model": "m"},
            integrations={
                "atl": {
                    "type": "atlassian",
                    "ATLASSIAN_API_TOKEN": "atl_DUMMY",
                    "ATLASSIAN_EMAIL": "a@b.c",
                    "ATLASSIAN_URL": "https://x.atlassian.net",
                },
            },
        )
        assert "ATLASSIAN_API_TOKEN" not in rendered
        assert "GITHUB_TOKEN" not in rendered

    def test_github_integration_name_sanitized_for_env_var(self):
        """Names with hyphens/uppercase must end up uppercase + underscored.
        Defense-in-depth: any char outside [A-Z0-9_] is stripped, mirroring
        hermes .env.j2:118."""
        rendered = _render_with_channels_and_integrations(
            provider={"type": "anthropic", "default_model": "m"},
            integrations={
                "team-a-gh": {"type": "github", "GITHUB_TOKEN": "ghp_X"},
            },
        )
        assert "GITHUB_TOKEN_TEAM_A_GH" in rendered


class TestSystemdDropIn:
    """clm-env.conf.j2 lands at /etc/systemd/system/zeroclaw-<n>.service.d/
    and must emit one canonical `Environment=GITHUB_TOKEN=` line plus a
    per-name line per github integration. Shell-quote semantics differ
    from hermes (.env files use single-quotes; systemd Environment= uses
    double-quotes)."""

    def test_dropin_is_empty_service_block_without_integrations(self):
        rendered = _render_systemd_dropin(integrations={})
        # systemd accepts a `[Service]` header with no directives as a no-op
        # overlay. Confirm we never emit Environment= when no github integrations.
        assert "[Service]" in rendered
        assert "Environment=" not in rendered

    def test_dropin_emits_per_name_and_canonical_lines(self):
        rendered = _render_systemd_dropin(
            integrations={
                "work-gh": {"type": "github", "GITHUB_TOKEN": "ghp_WORK"},
                "personal-gh": {"type": "github", "GITHUB_TOKEN": "ghp_PERSONAL"},
            },
        )
        # Both per-name entries.
        assert 'Environment=GITHUB_TOKEN_WORK_GH="ghp_WORK"' in rendered
        assert 'Environment=GITHUB_TOKEN_PERSONAL_GH="ghp_PERSONAL"' in rendered
        # Canonical GITHUB_TOKEN tracks the dictsort-last integration
        # (work-gh > personal-gh alphabetically).
        canonical_lines = [
            line
            for line in rendered.splitlines()
            if line.startswith('Environment=GITHUB_TOKEN="')
        ]
        # Two integrations → two canonical lines (one per loop iteration);
        # the last one wins at systemd's level. Mirrors hermes .env.j2.
        assert len(canonical_lines) == 2
        # Final canonical entry must be from the alphabetically-last name.
        assert canonical_lines[-1] == 'Environment=GITHUB_TOKEN="ghp_WORK"'

    def test_dropin_quote_escaping_systemd_style(self):
        """Tokens with embedded double-quotes or backslashes must be escaped
        with backslash-double-quote / double-backslash so systemd's
        Environment= parser doesn't terminate the value early."""
        rendered = _render_systemd_dropin(
            integrations={
                "gh": {
                    "type": "github",
                    "GITHUB_TOKEN": 'tok"with"quote\\and\\bs',
                },
            },
        )
        assert (
            'Environment=GITHUB_TOKEN="tok\\"with\\"quote\\\\and\\\\bs"'
            in rendered
        )

    def test_dropin_skips_non_github_integrations(self):
        rendered = _render_systemd_dropin(
            integrations={
                "atl": {
                    "type": "atlassian",
                    "ATLASSIAN_API_TOKEN": "atl_DUMMY",
                },
            },
        )
        assert "Environment=" not in rendered

    def test_dropin_strips_newline_injection_attempts(self):
        """ATX Round 1 W3: per systemd.exec(5), an embedded `\\n` inside a
        quoted Environment= value terminates the directive and the rest is
        parsed as a new systemd statement — a vector to inject e.g.
        `Environment=PATH=/evil`. The systemd_quote macro must strip CR/LF
        before quoting so a malformed token cannot smuggle in extra
        directives. github PATs never contain newlines so this drops only
        malicious-or-corrupted input."""
        rendered = _render_systemd_dropin(
            integrations={
                "gh": {
                    "type": "github",
                    "GITHUB_TOKEN": "ghp_real\nEnvironment=PATH=/evil\nthe_rest",
                },
            },
        )
        # The injection attempt must NOT appear as a new directive.
        for line in rendered.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("Environment=PATH="), (
                f"systemd-directive injection succeeded via newline in "
                f"GITHUB_TOKEN: {line!r}"
            )
        # The token (stripped of its newlines) lands on a single line.
        assert (
            'Environment=GITHUB_TOKEN="ghp_realEnvironment=PATH=/evilthe_rest"'
            in rendered
        )

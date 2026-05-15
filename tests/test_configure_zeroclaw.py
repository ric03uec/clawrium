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


def _render(
    provider: dict | None,
    provider_api_key: str = "",
    personality: dict | None = None,
    agent_name: str | None = None,
) -> str:
    """Render `config.toml.j2` with the given provider block."""
    env = Environment(loader=FileSystemLoader(str(ZEROCLAW_TEMPLATES)))
    env.filters["bool"] = _ansible_bool
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

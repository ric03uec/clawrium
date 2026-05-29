"""Tests for the Hermes configure playbook + template + API_SERVER_KEY persistence.

These cover:
- `.env.j2` rendering across openrouter / anthropic / openai / ollama branches
- `config.yaml.j2` rendering for ollama (model.provider=custom, base_url with /v1)
- `configure.yaml` playbook structure: handler triggers, /health probe, credential
  verification, missing-API_SERVER_KEY guard
- `configure_agent()` rejects hermes agents missing api_server.key in hosts.json
- `configure_agent()` reuses persisted api_server.key across reconfigures
  (idempotency contract)
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from jinja2 import Environment, FileSystemLoader

from clawrium.core.lifecycle import configure_agent


def _ansible_regex_replace(value, pattern, replacement=""):
    """Ansible's `regex_replace` filter, reimplemented for the bare-Jinja
    test renderer. Production rendering goes through Ansible's Jinja env
    which registers this filter natively; matching the test renderer keeps
    template assertions honest. Mirrors ansible.builtin.filter.regex_replace.
    """
    return re.sub(pattern, replacement, str(value))


HERMES_TEMPLATES = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "hermes"
    / "templates"
)
HERMES_PLAYBOOKS = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "registry"
    / "hermes"
    / "playbooks"
)


def _render_env(
    config: dict,
    provider_api_key: str = "",
    agent_name: str = "h",
    integrations: dict | None = None,
    pass_integrations_raw: bool = False,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(HERMES_TEMPLATES)),
        keep_trailing_newline=True,
    )
    env.filters["regex_replace"] = _ansible_regex_replace
    template = env.get_template("hermes.env.j2")
    # `pass_integrations_raw=True` lets a test pass `None` or other unusual
    # values through the helper without the `or {}` coercion — used to assert
    # the template's `default({})` guard actually fires.
    return template.render(
        config=config,
        provider_api_key=provider_api_key,
        agent_name=agent_name,
        integrations=integrations if pass_integrations_raw else (integrations or {}),
    )


def _render_config_yaml(config: dict, agent_name: str = "h") -> str:
    env = Environment(
        loader=FileSystemLoader(str(HERMES_TEMPLATES)),
        keep_trailing_newline=True,
    )
    template = env.get_template("hermes-config.yaml.j2")
    return template.render(config=config, agent_name=agent_name)


# ---------------------------------------------------------------------------
# .env.j2 rendering — provider branches
# ---------------------------------------------------------------------------


class TestEnvTemplateProviderBranches:
    """Verify each provider branch emits the right credential line and only that one."""

    def _api_server(self) -> dict:
        return {"key": "a" * 64, "host": "127.0.0.1", "port": 8642, "enabled": True}

    def test_openrouter_branch_emits_only_openrouter_key(self):
        rendered = _render_env(
            {
                "provider": {
                    "type": "openrouter",
                    "default_model": "anthropic/claude-opus-4.6",
                },
                "api_server": self._api_server(),
            },
            provider_api_key="sk-or-test-123",
        )
        assert "OPENROUTER_API_KEY='sk-or-test-123'" in rendered
        assert "ANTHROPIC_API_KEY=" not in rendered
        assert "OPENAI_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER='openrouter'" in rendered

    def test_anthropic_branch_emits_only_anthropic_key(self):
        rendered = _render_env(
            {
                "provider": {"type": "anthropic", "default_model": "claude-opus-4.6"},
                "api_server": self._api_server(),
            },
            provider_api_key="sk-ant-test-456",
        )
        assert "ANTHROPIC_API_KEY='sk-ant-test-456'" in rendered
        assert "OPENROUTER_API_KEY=" not in rendered
        assert "OPENAI_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER='anthropic'" in rendered

    def test_openai_branch_emits_only_openai_key(self):
        rendered = _render_env(
            {
                "provider": {"type": "openai", "default_model": "gpt-4o"},
                "api_server": self._api_server(),
            },
            provider_api_key="sk-openai-test-789",
        )
        assert "OPENAI_API_KEY='sk-openai-test-789'" in rendered
        assert "OPENROUTER_API_KEY=" not in rendered
        assert "ANTHROPIC_API_KEY=" not in rendered
        assert "HERMES_INFERENCE_PROVIDER='openai'" in rendered

    def test_ollama_branch_emits_no_provider_api_key_and_custom_provider(self):
        """Ollama / custom local endpoint: no API key required; provider maps to 'custom'."""
        rendered = _render_env(
            {
                "provider": {
                    "type": "ollama",
                    "endpoint": "http://192.168.1.17:11434",
                    "default_model": "qwen3-coder:30b-128k",
                },
                "api_server": self._api_server(),
            },
            provider_api_key="",  # no key for local endpoints
        )
        assert "OPENAI_API_KEY=" not in rendered
        assert "ANTHROPIC_API_KEY=" not in rendered
        assert "OPENROUTER_API_KEY=" not in rendered
        # HERMES_INFERENCE_PROVIDER is the alias 'custom', not 'ollama' (matches
        # hermes_cli/providers.py CUSTOM_ALIASES at v2026.5.7).
        assert "HERMES_INFERENCE_PROVIDER=custom" in rendered

    def test_api_server_block_always_rendered(self):
        rendered = _render_env(
            {
                "provider": {"type": "openrouter", "default_model": "x"},
                "api_server": self._api_server(),
            },
            provider_api_key="k",
        )
        assert "API_SERVER_ENABLED=1" in rendered
        assert "API_SERVER_HOST='127.0.0.1'" in rendered
        assert "API_SERVER_PORT=8642" in rendered
        assert "API_SERVER_KEY='" + ("a" * 64) + "'" in rendered

    def test_no_provider_api_key_omits_credential_line(self):
        """If provider_api_key is empty, the cloud-provider line is omitted entirely."""
        rendered = _render_env(
            {
                "provider": {"type": "openrouter", "default_model": "x"},
                "api_server": self._api_server(),
            },
            provider_api_key="",
        )
        assert "OPENROUTER_API_KEY=" not in rendered


# ---------------------------------------------------------------------------
# .env.j2 rendering — github integration handling (#419)
# ---------------------------------------------------------------------------


class TestEnvTemplateGithubIntegration:
    """Github integrations must populate GITHUB_TOKEN (canonical) and a
    GITHUB_TOKEN_<NAME> (multi-account) line per assigned integration. Mirrors
    the openclaw handling; without this, `clm agent configure` is a no-op for
    github on hermes agents (#419).
    """

    def _api_server(self) -> dict:
        return {"key": "a" * 64, "host": "127.0.0.1", "port": 8642, "enabled": True}

    def _provider_config(self) -> dict:
        return {
            "provider": {"type": "openrouter", "default_model": "x"},
            "api_server": self._api_server(),
        }

    def test_single_github_integration_emits_both_canonical_and_named_token(self):
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={
                "clawrium-github": {
                    "type": "github",
                    "GITHUB_TOKEN": "ghp_abc123",
                }
            },
        )
        assert "GITHUB_TOKEN_CLAWRIUM_GITHUB='ghp_abc123'" in rendered
        assert "GITHUB_TOKEN='ghp_abc123'" in rendered

    def test_multiple_github_integrations_each_get_named_token(self):
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={
                "work-gh": {"type": "github", "GITHUB_TOKEN": "ghp_work"},
                "personal-gh": {"type": "github", "GITHUB_TOKEN": "ghp_personal"},
            },
        )
        assert "GITHUB_TOKEN_WORK_GH='ghp_work'" in rendered
        assert "GITHUB_TOKEN_PERSONAL_GH='ghp_personal'" in rendered
        # At least one canonical bare GITHUB_TOKEN line must be present so
        # skills that hard-code the canonical name keep working.
        assert "GITHUB_TOKEN=" in rendered

    def test_canonical_github_token_resolution_is_deterministic(self):
        """With multiple github integrations, the bare GITHUB_TOKEN must
        resolve to the alphabetically-last name's value (dictsort order),
        not whatever dict insertion order happens to produce. Locks in the
        last-wins contract so re-renders don't shuffle which token is bare.
        """
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={
                # Insertion order intentionally NOT alphabetical:
                "zeta-gh": {"type": "github", "GITHUB_TOKEN": "ghp_zeta"},
                "alpha-gh": {"type": "github", "GITHUB_TOKEN": "ghp_alpha"},
            },
        )
        # Both per-name vars present
        assert "GITHUB_TOKEN_ALPHA_GH='ghp_alpha'" in rendered
        assert "GITHUB_TOKEN_ZETA_GH='ghp_zeta'" in rendered
        # The bare `GITHUB_TOKEN=` line for the alphabetically-last entry
        # (zeta-gh) must appear AFTER the bare line for alpha-gh, so systemd
        # / `export $(cat .env)` semantics resolve the canonical token to
        # ghp_zeta.
        idx_alpha_bare = rendered.find("\nGITHUB_TOKEN='ghp_alpha'\n")
        idx_zeta_bare = rendered.find("\nGITHUB_TOKEN='ghp_zeta'\n")
        assert idx_alpha_bare != -1 and idx_zeta_bare != -1
        assert idx_zeta_bare > idx_alpha_bare

    def test_no_integrations_emits_no_github_token(self):
        """Negative case: agents without any github integration must not see
        a stray GITHUB_TOKEN= line (would leak prior config across re-renders)."""
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={},
        )
        assert "GITHUB_TOKEN" not in rendered

    def test_only_atlassian_integrations_emits_no_github_token(self):
        """An agent with only atlassian (or any non-github) integrations must
        not get a GITHUB_TOKEN line — confirms the type filter works."""
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={
                "my-atl": {
                    "type": "atlassian",
                    "ATLASSIAN_URL": "https://x.atlassian.net",
                    "ATLASSIAN_EMAIL": "a@b.c",
                    "ATLASSIAN_API_TOKEN": "atl_xyz",
                }
            },
        )
        assert "GITHUB_TOKEN" not in rendered

    def test_github_integration_missing_token_emits_nothing(self):
        """Defensive: an integration record without GITHUB_TOKEN should not
        produce a `GITHUB_TOKEN=`/`GITHUB_TOKEN_X=` line with an empty or
        'None' value — the `is defined` guard must short-circuit cleanly."""
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={"broken-gh": {"type": "github"}},
        )
        assert "GITHUB_TOKEN" not in rendered

    def test_token_with_shell_metacharacters_is_quoted(self):
        """Tokens containing single quotes must be escaped via shell_quote so
        a malicious or weird token can't break out of the env-file scalar.
        POSIX form: 'val'"'"'ue' — see shell_quote macro at top of .env.j2."""
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={
                "weird-gh": {"type": "github", "GITHUB_TOKEN": "ghp_a'b\"c d$e"}
            },
        )
        # The full quoted form: 'ghp_a'"'"'b"c d$e'
        assert "GITHUB_TOKEN_WEIRD_GH='ghp_a'\"'\"'b\"c d$e'" in rendered

    def test_integration_name_with_hyphens_normalized_to_underscores(self):
        """Hyphens in integration names must be normalized to underscores in
        the env-var name (env vars can't contain hyphens)."""
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={
                "my-work-account": {"type": "github", "GITHUB_TOKEN": "ghp_x"}
            },
        )
        assert "GITHUB_TOKEN_MY_WORK_ACCOUNT='ghp_x'" in rendered
        # The original hyphenated name must NOT leak into the env-var name.
        assert "GITHUB_TOKEN_MY-WORK-ACCOUNT" not in rendered

    def test_env_var_key_strips_non_alphanumeric_characters(self):
        """Defense-in-depth: even if a future caller bypasses
        `INTEGRATION_NAME_PATTERN`, the rendered env-var key must contain
        only `[A-Z0-9_]`. Validates the `regex_replace('[^A-Z0-9_]','')`
        filter in `.env.j2`. Without it, a malformed name could produce a
        line systemd silently drops (or worse — splits unexpectedly).
        """
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations={
                "weird name.with$junk": {
                    "type": "github",
                    "GITHUB_TOKEN": "ghp_x",
                }
            },
        )
        # Spaces, dots, and `$` must be stripped — leaving only safe chars.
        # After upper+replace('-','_')+regex_replace('[^A-Z0-9_]',''):
        # "weird name.with$junk" → "WEIRD NAME.WITH$JUNK" → "WEIRDNAMEWITHJUNK"
        assert "GITHUB_TOKEN_WEIRDNAMEWITHJUNK='ghp_x'" in rendered
        # No raw special chars should appear in any key on the rendered line.
        for line in rendered.splitlines():
            if line.startswith("GITHUB_TOKEN_"):
                key, _, _ = line.partition("=")
                assert all(c.isalnum() or c == "_" for c in key.removeprefix("")), (
                    f"env-var key contains illegal char: {key!r}"
                )

    def test_integrations_none_does_not_crash(self):
        """Regression: a bare `{% if integrations is defined %}` guard would
        crash on `integrations=None` because `None is defined` is True in
        Jinja and `None | length` raises TypeError. The template uses
        `| default({})` so None coerces to an empty dict and the loop
        short-circuits cleanly. Asserts that with `pass_integrations_raw`
        the helper does NOT mask the None at the boundary.
        """
        rendered = _render_env(
            self._provider_config(),
            provider_api_key="sk-or-x",
            integrations=None,
            pass_integrations_raw=True,
        )
        # No crash, no GITHUB_TOKEN line emitted.
        assert "GITHUB_TOKEN" not in rendered


# ---------------------------------------------------------------------------
# config.yaml.j2 rendering
# ---------------------------------------------------------------------------


class TestConfigYamlTemplate:
    """The model: block is the canonical source of truth for provider / base_url / default."""

    def test_ollama_renders_custom_provider_with_v1_suffix_appended(self):
        rendered = _render_config_yaml(
            {
                "provider": {
                    "type": "ollama",
                    "endpoint": "http://192.168.1.17:11434",
                    "default_model": "qwen3-coder:30b-128k",
                }
            }
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "custom"
        assert parsed["model"]["base_url"] == "http://192.168.1.17:11434/v1"
        assert parsed["model"]["default"] == "qwen3-coder:30b-128k"

    def test_ollama_endpoint_already_has_v1_suffix_not_doubled(self):
        rendered = _render_config_yaml(
            {
                "provider": {
                    "type": "ollama",
                    "endpoint": "http://10.0.0.5:8000/v1",
                    "default_model": "any",
                }
            }
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["base_url"] == "http://10.0.0.5:8000/v1"

    def test_openrouter_renders_provider_and_base_url(self):
        rendered = _render_config_yaml(
            {
                "provider": {
                    "type": "openrouter",
                    "default_model": "anthropic/claude-opus-4.6",
                }
            }
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "openrouter"
        assert parsed["model"]["base_url"] == "https://openrouter.ai/api/v1"
        assert parsed["model"]["default"] == "anthropic/claude-opus-4.6"

    def test_anthropic_omits_base_url(self):
        rendered = _render_config_yaml(
            {"provider": {"type": "anthropic", "default_model": "claude-opus-4.6"}}
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "anthropic"
        assert "base_url" not in parsed["model"]

    def test_openai_omits_base_url(self):
        rendered = _render_config_yaml(
            {"provider": {"type": "openai", "default_model": "gpt-4o"}}
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "openai"
        assert "base_url" not in parsed["model"]

    def test_bedrock_renders_provider_region_and_aux_model(self):
        rendered = _render_config_yaml(
            {
                "provider": {
                    "type": "bedrock",
                    "default_model": "anthropic.claude-sonnet-4-5-20251001-v1:0",
                    "region": "eu-west-1",
                }
            }
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["model"]["provider"] == "bedrock"
        assert parsed["bedrock"]["region"] == "eu-west-1"
        # No `us.` cross-region prefix on the aux model — Bedrock routes
        # within bedrock.region, so eu/ap regions work.
        aux = parsed["auxiliary"]["title_generation"]["model"]
        assert aux == "anthropic.claude-haiku-4-5-20251001-v1:0"
        assert not aux.startswith("us.")

    def test_unknown_provider_falls_back_to_auto(self):
        """Unknown/misspelled provider must still emit a structurally valid
        config.yaml with `model.provider: auto` — never a config missing the
        model: key entirely."""
        rendered = _render_config_yaml(
            {"provider": {"type": "nonexistent-typo", "default_model": "m1"}}
        )
        parsed = yaml.safe_load(rendered)
        assert "model" in parsed
        assert parsed["model"]["provider"] == "auto"

    def test_empty_provider_falls_back_to_auto(self):
        rendered = _render_config_yaml({"provider": {"type": "", "default_model": "m"}})
        parsed = yaml.safe_load(rendered)
        assert "model" in parsed
        assert parsed["model"]["provider"] == "auto"

    def test_all_aux_title_generation_models_pinned(self):
        """Every provider for which clawrium pins an aux model must render the
        `auxiliary.title_generation.model:` block. Guards against future template
        regressions where the aux pin gets accidentally moved or dropped."""
        expected = {
            "anthropic": "claude-haiku-4-5-20251001",
            "openai": "gpt-5-nano",
            "openrouter": "anthropic/claude-haiku-4.5",
            "bedrock": "anthropic.claude-haiku-4-5-20251001-v1:0",
        }
        for provider_type, expected_model in expected.items():
            rendered = _render_config_yaml(
                {
                    "provider": {
                        "type": provider_type,
                        "default_model": "m",
                        "region": "us-east-1",
                    }
                }
            )
            parsed = yaml.safe_load(rendered)
            aux = parsed.get("auxiliary", {}).get("title_generation", {}).get("model")
            assert aux == expected_model, (
                f"{provider_type}: aux model should be {expected_model!r}, got {aux!r}"
            )

    def test_ollama_has_no_aux_title_generation_pin(self):
        """For ollama/custom the local model is already cheap — no aux pin so
        hermes' built-in auto-resolution kicks in."""
        rendered = _render_config_yaml(
            {
                "provider": {
                    "type": "ollama",
                    "endpoint": "http://10.0.0.1:11434",
                    "default_model": "q",
                }
            }
        )
        parsed = yaml.safe_load(rendered)
        assert "auxiliary" not in parsed


# ---------------------------------------------------------------------------
# configure.yaml playbook shape
# ---------------------------------------------------------------------------


class TestConfigurePlaybookShape:
    """Static checks on the configure playbook contract."""

    def _load_playbook(self) -> dict:
        return yaml.safe_load((HERMES_PLAYBOOKS / "configure.yaml").read_text())[0]

    def test_playbook_renders_env_and_config_yaml(self):
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("Render ~/.hermes/.env" in n for n in names)
        assert any("Render ~/.hermes/config.yaml" in n for n in names)

    def test_playbook_guards_missing_api_server_key(self):
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("Verify API_SERVER_KEY is present in config" == n for n in names)

    def test_playbook_has_health_probe(self):
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("Probe hermes /health endpoint" in n for n in names)

    def test_playbook_restart_handler_triggers_systemd(self):
        play = self._load_playbook()
        handlers = play.get("handlers", [])
        restart = [h for h in handlers if "Restart hermes service" in h.get("name", "")]
        assert restart, "configure.yaml must declare a Restart hermes service handler"
        sysd = restart[0]["ansible.builtin.systemd"]
        assert sysd["state"] == "restarted"
        assert sysd["enabled"] is True

    def test_env_template_is_referenced_by_render_task(self):
        play = self._load_playbook()
        tasks = play["tasks"]
        env_render = next(
            (t for t in tasks if "Render ~/.hermes/.env" in t.get("name", "")), None
        )
        assert env_render is not None
        tpl = env_render["ansible.builtin.template"]
        assert tpl["src"].endswith(".env.j2")
        assert tpl["dest"] == "/home/{{ agent_name }}/.hermes/.env"
        assert tpl["mode"] == "0600"
        assert tpl["force"] is True

    def test_ollama_branch_verifies_config_yaml_provider_and_base_url(self):
        """The ollama branch must verify both `provider: custom` and a base_url line."""
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("custom provider for Ollama" in n for n in names)
        assert any("base_url for Ollama" in n for n in names)

    def test_playbook_has_github_cli_auth_block(self):
        """Configure playbook must run `gh auth login --with-token` for each
        assigned github integration. Without this, hermes agents have an
        unauthenticated gh CLI even when `clm integration add --type github`
        succeeds (#419).
        """
        play = self._load_playbook()
        names = [t.get("name", "") for t in play["tasks"]]
        assert any("GitHub CLI authentication block" in n for n in names), (
            "configure.yaml must declare a 'GitHub CLI authentication block' task"
        )

        gh_block = next(
            t
            for t in play["tasks"]
            if "GitHub CLI authentication block" in t.get("name", "")
        )
        # The block must be gated on `integrations is defined` so it's a no-op
        # for agents without any integration assignments.
        assert "integrations is defined" in gh_block.get("when", "")

        # The inner tasks must include both the `which gh` probe and the
        # `gh auth login` command — guarding that future refactors don't
        # accidentally remove one or the other.
        block_tasks = gh_block.get("block", [])
        inner_names = [t.get("name", "") for t in block_tasks]
        assert any("Check if gh CLI is installed" in n for n in inner_names)
        assert any("Authenticate gh CLI" in n for n in inner_names)

        auth_task = next(
            t for t in block_tasks if "Authenticate gh CLI" in t.get("name", "")
        )
        # Must run as the agent user so credentials land in the agent's
        # ~/.config/gh/, not in xclm's home.
        assert auth_task.get("become_user") == "{{ agent_name }}"
        # Must suppress logs so tokens never reach ansible-runner output.
        assert auth_task.get("no_log") is True
        # Must be idempotent: re-running configure should report `ok`, not
        # `changed`, against an already-authenticated host.
        assert auth_task.get("changed_when") is False
        # Must filter loop items to github type and presence of GITHUB_TOKEN
        # so a malformed integration record doesn't crash the play.
        when_conditions = auth_task.get("when", [])
        joined = (
            " ".join(when_conditions)
            if isinstance(when_conditions, list)
            else when_conditions
        )
        assert "type == 'github'" in joined
        assert "GITHUB_TOKEN is defined" in joined
        assert "gh_check.rc == 0" in joined
        # argv must hardcode the bare `gh` binary (not interpolate the probe's
        # stdout) — Ansible's own PATH resolution handles it at exec time.
        argv = auth_task["ansible.builtin.command"].get("argv", [])
        assert argv[:4] == ["gh", "auth", "login", "--with-token"], (
            f"auth task argv must be ['gh', 'auth', 'login', '--with-token', ...], "
            f"got {argv!r}"
        )

    def test_systemd_unit_depends_on_network_online_and_journals(self):
        """The Phase 2 unit MUST wait for network-online and stream stdout/err
        to journald — regressions here cause flaky startup on DHCP hosts and
        silent operation with no `journalctl -u` output."""
        content = (HERMES_PLAYBOOKS / "configure.yaml").read_text()
        assert "After=network-online.target" in content
        assert "Wants=network-online.target" in content
        assert "StandardOutput=journal" in content
        assert "StandardError=journal" in content
        # Guard against accidental regression to plain network.target.
        assert "After=network.target\n" not in content

    def test_systemd_unit_uses_gateway_run_not_start(self):
        """The Phase 2 unit MUST use `hermes gateway run` — `gateway start`
        delegates to a per-user systemd unit that does not exist in our setup."""
        content = (HERMES_PLAYBOOKS / "configure.yaml").read_text()
        assert (
            "ExecStart=/home/{{ agent_name }}/.local/bin/hermes gateway run" in content
        )
        # Ensure the broken `gateway start` form is NOT what configure.yaml writes.
        # (Phase 1's install.yaml dropped a placeholder using `gateway start`;
        # configure.yaml owns the runtime ExecStart.)
        configure_content = (
            content.split("hermes systemd unit")[1]
            if "hermes systemd unit" in content
            else ""
        )
        assert "gateway start" not in configure_content

    def test_uv_arch_and_sha256_map_match_and_are_well_formed(self):
        """uv_arch_map / uv_sha256_map keys must be identical (every arch
        has a pinned hash), values must be lowercase 64-char hex. Bumping
        uv_version without updating hashes silently corrupts the install."""
        import re

        play = self._load_playbook()
        vars_ = play["vars"]
        arch_map = vars_["uv_arch_map"]
        sha_map = vars_["uv_sha256_map"]
        assert set(arch_map.keys()) == set(sha_map.keys()), (
            f"uv_arch_map and uv_sha256_map keys differ: "
            f"arch={sorted(arch_map.keys())} sha={sorted(sha_map.keys())}"
        )
        # ARM hosts are explicitly supported per memory (kevin = armv7l Pi).
        assert {"x86_64", "aarch64", "armv7l"} <= set(arch_map.keys())
        hex64 = re.compile(r"^[0-9a-f]{64}$")
        for arch, digest in sha_map.items():
            assert hex64.match(digest), (
                f"{arch}: not a 64-char lowercase hex sha256: {digest!r}"
            )

    def test_uv_get_url_has_checksum_and_validate_certs(self):
        """Supply-chain guard: the get_url for the uv tarball must reference
        the sha256 map and explicitly validate TLS."""
        play = self._load_playbook()
        download = next(
            (
                t
                for t in play["tasks"]
                if "Download pinned uv binary" in t.get("name", "")
            ),
            None,
        )
        assert download is not None, "Missing 'Download pinned uv binary' task"
        get_url = download["ansible.builtin.get_url"]
        assert "uv_sha256_map[ansible_architecture]" in get_url["checksum"]
        assert get_url["validate_certs"] is True
        # Staging path must be agent-owned, NOT /tmp (symlink-race surface).
        assert get_url["dest"].startswith("/home/{{ agent_name }}/.hermes/tmp/")

    def test_uv_arch_guard_fires_before_download(self):
        """An unsupported ansible_architecture must fail with a clear message
        BEFORE the get_url runs — otherwise the failure surfaces as a 404."""
        play = self._load_playbook()
        task_names = [t.get("name", "") for t in play["tasks"]]
        guard_idx = next(
            (
                i
                for i, n in enumerate(task_names)
                if "host architecture is unsupported" in n
            ),
            None,
        )
        download_idx = next(
            (i for i, n in enumerate(task_names) if "Download pinned uv binary" in n),
            None,
        )
        assert guard_idx is not None, "Missing arch fail-guard task"
        assert download_idx is not None
        assert guard_idx < download_idx, "Arch guard must precede the get_url task"

    def test_uv_unarchive_uses_version_probe_not_creates(self):
        """`creates:` on a non-version-stamped path silently skips on version
        bumps. We use a `uv --version` probe + set_fact gate instead — same
        rationale as the `--force` on the mcp-atlassian install below."""
        play = self._load_playbook()
        unarchive = next(
            (t for t in play["tasks"] if "Extract uv and uvx" in t.get("name", "")),
            None,
        )
        assert unarchive is not None, "Missing uv+uvx unarchive task"
        ua = unarchive["ansible.builtin.unarchive"]
        assert "creates" not in ua, (
            "unarchive must NOT use `creates:` — that would skip the task on "
            "uv version bumps, leaving a stale binary in place"
        )
        when = unarchive.get("when", [])
        joined = " ".join(when) if isinstance(when, list) else when
        assert "uv_needs_install" in joined, (
            "unarchive must be gated on the uv_needs_install fact"
        )
        # The probe task must exist and run before unarchive.
        probe_idx = next(
            (
                i
                for i, t in enumerate(play["tasks"])
                if "Probe installed uv version" in t.get("name", "")
            ),
            None,
        )
        unarchive_idx = play["tasks"].index(unarchive)
        assert probe_idx is not None and probe_idx < unarchive_idx

    def test_uv_extracts_both_uv_and_uvx_binaries(self):
        """config.yaml.j2's mcp_servers entry invokes uvx, so both binaries
        must land. The unarchive must not filter via `--wildcards '*/uv'`."""
        play = self._load_playbook()
        unarchive = next(
            (t for t in play["tasks"] if "Extract uv and uvx" in t.get("name", "")),
            None,
        )
        extra_opts = unarchive["ansible.builtin.unarchive"].get("extra_opts", [])
        # Bug from a previous iteration: '--wildcards' + '*/uv' excluded uvx.
        assert "--wildcards" not in extra_opts
        # The uv tarball ships as `uv-<triple>/{uv,uvx}`. Without
        # `--strip-components=1` the binaries land at
        # ~/.local/bin/uv-<triple>/uv — wrong path, silent failure.
        assert "--strip-components=1" in extra_opts
        # Assertion + chmod must cover both binaries.
        assert_task = next(
            (t for t in play["tasks"] if "Assert uv and uvx" in t.get("name", "")), None
        )
        assert assert_task is not None
        loop = assert_task.get("loop", [])
        assert set(loop) >= {"uv", "uvx"}

    def test_uv_staging_dir_is_agent_owned_and_mode_0700(self):
        """The tarball must NOT stage under /tmp (predictable, world-readable
        path → symlink-race surface). It must live under a mode-0700 dir owned
        by the agent user."""
        play = self._load_playbook()
        mkdir = next(
            (
                t
                for t in play["tasks"]
                if "Ensure ~/.local/bin and ~/.hermes/tmp exist" in t.get("name", "")
            ),
            None,
        )
        assert mkdir is not None
        loop_items = mkdir.get("loop", [])
        tmp_entry = next(
            (i for i in loop_items if i.get("path", "").endswith("/.hermes/tmp")),
            None,
        )
        assert tmp_entry is not None, "staging dir entry missing from loop"
        assert tmp_entry["mode"] == "0700"


# ---------------------------------------------------------------------------
# configure_agent() — api_server.key persistence + idempotency
# ---------------------------------------------------------------------------


class TestConfigureAgentApiServerKey:
    """configure_agent() must enforce + reuse the persisted api_server.key for hermes."""

    def test_hermes_malformed_secret_entry_missing_value_returns_error(self):
        """A secrets.json entry that exists but is missing the 'value' field
        must NOT raise KeyError out of configure_agent. The existing missing-
        key error path catches it via the validity check (value resolves to
        None) and returns a friendly remediation tuple."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {},
                }
            },
        }
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        # Truthy dict, no "value" key — the original `secret_entry["value"]`
        # access would raise KeyError before the validity check ran.
        malformed_secrets = {"HERMES_API_SERVER_KEY": {"key": "HERMES_API_SERVER_KEY"}}
        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=malformed_secrets,
            ):
                success, error = configure_agent(
                    "test-host", "hermes", config_data, agent_name="hermes-test"
                )
        assert success is False
        assert "HERMES_API_SERVER_KEY" in error
        assert "install" in error

    def test_hermes_without_persisted_key_returns_error(self):
        """Reject configure when secrets.json has no HERMES_API_SERVER_KEY."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {},
                }
            },
        }
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            # Empty secrets.json for this instance — should trigger the
            # "missing HERMES_API_SERVER_KEY" branch.
            with patch("clawrium.core.lifecycle.get_instance_secrets", return_value={}):
                success, error = configure_agent(
                    "test-host", "hermes", config_data, agent_name="hermes-test"
                )
        assert success is False
        assert "HERMES_API_SERVER_KEY" in error
        assert "install" in error  # remediation pointer

    def test_hermes_with_persisted_key_passes_to_ansible(self, tmp_path: Path):
        """When the bearer token is persisted in secrets.json, configure_agent
        hydrates it into the ansible config var alongside the non-sensitive
        shape from hosts.json."""
        persisted_key = "b" * 64
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        }
                    },
                }
            },
        }
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            mock = MagicMock()
            mock.status = "successful"
            mock.events = []
            return mock

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={
                    "HERMES_API_SERVER_KEY": {
                        "key": "HERMES_API_SERVER_KEY",
                        "value": persisted_key,
                        "created_at": "2026-05-10T00:00:00+00:00",
                        "updated_at": "2026-05-10T00:00:00+00:00",
                        "description": "",
                    }
                },
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        # api_server.key must reach the playbook (idempotency contract);
        # value is now sourced from secrets.json, not hosts.json.
        sent_config = captured["inventory"]["all"]["vars"]["config"]
        assert sent_config["api_server"]["key"] == persisted_key
        # Migration: legacy 127.0.0.1 is rewritten to 0.0.0.0 so hermes binds a
        # reachable interface (Phase 1 of #322 — `clm chat <hermes>` over LAN).
        assert sent_config["api_server"]["host"] == "0.0.0.0"
        assert sent_config["api_server"]["port"] == 8642

    def test_hermes_reconfigure_does_not_rotate_persisted_key(self, tmp_path: Path):
        """A second configure call with the same persisted record must use the same key
        (idempotency: keys never rotate on reconfigure). Key lives in secrets.json."""
        persisted_key = "c" * 64
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        }
                    },
                }
            },
        }
        # Caller passes config_data WITHOUT api_server (simulates
        # _sync_provider_config not carrying it through). configure_agent must
        # hydrate the shape from hosts.json and the bearer token from secrets.json.
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "ollama",
                "default_model": "x",
                "endpoint": "http://h:1/v1",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        secret_entry = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": persisted_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }

        seen_keys = []

        def fake_run(**kwargs):
            seen_keys.append(
                kwargs["inventory"]["all"]["vars"]["config"]["api_server"]["key"]
            )
            mock = MagicMock()
            mock.status = "successful"
            mock.events = []
            return mock

        for _ in range(2):
            with (
                patch("clawrium.core.lifecycle.get_host", return_value=host),
                patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook,
                ),
                patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ),
                patch(
                    "clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run
                ),
                patch("clawrium.core.lifecycle.update_host", return_value=True),
                patch(
                    "clawrium.core.lifecycle.get_instance_secrets",
                    return_value=secret_entry,
                ),
            ):
                success, error = configure_agent(
                    "test-host", "hermes", dict(config_data), agent_name="hermes-test"
                )
                assert success is True, error

        assert len(seen_keys) == 2
        assert seen_keys[0] == seen_keys[1] == persisted_key


class TestHermesApiServerKeySecretsHygiene:
    """Regression guards for the B3 migration and its iter-2 follow-ups."""

    def test_is_valid_hermes_api_server_key_accepts_canonical(self):
        """64-char lowercase hex is accepted."""
        from clawrium.core.install import _is_valid_hermes_api_server_key

        assert _is_valid_hermes_api_server_key("a" * 64) is True
        assert _is_valid_hermes_api_server_key("0123456789abcdef" * 4) is True

    def test_is_valid_hermes_api_server_key_rejects_invalid(self):
        """Anything non-64-lowercase-hex is rejected."""
        from clawrium.core.install import _is_valid_hermes_api_server_key

        assert _is_valid_hermes_api_server_key("a" * 63) is False  # short
        assert _is_valid_hermes_api_server_key("a" * 65) is False  # long
        assert _is_valid_hermes_api_server_key("A" * 64) is False  # uppercase
        assert _is_valid_hermes_api_server_key("g" * 64) is False  # non-hex
        assert _is_valid_hermes_api_server_key(None) is False
        assert _is_valid_hermes_api_server_key(123) is False
        assert _is_valid_hermes_api_server_key("") is False

    def test_configure_strips_api_server_key_from_persisted_hosts_json(
        self, tmp_path: Path
    ):
        """B3 invariant: the bearer token must NOT land in hosts.json after configure.

        The hydration path puts it on config_data['api_server']['key'] for
        Ansible, but the updater closure must strip it before persisting.
        """
        persisted_key = "d" * 64
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        }
                    },
                }
            },
        }
        config_data = {
            "gateway": {"host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured_updater_arg = {}

        def fake_update_host(hostname_arg, updater):
            # Run the updater on a copy of the host fixture to capture what
            # configure_agent intends to persist.
            updated = updater({"agents": dict(host["agents"])})
            captured_updater_arg["agents"] = updated["agents"]
            return True

        secrets_fixture = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": persisted_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch("clawrium.core.lifecycle.update_host", side_effect=fake_update_host),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=secrets_fixture,
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        persisted_api_server = (
            captured_updater_arg["agents"]["hermes-test"]
            .get("config", {})
            .get("api_server", {})
        )
        # B3 invariant — the bearer token must not be persisted to hosts.json.
        assert "key" not in persisted_api_server, (
            f"hermes bearer token leaked into hosts.json: {persisted_api_server}"
        )
        # Non-sensitive shape is preserved (with the host migration applied).
        assert persisted_api_server.get("enabled") is True
        assert persisted_api_server.get("host") == "0.0.0.0"
        assert persisted_api_server.get("port") == 8642

    def test_configure_rejects_invalid_hex_key_in_secrets(self, tmp_path: Path):
        """A corrupted (non-hex / wrong length) HERMES_API_SERVER_KEY is rejected
        before reaching the Ansible playbook."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        }
                    },
                }
            },
        }
        bad_secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "G" * 64,  # uppercase / non-hex
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }
        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=bad_secrets,
            ),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {"provider": {"name": "p", "type": "openrouter", "default_model": "x"}},
                agent_name="hermes-test",
            )
        assert success is False
        assert "invalid" in error.lower()
        assert "HERMES_API_SERVER_KEY" in error

    def test_configure_uses_canonical_hostname_for_instance_key(self, tmp_path: Path):
        """Issue #448: instance_key derives from host['key_id'] (immutable),
        with fallback to host['hostname'] for legacy records. This guards
        both the original ATX-iter-2 W1 (must not key by the CLI alias)
        and the #448 fix (must not key by the mutable hostname).
        Fixture key_id="test", so the canonical key is `test:hermes:<name>`."""
        persisted_key = "e" * 64
        host = {
            "hostname": "192.168.1.100",  # canonical
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        }
                    },
                }
            },
        }
        secrets_fixture = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": persisted_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        get_secrets_mock = MagicMock(return_value=secrets_fixture)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                side_effect=get_secrets_mock,
            ),
        ):
            # Caller passes the ALIAS form. Internally configure_agent must
            # resolve via host['hostname'] (canonical) for the instance_key.
            success, _ = configure_agent(
                "wolf-i",
                "hermes",
                {"provider": {"name": "p", "type": "openrouter", "default_model": "x"}},
                agent_name="hermes-test",
            )
        assert success is True
        # instance_key passed to get_instance_secrets must be the canonical form.
        # Ignore additional calls (lifecycle queries secrets for other purposes).
        called_keys = [args[0] for args, _ in get_secrets_mock.call_args_list]
        assert "test:hermes:hermes-test" in called_keys, called_keys
        assert "wolf-i:hermes:hermes-test" not in called_keys, called_keys
        assert "192.168.1.100:hermes:hermes-test" not in called_keys, called_keys


class TestConfigureYamlHandlerShape:
    """B1 (iter 1) regression guard: configure.yaml must have exactly one
    restart handler — having two caused a double restart on first configure."""

    def test_configure_playbook_has_single_restart_handler(self):
        playbook_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/hermes/playbooks/configure.yaml"
        )
        data = yaml.safe_load(playbook_path.read_text())
        assert isinstance(data, list) and len(data) == 1
        play = data[0]
        handlers = play.get("handlers", [])
        # All handlers must be restarts (no daemon-only handlers).
        restart_handlers = [h for h in handlers if "Restart" in h.get("name", "")]
        assert len(handlers) == len(restart_handlers) == 1, (
            f"expected exactly 1 restart handler, got {len(handlers)} total / "
            f"{len(restart_handlers)} restart: "
            f"{[h.get('name') for h in handlers]}"
        )


# ---------------------------------------------------------------------------
# Discord channel — .env.j2 rendering + lifecycle hydration + B3 strip
# ---------------------------------------------------------------------------


class TestEnvTemplateDiscordBranch:
    """Verify the Discord block in .env.j2 emits the right env vars under
    each config shape (issue #324)."""

    def _base_config(self) -> dict:
        return {
            "provider": {"type": "openrouter", "default_model": "anthropic/x"},
            "api_server": {
                "key": "a" * 64,
                "host": "127.0.0.1",
                "port": 8642,
                "enabled": True,
            },
        }

    def test_discord_block_omitted_when_disabled(self):
        cfg = self._base_config()
        cfg["channels"] = {"discord": {"enabled": False}}
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_BOT_TOKEN" not in rendered
        assert "DISCORD_ALLOWED_USERS" not in rendered

    def test_discord_block_omitted_when_channels_missing(self):
        rendered = _render_env(self._base_config(), provider_api_key="sk-x")
        assert "DISCORD_" not in rendered

    def test_discord_block_omitted_when_enabled_but_no_token(self):
        """Partial config — enabled but token missing — must not emit an
        empty DISCORD_BOT_TOKEN= line that would crash discord.py."""
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "allowed_users": ["740723459344302120"],
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_BOT_TOKEN" not in rendered
        # Other DISCORD_* lines guarded behind the same `if` should also be absent.
        assert "DISCORD_ALLOWED_USERS" not in rendered

    def test_discord_minimal_renders_token_and_allowed_users(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "bot_token": "BOT.TOKEN.VALUE",
                "allowed_users": ["740723459344302120"],
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_BOT_TOKEN='BOT.TOKEN.VALUE'" in rendered
        assert "DISCORD_ALLOWED_USERS='740723459344302120'" in rendered
        # Optional vars not provided should not appear as empty lines.
        assert "DISCORD_HOME_CHANNEL=" not in rendered
        assert "DISCORD_ALLOWED_CHANNELS=" not in rendered

    def test_discord_full_renders_all_envvars(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "bot_token": "BOT.TOKEN.VALUE",
                "allowed_users": ["111111111111111111", "222222222222222222"],
                "home_channel": "333333333333333333",
                "home_channel_name": "General",
                "home_channel_thread_id": "444444444444444444",
                "allowed_channels": ["555555555555555555", "666666666666666666"],
                "require_mention": True,
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_BOT_TOKEN='BOT.TOKEN.VALUE'" in rendered
        assert (
            "DISCORD_ALLOWED_USERS='111111111111111111,222222222222222222'" in rendered
        )
        assert "DISCORD_HOME_CHANNEL='333333333333333333'" in rendered
        assert "DISCORD_HOME_CHANNEL_NAME='General'" in rendered
        assert "DISCORD_HOME_CHANNEL_THREAD_ID='444444444444444444'" in rendered
        assert (
            "DISCORD_ALLOWED_CHANNELS='555555555555555555,666666666666666666'"
            in rendered
        )
        assert "DISCORD_REQUIRE_MENTION='true'" in rendered
        # allow_all_users defaults absent
        assert "DISCORD_ALLOW_ALL_USERS" not in rendered

    def test_discord_allow_all_users_renders_when_true(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "bot_token": "BOT.TOKEN.VALUE",
                "allow_all_users": True,
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_ALLOW_ALL_USERS=true" in rendered

    def test_discord_require_mention_false_renders_lowercase(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "discord": {
                "enabled": True,
                "bot_token": "BOT.TOKEN.VALUE",
                "allowed_users": ["111111111111111111"],
                "require_mention": False,
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "DISCORD_REQUIRE_MENTION='false'" in rendered


class TestHermesDiscordHydration:
    """lifecycle.configure_agent hydrates DISCORD_BOT_TOKEN from secrets.json
    and threads it onto config_data['channels']['discord']['bot_token'] when
    the user has enabled the Discord channel for the agent."""

    def _make_host(self, discord_persisted: dict | None = None) -> dict:
        agent_config: dict = {
            "api_server": {"enabled": True, "host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        agent_record: dict = {
            "type": "hermes",
            "agent_name": "hermes-test",
            "config": agent_config,
        }
        # #560: channels are declared via the canonical `channels` list
        # on the agent record (canonical channels.json is mocked via the
        # `canonical_channels` fixture). The legacy
        # `agent_config["channels"]["<type>"]` shape was removed.
        if discord_persisted is not None:
            agent_record["channels"] = ["my-discord"]
        return {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {"hermes-test": agent_record},
        }

    def _secrets_with(self, api_key: str, discord_token: str | None) -> dict:
        s = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": api_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }
        if discord_token is not None:
            s["DISCORD_BOT_TOKEN"] = {
                "key": "DISCORD_BOT_TOKEN",
                "value": discord_token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Discord bot token",
            }
        return s

    def test_discord_token_hydrated_into_ansible_config(
        self, tmp_path: Path, canonical_channels
    ):
        token = "B" * 64
        cfg = {
            "allowed_users": ["740723459344302120"],
            "home_channel": "1503238729962356777",
            "home_channel_name": "Home",
            "require_mention": True,
        }
        canonical_channels(discord={"my-discord": (cfg, token)})
        host = self._make_host(discord_persisted=cfg)
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        secrets = self._secrets_with("a" * 64, token)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["channels"]["discord"]["bot_token"] == token
        # Persisted shape from hosts.json is merged onto config_data.
        assert sent["channels"]["discord"]["allowed_users"] == ["740723459344302120"]
        assert sent["channels"]["discord"]["home_channel"] == "1503238729962356777"

    def test_discord_disabled_does_not_hydrate(self, tmp_path: Path):
        """When discord.enabled is False (or missing), no DISCORD_BOT_TOKEN is
        threaded onto config_data, even if the token exists in secrets.json."""
        host = self._make_host(discord_persisted=None)
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        # Discord secret exists but channels.discord block doesn't — hydration
        # block should be a no-op.
        secrets = self._secrets_with("a" * 64, "Z" * 64)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        # channels block either absent or, if present, no bot_token field.
        discord = sent.get("channels", {}).get("discord", {})
        assert "bot_token" not in discord

    def test_discord_enabled_without_token_rejected(
        self, tmp_path: Path, canonical_channels
    ):
        cfg = {"allowed_users": ["740723459344302120"]}
        # Channel attached but no token in secrets → reject.
        canonical_channels(discord={"my-discord": (cfg, None)})
        host = self._make_host(discord_persisted=cfg)
        secrets = self._secrets_with("a" * 64, None)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )
        assert success is False
        assert "BOT_TOKEN" in error
        assert "secrets.json" in error or "configure" in error.lower()

    def test_discord_reconfigure_does_not_rotate_token(
        self, tmp_path: Path, canonical_channels
    ):
        """Two configure calls must hydrate the byte-identical token from
        secrets.json (idempotency)."""
        token = "C" * 64
        cfg = {"allowed_users": ["740723459344302120"]}
        canonical_channels(discord={"my-discord": (cfg, token)})
        host = self._make_host(discord_persisted=cfg)
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        secrets = self._secrets_with("a" * 64, token)
        seen_tokens = []

        def fake_run(**kwargs):
            sent = kwargs["inventory"]["all"]["vars"]["config"]
            seen_tokens.append(sent["channels"]["discord"]["bot_token"])
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        for _ in range(2):
            with (
                patch("clawrium.core.lifecycle.get_host", return_value=host),
                patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook,
                ),
                patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ),
                patch(
                    "clawrium.core.lifecycle.ansible_runner.run",
                    side_effect=fake_run,
                ),
                patch("clawrium.core.lifecycle.update_host", return_value=True),
                patch(
                    "clawrium.core.lifecycle.get_instance_secrets",
                    return_value=secrets,
                ),
            ):
                success, error = configure_agent(
                    "test-host",
                    "hermes",
                    {
                        "provider": {
                            "name": "p",
                            "type": "openrouter",
                            "default_model": "x",
                        }
                    },
                    agent_name="hermes-test",
                )
                assert success is True, error

        assert len(seen_tokens) == 2
        assert seen_tokens[0] == seen_tokens[1] == token


class TestHermesDiscordSecretsHygiene:
    """B3 invariant for Discord: bot_token must never appear in hosts.json
    after configure (mirror of the api_server.key strip)."""

    def test_configure_strips_discord_bot_token_from_persisted_hosts_json(
        self, tmp_path: Path, canonical_channels
    ):
        token = "D" * 64
        cfg = {
            "allowed_users": ["740723459344302120"],
            "home_channel": "1503238729962356777",
        }
        canonical_channels(discord={"my-discord": (cfg, token)})
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "channels": ["my-discord"],
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        },
                    },
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {}

        def fake_update_host(hostname_arg, updater):
            updated = updater({"agents": dict(host["agents"])})
            captured["agents"] = updated["agents"]
            return True

        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "DISCORD_BOT_TOKEN": {
                "key": "DISCORD_BOT_TOKEN",
                "value": token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Discord bot token",
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch("clawrium.core.lifecycle.update_host", side_effect=fake_update_host),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        persisted_discord = (
            captured["agents"]["hermes-test"]
            .get("config", {})
            .get("channels", {})
            .get("discord", {})
        )
        # B3 invariant: bot_token must NOT be persisted.
        assert "bot_token" not in persisted_discord, (
            f"Discord bot token leaked into hosts.json: {persisted_discord}"
        )
        # Non-sensitive shape preserved.
        assert persisted_discord.get("enabled") is True
        assert persisted_discord.get("allowed_users") == ["740723459344302120"]
        assert persisted_discord.get("home_channel") == "1503238729962356777"


class TestConfigureYamlDiscordVerifyTasks:
    """The configure.yaml playbook gates Discord verification tasks on the
    enabled flag — they must not run for cli-only agents."""

    def _playbook(self) -> dict:
        playbook_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/hermes/playbooks/configure.yaml"
        )
        return yaml.safe_load(playbook_path.read_text())[0]

    def test_discord_token_verify_task_gated_on_enabled(self):
        play = self._playbook()
        tasks = play.get("tasks", [])
        names = [t.get("name", "") for t in tasks]
        token_tasks = [t for t in tasks if "DISCORD_BOT_TOKEN" in t.get("name", "")]
        assert token_tasks, (
            f"expected a DISCORD_BOT_TOKEN verify task in configure.yaml: {names}"
        )
        for task in token_tasks:
            when_clauses = task.get("when") or []
            joined = (
                " ".join(when_clauses)
                if isinstance(when_clauses, list)
                else str(when_clauses)
            )
            assert (
                "channels" in joined and "discord" in joined and "enabled" in joined
            ), f"DISCORD_BOT_TOKEN task missing gating clause: {when_clauses}"

    def test_discord_allowlist_verify_task_gated_on_enabled(self):
        play = self._playbook()
        tasks = play.get("tasks", [])
        allowlist_tasks = [t for t in tasks if "allowlist" in t.get("name", "").lower()]
        assert allowlist_tasks, "expected a Discord allowlist verify task"
        for task in allowlist_tasks:
            when_clauses = task.get("when") or []
            joined = (
                " ".join(when_clauses)
                if isinstance(when_clauses, list)
                else str(when_clauses)
            )
            assert "channels" in joined and "discord" in joined and "enabled" in joined


class TestHermesDiscordSecretsHygieneNegative:
    """B3 negative guard: even if an upstream caller injects bot_token into
    config_data directly, the updater closure strips it before persisting."""

    def test_strip_runs_even_when_bot_token_injected_into_config_data(
        self, tmp_path: Path
    ):
        """Simulate a future code path (or test harness) that accidentally
        passes config_data with bot_token already set — the updater closure
        MUST still strip it. This is the failure mode the strip exists to
        guard against; we test it explicitly here."""
        token = "E" * 64
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        },
                        "channels": {
                            "discord": {
                                "enabled": True,
                                "allowed_users": ["111111111111111111"],
                            }
                        },
                    },
                }
            },
        }
        # Caller passes config_data with bot_token already inlined — this is
        # the leaky scenario the strip exists to defeat.
        config_data = {
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
            "channels": {
                "discord": {
                    "enabled": True,
                    "allowed_users": ["111111111111111111"],
                    "bot_token": "INJECTED-FROM-CALLER",  # must be stripped
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured: dict = {}

        def fake_update_host(hostname_arg, updater):
            updated = updater({"agents": dict(host["agents"])})
            captured["agents"] = updated["agents"]
            return True

        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "DISCORD_BOT_TOKEN": {
                "key": "DISCORD_BOT_TOKEN",
                "value": token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Discord bot token",
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch("clawrium.core.lifecycle.update_host", side_effect=fake_update_host),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        persisted_discord = (
            captured["agents"]["hermes-test"]
            .get("config", {})
            .get("channels", {})
            .get("discord", {})
        )
        # Even though the caller passed bot_token, the strip layer caught it.
        assert "bot_token" not in persisted_discord, (
            f"Strip layer failed to catch injected bot_token: {persisted_discord}"
        )


class TestHermesDiscordIdempotency:
    """Re-running channels configure with the same inputs must produce
    byte-identical .env output and same DISCORD_BOT_TOKEN value."""

    def test_reconfigure_renders_byte_identical_env(
        self, tmp_path: Path, canonical_channels
    ):
        """Two configure calls hydrate the same DISCORD_BOT_TOKEN value and
        the same channels.discord shape; .env.j2 against both produces
        byte-identical output (no field reordering, no whitespace drift)."""
        token = "F" * 64
        cfg = {
            "allowed_users": ["111111111111111111"],
            "home_channel": "222222222222222222",
            "home_channel_name": "Home",
            "require_mention": True,
        }
        canonical_channels(discord={"my-discord": (cfg, token)})
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "channels": ["my-discord"],
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        },
                    },
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "DISCORD_BOT_TOKEN": {
                "key": "DISCORD_BOT_TOKEN",
                "value": token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Discord bot token",
            },
        }
        renders: list[str] = []

        def fake_run(**kwargs):
            sent = kwargs["inventory"]["all"]["vars"]["config"]
            # Render .env.j2 with the hydrated config and capture the output.
            from jinja2 import Environment, FileSystemLoader

            env_jinja = Environment(
                loader=FileSystemLoader(str(HERMES_TEMPLATES)),
                keep_trailing_newline=True,
            )
            tpl = env_jinja.get_template("hermes.env.j2")
            renders.append(
                tpl.render(config=sent, provider_api_key="sk-x", agent_name="h")
            )
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        for _ in range(2):
            with (
                patch("clawrium.core.lifecycle.get_host", return_value=host),
                patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook,
                ),
                patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ),
                patch(
                    "clawrium.core.lifecycle.ansible_runner.run",
                    side_effect=fake_run,
                ),
                patch("clawrium.core.lifecycle.update_host", return_value=True),
                patch(
                    "clawrium.core.lifecycle.get_instance_secrets",
                    return_value=secrets,
                ),
            ):
                success, error = configure_agent(
                    "test-host",
                    "hermes",
                    {
                        "provider": {
                            "name": "p",
                            "type": "openrouter",
                            "default_model": "x",
                        }
                    },
                    agent_name="hermes-test",
                )
                assert success is True, error

        assert len(renders) == 2
        assert renders[0] == renders[1], "non-idempotent .env render"
        # And the rendered token is the expected value.
        assert f"DISCORD_BOT_TOKEN='{token}'" in renders[0]


class TestDiscordSecretRemoval:
    """clm agent remove purges DISCORD_BOT_TOKEN alongside HERMES_API_SERVER_KEY
    via remove_instance_secrets() — no Discord-specific code path needed."""

    def test_remove_instance_secrets_purges_discord_token(self, tmp_path: Path):
        import os

        from clawrium.core.secrets import (
            list_instances_with_secrets,
            remove_instance_secrets,
            set_instance_secret,
        )

        os.environ["CLAWRIUM_CONFIG_DIR"] = str(tmp_path)
        try:
            ik = "host:hermes:agent"
            set_instance_secret(ik, "HERMES_API_SERVER_KEY", "a" * 64, "")
            set_instance_secret(ik, "DISCORD_BOT_TOKEN", "B" * 64, "Discord")
            assert ik in list_instances_with_secrets()

            assert remove_instance_secrets(ik) is True
            assert ik not in list_instances_with_secrets()
        finally:
            os.environ.pop("CLAWRIUM_CONFIG_DIR", None)


# ---------------------------------------------------------------------------
# Bind migration (Phase 1 of #322) — opportunistically rewrite legacy
# host="127.0.0.1" to "0.0.0.0" in hosts.json on the next configure call.
# ---------------------------------------------------------------------------


class TestHermesBindMigration:
    """Existing hermes installs with loopback bind get rewritten on configure."""

    def _persisted_key_secret(self, key_value: str) -> dict:
        return {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": key_value,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }

    def _make_host(self, host_value: str) -> dict:
        return {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": host_value,
                            "port": 8642,
                        }
                    },
                }
            },
        }

    def _run_configure(self, host_value: str, tmp_path: Path):
        host = self._make_host(host_value)
        config_data = {
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {"inventory": None, "update_calls": []}

        def fake_update_host(hostname_arg, updater):
            # Mutate the in-memory fixture so subsequent reads see the migration.
            updated = updater(host)
            captured["update_calls"].append(
                updated["agents"]["hermes-test"]["config"]["api_server"].copy()
            )
            return True

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            mock = MagicMock()
            mock.status = "successful"
            mock.events = []
            return mock

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", side_effect=fake_update_host),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=self._persisted_key_secret("a" * 64),
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )
        assert success is True, error
        return host, captured

    def test_legacy_loopback_is_rewritten_to_zero_bind(self, tmp_path: Path):
        """Persisted host=127.0.0.1 must be rewritten to 0.0.0.0 on configure."""
        host, captured = self._run_configure("127.0.0.1", tmp_path)

        # The in-memory fixture was mutated by the migration's update_host call.
        assert (
            host["agents"]["hermes-test"]["config"]["api_server"]["host"] == "0.0.0.0"
        )
        # The config sent to the playbook reflects the migrated bind.
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["api_server"]["host"] == "0.0.0.0"

    def test_migration_is_idempotent(self, tmp_path: Path):
        """A second configure on an already-migrated record makes no migration
        write. configure_agent still performs its single post-Ansible persist
        of the agent record (line 1137), so we expect exactly one update_host
        call total — the persist, not a migration rewrite. A no-op migration
        write would push the count to two and this assertion would catch it."""
        host, captured = self._run_configure("0.0.0.0", tmp_path)

        assert (
            host["agents"]["hermes-test"]["config"]["api_server"]["host"] == "0.0.0.0"
        )
        # Exactly one update_host call: the final post-Ansible persist.
        # If the migration block ever fires unnecessarily, count goes to 2.
        assert len(captured["update_calls"]) == 1, (
            f"expected 1 update_host call (post-Ansible persist only), "
            f"got {len(captured['update_calls'])}: {captured['update_calls']}"
        )
        # And the persisted value is still 0.0.0.0 (sanity check).
        assert captured["update_calls"][0]["host"] == "0.0.0.0"

    def test_migration_pass_writes_twice(self, tmp_path: Path):
        """On a legacy 127.0.0.1 record, configure_agent calls update_host
        exactly twice: once for the migration rewrite, once for the
        post-Ansible persist. This pairs with `test_migration_is_idempotent`
        — together they prove the migration runs exactly when it should."""
        _host, captured = self._run_configure("127.0.0.1", tmp_path)

        assert len(captured["update_calls"]) == 2, (
            f"expected 2 update_host calls (migration + post-Ansible persist), "
            f"got {len(captured['update_calls'])}: {captured['update_calls']}"
        )
        # The migration write (first) and the persist (second) both end with
        # host=0.0.0.0 because the migration mutates the fixture in place.
        assert captured["update_calls"][0]["host"] == "0.0.0.0"
        assert captured["update_calls"][1]["host"] == "0.0.0.0"

    def test_legacy_missing_api_server_block_uses_zero_bind_default(
        self, tmp_path: Path
    ):
        """If hosts.json has no api_server block at all (legacy/corrupted),
        configure rebuilds defaults with host=0.0.0.0 — not the loopback we
        used to ship with."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {},  # no api_server block
                }
            },
        }
        config_data = {
            "provider": {"name": "p", "type": "openrouter", "default_model": "x"},
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            mock = MagicMock()
            mock.status = "successful"
            mock.events = []
            return mock

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=self._persisted_key_secret("b" * 64),
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["api_server"]["host"] == "0.0.0.0"
        # Issue #533: legacy-shape reconstruction picks a per-instance port
        # in 8600..8699 and persists it back. ATX iter-2 W1: prefers 8642
        # (the literal that pre-#533 hermes daemons are actually bound to)
        # when free on the host, so the running daemon is what `clm chat`
        # reaches without a daemon restart.
        assert 8600 <= sent["api_server"]["port"] <= 8699
        assert sent["api_server"]["port"] == 8642  # 8642 was free on this host


class TestHermesApiServerPortIssue533:
    """Tests for the api_server port validation/reconstruction branches added
    in issue #533. See ATX iter-2 W1 (legacy reconstruct) and W6 (range check
    on persisted port)."""

    def _persisted_key_secret(self, key: str) -> dict:
        return {"HERMES_API_SERVER_KEY": {"value": key}}

    def test_configure_rejects_out_of_range_persisted_port_picks_fresh(
        self, tmp_path: Path
    ):
        """ATX iter-2 W6: a hand-edited hosts.json with `api_server.port=22`
        must NOT be forwarded to Ansible. lifecycle.py warns and picks a
        fresh port in 8600..8699 via _pick_per_instance_port."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "0.0.0.0",
                            "port": 22,  # privileged port, hand-edited
                        }
                    },
                }
            },
        }
        config_data = {
            "provider": {"name": "p", "type": "openrouter", "default_model": "x"},
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            mock = MagicMock()
            mock.status = "successful"
            mock.events = []
            return mock

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=self._persisted_key_secret("b" * 64),
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert 8600 <= sent["api_server"]["port"] <= 8699
        assert sent["api_server"]["port"] != 22

    def test_configure_legacy_no_api_server_prefers_8642(self, tmp_path: Path):
        """ATX iter-2 W1: legacy hermes records without an api_server block
        are reconstructed with port=8642 (the pre-#533 literal that the live
        daemon is bound to) when 8642 is free, plus update_host persists the
        block back so subsequent configures are stable. B3 invariant: the
        persisted block must NOT contain the bearer `key` field."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {},  # no api_server block at all
                }
            },
        }
        config_data = {
            "provider": {"name": "p", "type": "openrouter", "default_model": "x"},
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {"inventory": None, "update_calls": []}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            mock = MagicMock()
            mock.status = "successful"
            mock.events = []
            return mock

        def fake_update_host(_hostname, updater):
            h_copy = {
                "hostname": "test-host",
                "agents": {
                    "hermes-test": {
                        "type": "hermes",
                        "agent_name": "hermes-test",
                        "config": {},
                    }
                },
            }
            mutated = updater(h_copy)
            captured["update_calls"].append(mutated["agents"]["hermes-test"]["config"])
            return True

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch(
                "clawrium.core.lifecycle.update_host", side_effect=fake_update_host
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value=self._persisted_key_secret("b" * 64),
            ),
        ):
            success, error = configure_agent(
                "test-host", "hermes", config_data, agent_name="hermes-test"
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        # Prefers 8642 (free on this single-agent host).
        assert sent["api_server"]["port"] == 8642
        # B3 invariant: bearer key must not leak into the persisted block.
        # update_calls captures every persisted snapshot — none may carry key.
        for snapshot in captured["update_calls"]:
            persisted = snapshot.get("api_server") or {}
            assert "key" not in persisted


# ---------------------------------------------------------------------------
# Slack template + hydration tests (mirrors Discord test classes above)
# ---------------------------------------------------------------------------


class TestEnvTemplateSlackBranch:
    """Verify the Slack block in .env.j2 emits the right env vars under
    each config shape."""

    def _base_config(self) -> dict:
        return {
            "provider": {"type": "openrouter", "default_model": "anthropic/x"},
            "api_server": {
                "key": "a" * 64,
                "host": "127.0.0.1",
                "port": 8642,
                "enabled": True,
            },
        }

    def test_slack_block_omitted_when_disabled(self):
        cfg = self._base_config()
        cfg["channels"] = {"slack": {"enabled": False}}
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "SLACK_BOT_TOKEN" not in rendered
        assert "SLACK_APP_TOKEN" not in rendered
        assert "SLACK_ALLOWED_USERS" not in rendered

    def test_slack_block_omitted_when_channels_missing(self):
        rendered = _render_env(self._base_config(), provider_api_key="sk-x")
        assert "SLACK_" not in rendered

    def test_slack_block_omitted_when_enabled_but_no_tokens(self):
        """Partial config — enabled but tokens missing — must not emit empty
        SLACK_BOT_TOKEN= line that would crash the Slack connector."""
        cfg = self._base_config()
        cfg["channels"] = {
            "slack": {
                "enabled": True,
                "allowed_users": ["U01ABC2DEF3"],
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "SLACK_BOT_TOKEN" not in rendered
        assert "SLACK_APP_TOKEN" not in rendered
        assert "SLACK_ALLOWED_USERS" not in rendered

    def test_slack_minimal_renders_tokens_and_allowed_users(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "slack": {
                "enabled": True,
                "bot_token": "xoxb-TOKEN-VALUE",
                "app_token": "xapp-TOKEN-VALUE",
                "allowed_users": ["U01ABC2DEF3"],
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "SLACK_BOT_TOKEN='xoxb-TOKEN-VALUE'" in rendered
        assert "SLACK_APP_TOKEN='xapp-TOKEN-VALUE'" in rendered
        assert "SLACK_ALLOWED_USERS='U01ABC2DEF3'" in rendered
        # Optional vars not provided should not appear as empty lines.
        assert "SLACK_HOME_CHANNEL=" not in rendered
        assert "SLACK_HOME_CHANNEL_NAME=" not in rendered

    def test_slack_full_renders_all_envvars(self):
        cfg = self._base_config()
        cfg["channels"] = {
            "slack": {
                "enabled": True,
                "bot_token": "xoxb-TOKEN-VALUE",
                "app_token": "xapp-TOKEN-VALUE",
                "allowed_users": ["U01ABC2DEF3", "U99XYZ8PQRS"],
                "home_channel": "C01234567890",
                "home_channel_name": "general",
            }
        }
        rendered = _render_env(cfg, provider_api_key="sk-x")
        assert "SLACK_BOT_TOKEN='xoxb-TOKEN-VALUE'" in rendered
        assert "SLACK_APP_TOKEN='xapp-TOKEN-VALUE'" in rendered
        assert "SLACK_ALLOWED_USERS='U01ABC2DEF3,U99XYZ8PQRS'" in rendered
        assert "SLACK_HOME_CHANNEL='C01234567890'" in rendered
        assert "SLACK_HOME_CHANNEL_NAME='general'" in rendered


class TestHermesSlackHydration:
    """lifecycle.configure_agent hydrates SLACK_BOT_TOKEN and SLACK_APP_TOKEN
    from secrets.json and threads them onto config_data['channels']['slack']
    when the user has enabled the Slack channel for the agent."""

    def _make_host(self, slack_persisted: dict | None = None) -> dict:
        agent_config: dict = {
            "api_server": {"enabled": True, "host": "127.0.0.1", "port": 8642},
            "provider": {
                "name": "p",
                "type": "openrouter",
                "default_model": "x",
            },
        }
        agent_record: dict = {
            "type": "hermes",
            "agent_name": "hermes-test",
            "config": agent_config,
        }
        if slack_persisted is not None:
            agent_record["channels"] = ["my-slack"]
        return {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {"hermes-test": agent_record},
        }

    def _secrets_with(
        self, api_key: str, slack_bot: str | None, slack_app: str | None
    ) -> dict:
        s = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": api_key,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            }
        }
        if slack_bot is not None:
            s["SLACK_BOT_TOKEN"] = {
                "key": "SLACK_BOT_TOKEN",
                "value": slack_bot,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack bot token",
            }
        if slack_app is not None:
            s["SLACK_APP_TOKEN"] = {
                "key": "SLACK_APP_TOKEN",
                "value": slack_app,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack app token",
            }
        return s

    def test_slack_tokens_hydrated_into_ansible_config(
        self, tmp_path: Path, canonical_channels
    ):
        bot_token = "xoxb-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        app_token = "xapp-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        cfg = {
            "allowed_users": ["U01ABC2DEF3"],
            "home_channel": "C01234567890",
            "home_channel_name": "general",
        }
        canonical_channels(slack={"my-slack": (cfg, bot_token, app_token)})
        host = self._make_host(slack_persisted=cfg)
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        secrets = self._secrets_with("a" * 64, bot_token, app_token)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["channels"]["slack"]["bot_token"] == bot_token
        assert sent["channels"]["slack"]["app_token"] == app_token
        # Persisted shape from hosts.json is merged onto config_data.
        assert sent["channels"]["slack"]["allowed_users"] == ["U01ABC2DEF3"]
        assert sent["channels"]["slack"]["home_channel"] == "C01234567890"

    def test_slack_disabled_does_not_hydrate(self, tmp_path: Path):
        """When slack.enabled is False (or missing), no SLACK_BOT_TOKEN is
        threaded onto config_data, even if the tokens exist in secrets.json."""
        host = self._make_host(slack_persisted=None)
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            return m

        secrets = self._secrets_with(
            "a" * 64,
            "xoxb-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS",
            "xapp-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS",
        )

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        # No slack key in channels at all (or if present, no bot_token hydrated)
        slack_cfg = sent.get("channels", {}).get("slack", {})
        assert "bot_token" not in slack_cfg
        assert "app_token" not in slack_cfg

    def test_slack_enabled_without_bot_token_rejected(
        self, tmp_path: Path, canonical_channels
    ):
        """Slack channel attached but tokens missing from secrets must fail
        with a clear error message."""
        cfg = {"allowed_users": ["U01ABC2DEF3"]}
        # Channel attached, no tokens.
        canonical_channels(slack={"my-slack": (cfg, None, None)})
        host = self._make_host(slack_persisted=cfg)
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        # No Slack tokens in secrets
        secrets = self._secrets_with("a" * 64, None, None)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is False
        assert "SLACK_BOT_TOKEN" in error


class TestHermesSlackSecretsHygiene:
    """B3 invariant for Slack: bot_token and app_token must never appear in
    hosts.json after configure (mirror of the Discord strip)."""

    def test_configure_strips_slack_tokens_from_persisted_hosts_json(
        self, tmp_path: Path, canonical_channels
    ):
        bot_token = "xoxb-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        app_token = "xapp-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        cfg = {
            "allowed_users": ["U01ABC2DEF3"],
            "home_channel": "C01234567890",
            "home_channel_name": "general",
        }
        canonical_channels(slack={"my-slack": (cfg, bot_token, app_token)})
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "channels": ["my-slack"],
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        },
                    },
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        captured = {}

        def fake_update_host(hostname_arg, updater):
            updated = updater({"agents": dict(host["agents"])})
            captured["agents"] = updated["agents"]
            return True

        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "SLACK_BOT_TOKEN": {
                "key": "SLACK_BOT_TOKEN",
                "value": bot_token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack bot token",
            },
            "SLACK_APP_TOKEN": {
                "key": "SLACK_APP_TOKEN",
                "value": app_token,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack app token",
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch("clawrium.core.lifecycle.update_host", side_effect=fake_update_host),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    }
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        persisted_slack = (
            captured["agents"]["hermes-test"]
            .get("config", {})
            .get("channels", {})
            .get("slack", {})
        )
        assert "bot_token" not in persisted_slack, (
            f"Slack bot_token leaked into hosts.json: {persisted_slack}"
        )
        assert "app_token" not in persisted_slack, (
            f"Slack app_token leaked into hosts.json: {persisted_slack}"
        )
        # Non-sensitive shape preserved.
        assert persisted_slack.get("enabled") is True
        assert persisted_slack.get("allowed_users") == ["U01ABC2DEF3"]
        assert persisted_slack.get("home_channel") == "C01234567890"
        assert persisted_slack.get("home_channel_name") == "general"

    def test_strip_runs_when_slack_tokens_injected_into_config_data(
        self, tmp_path: Path
    ):
        """Defense-in-depth: even if a caller passes config_data with Slack
        tokens already inlined, the persist-time strip removes them before
        hosts.json is written."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "hermes-test": {
                    "type": "hermes",
                    "agent_name": "hermes-test",
                    "config": {
                        "api_server": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 8642,
                        }
                    },
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        captured = {}

        def fake_update_host(hostname_arg, updater):
            updated = updater({"agents": dict(host["agents"])})
            captured["agents"] = updated["agents"]
            return True

        valid_bot = "xoxb-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        valid_app = "xapp-NOT-A-REAL-TOKEN-FIXTURE-FOR-TESTS"
        secrets = {
            "HERMES_API_SERVER_KEY": {
                "key": "HERMES_API_SERVER_KEY",
                "value": "a" * 64,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "",
            },
            "SLACK_BOT_TOKEN": {
                "key": "SLACK_BOT_TOKEN",
                "value": valid_bot,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack bot token",
            },
            "SLACK_APP_TOKEN": {
                "key": "SLACK_APP_TOKEN",
                "value": valid_app,
                "created_at": "2026-05-10T00:00:00+00:00",
                "updated_at": "2026-05-10T00:00:00+00:00",
                "description": "Slack app token",
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=MagicMock(status="successful", events=[]),
            ),
            patch("clawrium.core.lifecycle.update_host", side_effect=fake_update_host),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "hermes",
                {
                    "provider": {
                        "name": "p",
                        "type": "openrouter",
                        "default_model": "x",
                    },
                    "channels": {
                        "slack": {
                            "enabled": True,
                            "bot_token": "INJECTED-BOT",
                            "app_token": "INJECTED-APP",
                            "allowed_users": ["U01ABC2DEF3"],
                        }
                    },
                },
                agent_name="hermes-test",
            )

        assert success is True, error
        persisted_slack = (
            captured["agents"]["hermes-test"]
            .get("config", {})
            .get("channels", {})
            .get("slack", {})
        )
        assert "bot_token" not in persisted_slack, (
            f"Strip layer failed to catch injected bot_token: {persisted_slack}"
        )
        assert "app_token" not in persisted_slack, (
            f"Strip layer failed to catch injected app_token: {persisted_slack}"
        )


# ---------------------------------------------------------------------------
# config.yaml.j2 rendering — MCP servers from integrations
# ---------------------------------------------------------------------------


def _render_config_yaml_with_integrations(
    config: dict,
    integrations: dict,
    agent_name: str = "h",
    mcp_atlassian_version: str = "0.21.1",
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(HERMES_TEMPLATES)),
        keep_trailing_newline=True,
    )
    template = env.get_template("hermes-config.yaml.j2")
    return template.render(
        config=config,
        integrations=integrations,
        agent_name=agent_name,
        mcp_atlassian_version=mcp_atlassian_version,
    )


class TestConfigYamlMCPServers:
    """Verify MCP server blocks render correctly from integrations."""

    def _base_config(self) -> dict:
        return {
            "provider": {
                "type": "bedrock",
                "default_model": "anthropic.claude-sonnet-4-20250514-v1:0",
                "region": "us-east-1",
            },
        }

    def test_no_mcp_servers_when_no_integrations(self):
        """config.yaml has no mcp_servers key when integrations is empty."""
        rendered = _render_config_yaml_with_integrations(self._base_config(), {})
        assert "mcp_servers" not in rendered

    def test_no_mcp_servers_when_integrations_undefined(self):
        """config.yaml has no mcp_servers key when integrations is not passed."""
        rendered = _render_config_yaml(self._base_config())
        assert "mcp_servers" not in rendered

    def test_no_mcp_servers_for_non_atlassian_integrations(self):
        """Non-atlassian integrations don't produce mcp_servers."""
        integrations = {
            "work-github": {
                "type": "github",
                "GITHUB_TOKEN": "ghp_test123",
            }
        }
        rendered = _render_config_yaml_with_integrations(
            self._base_config(), integrations
        )
        assert "mcp_servers" not in rendered

    def test_atlassian_integration_renders_mcp_server(self):
        """Atlassian integration renders mcp-atlassian server config."""
        integrations = {
            "work-atlassian": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://company.atlassian.net",
                "ATLASSIAN_EMAIL": "dev@company.com",
                "ATLASSIAN_API_TOKEN": "secret_token_123",
            }
        }
        rendered = _render_config_yaml_with_integrations(
            self._base_config(), integrations
        )
        parsed = yaml.safe_load(rendered)

        assert "mcp_servers" in parsed
        # Server name: hyphens replaced with underscores
        assert "work_atlassian" in parsed["mcp_servers"]
        server = parsed["mcp_servers"]["work_atlassian"]
        assert server["command"] == "/home/h/.local/bin/uvx"
        # args pin the runtime mcp-atlassian version via `--from` so a missing
        # uv tool venv cannot silently resolve to latest.
        assert server["args"] == ["--from", "mcp-atlassian==0.21.1", "mcp-atlassian"]
        assert server["env"]["JIRA_URL"] == "https://company.atlassian.net"
        assert server["env"]["JIRA_USERNAME"] == "dev@company.com"
        assert server["env"]["JIRA_API_TOKEN"] == "secret_token_123"
        assert server["env"]["CONFLUENCE_URL"] == "https://company.atlassian.net/wiki"
        assert server["env"]["CONFLUENCE_USERNAME"] == "dev@company.com"
        assert server["env"]["CONFLUENCE_API_TOKEN"] == "secret_token_123"

    def test_atlassian_with_space_and_project_filters(self):
        """Optional CONFLUENCE_SPACES_FILTER and JIRA_PROJECTS_FILTER render."""
        integrations = {
            "filtered-atlassian": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://co.atlassian.net",
                "ATLASSIAN_EMAIL": "user@co.com",
                "ATLASSIAN_API_TOKEN": "token",
                "CONFLUENCE_SPACES_FILTER": "ENG,PROD",
                "JIRA_PROJECTS_FILTER": "PROJ,OPS",
            }
        }
        rendered = _render_config_yaml_with_integrations(
            self._base_config(), integrations
        )
        parsed = yaml.safe_load(rendered)

        server = parsed["mcp_servers"]["filtered_atlassian"]
        assert server["env"]["CONFLUENCE_SPACES_FILTER"] == "ENG,PROD"
        assert server["env"]["JIRA_PROJECTS_FILTER"] == "PROJ,OPS"

    def test_atlassian_without_optional_filters_omits_them(self):
        """When no filters are provided, those keys are absent from env."""
        integrations = {
            "plain-atlassian": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://co.atlassian.net",
                "ATLASSIAN_EMAIL": "user@co.com",
                "ATLASSIAN_API_TOKEN": "token",
            }
        }
        rendered = _render_config_yaml_with_integrations(
            self._base_config(), integrations
        )
        parsed = yaml.safe_load(rendered)

        server = parsed["mcp_servers"]["plain_atlassian"]
        assert "CONFLUENCE_SPACES_FILTER" not in server["env"]
        assert "JIRA_PROJECTS_FILTER" not in server["env"]

    def test_multiple_atlassian_integrations_render_separate_servers(self):
        """Multiple atlassian integrations each get their own server entry."""
        integrations = {
            "team-a": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://teama.atlassian.net",
                "ATLASSIAN_EMAIL": "a@team.com",
                "ATLASSIAN_API_TOKEN": "token_a",
            },
            "team-b": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://teamb.atlassian.net",
                "ATLASSIAN_EMAIL": "b@team.com",
                "ATLASSIAN_API_TOKEN": "token_b",
            },
        }
        rendered = _render_config_yaml_with_integrations(
            self._base_config(), integrations
        )
        parsed = yaml.safe_load(rendered)

        assert "team_a" in parsed["mcp_servers"]
        assert "team_b" in parsed["mcp_servers"]
        assert (
            parsed["mcp_servers"]["team_a"]["env"]["JIRA_URL"]
            == "https://teama.atlassian.net"
        )
        assert (
            parsed["mcp_servers"]["team_b"]["env"]["JIRA_URL"]
            == "https://teamb.atlassian.net"
        )

    def test_mixed_integrations_only_atlassian_renders_mcp(self):
        """Only atlassian types produce mcp_servers entries; others ignored."""
        integrations = {
            "my-github": {
                "type": "github",
                "GITHUB_TOKEN": "ghp_xxx",
            },
            "my-atlassian": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://co.atlassian.net",
                "ATLASSIAN_EMAIL": "u@co.com",
                "ATLASSIAN_API_TOKEN": "tok",
            },
        }
        rendered = _render_config_yaml_with_integrations(
            self._base_config(), integrations
        )
        parsed = yaml.safe_load(rendered)

        assert "mcp_servers" in parsed
        assert len(parsed["mcp_servers"]) == 1
        assert "my_atlassian" in parsed["mcp_servers"]

    def test_trailing_slash_url_does_not_produce_double_slash(self):
        """ATLASSIAN_URL with trailing slash collapses to a single slash before /wiki."""
        integrations = {
            "trailing-slash": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://co.atlassian.net/",
                "ATLASSIAN_EMAIL": "u@co.com",
                "ATLASSIAN_API_TOKEN": "tok",
            }
        }
        rendered = _render_config_yaml_with_integrations(
            self._base_config(), integrations
        )
        parsed = yaml.safe_load(rendered)

        server = parsed["mcp_servers"]["trailing_slash"]
        assert server["env"]["JIRA_URL"] == "https://co.atlassian.net"
        assert server["env"]["CONFLUENCE_URL"] == "https://co.atlassian.net/wiki"

    def test_token_with_special_chars_does_not_break_yaml(self):
        """A token containing characters that could break out of a YAML scalar is neutralized.

        Single-quoted YAML scalars fold newlines into spaces, so we check the
        token does NOT inject top-level keys rather than asserting byte
        equality (folding is a property of YAML, not an injection)."""
        nasty_token = "abc'def\"\nrogue: true\nadmin: yes\n: sneaky"
        integrations = {
            "nasty": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://co.atlassian.net",
                "ATLASSIAN_EMAIL": "u@co.com",
                "ATLASSIAN_API_TOKEN": nasty_token,
            }
        }
        rendered = _render_config_yaml_with_integrations(
            self._base_config(), integrations
        )
        parsed = yaml.safe_load(rendered)

        env = parsed["mcp_servers"]["nasty"]["env"]
        # Both JIRA_API_TOKEN and CONFLUENCE_API_TOKEN render via the same
        # yaml_quote macro — assert symmetrically so a macro removal on either
        # line is caught.
        for token_key in ("JIRA_API_TOKEN", "CONFLUENCE_API_TOKEN"):
            assert isinstance(env[token_key], str), token_key
            assert "abc'def" in env[token_key], token_key
            # Injection text stays inside the scalar; it does NOT escape.
            assert "rogue" in env[token_key], token_key

        # No injected top-level keys.
        assert "rogue" not in parsed
        assert "admin" not in parsed
        # No injected sibling keys inside the env dict either.
        assert set(env.keys()) <= {
            "JIRA_URL",
            "JIRA_USERNAME",
            "JIRA_API_TOKEN",
            "CONFLUENCE_URL",
            "CONFLUENCE_USERNAME",
            "CONFLUENCE_API_TOKEN",
        }

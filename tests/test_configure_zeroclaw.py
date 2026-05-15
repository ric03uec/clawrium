"""Rendering tests for zeroclaw config.toml.j2.

Covers the unified `atlassian` integration branch added in issue #348:
trailing-slash URL normalization (so CONFLUENCE_URL doesn't double-slash) and
TOML escape correctness on the api_token fields (which embed secrets).
"""

from pathlib import Path

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

_BASE_CONFIG = {
    "gateway": {"host": "localhost", "port": 4080, "allow_public_bind": False},
}


def _render_config_toml(integrations: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(ZEROCLAW_TEMPLATES)))
    # The zeroclaw template uses Ansible's `bool` filter for the gateway flag.
    # Mirror Ansible's string coercion (which treats 'no', 'false', '0', '' as
    # False) — a plain `bool()` diverges silently for those string inputs.
    def _ansible_bool(v):
        if isinstance(v, str):
            return v.lower() not in ("no", "false", "0", "")
        return bool(v)
    env.filters["bool"] = _ansible_bool
    template = env.get_template("config.toml.j2")
    return template.render(config=_BASE_CONFIG, integrations=integrations)


class TestZeroclawAtlassianRendering:
    """Verify the unified atlassian branch in config.toml.j2 emits correct TOML."""

    def test_atlassian_renders_jira_and_confluence_urls(self):
        rendered = _render_config_toml({
            "work": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://co.atlassian.net",
                "ATLASSIAN_EMAIL": "u@co.com",
                "ATLASSIAN_API_TOKEN": "token",
            }
        })
        assert 'jira_url = "https://co.atlassian.net"' in rendered
        assert 'confluence_url = "https://co.atlassian.net/wiki"' in rendered
        assert 'jira_email = "u@co.com"' in rendered
        assert 'confluence_email = "u@co.com"' in rendered

    def test_atlassian_trailing_slash_does_not_produce_double_slash(self):
        """A user-entered URL with trailing slash collapses before /wiki."""
        rendered = _render_config_toml({
            "work": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://co.atlassian.net/",
                "ATLASSIAN_EMAIL": "u@co.com",
                "ATLASSIAN_API_TOKEN": "token",
            }
        })
        assert 'jira_url = "https://co.atlassian.net"' in rendered
        assert 'confluence_url = "https://co.atlassian.net/wiki"' in rendered
        assert "//wiki" not in rendered

    def test_atlassian_api_token_toml_escaping(self):
        """API tokens containing quotes and backslashes must be TOML-escaped on
        both jira_api_token and confluence_api_token (same value, same macro).
        """
        token = 'tok"with"quote\\and\\backslash'
        rendered = _render_config_toml({
            "work": {
                "type": "atlassian",
                "ATLASSIAN_URL": "https://co.atlassian.net",
                "ATLASSIAN_EMAIL": "u@co.com",
                "ATLASSIAN_API_TOKEN": token,
            }
        })
        # Expected after escape: \\ for backslash, \" for quote.
        expected_escaped = r'tok\"with\"quote\\and\\backslash'
        assert f'jira_api_token = "{expected_escaped}"' in rendered
        assert f'confluence_api_token = "{expected_escaped}"' in rendered

    def test_non_atlassian_integrations_do_not_render_atlassian_keys(self):
        """A github integration must not produce jira_* or confluence_* keys."""
        rendered = _render_config_toml({
            "work": {"type": "github", "GITHUB_TOKEN": "ghp_test"}
        })
        assert "jira_url" not in rendered
        assert "confluence_url" not in rendered
        assert "jira_api_token" not in rendered
        assert "confluence_api_token" not in rendered
        assert 'github_token = "ghp_test"' in rendered

    def test_atlassian_partial_dict_omits_absent_keys(self):
        """Per-key `is defined` guards in the template must drop unset fields
        cleanly — never produce stray `= ''` or `= None` lines from the missing
        ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN halves.
        """
        rendered = _render_config_toml({
            "work": {"type": "atlassian", "ATLASSIAN_URL": "https://co.atlassian.net"},
        })
        assert 'jira_url = "https://co.atlassian.net"' in rendered
        assert 'confluence_url = "https://co.atlassian.net/wiki"' in rendered
        assert "jira_email" not in rendered
        assert "confluence_email" not in rendered
        assert "jira_api_token" not in rendered
        assert "confluence_api_token" not in rendered

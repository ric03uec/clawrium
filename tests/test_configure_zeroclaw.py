"""Rendering tests for the zeroclaw systemd EnvironmentFile drop-in.

History (ATX #555 polish): this file previously contained 12 test
classes (≈45 tests) covering the legacy ansible-conditional render
shape of `zeroclaw-config.toml.j2`. PR #565 replaced that template
wholesale with the canonical full-config render (1027-line template
including every section the daemon expects, with only clawctl-managed
values templated). The legacy tests asserted obsolete schema:

  - `default_provider = "..."`           — replaced by `fallback`
  - `kind = "..."` discriminator         — gone
  - conditional `[channels.discord]`     — now unconditional
  - `[personality]` block                — gone
  - `_render(config={"gateway": ...})`   — template expects top-level
                                           `gateway`/`provider` vars

All 45 obsolete tests have been deleted. Coverage of the canonical
zeroclaw render is now provided by:

  - `tests/core/test_render.py` — per-provider byte-locks, integration
    rendering, channel rendering, TOML injection regression, missing-
    section assertions
  - `tests/integration/test_render_matrix.py` — agent × provider ×
    channel × integration matrix
  - `tests/core/test_lifecycle_canonical.py` — full pipeline including
    diff + secret-removal guard + atomic write + bearer re-pair

The surviving class below tests the `zeroclaw-env.conf.j2` systemd
drop-in, which was NOT replaced by #565 and remains the canonical
production template for GITHUB_TOKEN env vars on the zeroclaw host.
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


def _ansible_regex_replace(value, pattern, replacement=""):
    """Ansible's `regex_replace` filter, reimplemented for the bare-Jinja
    test renderer (same pattern as tests/test_hermes_configure.py)."""
    import re as _re

    return _re.sub(pattern, replacement, str(value))


def _render_systemd_dropin(integrations: dict | None) -> str:
    """Render the clm-env.conf.j2 drop-in with the supplied integrations dict."""
    env = Environment(
        loader=FileSystemLoader(str(ZEROCLAW_TEMPLATES)),
        keep_trailing_newline=True,
    )
    env.filters["regex_replace"] = _ansible_regex_replace
    template = env.get_template("zeroclaw-env.conf.j2")
    return template.render(integrations=integrations or {}, agent_name="zc1")


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
        assert 'Environment=GITHUB_TOKEN="tok\\"with\\"quote\\\\and\\\\bs"' in rendered

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

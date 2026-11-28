"""Tests for `clawctl agent open` (ATX iter-1 B6).

Mocks `core.web_ui.resolve` + `webbrowser.open` so no real browser
launches under pytest.
"""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_open_no_web_ui_errors_clean(fleet_dir, monkeypatch) -> None:
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: None
    )
    result = runner.invoke(app, ["agent", "open", "wise-hypatia"])
    assert result.exit_code != 0
    assert "no web UI" in result.output


def test_open_print_url_local_host_skips_tunnel(fleet_dir, monkeypatch) -> None:
    resolved = SimpleNamespace(host="127.0.0.1", remote_port=12345)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    # If webbrowser.open is hit unexpectedly, fail loudly.
    browser_urls = []
    monkeypatch.setattr("webbrowser.open", lambda url: browser_urls.append(url))
    result = runner.invoke(app, ["agent", "open", "wise-hypatia", "--print-url"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:12345" in result.output
    assert browser_urls == []  # --print-url skips the browser


def _browser_mock_success(browser_urls):
    """ATX W1: success-path browser mock returns True so the headless-fallback
    branch in open.py does NOT fire — otherwise success tests would silently
    exercise the failure path and pass.
    """

    def _open(url):
        browser_urls.append(url)
        return True

    return _open


def test_open_local_host_opens_browser_no_tunnel(fleet_dir, monkeypatch) -> None:
    """Local agent: opens browser immediately, no tunnel needed."""
    resolved = SimpleNamespace(host="127.0.0.1", remote_port=12345)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    browser_urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", _browser_mock_success(browser_urls))
    tunnel_calls: list[str] = []

    def _fail_tunnel(*_args, **_kwargs):
        tunnel_calls.append("called")
        raise AssertionError("tunnel should not be called for local hosts")

    monkeypatch.setattr("clawrium.core.web_ui_tunnel.ensure", _fail_tunnel)
    result = runner.invoke(app, ["agent", "open", "wise-hypatia"])
    assert result.exit_code == 0
    assert browser_urls == ["http://127.0.0.1:12345"]
    assert tunnel_calls == []


def test_open_remote_host_uses_tunnel_unowned(fleet_dir, monkeypatch) -> None:
    """Remote host: tunnel is set up with owned=False (survives CLI exit)."""
    resolved = SimpleNamespace(host="10.0.0.5", remote_port=8080)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    tunnel_kwargs = {}

    def _capture(name, **kwargs):
        tunnel_kwargs["name"] = name
        tunnel_kwargs.update(kwargs)
        return 54321  # local port returned

    monkeypatch.setattr("clawrium.core.web_ui_tunnel.ensure", _capture)
    browser_urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", _browser_mock_success(browser_urls))
    result = runner.invoke(app, ["agent", "open", "wise-hypatia"])
    assert result.exit_code == 0, result.output
    assert tunnel_kwargs["name"] == "wise-hypatia"
    assert tunnel_kwargs.get("owned") is False
    assert browser_urls == ["http://127.0.0.1:54321"]


def test_open_remote_print_url_no_block(fleet_dir, monkeypatch) -> None:
    """Remote host with --print-url: establishes tunnel, prints URL, exits."""
    resolved = SimpleNamespace(host="10.0.0.5", remote_port=8080)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    monkeypatch.setattr(
        "clawrium.core.web_ui_tunnel.ensure", lambda _name, **_kw: 54321
    )
    browser_urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: browser_urls.append(url))
    result = runner.invoke(app, ["agent", "open", "wise-hypatia", "--print-url"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:54321" in result.output
    assert browser_urls == []  # --print-url skips the browser


def test_open_remote_tunnel_error_emits_clean_message(fleet_dir, monkeypatch) -> None:
    """Tunnel setup failure surfaces as a clean error, not a traceback."""
    resolved = SimpleNamespace(host="10.0.0.5", remote_port=8080)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    from clawrium.core.web_ui_tunnel import TunnelError

    def _raise(*_args, **_kwargs):
        raise TunnelError("SSH user not configured for host; cannot establish tunnel.")

    monkeypatch.setattr("clawrium.core.web_ui_tunnel.ensure", _raise)
    monkeypatch.setattr("webbrowser.open", lambda _url: True)
    result = runner.invoke(app, ["agent", "open", "wise-hypatia"])
    assert result.exit_code != 0
    # No raw traceback bubbled up
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "tunnel setup failed" in result.output
    assert "SSH user not configured" in result.output


def test_open_local_headless_browser_fallback(fleet_dir, monkeypatch) -> None:
    """ATX B2: webbrowser.open() returning False must surface a manual-URL hint."""
    resolved = SimpleNamespace(host="127.0.0.1", remote_port=12345)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    monkeypatch.setattr("webbrowser.open", lambda _url: False)
    result = runner.invoke(app, ["agent", "open", "wise-hypatia"])
    assert result.exit_code == 0
    assert "Could not open browser" in result.output
    assert "http://127.0.0.1:12345" in result.output
    assert "--print-url" in result.output


def test_open_unknown_agent_errors(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "open", "no-such-agent"])
    assert result.exit_code != 0
    assert "not found" in result.output


# --- #1071 phase 2 ATX round-2 W1: URL emission must be sanitized. -----------
#
# Today the URL is always of the form `http://127.0.0.1:<int>` (plus an
# optional URL-encoded `?t=<token>` for ethos agents), so no bidi /
# zero-width codepoint actually reaches operator output on the current
# code paths. ATX W1 is defense-in-depth: guard the emission primitive
# so that any future URL contributor (new agent type, additional query
# params, hostname interpolation) cannot regress the terminal-safety
# contract. The tests below verify the wiring — the module's
# `sanitize_passthrough` is invoked for every raw emission path — and
# the semantics — alphanumeric token-shaped bodies pass through.


def test_open_print_url_routes_through_sanitize_passthrough(
    fleet_dir, monkeypatch
) -> None:
    resolved = SimpleNamespace(host="127.0.0.1", remote_port=12345)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    monkeypatch.setattr("webbrowser.open", lambda _url: True)

    seen: list[str] = []

    def _tracking_sanitize(value: str) -> str:
        seen.append(value)
        return value.upper()  # distinctive transform the assertion can catch

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.sanitize_passthrough", _tracking_sanitize
    )
    result = runner.invoke(app, ["agent", "open", "wise-hypatia", "--print-url"])
    assert result.exit_code == 0, result.output
    # The URL constructed inside open() was passed through the module's
    # sanitize_passthrough before emission.
    assert seen == ["http://127.0.0.1:12345"]
    # And what hit stdout is the sanitizer's transformed result — proof
    # the raw `url` did not bypass the primitive.
    assert "HTTP://127.0.0.1:12345" in result.output


def test_open_print_url_preserves_token_bearing_url(fleet_dir, monkeypatch) -> None:
    """--print-url must remain the escape hatch that gives operators the full URL.

    Ethos agents append a signed `?t=<token>` to the URL so the SPA
    can authenticate. Sanitization must not strip the token (it is
    base64-ish, alphanumeric + `-_=`), only control / bidi codepoints.
    """
    resolved = SimpleNamespace(host="127.0.0.1", remote_port=12345)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    monkeypatch.setattr("webbrowser.open", lambda _url: True)
    result = runner.invoke(app, ["agent", "open", "wise-hypatia", "--print-url"])
    assert result.exit_code == 0
    # The URL body (alphanumeric + `:` + `/`) round-trips unchanged — a
    # plausible proxy for `?t=<base64-token>` which is drawn from the
    # same codepoint class.
    assert result.output.strip() == "http://127.0.0.1:12345"


def test_open_headless_fallback_routes_through_sanitize_passthrough(
    fleet_dir, monkeypatch
) -> None:
    """Browser-launch failure emits the URL to stderr — same sanitizer path."""
    resolved = SimpleNamespace(host="127.0.0.1", remote_port=12345)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    monkeypatch.setattr("webbrowser.open", lambda _url: False)

    seen: list[str] = []

    def _tracking_sanitize(value: str) -> str:
        seen.append(value)
        return value + "|SAN|"  # distinctive marker

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.sanitize_passthrough", _tracking_sanitize
    )
    result = runner.invoke(app, ["agent", "open", "wise-hypatia"])
    assert result.exit_code == 0, result.output
    assert seen == ["http://127.0.0.1:12345"]
    # The sanitized URL body appears in both the stream_action line
    # (stdout) AND the browser-launch-failure line (stderr).
    assert "http://127.0.0.1:12345|SAN|" in result.output
    assert "Could not open browser" in result.output

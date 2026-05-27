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
    result = runner.invoke(app, ["agent", "open", "wise-hypatia"])
    assert result.exit_code == 0
    assert browser_urls == ["http://127.0.0.1:12345"]
    assert "Could not open browser" not in result.output


def test_open_remote_host_uses_tunnel_unowned(fleet_dir, monkeypatch) -> None:
    """Remote agent: creates unowned tunnel (survives CLI exit), opens browser."""
    resolved = SimpleNamespace(host="10.0.0.1", remote_port=9999)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    ensure_calls = []
    monkeypatch.setattr(
        "clawrium.core.web_ui_tunnel.ensure",
        lambda agent_key, *, owned=True: (ensure_calls.append(owned), 45678)[1],
    )
    browser_urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", _browser_mock_success(browser_urls))
    result = runner.invoke(app, ["agent", "open", "wise-hypatia"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:45678" in result.output
    assert browser_urls == ["http://127.0.0.1:45678"]
    assert "Could not open browser" not in result.output
    # CLI must pass owned=False so tunnel outlives the process
    assert ensure_calls == [False]


def test_open_remote_print_url_no_block(fleet_dir, monkeypatch) -> None:
    """Remote + --print-url: prints URL and exits immediately (no blocking)."""
    resolved = SimpleNamespace(host="10.0.0.1", remote_port=9999)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )
    ensure_calls = []
    monkeypatch.setattr(
        "clawrium.core.web_ui_tunnel.ensure",
        lambda agent_key, *, owned=True: (ensure_calls.append(owned), 45678)[1],
    )
    browser_urls = []
    monkeypatch.setattr("webbrowser.open", lambda url: browser_urls.append(url))
    result = runner.invoke(app, ["agent", "open", "wise-hypatia", "--print-url"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:45678" in result.output
    assert browser_urls == []  # --print-url skips browser
    assert ensure_calls == [False]  # still unowned


def test_open_remote_tunnel_error_emits_clean_message(fleet_dir, monkeypatch) -> None:
    """ATX B1: TunnelError must surface as a clean emit_error, not a raw traceback."""
    from clawrium.core.web_ui_tunnel import TunnelError

    resolved = SimpleNamespace(host="10.0.0.1", remote_port=9999)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.open.resolve_web_ui", lambda _: resolved
    )

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

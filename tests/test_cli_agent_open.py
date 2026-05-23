"""Tests for `clm agent open` (issue #478 phase 3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from clawrium.cli.main import app
from clawrium.core.health import ClawStatus
from clawrium.core.web_ui import ResolvedUI

runner = CliRunner()


def _seed_hosts(config_dir: Path, agent_type: str) -> None:
    """Write a minimal hosts.json with one agent of the given type."""
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "box",
            "port": 22,
            "user": "xclm",
            "agents": {
                "demo": {
                    "type": agent_type,
                    "agent_name": "demo",
                    "name": "demo",
                    "config": {},
                }
            },
        }
    ]
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(json.dumps(hosts))


def test_open_rejects_agent_without_web_ui_feature(isolated_config: Path):
    """openclaw has no `features.web_ui` in its manifest → resolver returns
    None → CLI exits with a clear "does not declare a native web UI" error.

    The hermes-only gate was dropped in #491 (zeroclaw also exposes a UI);
    the manifest's `features.web_ui` block is now the only gate.
    """
    _seed_hosts(isolated_config, "openclaw")
    result = runner.invoke(app, ["agent", "open", "demo"])
    assert result.exit_code == 1
    assert "does not declare" in result.output.lower()
    assert "native web ui" in result.output.lower()


def test_open_unknown_agent_exits_nonzero(isolated_config: Path):
    _seed_hosts(isolated_config, "openclaw")
    result = runner.invoke(app, ["agent", "open", "nope"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_open_print_mode_prints_remote_url_without_tunnel(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="192.168.1.100",
        remote_port=45123,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch("clawrium.core.web_ui_tunnel.ensure") as mock_ensure,
        patch("webbrowser.open") as mock_browser,
    ):
        result = runner.invoke(app, ["agent", "open", "demo", "--print"])

    assert result.exit_code == 0, result.output
    assert "http://192.168.1.100:45123/" in result.output
    mock_ensure.assert_not_called()
    mock_browser.assert_not_called()


def test_open_local_host_skips_tunnel_and_opens_browser(isolated_config: Path):
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="127.0.0.1",
        remote_port=9119,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    health_ok = {
        "agent": "hermes",
        "host": "127.0.0.1",
        "status": ClawStatus.RUNNING,
        "agent_name": "demo",
        "error": None,
        "missing_secrets": None,
        "onboarding_step": None,
        "process_running": True,
        "onboarding_stages": None,
        "cpu_count": None,
        "memory_total_mb": None,
    }

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch("clawrium.core.health.check_claw_health", return_value=health_ok),
        patch("clawrium.core.web_ui_tunnel.ensure") as mock_ensure,
        patch("webbrowser.open") as mock_browser,
    ):
        result = runner.invoke(app, ["agent", "open", "demo"])

    assert result.exit_code == 0, result.output
    mock_ensure.assert_not_called()
    mock_browser.assert_called_once_with("http://127.0.0.1:9119/")


def test_open_print_skips_health_probe_and_tunnel(isolated_config: Path):
    """--print is a pure data lookup; never calls SSH or runs health checks."""
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="192.168.1.100",
        remote_port=45123,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch(
            "clawrium.core.health.check_claw_health",
            side_effect=AssertionError("must not be called"),
        ),
        patch(
            "clawrium.core.web_ui_tunnel.ensure",
            side_effect=AssertionError("must not be called"),
        ),
    ):
        result = runner.invoke(app, ["agent", "open", "demo", "--print"])

    assert result.exit_code == 0


def _running_health(agent_type: str = "hermes", host: str = "192.168.1.100") -> dict:
    """Return a `check_claw_health` payload that satisfies the RUNNING gate."""
    return {
        "agent": agent_type,
        "host": host,
        "status": ClawStatus.RUNNING,
        "agent_name": "demo",
        "error": None,
        "missing_secrets": None,
        "onboarding_step": None,
        "process_running": True,
        "onboarding_stages": None,
        "cpu_count": None,
        "memory_total_mb": None,
    }


def test_open_remote_agent_spawns_tunnel_and_opens_browser(isolated_config: Path):
    """Remote hermes agent: tunnel is established and the browser is opened
    at the tunnel's local end. Regression anchor for ATX B5 (#491).
    """
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="hermes.local",
        remote_port=45123,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch(
            "clawrium.core.health.check_claw_health",
            return_value=_running_health(host="hermes.local"),
        ),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=54321) as mock_ensure,
        patch("clawrium.core.web_ui_tunnel.close") as mock_close,
        patch("webbrowser.open") as mock_browser,
        patch("threading.Event") as mock_event_cls,
    ):
        # threading.Event().wait() blocks until the SIGINT handler fires.
        # Tests run in-process: wait() must return immediately.
        mock_event_cls.return_value.wait.return_value = None
        result = runner.invoke(app, ["agent", "open", "demo"])

    assert result.exit_code == 0, result.output
    mock_ensure.assert_called_once_with("demo")
    mock_browser.assert_called_once_with("http://127.0.0.1:54321/")
    mock_close.assert_called_once_with("demo")


def test_open_remote_agent_tunnel_error_exits_nonzero(isolated_config: Path):
    """TunnelError from ensure_tunnel surfaces as exit 1 with the message.
    Regression anchor for ATX B6 (#491).
    """
    from clawrium.core.web_ui_tunnel import TunnelError

    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="hermes.local",
        remote_port=45123,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch(
            "clawrium.core.health.check_claw_health",
            return_value=_running_health(host="hermes.local"),
        ),
        patch(
            "clawrium.core.web_ui_tunnel.ensure",
            side_effect=TunnelError("ssh refused"),
        ),
        patch("webbrowser.open") as mock_browser,
    ):
        result = runner.invoke(app, ["agent", "open", "demo"])

    assert result.exit_code == 1
    assert "ssh refused" in result.output.lower()
    mock_browser.assert_not_called()


def test_open_refuses_when_agent_not_running(isolated_config: Path):
    """Health status outside {READY, RUNNING} blocks the tunnel attempt.
    Regression anchor for ATX B7 (#491).
    """
    _seed_hosts(isolated_config, "hermes")
    resolved = ResolvedUI(
        host="hermes.local",
        remote_port=45123,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    health_stopped = _running_health(host="hermes.local")
    health_stopped["status"] = ClawStatus.STOPPED

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch(
            "clawrium.core.health.check_claw_health",
            return_value=health_stopped,
        ),
        patch(
            "clawrium.core.web_ui_tunnel.ensure",
            side_effect=AssertionError("tunnel must not be attempted"),
        ),
        patch("webbrowser.open") as mock_browser,
    ):
        result = runner.invoke(app, ["agent", "open", "demo"])

    assert result.exit_code == 1
    assert "not running" in result.output.lower()
    assert "clm agent start" in result.output.lower()
    mock_browser.assert_not_called()


def test_open_remote_zeroclaw_spawns_tunnel_with_wildcard_bind(isolated_config: Path):
    """zeroclaw resolves with `bind='wildcard'` and still tunnels to remote
    loopback (BIND_ADDRESS_MAP['wildcard'] == '127.0.0.1'). Regression
    anchor for ATX W15 (#491).
    """
    _seed_hosts(isolated_config, "zeroclaw")
    resolved = ResolvedUI(
        host="zero.local",
        remote_port=40123,
        bind="wildcard",
        ssh_config={"user": "xclm"},
    )

    with (
        patch("clawrium.core.web_ui.resolve", return_value=resolved),
        patch(
            "clawrium.core.health.check_claw_health",
            return_value=_running_health(agent_type="zeroclaw", host="zero.local"),
        ),
        patch("clawrium.core.web_ui_tunnel.ensure", return_value=39211) as mock_ensure,
        patch("clawrium.core.web_ui_tunnel.close"),
        patch("webbrowser.open") as mock_browser,
        patch("threading.Event") as mock_event_cls,
    ):
        mock_event_cls.return_value.wait.return_value = None
        result = runner.invoke(app, ["agent", "open", "demo"])

    assert result.exit_code == 0, result.output
    mock_ensure.assert_called_once_with("demo")
    mock_browser.assert_called_once_with("http://127.0.0.1:39211/")

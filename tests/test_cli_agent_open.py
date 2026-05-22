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


def test_open_rejects_non_hermes_agent(isolated_config: Path):
    _seed_hosts(isolated_config, "openclaw")
    result = runner.invoke(app, ["agent", "open", "demo"])
    assert result.exit_code == 1
    assert "not supported" in result.output.lower()
    assert "hermes" in result.output.lower()


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

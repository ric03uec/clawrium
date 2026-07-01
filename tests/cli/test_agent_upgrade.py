"""Tests for `clawctl agent upgrade` (issue #592).

The upgrade subcommand is forward-only and max-only — the manifest's
max-compatible entry is always the target. Every test patches
`run_installation` and the drift helper so we exercise the CLI logic
without touching SSH or ansible-runner. Where state mutation is part of
the contract, the test reads `hosts.json` back to confirm.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _write_host(
    config_dir: Path,
    agent_type: str,
    installed_version: str,
    *,
    agent_name: str = "test-agent",
    hostname: str = "192.168.1.100",
) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "keys" / hostname).mkdir(parents=True, exist_ok=True)
    (config_dir / "keys" / hostname / "xclm_ed25519").write_text("k")
    (config_dir / "keys" / hostname / "xclm_ed25519").chmod(0o600)
    (config_dir / "keys" / hostname / "xclm_ed25519.pub").write_text(
        "ssh-ed25519 AAAA"
    )
    hosts = [
        {
            "hostname": hostname,
            "key_id": hostname,
            "port": 22,
            "user": "xclm",
            "auth_method": "key",
            "alias": "h1",
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 4,
                "memtotal_mb": 8192,
                "os": "ubuntu",
                "os_version": "24.04",
                "gpu": {"present": False},
            },
            "metadata": {
                "added_at": "2026-06-01T00:00:00Z",
                "last_seen": "2026-06-01T00:00:00Z",
                "tags": [],
            },
            "agents": {
                agent_name: {
                    "type": agent_type,
                    "agent_name": agent_name,
                    "version": installed_version,
                    "installed_at": "2026-06-01T00:00:00Z",
                    "status": "installed",
                    "onboarding": {"state": "ready", "stages": {}},
                    "config": {},
                }
            },
        }
    ]
    (config_dir / "hosts.json").write_text(json.dumps(hosts, indent=2))


def _read_version(config_dir: Path, agent_name: str = "test-agent") -> str:
    data = json.loads((config_dir / "hosts.json").read_text())
    return data[0]["agents"][agent_name]["version"]


@pytest.fixture
def _patch_drift_clean():
    """Patch the drift helper to return no changed files."""
    with patch(
        "clawrium.cli.clawctl.agent.upgrade._drift_files", return_value=[]
    ) as m:
        yield m


def test_upgrade_no_op_when_already_at_max(isolated_config: Path):
    """Already at manifest max → exit 0, no install, no version mutation."""
    _write_host(isolated_config, "openclaw", "2026.6.11")
    with patch("clawrium.core.install.run_installation") as mock_install:
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code == 0, result.output
    assert "already at latest" in result.output.lower()
    mock_install.assert_not_called()
    assert _read_version(isolated_config) == "2026.6.11"


def test_upgrade_nochange_zeroclaw_exits_zero(isolated_config: Path):
    """Zeroclaw manifest max is unchanged → upgrade is a no-op."""
    _write_host(isolated_config, "zeroclaw", "0.7.5")
    with patch("clawrium.core.install.run_installation") as mock_install:
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code == 0, result.output
    assert "already at latest" in result.output.lower()
    mock_install.assert_not_called()
    assert _read_version(isolated_config) == "0.7.5"


def test_upgrade_rejects_drift(isolated_config: Path):
    """Drift detected → non-zero exit; install not called; version unchanged."""
    _write_host(isolated_config, "openclaw", "2026.4.2")
    with patch(
        "clawrium.cli.clawctl.agent.upgrade._drift_files",
        return_value=["~/.openclaw/config.yaml"],
    ), patch("clawrium.core.install.run_installation") as mock_install:
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code != 0, result.output
    assert "drift" in result.output.lower()
    assert "~/.openclaw/config.yaml" in result.output
    mock_install.assert_not_called()
    assert _read_version(isolated_config) == "2026.4.2"


def test_upgrade_rejects_downgrade_attempt(
    isolated_config: Path, _patch_drift_clean
):
    """Installed > manifest max → hard reject."""
    _write_host(isolated_config, "openclaw", "9999.0.0")
    with patch("clawrium.core.install.run_installation") as mock_install:
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code != 0, result.output
    assert "downgrade" in result.output.lower()
    mock_install.assert_not_called()
    assert _read_version(isolated_config) == "9999.0.0"


def test_upgrade_happy_path_openclaw(isolated_config: Path, _patch_drift_clean):
    """Happy path: force=True is forwarded; hosts.json reflects new version."""
    _write_host(isolated_config, "openclaw", "2026.4.2")

    def _fake_install(claw_name, hostname, name=None, **kwargs):
        # Simulate the real write at install.py:562.
        path = isolated_config / "hosts.json"
        data = json.loads(path.read_text())
        data[0]["agents"]["test-agent"]["version"] = "2026.6.11"
        path.write_text(json.dumps(data, indent=2))
        return {
            "success": True,
            "agent": "openclaw",
            "version": "2026.6.11",
            "host": hostname,
            "playbooks_run": [],
            "error": None,
        }

    with patch(
        "clawrium.core.install.run_installation", side_effect=_fake_install
    ) as mock_install:
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code == 0, result.output
    mock_install.assert_called_once()
    _, kwargs = mock_install.call_args
    # `run_installation` is called positionally too — normalize.
    call_kwargs = {**kwargs}
    if mock_install.call_args.args:
        # First positional is claw_name
        call_kwargs.setdefault("claw_name", mock_install.call_args.args[0])
    assert call_kwargs.get("force") is True
    assert _read_version(isolated_config) == "2026.6.11"


def test_upgrade_happy_path_hermes(isolated_config: Path, _patch_drift_clean):
    """Hermes happy path: forwards force=True; version persisted."""
    _write_host(isolated_config, "hermes", "2026.5.7")

    def _fake_install(*args, **kwargs):
        path = isolated_config / "hosts.json"
        data = json.loads(path.read_text())
        data[0]["agents"]["test-agent"]["version"] = "2026.5.29.2"
        path.write_text(json.dumps(data, indent=2))
        return {
            "success": True,
            "agent": "hermes",
            "version": "2026.5.29.2",
            "host": args[1] if len(args) > 1 else kwargs.get("hostname", ""),
            "playbooks_run": [],
            "error": None,
        }

    with patch(
        "clawrium.core.install.run_installation", side_effect=_fake_install
    ) as mock_install:
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code == 0, result.output
    mock_install.assert_called_once()
    assert _read_version(isolated_config) == "2026.5.29.2"


def test_upgrade_json_output_mode(isolated_config: Path, _patch_drift_clean):
    """`-o json --yes` emits a parseable payload with expected keys."""
    _write_host(isolated_config, "openclaw", "2026.4.2")

    def _fake_install(*args, **kwargs):
        return {
            "success": True,
            "agent": "openclaw",
            "version": "2026.6.11",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

    with patch("clawrium.core.install.run_installation", side_effect=_fake_install):
        result = runner.invoke(
            app,
            ["agent", "upgrade", "test-agent", "-o", "json", "--yes"],
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    # The last line of output is the JSON payload.
    payload = None
    for line in reversed(result.output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            payload = json.loads(line)
            break
    assert payload is not None, result.output
    assert payload["agent"] == "test-agent"
    assert payload["from_version"] == "2026.4.2"
    assert payload["to_version"] == "2026.6.11"


def test_upgrade_retries_after_previous_failed_install(
    isolated_config: Path, _patch_drift_clean
):
    """ATX B3: a prior failed install leaves version=target+status=failed.

    Without the failed-status retry path the no-op shortcut would trap
    the operator forever. Confirm the retry path calls run_installation
    even when installed == manifest max.
    """
    # Seed at the current manifest max so the ONLY reason
    # `run_installation` fires is the `status=failed` flag — otherwise
    # this test silently degrades into the ordinary "installed < max"
    # upgrade path and would still pass if the failed-status retry
    # branch were deleted.
    _write_host(isolated_config, "openclaw", "2026.6.11")
    # Flip the status to 'failed' to simulate the trap.
    data = json.loads((isolated_config / "hosts.json").read_text())
    data[0]["agents"]["test-agent"]["status"] = "failed"
    (isolated_config / "hosts.json").write_text(json.dumps(data))

    def _fake_install(*args, **kwargs):
        return {
            "success": True,
            "agent": "openclaw",
            "version": "2026.6.11",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

    with patch(
        "clawrium.core.install.run_installation", side_effect=_fake_install
    ) as mock_install:
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code == 0, result.output
    mock_install.assert_called_once()
    assert "already at latest" not in result.output.lower()


def test_upgrade_zeroclaw_invokes_restart_agent_for_bearer_rotation(
    isolated_config: Path, _patch_drift_clean
):
    """ATX B2: zeroclaw install never re-pairs; upgrade must drive the

    canonical lifecycle via `restart_agent` so the bearer rotates and
    `gateway_token_rotated` fires per AGENTS.md.
    """
    _write_host(isolated_config, "zeroclaw", "0.6.0")

    def _fake_install(*args, **kwargs):
        return {
            "success": True,
            "agent": "zeroclaw",
            "version": "0.7.5",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

    def _fake_restart(*args, **kwargs):
        return {
            "success": True,
            "agent": kwargs.get("agent_name") or "zeroclaw",
            "host": kwargs.get("hostname", ""),
            "error": None,
        }

    with patch(
        "clawrium.core.install.run_installation", side_effect=_fake_install
    ), patch(
        "clawrium.core.lifecycle.restart_agent", side_effect=_fake_restart
    ) as mock_restart:
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code == 0, result.output
    mock_restart.assert_called_once()


def test_upgrade_zeroclaw_surfaces_failed_restart_as_error(
    isolated_config: Path, _patch_drift_clean
):
    """ATX iter-2 W1: a `success=False` return from `restart_agent` must

    NOT fall through as a silent "upgraded" success. The bearer rotation
    guarantee in AGENTS.md is conditional on confirmed restart success.
    """
    _write_host(isolated_config, "zeroclaw", "0.6.0")

    def _fake_install(*args, **kwargs):
        return {
            "success": True,
            "agent": "zeroclaw",
            "version": "0.7.5",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

    def _fake_restart_failed(*args, **kwargs):
        return {
            "success": False,
            "agent": "zeroclaw",
            "host": "192.168.1.100",
            "error": "systemd unit failed to come up",
        }

    with patch(
        "clawrium.core.install.run_installation", side_effect=_fake_install
    ), patch(
        "clawrium.core.lifecycle.restart_agent", side_effect=_fake_restart_failed
    ):
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code != 0, result.output
    assert "restart failed" in result.output.lower()
    assert "systemd unit failed to come up" in result.output


def test_upgrade_openclaw_does_not_invoke_restart_agent(
    isolated_config: Path, _patch_drift_clean
):
    """openclaw is intentionally NOT in `_PAIRING_AGENT_TYPES` — its

    bearer is a static install-time token (see AGENTS.md §"Native
    Dashboards"). The post-install restart path must NOT fire for it.
    """
    _write_host(isolated_config, "openclaw", "2026.4.2")

    def _fake_install(*args, **kwargs):
        return {
            "success": True,
            "agent": "openclaw",
            "version": "2026.6.8",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

    with patch(
        "clawrium.core.install.run_installation", side_effect=_fake_install
    ), patch(
        "clawrium.core.lifecycle.restart_agent",
        side_effect=AssertionError("restart_agent must not be called for openclaw"),
    ):
        result = runner.invoke(
            app, ["agent", "upgrade", "test-agent", "--yes"], env=os.environ
        )
    assert result.exit_code == 0, result.output


def test_upgrade_skip_drift_check_bypasses_preflight(isolated_config: Path):
    """`--skip-drift-check` means the drift helper is never called."""
    _write_host(isolated_config, "openclaw", "2026.4.2")

    def _fake_install(*args, **kwargs):
        return {
            "success": True,
            "agent": "openclaw",
            "version": "2026.6.8",
            "host": "192.168.1.100",
            "playbooks_run": [],
            "error": None,
        }

    with patch(
        "clawrium.cli.clawctl.agent.upgrade._drift_files",
        side_effect=AssertionError("drift helper must not be called"),
    ), patch(
        "clawrium.core.install.run_installation", side_effect=_fake_install
    ) as mock_install:
        result = runner.invoke(
            app,
            [
                "agent",
                "upgrade",
                "test-agent",
                "--skip-drift-check",
                "--yes",
            ],
            env=os.environ,
        )
    assert result.exit_code == 0, result.output
    mock_install.assert_called_once()

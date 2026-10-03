"""No-daemon lifecycle contracts for Claude Code (#996)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawrium.cli.tui.data import get_fleet_data_local
from clawrium.core import lifecycle, lifecycle_canonical, lifecycle_macos
from clawrium.core.agent_lifecycle import incomplete_install_message
from clawrium.core.health import ClawStatus, check_claw_health
from clawrium.core.playbook_resolver import resolve_agent_playbook


def _claude_host(*, os_family: str = "linux") -> dict:
    return {
        "hostname": "claude-host",
        "key_id": "claude-host",
        "os_family": os_family,
        "agents": {
            "claude-code": {
                "type": "claude",
                "agent_name": "claude-code",
                "status": "installed",
                "installed_at": "2026-10-03T00:00:00+00:00",
                "config": {},
            }
        },
    }


def _unexpected(*_args, **_kwargs):
    raise AssertionError("daemon transport must not run for Claude Code")


@pytest.mark.parametrize("operation", ["start", "stop", "restart"])
def test_linux_lifecycle_rejects_claude_before_daemon_transport(
    monkeypatch, operation: str
):
    host = _claude_host()
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "_assert_install_present", _unexpected)
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _unexpected)

    with pytest.raises(lifecycle.LifecycleError, match="does not run a daemon"):
        getattr(lifecycle, f"{operation}_agent")(
            "claude-host", "claude", agent_name="claude-code"
        )


@pytest.mark.parametrize("operation", ["start", "stop", "restart"])
def test_macos_lifecycle_rejects_claude_before_launchctl(monkeypatch, operation: str):
    host = _claude_host(os_family="darwin")
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _: host)
    monkeypatch.setattr(lifecycle_macos, "start_agent_macos", _unexpected)
    monkeypatch.setattr(lifecycle_macos, "stop_agent_macos", _unexpected)
    monkeypatch.setattr(lifecycle_macos, "restart_agent_macos", _unexpected)

    with pytest.raises(lifecycle_macos.LifecycleError, match="does not run a daemon"):
        getattr(lifecycle_macos, f"{operation}_agent")(
            "claude-host", "claude", agent_name="claude-code"
        )


def test_no_daemon_sync_and_configure_skip_renderer_ssh_and_restart(monkeypatch):
    host = _claude_host()
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "_assert_install_present", _unexpected)
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _unexpected)

    sync_result = lifecycle.sync_agent(
        "claude-host", "claude", agent_name="claude-code"
    )
    configure_result = lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    )

    assert sync_result["success"] is True
    assert configure_result == (True, None)


@pytest.mark.parametrize(
    ("status", "installed_at"),
    [("failed", None), ("installing", None), ("installed", None)],
)
def test_incomplete_claude_install_rejects_reconcile_without_daemon_transport(
    monkeypatch, status: str, installed_at: str | None
):
    host = _claude_host()
    record = host["agents"]["claude-code"]
    record["status"] = status
    record["installed_at"] = installed_at
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "_assert_install_present", _unexpected)
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _unexpected)

    with pytest.raises(lifecycle.LifecycleError, match="incomplete installation"):
        lifecycle.sync_agent("claude-host", "claude", agent_name="claude-code")
    assert lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    ) == (False, incomplete_install_message("claude", "configure"))

    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "build_render_inputs", _unexpected)
    with pytest.raises(
        lifecycle_canonical.CanonicalSyncError, match="incomplete installation"
    ):
        lifecycle_canonical.sync_agent_canonical("claude-code")


def test_macos_sync_and_configure_do_not_resolve_missing_configure_playbook(
    monkeypatch,
):
    calls: list[str] = []

    def _configure(**_kwargs):
        calls.append("configure")
        return True, None

    def _sync(**_kwargs):
        calls.append("sync")
        return {"success": True, "agent": "claude-code"}

    monkeypatch.setattr("clawrium.core.lifecycle.configure_agent", _configure)
    monkeypatch.setattr("clawrium.core.lifecycle.sync_agent", _sync)
    monkeypatch.setattr(
        "clawrium.core.playbook_resolver.resolve_agent_playbook", _unexpected
    )

    assert lifecycle_macos.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    ) == (True, None)
    assert (
        lifecycle_macos.sync_agent("claude-host", "claude", agent_name="claude-code")[
            "success"
        ]
        is True
    )
    assert calls == ["configure", "sync"]


def test_canonical_sync_for_claude_does_not_build_render_inputs_or_open_ssh(
    monkeypatch,
):
    host = _claude_host()
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", host["agents"]["claude-code"]),
    )
    monkeypatch.setattr(lifecycle_canonical, "build_render_inputs", _unexpected)
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", _unexpected)

    result = lifecycle_canonical.sync_agent_canonical("claude-code")

    assert result.success is True
    assert result.files_written == ()
    assert result.files_unchanged == ()


def test_claude_health_is_ready_without_ssh_or_process_probe(monkeypatch):
    host = _claude_host()
    monkeypatch.setattr("clawrium.core.health.get_host_private_key", _unexpected)
    monkeypatch.setattr("clawrium.core.health.ansible_runner.run", _unexpected)

    result = check_claw_health("claude-code", host)

    assert result["status"] is ClawStatus.READY
    assert result["process_running"] is False
    assert result["error"] is None


@pytest.mark.parametrize(
    ("status", "installed_at"),
    [("failed", None), ("installing", None), ("installed", None)],
)
def test_incomplete_claude_install_is_not_reported_ready_without_a_probe(
    monkeypatch, status: str, installed_at: str | None
):
    host = _claude_host()
    record = host["agents"]["claude-code"]
    record["status"] = status
    record["installed_at"] = installed_at
    monkeypatch.setattr("clawrium.core.health.get_host_private_key", _unexpected)
    monkeypatch.setattr("clawrium.core.health.ansible_runner.run", _unexpected)

    result = check_claw_health("claude-code", host)

    assert result["status"] is ClawStatus.INSTALL_MISSING
    assert result["process_running"] is False
    assert result["error"] == "Installation is incomplete"


def test_claude_fleet_entry_is_ready_without_gateway_state(isolated_config: Path):
    config = isolated_config
    config.mkdir(parents=True)
    (config / "hosts.json").write_text(
        """[
  {
    "hostname": "claude-host",
    "agents": {
      "claude-code": {
        "type": "claude",
        "agent_name": "claude-code",
        "version": "2.1.100",
        "config": {}
      }
    }
  }
]
"""
    )

    agents, summary = get_fleet_data_local()

    assert summary["total"] == 1
    assert agents[0]["status"] is ClawStatus.READY
    assert agents[0]["process_running"] is False
    assert agents[0]["gateway_port"] is None
    assert agents[0]["gateway_url"] is None


def test_static_fleet_marks_incomplete_claude_install_not_ready(isolated_config: Path):
    config = isolated_config
    config.mkdir(parents=True)
    (config / "hosts.json").write_text(
        """[
  {
    "hostname": "claude-host",
    "agents": {
      "claude-code": {
        "type": "claude",
        "agent_name": "claude-code",
        "status": "failed",
        "error": "npm install failed",
        "config": {}
      }
    }
  }
]
"""
    )

    agents, _summary = get_fleet_data_local()

    assert agents[0]["status"] is ClawStatus.INSTALL_MISSING
    assert agents[0]["process_running"] is False
    assert agents[0]["health_error"] == "npm install failed"


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_claude_removal_uses_os_specific_playbook_before_local_cleanup(
    monkeypatch, os_family: str
):
    host = _claude_host(os_family=os_family)
    captured: dict = {}

    def _run(*_args, **kwargs):
        captured.update(kwargs)
        return True, None

    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _run)
    monkeypatch.setattr(lifecycle, "remove_instance_secrets", lambda _: None)
    monkeypatch.setattr(lifecycle, "cleanup_agent_state", lambda _: False)
    monkeypatch.setattr(lifecycle, "remove_agent_from_host", lambda *_: True)

    result = lifecycle.remove_agent("claude-host", "claude", agent_name="claude-code")

    assert result["success"] is True
    assert captured["playbook_path_override"] == resolve_agent_playbook(
        "claude", "remove", os_family
    )


def test_claude_remote_removal_failure_preserves_local_record(monkeypatch):
    host = _claude_host()
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(
        lifecycle, "_run_lifecycle_playbook", lambda *_args, **_kwargs: (False, "boom")
    )
    monkeypatch.setattr(lifecycle, "remove_agent_from_host", _unexpected)
    monkeypatch.setattr(lifecycle, "remove_instance_secrets", _unexpected)
    monkeypatch.setattr(lifecycle, "cleanup_agent_state", _unexpected)

    result = lifecycle.remove_agent("claude-host", "claude", agent_name="claude-code")

    assert result["success"] is False
    assert result["error"] == "boom"

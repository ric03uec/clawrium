"""No-daemon lifecycle contracts for Claude Code (#996)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawrium.cli.tui.data import get_fleet_data_local
from clawrium.core import lifecycle, lifecycle_canonical, lifecycle_macos
from clawrium.core.agent_lifecycle import incomplete_install_message
from clawrium.core.health import ClawStatus, check_claw_health
from clawrium.core.hosts import get_host
from clawrium.core.playbook_resolver import resolve_agent_playbook
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
    set_instance_secret,
)


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


def test_no_daemon_legacy_entrypoints_delegate_without_daemon_transport(monkeypatch):
    host = _claude_host()
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "_assert_install_present", _unexpected)
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _unexpected)
    monkeypatch.setattr(
        lifecycle,
        "_configure_claude_settings",
        lambda **_kwargs: (True, None),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "sync_agent_canonical",
        lambda *_args, **_kwargs: lifecycle_canonical.CanonicalSyncResult(
            success=True,
            agent="claude-code",
            host="claude-host",
            files_written=(".claude/settings.json",),
            files_unchanged=(),
            diffs=(),
        ),
    )

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


def test_canonical_sync_for_claude_dispatches_settings_without_provider_assembly(
    monkeypatch,
):
    host = _claude_host()
    captured: dict = {}
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", host["agents"]["claude-code"]),
    )
    monkeypatch.setattr(lifecycle_canonical, "build_render_inputs", _unexpected)

    def _sync_settings(**kwargs):
        captured.update(kwargs)
        return lifecycle_canonical.CanonicalSyncResult(
            success=True,
            agent="claude-code",
            host="claude-host",
            files_written=(".claude/settings.json",),
            files_unchanged=(),
            diffs=(),
        )

    monkeypatch.setattr(lifecycle_canonical, "_sync_claude_settings", _sync_settings)

    result = lifecycle_canonical.sync_agent_canonical("claude-code")

    assert result.success is True
    assert result.files_written == (".claude/settings.json",)
    assert captured["claw_record"] == host["agents"]["claude-code"]


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


def _persist_claude_removal_state(
    config: Path, *, os_family: str = "linux"
) -> tuple[dict, str]:
    """Persist a Claude record and secret so remove ordering is observable."""
    host = _claude_host(os_family=os_family)
    config.mkdir(parents=True)
    (config / "hosts.json").write_text(json.dumps([host]))
    instance_key = get_instance_key(host["key_id"], "claude", "claude-code")
    set_instance_secret(
        instance_key,
        "CLAUDE_CODE_OAUTH_TOKEN",
        "removal-ordering-test-token",
    )
    return host, instance_key


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_claude_successful_remote_removal_prunes_local_state_after_cleanup(
    isolated_config: Path, monkeypatch, os_family: str
):
    host, instance_key = _persist_claude_removal_state(
        isolated_config, os_family=os_family
    )
    order: list[str] = []
    playbook_paths = []
    remove_secrets = lifecycle.remove_instance_secrets
    remove_record = lifecycle.remove_agent_from_host

    def _run(*_args, **kwargs):
        order.append("remote")
        playbook_paths.append(kwargs["playbook_path_override"])
        assert set(get_instance_secrets(instance_key)) == {"CLAUDE_CODE_OAUTH_TOKEN"}
        assert "claude-code" in get_host(host["hostname"])["agents"]
        return True, None

    def _remove_secrets(received_instance_key: str) -> bool:
        assert received_instance_key == instance_key
        assert order == ["remote"]
        order.append("secrets")
        return remove_secrets(received_instance_key)

    def _cleanup_state(agent_name: str) -> bool:
        assert agent_name == "claude-code"
        assert order == ["remote", "secrets"]
        order.append("state")
        return False

    def _remove_record(hostname: str, agent_name: str) -> bool:
        assert (hostname, agent_name) == ("claude-host", "claude-code")
        assert order == ["remote", "secrets", "state"]
        order.append("hosts")
        return remove_record(hostname, agent_name)

    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _run)
    monkeypatch.setattr(lifecycle, "remove_instance_secrets", _remove_secrets)
    monkeypatch.setattr(lifecycle, "cleanup_agent_state", _cleanup_state)
    monkeypatch.setattr(lifecycle, "remove_agent_from_host", _remove_record)

    result = lifecycle.remove_agent("claude-host", "claude", agent_name="claude-code")

    assert result["success"] is True
    assert order == ["remote", "secrets", "state", "hosts"]
    assert playbook_paths == [resolve_agent_playbook("claude", "remove", os_family)]
    assert get_instance_secrets(instance_key) == {}
    assert "claude-code" not in get_host(host["hostname"])["agents"]


def test_claude_remote_removal_failure_preserves_persisted_local_state(
    isolated_config: Path, monkeypatch
):
    host, instance_key = _persist_claude_removal_state(isolated_config)
    monkeypatch.setattr(
        lifecycle, "_run_lifecycle_playbook", lambda *_args, **_kwargs: (False, "boom")
    )
    monkeypatch.setattr(lifecycle, "remove_agent_from_host", _unexpected)
    monkeypatch.setattr(lifecycle, "remove_instance_secrets", _unexpected)
    monkeypatch.setattr(lifecycle, "cleanup_agent_state", _unexpected)

    result = lifecycle.remove_agent("claude-host", "claude", agent_name="claude-code")

    assert result["success"] is False
    assert result["error"] == "boom"
    assert set(get_instance_secrets(instance_key)) == {"CLAUDE_CODE_OAUTH_TOKEN"}
    assert "claude-code" in get_host(host["hostname"])["agents"]

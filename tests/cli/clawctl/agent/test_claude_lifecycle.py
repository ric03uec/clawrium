"""CLI contracts for the install-only Claude Code agent type (#996)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.agent_lifecycle import (
    incomplete_install_message,
    lifecycle_not_applicable_message,
)
from clawrium.core.lifecycle import LifecycleError
from clawrium.core.lifecycle_canonical import CanonicalSyncError

runner = CliRunner()


def _add_claude_agent(fleet_dir, *, config: object = None) -> None:
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["claude-code"] = {
        "type": "claude",
        "agent_name": "claude-code",
        "version": "2.1.100",
        "status": "installed",
        "installed_at": "2026-10-03T00:00:00+00:00",
        "config": config or {},
    }
    hosts_path.write_text(json.dumps(hosts, indent=2))


def test_claude_is_visible_in_get_and_describe(fleet_dir) -> None:
    _add_claude_agent(fleet_dir)

    listed = runner.invoke(app, ["agent", "get", "-o", "name"])
    detail = runner.invoke(app, ["agent", "describe", "claude-code"])

    assert listed.exit_code == 0
    assert "agent/claude-code" in listed.output
    assert detail.exit_code == 0
    assert "claude" in detail.output.lower()


def test_claude_open_remains_manifest_capability_unavailable(fleet_dir) -> None:
    _add_claude_agent(fleet_dir)

    result = runner.invoke(app, ["agent", "open", "claude-code", "--print-url"])

    assert result.exit_code != 0
    assert "no web ui" in result.output.lower()


def test_claude_help_and_exec_use_the_native_dedicated_binary(
    fleet_dir, monkeypatch
) -> None:
    _add_claude_agent(fleet_dir)
    calls: list[dict] = []

    def _native_exec(**kwargs):
        calls.append(kwargs)
        return "2.1.100\n", "", 0

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.exec.run_agent_exec", _native_exec
    )

    help_result = runner.invoke(app, ["agent", "--help"])
    create_help_result = runner.invoke(app, ["agent", "create", "--help"])
    shell_help_result = runner.invoke(app, ["agent", "shell", "--help"])
    exec_help_result = runner.invoke(app, ["agent", "exec", "--help"])
    exec_result = runner.invoke(
        app, ["agent", "exec", "claude-code", "--", "--version"]
    )

    assert help_result.exit_code == 0
    normalized_help = " ".join(help_result.output.split())
    for text in (
        "create Install agent (Claude Code/Codex are CLI-only).",
        "start Start daemon agent (not CLI-only agents).",
        "stop Stop daemon agent (not CLI-only agents).",
        "restart Restart daemon agent (not CLI-only agents).",
        "logs Stream agent logs (not CLI-only agents).",
        "chat Chat with a chat-enabled agent.",
        "open Open native UI (not available for CLI-only agents).",
    ):
        assert text in normalized_help
    assert create_help_result.exit_code == 0
    assert shell_help_result.exit_code == 0
    assert exec_help_result.exit_code == 0
    assert (
        "Agent type (e.g., openclaw, zeroclaw, hermes, claude, codex; Claude and Codex are install-only)."
        in " ".join(create_help_result.output.split())
    )
    assert (
        "Execute a native CLI command on the agent host."
        in " ".join(exec_help_result.output.split())
    )
    assert (
        "For daemonless Claude Code agents, structured native arguments use"
        in " ".join(shell_help_result.output.split())
    )
    assert exec_result.exit_code == 0, exec_result.output
    assert exec_result.output == "2.1.100\n"
    assert calls == [
        {
            "hostname": "10.0.0.1",
            "agent_name": "claude-code",
            "claw_type": "claude",
            "cmd_argv": ["--version"],
        }
    ]


@pytest.mark.parametrize("verb", ["start", "stop", "restart", "logs"])
def test_claude_daemon_operations_are_not_applicable(
    fleet_dir, monkeypatch, verb: str
) -> None:
    _add_claude_agent(fleet_dir)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("daemon lifecycle must not be invoked for Claude Code")

    if verb == "start":
        monkeypatch.setattr("clawrium.cli.clawctl.agent.start.start_agent", _unexpected)
    elif verb == "stop":
        monkeypatch.setattr("clawrium.cli.clawctl.agent.stop.stop_agent", _unexpected)
    elif verb == "restart":
        monkeypatch.setattr(
            "clawrium.cli.clawctl.agent.restart.restart_agent", _unexpected
        )
    else:
        monkeypatch.setattr(
            "clawrium.core.lifecycle._run_lifecycle_playbook", _unexpected
        )

    result = runner.invoke(app, ["agent", verb, "claude-code"])

    assert result.exit_code != 0
    assert lifecycle_not_applicable_message("claude", verb) in result.output


def test_claude_sync_and_configure_render_global_settings_without_daemon(
    fleet_dir, monkeypatch
) -> None:
    settings = {
        "model": "claude-sonnet-4-5",
        "permissions": {"deny": ["Read(.env)"]},
    }
    _add_claude_agent(fleet_dir, config=settings)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hostname = hosts[0]["hostname"]
    sync_calls: list[tuple[tuple, dict]] = []
    configure_calls: list[dict] = []

    class _Result:
        success = True
        files_written = (".claude/settings.json",)
        files_unchanged = ()
        error = None

    def fake_sync(*args, **kwargs):
        sync_calls.append((args, kwargs))
        return _Result()

    class _Backend:
        @staticmethod
        def configure_agent(**kwargs):
            configure_calls.append(kwargs)
            return True, None

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", fake_sync
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.resolve_lifecycle_backend",
        lambda _os_family: _Backend(),
    )

    sync_result = runner.invoke(app, ["agent", "sync", "claude-code"])
    configure_result = runner.invoke(app, ["agent", "configure", "claude-code"])

    assert sync_result.exit_code == 0
    assert configure_result.exit_code == 0
    assert len(sync_calls) == 1
    sync_args, sync_kwargs = sync_calls[0]
    assert sync_args == ("claude-code",)
    assert sync_kwargs.keys() == {
        "restart",
        "verify",
        "push_workspace",
        "workspace_only",
        "dry_run",
        "on_event",
    }
    assert sync_kwargs["restart"] is False
    assert sync_kwargs["verify"] is False
    assert sync_kwargs["push_workspace"] is False
    assert sync_kwargs["workspace_only"] is False
    assert sync_kwargs["dry_run"] is False
    assert callable(sync_kwargs["on_event"])
    assert len(configure_calls) == 1
    configure_kwargs = configure_calls[0]
    assert configure_kwargs.keys() == {
        "hostname",
        "claw_name",
        "config_data",
        "agent_name",
        "on_event",
    }
    assert configure_kwargs["hostname"] == hostname
    assert configure_kwargs["claw_name"] == "claude"
    assert configure_kwargs["config_data"] == settings
    assert configure_kwargs["agent_name"] == "claude-code"
    assert callable(configure_kwargs["on_event"])
    for result in (sync_result, configure_result):
        assert "global settings" in result.output
        assert "no daemon restart" in result.output


@pytest.mark.parametrize(
    ("flag", "workspace_only", "dry_run"),
    [
        ("--workspace-only", True, False),
        ("--dry-run", False, True),
        ("--diff", False, True),
    ],
)
def test_claude_sync_nonstandard_modes_never_request_daemon_restart(
    fleet_dir, monkeypatch, flag: str, workspace_only: bool, dry_run: bool
) -> None:
    _add_claude_agent(fleet_dir)
    calls: list[dict] = []

    class _Result:
        success = True
        files_written = ()
        files_unchanged = (".claude/settings.json",)
        error = None

    def fake_sync(*_args, **kwargs):
        calls.append(kwargs)
        return _Result()

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", fake_sync
    )

    result = runner.invoke(app, ["agent", "sync", "claude-code", flag])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0]["workspace_only"] is workspace_only
    assert calls[0]["dry_run"] is dry_run
    assert calls[0]["restart"] is False
    assert calls[0]["verify"] is False
    assert calls[0]["push_workspace"] is False


@pytest.mark.parametrize(
    ("flag", "failure"),
    [
        ("--dry-run", "returned error"),
        ("--dry-run", "raised error"),
        ("--diff", "returned error"),
        ("--diff", "raised error"),
    ],
)
def test_claude_dry_run_and_diff_errors_do_not_report_success(
    fleet_dir, monkeypatch, flag: str, failure: str
) -> None:
    _add_claude_agent(fleet_dir)
    calls: list[dict] = []

    class _FailedResult:
        success = False
        files_written = ()
        files_unchanged = ()
        error = "render failed"

    def fake_sync(*_args, **kwargs):
        calls.append(kwargs)
        if failure == "raised error":
            raise CanonicalSyncError("render failed")
        return _FailedResult()

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", fake_sync
    )

    result = runner.invoke(app, ["agent", "sync", "claude-code", flag])

    assert result.exit_code != 0
    assert "agent 'claude-code' on host" in result.output
    assert "sync failed: render failed" in result.output
    assert "dry-run complete" not in result.output
    assert calls[0]["dry_run"] is True
    assert calls[0]["restart"] is False
    assert calls[0]["verify"] is False
    assert calls[0]["push_workspace"] is False


@pytest.mark.parametrize("failure", ["returned error", "raised error"])
def test_claude_sync_errors_do_not_report_success(fleet_dir, monkeypatch, failure: str) -> None:
    _add_claude_agent(fleet_dir)

    class _FailedResult:
        success = False
        files_written = ()
        files_unchanged = ()
        error = "render failed"

    def fake_sync(*_args, **_kwargs):
        if failure == "raised error":
            raise CanonicalSyncError("render failed")
        return _FailedResult()

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", fake_sync
    )

    result = runner.invoke(app, ["agent", "sync", "claude-code"])

    assert result.exit_code != 0
    assert "agent 'claude-code' on host" in result.output
    assert "sync failed: render failed" in result.output
    assert "synced Claude global settings" not in result.output


def test_claude_configure_rejects_non_object_config_before_backend(
    fleet_dir, monkeypatch
) -> None:
    _add_claude_agent(fleet_dir, config=["not", "settings"])

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("configure backend must not receive malformed config")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.resolve_lifecycle_backend", _unexpected
    )
    result = runner.invoke(app, ["agent", "configure", "claude-code"])

    assert result.exit_code != 0
    assert "agent 'claude-code' on host" in result.output
    assert "Claude configuration must be an object" in result.output
    assert "Claude global settings configured" not in result.output


@pytest.mark.parametrize("failure", ["returned error", "raised error"])
def test_claude_configure_errors_do_not_report_success(
    fleet_dir, monkeypatch, failure: str
) -> None:
    _add_claude_agent(fleet_dir)

    class _Backend:
        @staticmethod
        def configure_agent(**_kwargs):
            if failure == "raised error":
                raise LifecycleError("render failed")
            return False, "render failed"

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.resolve_lifecycle_backend",
        lambda _os_family: _Backend(),
    )
    result = runner.invoke(app, ["agent", "configure", "claude-code"])

    assert result.exit_code != 0
    assert "agent 'claude-code' on host" in result.output
    assert "Claude settings configure failed: render failed" in result.output
    assert "Claude global settings configured" not in result.output


@pytest.mark.parametrize("verb", ["sync", "configure"])
def test_incomplete_claude_install_rejects_cli_reconcile(
    fleet_dir, monkeypatch, verb: str
) -> None:
    _add_claude_agent(fleet_dir)
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["claude-code"].update(
        {"status": "failed", "installed_at": None}
    )
    hosts_path.write_text(json.dumps(hosts, indent=2))

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("canonical sync must not run for an incomplete install")
        ),
    )
    result = runner.invoke(app, ["agent", verb, "claude-code"])

    assert result.exit_code != 0
    assert incomplete_install_message("claude", verb) in result.output

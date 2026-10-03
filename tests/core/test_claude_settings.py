"""Bounded, global-only Claude Code settings contracts (#997)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from clawrium.core import lifecycle, lifecycle_canonical
from clawrium.core.lifecycle_canonical import CanonicalSyncError
from clawrium.core.render import (
    AgentConfigError,
    parse_claude_settings,
    render_claude_settings,
)
from clawrium.core.render_diff import FileDiff


def _claude_host(*, os_family: str = "linux", settings: object = None) -> dict:
    config = settings if settings is not None else {}
    return {
        "hostname": "claude-host",
        "key_id": "claude-host-key",
        "os_family": os_family,
        "agents": {
            "claude-code": {
                "type": "claude",
                "agent_name": "claude-code",
                "status": "installed",
                "installed_at": "2026-10-03T00:00:00+00:00",
                "config": config,
            }
        },
    }


def _unexpected(*_args, **_kwargs):
    raise AssertionError("unexpected daemon, provider, or secret transport")


def _playbook_task(playbook: dict, name: str) -> dict:
    return next(task for task in playbook[0]["tasks"] if task["name"] == name)


def test_render_claude_settings_is_typed_deterministic_and_global_only():
    settings = parse_claude_settings(
        {
            "model": "claude-sonnet-4-5",
            "effortLevel": "high",
            "permissions": {
                "ask": ["Bash(git status:*)"],
                "deny": ["Read(.env)"],
                "additionalDirectories": ["/srv/repo", "/tmp/scratch"],
            },
        }
    )

    rendered = render_claude_settings(settings)

    assert set(rendered.files) == {".claude/settings.json"}
    assert json.loads(rendered.files[".claude/settings.json"]) == {
        "model": "claude-sonnet-4-5",
        "effortLevel": "high",
        "permissions": {
            "ask": ["Bash(git status:*)"],
            "deny": ["Read(.env)"],
            "additionalDirectories": ["/srv/repo", "/tmp/scratch"],
        },
    }
    assert rendered == render_claude_settings(settings)
    assert ".claude/settings.local.json" not in rendered.files


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ({"apiKey": "secret"}, "unsupported key"),
        ({"oauthToken": "secret"}, "unsupported key"),
        ({"session": "secret"}, "unsupported key"),
        ({"model": 4}, "model must be a string"),
        ({"effortLevel": None}, "effortLevel must be a string"),
        ({"permissions": ["Read"]}, "permissions must be an object"),
        ({"permissions": {"ask": "Read"}}, "permissions.ask must be a list"),
        (
            {"permissions": {"additionalDirectories": ["/ok", 3]}},
            "permissions.additionalDirectories must be a list",
        ),
        ({"permissions": {"allow": ["Read"]}}, "unsupported key"),
    ],
)
def test_claude_settings_rejects_passthrough_secrets_and_invalid_types(raw, error):
    with pytest.raises(AgentConfigError, match=error):
        parse_claude_settings(raw)


def test_configure_renders_only_validated_settings_without_daemon_or_secrets(
    monkeypatch, tmp_path: Path
):
    host = _claude_host(settings={"model": "old-model"})
    # This simulated legacy/tampered value must be discarded rather than merged
    # into hosts.json by the bounded Claude configure path.
    host["agents"]["claude-code"]["config"]["oauthToken"] = "not-allowed"
    captured: dict[str, object] = {}

    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _: tmp_path / "key")
    monkeypatch.setattr(lifecycle, "_get_logs_dir", lambda: tmp_path / "logs")

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="successful")

    def fake_update(hostname, updater):
        assert hostname == "claude-host"
        updater(host)
        return True

    monkeypatch.setattr(lifecycle.ansible_runner, "run", fake_run)
    monkeypatch.setattr(lifecycle, "update_host", fake_update)
    monkeypatch.setattr(lifecycle, "get_instance_secrets", _unexpected)
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _unexpected)

    ok, error = lifecycle.configure_agent(
        "claude-host",
        "claude",
        {
            "model": "claude-opus-4-6",
            "permissions": {"deny": ["Read(.env)"]},
        },
        agent_name="claude-code",
    )

    assert (ok, error) == (True, None)
    assert str(captured["playbook"]).endswith("claude/playbooks/configure.yaml")
    inventory = captured["inventory"]
    assert inventory["all"]["vars"] == {
        "agent_name": "claude-code",
        "agent_type": "claude",
        "prerendered_claude_settings_json": (
            "{\n"
            '  "model": "claude-opus-4-6",\n'
            '  "permissions": {\n'
            '    "deny": [\n'
            '      "Read(.env)"\n'
            "    ]\n"
            "  }\n"
            "}\n"
        ),
    }
    assert host["agents"]["claude-code"]["config"] == {
        "model": "claude-opus-4-6",
        "permissions": {"deny": ["Read(.env)"]},
    }


def test_configure_rejects_unknown_claude_settings_before_ansible(monkeypatch):
    host = _claude_host()
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle.ansible_runner, "run", _unexpected)
    monkeypatch.setattr(lifecycle, "update_host", _unexpected)

    ok, error = lifecycle.configure_agent(
        "claude-host",
        "claude",
        {"apiKey": "must-not-pass-through"},
        agent_name="claude-code",
    )

    assert ok is False
    assert "unsupported key" in (error or "")


def test_canonical_sync_writes_only_claude_global_settings_without_restart(
    monkeypatch,
):
    host = _claude_host(
        os_family="darwin",
        settings={"permissions": {"additionalDirectories": ["/Users/shared"]}},
    )
    record = host["agents"]["claude-code"]
    captured: dict[str, object] = {}
    client = MagicMock()

    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "build_render_inputs", _unexpected)
    monkeypatch.setattr(lifecycle_canonical, "_restart_unit", _unexpected)
    monkeypatch.setattr(lifecycle_canonical, "_verify_health", _unexpected)

    def fake_diff_files(**kwargs):
        captured["diff_host"] = kwargs["host"]
        assert kwargs["rendered_files"].keys() == {".claude/settings.json"}
        body = kwargs["rendered_files"][".claude/settings.json"]
        return [
            FileDiff(
                path=".claude/settings.json",
                remote_path="/Users/claude-code/.claude/settings.json",
                remote_present=False,
                remote_body="",
                rendered_body=body,
                unified_diff="--- host\n+++ rendered\n",
            )
        ]

    monkeypatch.setattr(lifecycle_canonical, "diff_files", fake_diff_files)
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_settings_directory",
        lambda _client, **kwargs: captured.setdefault("directory", kwargs),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda _client, **kwargs: captured.setdefault("write", kwargs),
    )

    result = lifecycle_canonical.sync_agent_canonical("claude-code")

    assert result.success is True
    assert result.files_written == (".claude/settings.json",)
    assert captured["diff_host"]["os_family"] == "darwin"
    assert captured["directory"]["os_family"] == "darwin"
    assert (
        captured["write"]["remote_path"] == "/Users/claude-code/.claude/settings.json"
    )
    assert client.close.call_count == 1


def test_canonical_sync_rejects_secret_passthrough_before_remote_io(monkeypatch):
    host = _claude_host(settings={"permissions": {"oauthToken": ["secret"]}})
    record = host["agents"]["claude-code"]
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "diff_files", _unexpected)
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", _unexpected)

    with pytest.raises(CanonicalSyncError, match="unsupported key"):
        lifecycle_canonical.sync_agent_canonical("claude-code")


@pytest.mark.parametrize(
    ("filename", "expected_home", "expected_group", "guard"),
    [
        (
            "configure.yaml",
            "/home/{{ agent_name }}/.claude",
            "{{ agent_name }}",
            'ansible_os_family == "Darwin"',
        ),
        (
            "configure_macos.yaml",
            "/Users/{{ agent_name }}/.claude",
            "staff",
            'ansible_os_family != "Darwin"',
        ),
    ],
)
def test_claude_settings_playbooks_only_write_global_settings(
    filename, expected_home, expected_group, guard
):
    path = Path("src/clawrium/platform/registry/claude/playbooks") / filename
    playbook = yaml.safe_load(path.read_text())
    tasks = playbook[0]["tasks"]
    serialized = json.dumps(playbook)

    assert tasks[0]["when"] == guard
    directory = _playbook_task(
        playbook, "Create dedicated Claude global settings directory"
    )["ansible.builtin.file"]
    settings = _playbook_task(playbook, "Write bounded global Claude settings")[
        "ansible.builtin.copy"
    ]
    assert directory == {
        "path": expected_home,
        "state": "directory",
        "owner": "{{ agent_name }}",
        "group": expected_group,
        "mode": "0700",
    }
    assert settings == {
        "content": "{{ prerendered_claude_settings_json }}",
        "dest": f"{expected_home}/settings.json",
        "owner": "{{ agent_name }}",
        "group": expected_group,
        "mode": "0600",
    }
    assert "ansible_user_dir" not in serialized
    assert "settings.local.json" not in serialized
    assert "ansible.builtin.command" not in serialized
    assert "ansible.builtin.shell" not in serialized
    assert "systemctl" not in serialized
    assert "launchctl" not in serialized

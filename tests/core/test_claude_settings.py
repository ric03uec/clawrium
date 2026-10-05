"""Native Claude Code configuration contracts (#1021)."""

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
    render_claude_native_files,
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
    def walk(tasks: list[dict]):
        for task in tasks:
            yield task
            for key in ("block", "rescue"):
                nested = task.get(key)
                if isinstance(nested, list):
                    yield from walk(nested)

    return next(task for task in walk(playbook[0]["tasks"]) if task["name"] == name)


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


def test_render_claude_native_files_emits_onboarding_marker_and_settings():
    settings = parse_claude_settings({"model": "claude-opus-4-6"})

    rendered = render_claude_native_files(settings)

    assert set(rendered.files) == {".claude/settings.json", ".claude.json"}
    assert json.loads(rendered.files[".claude.json"]) == {
        "hasCompletedOnboarding": True
    }
    assert json.loads(rendered.files[".claude/settings.json"]) == {
        "model": "claude-opus-4-6"
    }
    assert rendered == render_claude_native_files(settings)
    assert ".claude/.credentials.json" not in rendered.files


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


def test_configure_renders_native_files_without_daemon_or_secrets(
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
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _unexpected)
    monkeypatch.setattr(
        "clawrium.core.claude_credentials.get_active_claude_credential",
        lambda _: ("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test-value"),
    )

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
    variables = captured["inventory"]["all"]["vars"]
    assert variables["agent_name"] == "claude-code"
    assert variables["agent_type"] == "claude"
    assert variables["prerendered_claude_settings_json"] == (
        "{\n"
        '  "model": "claude-opus-4-6",\n'
        '  "permissions": {\n'
        '    "deny": [\n'
        '      "Read(.env)"\n'
        "    ]\n"
        "  }\n"
        "}\n"
    )
    assert variables["prerendered_claude_onboarding_json"] == (
        "{\n"
        '  "hasCompletedOnboarding": true\n'
        "}\n"
    )
    assert json.loads(variables["claude_oauth_credentials"]) == {
        "claudeAiOauth": {"accessToken": "oauth-test-value"}
    }
    assert "claude_credential_key" not in variables
    assert "claude_credential_value" not in variables
    assert host["agents"]["claude-code"]["config"] == {
        "model": "claude-opus-4-6",
        "permissions": {"deny": ["Read(.env)"]},
    }


def test_configure_transports_api_key_without_oauth_inventory_value(
    monkeypatch, tmp_path: Path
):
    host = _claude_host()
    captured: dict[str, object] = {}
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _: tmp_path / "key")
    monkeypatch.setattr(lifecycle, "_get_logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(
        lifecycle.ansible_runner,
        "run",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(status="successful"),
    )
    monkeypatch.setattr(lifecycle, "update_host", lambda *_args: True)
    monkeypatch.setattr(
        "clawrium.core.claude_credentials.get_active_claude_credential",
        lambda _: ("ANTHROPIC_API_KEY", "api-value"),
    )

    ok, error = lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    )

    assert (ok, error) == (True, None)
    variables = captured["inventory"]["all"]["vars"]
    assert variables["claude_credential_mode"] == "api_key"
    assert variables["claude_api_key_environment"] == "export ANTHROPIC_API_KEY=api-value\n"
    assert "claude_oauth_credentials" not in variables


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


def test_canonical_sync_writes_native_files_and_oauth_credentials(monkeypatch):
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
        assert set(kwargs["rendered_files"]) == {
            ".claude/settings.json",
            ".claude.json",
        }
        bodies = kwargs["rendered_files"]
        return [
            FileDiff(
                path=".claude/settings.json",
                remote_path="/Users/claude-code/.claude/settings.json",
                remote_present=False,
                remote_body="",
                rendered_body=bodies[".claude/settings.json"],
                unified_diff="--- host\n+++ rendered\n",
            ),
            FileDiff(
                path=".claude.json",
                remote_path="/Users/claude-code/.claude.json",
                remote_present=False,
                remote_body="",
                rendered_body=bodies[".claude.json"],
                unified_diff="--- host\n+++ rendered\n",
            ),
        ]

    monkeypatch.setattr(lifecycle_canonical, "diff_files", fake_diff_files)
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_validate_claude_credential_activation",
        lambda _: ("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test-value"),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_settings_directory",
        lambda _client, **kwargs: captured.setdefault("directory", kwargs),
    )

    def fake_atomic_write(_client, **kwargs):
        captured.setdefault("writes", []).append(kwargs)

    monkeypatch.setattr(lifecycle_canonical, "_atomic_write", fake_atomic_write)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_stale_claude_credential_artifacts",
        lambda *_args, **kwargs: captured.setdefault("stale_cleanup", []).append(kwargs),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_retired_claude_artifacts",
        lambda *_args, **kwargs: captured.setdefault(
            "retired_cleanup", []
        ).append(kwargs),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_promote_staged_claude_credential_artifact",
        lambda *_args, **kwargs: captured.setdefault("promotion", []).append(kwargs),
    )

    result = lifecycle_canonical.sync_agent_canonical("claude-code")

    assert result.success is True
    # Credentials write is deliberately not reported in result files or diffs;
    # only the non-secret native files are observable.
    assert set(result.files_written) == {".claude/settings.json", ".claude.json"}
    assert all(".credentials.json" not in diff.path for diff in result.diffs)
    assert captured["diff_host"]["os_family"] == "darwin"
    assert captured["directory"]["os_family"] == "darwin"
    assert [write["remote_path"] for write in captured["writes"]] == [
        "/Users/claude-code/.claude/settings.json",
        "/Users/claude-code/.claude.json",
        "/Users/claude-code/.claude/.credentials.json.clawrium-stage",
    ]
    # The stale credential artifact is cleaned and verified before the
    # unrelated retired profile hook is removed.
    assert captured["stale_cleanup"] == [
        {
            "agent_name": "claude-code",
            "selected_path": "/Users/claude-code/.claude/.credentials.json.clawrium-stage",
            "stale_paths": ("/Users/claude-code/.claude/clawrium-credentials.env",),
        }
    ]
    assert captured["promotion"] == [
        {
            "agent_name": "claude-code",
            "staged_path": "/Users/claude-code/.claude/.credentials.json.clawrium-stage",
            "destination_path": "/Users/claude-code/.claude/.credentials.json",
        }
    ]
    assert captured["retired_cleanup"] == [
        {
            "agent_name": "claude-code",
            "retired_paths": ("/Users/claude-code/.profile.d/clawrium-claude.sh",),
        }
    ]
    assert json.loads(captured["writes"][-1]["body"]) == {
        "claudeAiOauth": {"accessToken": "oauth-test-value"}
    }
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
            None,
        ),
        (
            "configure_macos.yaml",
            "/Users/{{ agent_name }}/.claude",
            "staff",
            'ansible_os_family != "Darwin"',
        ),
    ],
)
def test_claude_settings_playbooks_only_write_native_files(
    filename, expected_home, expected_group, guard
):
    path = Path("src/clawrium/platform/registry/claude/playbooks") / filename
    playbook = yaml.safe_load(path.read_text())
    tasks = playbook[0]["tasks"]
    serialized = json.dumps(playbook)

    # Dispatcher-only OS fork invariant: the Linux configure playbook
    # relies entirely on ``core.playbook_resolver`` for OS selection and
    # carries no ``ansible_os_family`` branch. The macOS sibling keeps
    # the task-0 non-Darwin fail-fast guard, mirroring the
    # install_macos.yaml precedent.
    if guard is None:
        assert "ansible_os_family" not in serialized
    else:
        assert tasks[0]["when"] == guard
    directory = _playbook_task(
        playbook, "Create dedicated Claude global settings directory"
    )["ansible.builtin.file"]
    settings = _playbook_task(playbook, "Write bounded global Claude settings")[
        "ansible.builtin.copy"
    ]
    onboarding = _playbook_task(
        playbook, "Write Claude first-run onboarding marker"
    )["ansible.builtin.copy"]
    home_root = expected_home.rsplit("/", 1)[0]
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
    assert onboarding == {
        "content": "{{ prerendered_claude_onboarding_json }}",
        "dest": f"{home_root}/.claude.json",
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
    api_environment = _playbook_task(
        playbook, "Atomically replace Claude API-key environment"
    )["ansible.builtin.copy"]
    assert api_environment == {
        "content": "{{ claude_api_key_environment }}",
        "dest": f"{expected_home}/clawrium-credentials.env",
        "owner": "{{ agent_name }}",
        "group": expected_group,
        "mode": "0600",
        "unsafe_writes": False,
    }
    assert _playbook_task(playbook, "Atomically replace Claude API-key environment")[
        "no_log"
    ] is True
    assert _playbook_task(playbook, "Atomically replace Claude API-key environment")[
        "diff"
    ] is False
    assert "clawrium-claude.sh" in serialized

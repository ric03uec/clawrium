"""Native Claude Code credential rendering contracts (#1021)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from clawrium.core import lifecycle, lifecycle_canonical
from clawrium.core.claude_credentials import configure_claude_credentials
from clawrium.core.render import (
    AgentConfigError,
    render_claude_api_key_environment,
    render_claude_oauth_credentials,
)
from clawrium.core.render_diff import FileDiff


_SECRET = "activation-secret-value"


def _host(*, os_family: str = "linux") -> dict:
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
                "config": {"model": "claude-sonnet-4-5"},
            }
        },
    }


def _seed_host(config_dir: Path, *, os_family: str = "linux") -> dict:
    config_dir.mkdir(parents=True, exist_ok=True)
    host = _host(os_family=os_family)
    (config_dir / "hosts.json").write_text(json.dumps([host]))
    return host


def _task(playbook: dict, name: str) -> dict:
    def walk(tasks: list[dict]):
        for task in tasks:
            yield task
            for key in ("block", "rescue"):
                nested = task.get(key)
                if isinstance(nested, list):
                    yield from walk(nested)

    return next(task for task in walk(playbook[0]["tasks"]) if task["name"] == name)


def _unexpected(*_args, **_kwargs):
    raise AssertionError("unexpected daemon or command transport")


def test_render_claude_oauth_credentials_shape_matches_native_contract():
    body = render_claude_oauth_credentials(_SECRET)
    assert json.loads(body) == {"claudeAiOauth": {"accessToken": _SECRET}}
    assert body.endswith("\n")


def test_render_claude_oauth_credentials_rejects_empty_and_non_string():
    with pytest.raises(AgentConfigError):
        render_claude_oauth_credentials("")
    with pytest.raises(AgentConfigError):
        render_claude_oauth_credentials(None)  # type: ignore[arg-type]


def test_render_claude_api_key_environment_is_shell_safe():
    body = render_claude_api_key_environment("api-$value-'quoted'")

    assert body == "export ANTHROPIC_API_KEY='api-$value-'\"'\"'quoted'\"'\"''\n"
    assert body.count("ANTHROPIC_API_KEY") == 1
    with pytest.raises(AgentConfigError):
        render_claude_api_key_environment("")


def test_configure_transports_oauth_body_in_no_log_inventory(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    host = _seed_host(isolated_config)
    configure_claude_credentials("claude-code", oauth_token=_SECRET)
    captured: dict[str, object] = {}

    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _: tmp_path / "key")
    monkeypatch.setattr(lifecycle, "_get_logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(
        lifecycle, "update_host", lambda _hostname, updater: updater(host)
    )

    def fake_run(**kwargs):
        captured.update(kwargs)
        private_data_dir = Path(kwargs["private_data_dir"])
        # Simulate every documented and undocumented runner location: cleanup
        # must remove the whole private directory, not merely known children.
        for relative in (
            "artifacts/job_events/event.json",
            "inventory/hosts.json",
            "env/vars",
            "project/cache",
        ):
            path = private_data_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_SECRET)
        return SimpleNamespace(status="successful")

    monkeypatch.setattr(lifecycle.ansible_runner, "run", fake_run)
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _unexpected)

    assert lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    ) == (True, None)

    inventory = captured["inventory"]
    variables = inventory["all"]["vars"]
    assert json.loads(variables["claude_oauth_credentials"]) == {
        "claudeAiOauth": {"accessToken": _SECRET}
    }
    assert "claude_credential_key" not in variables
    assert "claude_credential_value" not in variables
    assert _SECRET not in json.dumps(host)
    assert str(captured["playbook"]).endswith(
        "claude/playbooks/configure.yaml"
    )
    assert "claude" not in str(captured.get("envvars", {})).lower()
    assert not Path(captured["private_data_dir"]).exists()


def test_configure_transports_only_api_key_environment_in_no_log_inventory(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    host = _seed_host(isolated_config)
    configure_claude_credentials("claude-code", anthropic_api_key=_SECRET)
    captured: dict[str, object] = {}
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _: tmp_path / "key")
    monkeypatch.setattr(lifecycle, "_get_logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(
        lifecycle.ansible_runner,
        "run",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(status="successful"),
    )

    assert lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    ) == (True, None)

    variables = captured["inventory"]["all"]["vars"]
    assert variables["claude_credential_mode"] == "api_key"
    assert variables["claude_api_key_environment"] == (
        f"export ANTHROPIC_API_KEY={_SECRET}\n"
    )
    assert "claude_oauth_credentials" not in variables
    assert _SECRET not in json.dumps(host)


def test_configure_refuses_missing_credential_before_remote_transport(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle.ansible_runner, "run", _unexpected)

    ok, error = lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    )

    assert ok is False
    assert "credential activation failed" in (error or "")
    assert _SECRET not in (error or "")


def test_configure_runner_exception_is_redacted_and_removes_artifacts(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    host = _seed_host(isolated_config)
    configure_claude_credentials("claude-code", oauth_token=_SECRET)
    captured: dict[str, object] = {}
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _: tmp_path / "key")
    monkeypatch.setattr(lifecycle, "_get_logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(lifecycle, "update_host", _unexpected)

    def failing_run(**kwargs):
        captured.update(kwargs)
        private_data_dir = Path(kwargs["private_data_dir"])
        artifact = private_data_dir / "command.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(_SECRET)
        raise RuntimeError(f"runner failed with {_SECRET}")

    monkeypatch.setattr(lifecycle.ansible_runner, "run", failing_run)

    ok, error = lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    )

    assert (ok, error) == (False, "Claude settings configure failed")
    assert _SECRET not in (error or "")
    assert not Path(captured["private_data_dir"]).exists()


@pytest.mark.parametrize(
    ("filename", "home", "group", "guard"),
    [
        (
            "configure.yaml",
            "/home/{{ agent_name }}",
            "{{ agent_name }}",
            None,
        ),
        (
            "configure_macos.yaml",
            "/Users/{{ agent_name }}",
            "staff",
            'ansible_os_family != "Darwin"',
        ),
    ],
)
def test_activation_playbooks_write_native_credentials_privately_and_no_log(
    filename: str, home: str, group: str, guard: str | None
):
    playbook = yaml.safe_load(
        (Path("src/clawrium/platform/registry/claude/playbooks") / filename).read_text()
    )
    serialized = json.dumps(playbook)

    # The Linux configure playbook defers OS selection to
    # ``core.playbook_resolver`` and carries no ``ansible_os_family``
    # branch. The macOS sibling keeps the task-0 non-Darwin fail-fast
    # guard.
    if guard is None:
        assert "ansible_os_family" not in serialized
    else:
        assert playbook[0]["tasks"][0]["when"] == guard
    assert (
        _task(playbook, "Validate rendered Claude OAuth credential body")["no_log"]
        is True
    )
    credential_task = _task(
        playbook, "Atomically replace native Claude OAuth credentials"
    )
    credential = credential_task["ansible.builtin.copy"]
    assert credential_task["no_log"] is True
    # Defense-in-depth: ``diff: false`` suppresses the Ansible unified
    # diff of the rendered OAuth body even if a verbose runner config
    # would otherwise emit it alongside no_log's redaction (#1021 R3 S1).
    assert credential_task["diff"] is False
    assert credential == {
        "content": "{{ claude_oauth_credentials }}",
        "dest": f"{home}/.claude/.credentials.json",
        "owner": "{{ agent_name }}",
        "group": group,
        "mode": "0600",
        "unsafe_writes": False,
    }
    api_key_task = _task(playbook, "Atomically replace Claude API-key environment")
    assert api_key_task["no_log"] is True
    assert api_key_task["diff"] is False
    assert api_key_task["ansible.builtin.copy"] == {
        "content": "{{ claude_api_key_environment }}",
        "dest": f"{home}/.claude/clawrium-credentials.env",
        "owner": "{{ agent_name }}",
        "group": group,
        "mode": "0600",
        "unsafe_writes": False,
    }
    assert "ansible.builtin.command" not in serialized
    assert "ansible.builtin.shell" not in serialized
    assert "systemctl" not in serialized
    assert "launchctl" not in serialized
    assert "ansible_user_dir" not in serialized

    # Each mode snapshots its prior selected artifact before replacement.
    # Stale cleanup is verified; a failure restores that snapshot (or removes
    # a newly introduced selected artifact when no prior state existed).
    for name, transition_name, backup_name, stale_path, selected_path in (
        (
            "Remove stale Claude API-key environment",
            "Replace native Claude OAuth credentials exclusively",
            "Back up native Claude OAuth credentials before replacement",
            f"{home}/.claude/clawrium-credentials.env",
            f"{home}/.claude/.credentials.json",
        ),
        (
            "Remove stale native Claude OAuth credentials",
            "Replace Claude API-key environment exclusively",
            "Back up Claude API-key environment before replacement",
            f"{home}/.claude/.credentials.json",
            f"{home}/.claude/clawrium-credentials.env",
        ),
    ):
        backup = _task(playbook, backup_name)
        assert backup["no_log"] is True
        assert backup["diff"] is False
        assert backup["ansible.builtin.copy"]["remote_src"] is True
        assert backup["ansible.builtin.copy"]["dest"] == (
            f"{selected_path}.clawrium-backup"
        )
        cleanup = _task(playbook, name)
        assert cleanup["ansible.builtin.file"] == {
            "path": stale_path,
            "state": "absent",
        }
        verify_name = (
            "Verify stale Claude API-key environment is absent"
            if name == "Remove stale Claude API-key environment"
            else "Verify stale native Claude OAuth credentials are absent"
        )
        assert _task(playbook, verify_name)["ansible.builtin.stat"] == {
            "path": stale_path
        }
        transition = _task(playbook, transition_name)
        assert backup in transition["block"]
        assert cleanup in transition["block"]
        assert transition["block"][-1]["ansible.builtin.file"] == {
            "path": f"{selected_path}.clawrium-backup",
            "state": "absent",
        }
        assert transition["rescue"][0]["ansible.builtin.copy"] == {
            "remote_src": True,
            "src": f"{selected_path}.clawrium-backup",
            "dest": selected_path,
            "owner": "{{ agent_name }}",
            "group": group,
            "mode": "0600",
            "unsafe_writes": False,
        }
        assert transition["rescue"][0]["no_log"] is True
        assert transition["rescue"][1]["ansible.builtin.file"] == {
            "path": selected_path,
            "state": "absent",
        }
        assert transition["rescue"][2]["ansible.builtin.file"] == {
            "path": f"{selected_path}.clawrium-backup",
            "state": "absent",
        }
    assert _task(playbook, "Remove retired Claude profile hook")[
        "ansible.builtin.file"
    ] == {"path": f"{home}/.profile.d/clawrium-claude.sh", "state": "absent"}


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_sync_writes_native_credentials_file_with_exactly_one_json_body(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, os_family: str
):
    host = _seed_host(isolated_config, os_family=os_family)
    record = host["agents"]["claude-code"]
    configure_claude_credentials("claude-code", oauth_token="oauth-switch-token")
    writes: list[dict] = []
    events: list[tuple[str, str]] = []
    client = MagicMock()

    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )

    def fake_diff_files(**kwargs):
        rendered = kwargs["rendered_files"]
        assert set(rendered) == {".claude/settings.json", ".claude.json"}
        for body in rendered.values():
            assert "oauth-switch-token" not in body
        return [
            FileDiff(
                path=".claude/settings.json",
                remote_path=(
                    f"{'/Users' if os_family == 'darwin' else '/home'}"
                    "/claude-code/.claude/settings.json"
                ),
                remote_present=False,
                remote_body="",
                rendered_body=rendered[".claude/settings.json"],
                unified_diff="settings only",
            ),
            FileDiff(
                path=".claude.json",
                remote_path=(
                    f"{'/Users' if os_family == 'darwin' else '/home'}"
                    "/claude-code/.claude.json"
                ),
                remote_present=False,
                remote_body="",
                rendered_body=rendered[".claude.json"],
                unified_diff="onboarding",
            ),
        ]

    monkeypatch.setattr(lifecycle_canonical, "diff_files", fake_diff_files)
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_settings_directory",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda _client, **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_stale_claude_credential_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_retired_claude_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_promote_staged_claude_credential_artifact",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(lifecycle_canonical, "_restart_unit", _unexpected)
    monkeypatch.setattr(lifecycle_canonical, "_verify_health", _unexpected)

    result = lifecycle_canonical.sync_agent_canonical(
        "claude-code", on_event=lambda stage, message: events.append((stage, message))
    )
    credential_write = next(
        write
        for write in writes
        if write["remote_path"].endswith(".credentials.json.clawrium-stage")
    )
    assert json.loads(credential_write["body"]) == {
        "claudeAiOauth": {"accessToken": "oauth-switch-token"}
    }
    assert all("oauth-switch-token" not in message for _, message in events)
    assert all(
        "oauth-switch-token" not in diff.rendered_body for diff in result.diffs
    )
    assert all(
        ".credentials.json" not in diff.path for diff in result.diffs
    )
    assert set(result.files_written) == {".claude/settings.json", ".claude.json"}
    assert all(write["host"]["os_family"] == os_family for write in writes)


def test_sync_writes_private_api_key_environment_and_cleans_oauth(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    configure_claude_credentials("claude-code", anthropic_api_key=_SECRET)
    writes: list[dict] = []
    stale_cleanups: list[dict] = []
    client = MagicMock()
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "diff_files", lambda **_: [])
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_settings_directory",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda _client, **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_stale_claude_credential_artifacts",
        lambda _client, **kwargs: stale_cleanups.append(kwargs),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_retired_claude_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_promote_staged_claude_credential_artifact",
        lambda *_args, **_kwargs: None,
    )

    lifecycle_canonical.sync_agent_canonical("claude-code")

    home = "/home/claude-code"
    assert [write["remote_path"] for write in writes] == [
        f"{home}/.claude/clawrium-credentials.env.clawrium-stage"
    ]
    assert writes[0]["body"] == f"export ANTHROPIC_API_KEY={_SECRET}\n"
    assert stale_cleanups == [
        {
            "agent_name": "claude-code",
            "selected_path": f"{home}/.claude/clawrium-credentials.env.clawrium-stage",
            "stale_paths": (f"{home}/.claude/.credentials.json",),
        }
    ]


def test_sync_writes_credentials_even_when_native_files_unchanged(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    configure_claude_credentials("claude-code", oauth_token="oauth-rotation-token")
    writes: list[dict] = []
    events: list[tuple[str, str]] = []
    client = MagicMock()
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "diff_files",
        lambda **_: [
            FileDiff(
                path=".claude/settings.json",
                remote_path="/home/claude-code/.claude/settings.json",
                remote_present=True,
                remote_body="same",
                rendered_body="same",
                unified_diff="",
            ),
            FileDiff(
                path=".claude.json",
                remote_path="/home/claude-code/.claude.json",
                remote_present=True,
                remote_body="same",
                rendered_body="same",
                unified_diff="",
            ),
        ],
    )
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_settings_directory",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda _client, **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_stale_claude_credential_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_retired_claude_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_promote_staged_claude_credential_artifact",
        lambda *_args, **_kwargs: None,
    )

    result = lifecycle_canonical.sync_agent_canonical(
        "claude-code", on_event=lambda stage, message: events.append((stage, message))
    )

    assert result.files_written == ()
    assert set(result.files_unchanged) == {".claude/settings.json", ".claude.json"}
    assert [write["remote_path"] for write in writes] == [
        "/home/claude-code/.claude/.credentials.json.clawrium-stage",
    ]
    assert json.loads(writes[-1]["body"]) == {
        "claudeAiOauth": {"accessToken": "oauth-rotation-token"}
    }
    assert all("oauth-rotation-token" not in message for _, message in events)
    client.close.assert_called_once_with()


@pytest.mark.parametrize("failure", ["directory", "credential"])
def test_sync_credential_write_failure_sanitizes_error(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, failure: str
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    configure_claude_credentials("claude-code", oauth_token=_SECRET)
    client = MagicMock()
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "diff_files", lambda **_: [])
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)

    if failure == "directory":
        monkeypatch.setattr(
            lifecycle_canonical,
            "_ensure_claude_settings_directory",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                lifecycle_canonical.CanonicalSyncError(
                    "/home/claude-code/.claude directory failed"
                )
            ),
        )
    else:
        monkeypatch.setattr(
            lifecycle_canonical,
            "_ensure_claude_settings_directory",
            lambda *_args, **_kwargs: None,
        )

        def fail_credential_write(_client, **kwargs):
            if kwargs["remote_path"].endswith(".credentials.json.clawrium-stage"):
                raise lifecycle_canonical.CanonicalSyncError(
                    f"{kwargs['remote_path']} write failed: {_SECRET}"
                )

        monkeypatch.setattr(lifecycle_canonical, "_atomic_write", fail_credential_write)

    with pytest.raises(lifecycle_canonical.CanonicalSyncError) as error:
        lifecycle_canonical.sync_agent_canonical(
            "claude-code",
            on_event=lambda stage, message: events.append((stage, message)),
        )

    assert str(error.value) == "Claude credential activation failed"
    assert _SECRET not in str(error.value)
    assert _SECRET not in repr(events)
    assert not any(stage == "sync" for stage, _ in events)
    client.close.assert_called_once_with()


def test_sync_resolves_selected_credential_once_for_the_entire_operation(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    calls: list[str] = []
    writes: list[dict] = []
    client = MagicMock()
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "diff_files", lambda **_: [])
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_settings_directory",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda _client, **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_stale_claude_credential_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_retired_claude_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_promote_staged_claude_credential_artifact",
        lambda *_args, **_kwargs: None,
    )

    def selected(agent_name: str) -> tuple[str, str]:
        calls.append(agent_name)
        return "CLAUDE_CODE_OAUTH_TOKEN", "one-selection-test-value"

    monkeypatch.setattr(
        "clawrium.core.claude_credentials.get_active_claude_credential", selected
    )

    lifecycle_canonical.sync_agent_canonical("claude-code")

    assert calls == ["claude-code"]
    assert json.loads(writes[-1]["body"]) == {
        "claudeAiOauth": {"accessToken": "one-selection-test-value"}
    }


def test_sync_dry_run_validates_selected_credential_before_remote_io(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "diff_files", lambda **_: [])
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", _unexpected)

    with pytest.raises(
        lifecycle_canonical.CanonicalSyncError, match="activation failed"
    ):
        lifecycle_canonical.sync_agent_canonical("claude-code", dry_run=True)


def test_sync_cleans_up_retired_artifacts_after_credential_write(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    configure_claude_credentials("claude-code", oauth_token="oauth-cleanup-token")
    call_log: list[tuple[str, object]] = []
    client = MagicMock()
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "diff_files", lambda **_: [])
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_settings_directory",
        lambda *_args, **_kwargs: None,
    )

    def recording_write(_client, **kwargs):
        call_log.append(("write", kwargs["remote_path"]))

    def recording_stale_cleanup(_client, **kwargs):
        call_log.append(
            ("stale_cleanup", (kwargs["selected_path"], kwargs["stale_paths"]))
        )

    def recording_retired_cleanup(_client, **kwargs):
        call_log.append(("retired_cleanup", kwargs["retired_paths"]))

    def recording_promotion(_client, **kwargs):
        call_log.append(
            ("promote", (kwargs["staged_path"], kwargs["destination_path"]))
        )

    monkeypatch.setattr(lifecycle_canonical, "_atomic_write", recording_write)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_stale_claude_credential_artifacts",
        recording_stale_cleanup,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_retired_claude_artifacts",
        recording_retired_cleanup,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_promote_staged_claude_credential_artifact",
        recording_promotion,
    )

    lifecycle_canonical.sync_agent_canonical("claude-code")

    assert call_log == [
        ("write", "/home/claude-code/.claude/.credentials.json.clawrium-stage"),
        (
            "stale_cleanup",
            (
                "/home/claude-code/.claude/.credentials.json.clawrium-stage",
                ("/home/claude-code/.claude/clawrium-credentials.env",),
            ),
        ),
        (
            "promote",
            (
                "/home/claude-code/.claude/.credentials.json.clawrium-stage",
                "/home/claude-code/.claude/.credentials.json",
            ),
        ),
        ("retired_cleanup", ("/home/claude-code/.profile.d/clawrium-claude.sh",)),
    ]


def test_sync_skips_cleanup_when_credential_write_fails(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    configure_claude_credentials("claude-code", oauth_token=_SECRET)
    cleanup_called: list[bool] = []
    client = MagicMock()
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda _: (host, "claude", record),
    )
    monkeypatch.setattr(lifecycle_canonical, "diff_files", lambda **_: [])
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_settings_directory",
        lambda *_args, **_kwargs: None,
    )

    def failing_write(_client, **kwargs):
        if kwargs["remote_path"].endswith(".credentials.json.clawrium-stage"):
            raise lifecycle_canonical.CanonicalSyncError(
                f"credential write failed: {_SECRET}"
            )

    monkeypatch.setattr(lifecycle_canonical, "_atomic_write", failing_write)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_stale_claude_credential_artifacts",
        lambda *_args, **_kwargs: cleanup_called.append(True),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_remove_retired_claude_artifacts",
        lambda *_args, **_kwargs: cleanup_called.append(True),
    )

    with pytest.raises(lifecycle_canonical.CanonicalSyncError):
        lifecycle_canonical.sync_agent_canonical("claude-code")

    # Cleanup must never run before a successful credentials write — a
    # mid-sync failure must leave the retired env file as the only
    # active credential path.
    assert cleanup_called == []


def test_remove_retired_claude_artifacts_runs_as_agent_and_is_idempotent():
    commands: list[str] = []

    class Chan:
        def recv_exit_status(self):
            return 0

    class Stream:
        channel = Chan()

        def read(self):
            return b""

    class Client:
        def exec_command(self, command, timeout=None):
            commands.append(command)
            return None, Stream(), Stream()

    lifecycle_canonical._remove_retired_claude_artifacts(
        Client(),
        agent_name="claude-code",
        retired_paths=(
            "/home/claude-code/.claude/clawrium-credentials.env",
            "/home/claude-code/.profile.d/clawrium-claude.sh",
        ),
    )

    assert commands == [
        "sudo -n -H -u claude-code rm -f "
        "/home/claude-code/.claude/clawrium-credentials.env",
        "sudo -n -H -u claude-code rm -f "
        "/home/claude-code/.profile.d/clawrium-claude.sh",
    ]


def test_remove_retired_claude_artifacts_raises_on_rm_failure():
    class Chan:
        def __init__(self, rc: int):
            self._rc = rc

        def recv_exit_status(self):
            return self._rc

    class Stream:
        def __init__(self, rc: int, body: bytes = b""):
            self.channel = Chan(rc)
            self._body = body

        def read(self):
            return self._body

    class Client:
        def exec_command(self, command, timeout=None):
            return None, Stream(1), Stream(1, b"permission denied")

    with pytest.raises(
        lifecycle_canonical.CanonicalSyncError, match="could not remove retired"
    ):
        lifecycle_canonical._remove_retired_claude_artifacts(
            Client(),
            agent_name="claude-code",
            retired_paths=(
                "/home/claude-code/.claude/clawrium-credentials.env",
            ),
        )


def test_stale_credential_cleanup_failure_rolls_back_selected_artifact(
    monkeypatch: pytest.MonkeyPatch,
):
    stale = "/home/claude-code/.claude/clawrium-credentials.env"
    selected = "/home/claude-code/.claude/.credentials.json"
    removals: list[tuple[str, ...]] = []

    def remove(_client, **kwargs):
        paths = kwargs["retired_paths"]
        removals.append(paths)
        if paths == (stale,):
            raise lifecycle_canonical.CanonicalSyncError("stale cleanup failed")

    monkeypatch.setattr(lifecycle_canonical, "_remove_retired_claude_artifacts", remove)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_assert_claude_artifact_absent",
        _unexpected,
    )

    with pytest.raises(
        lifecycle_canonical.CanonicalSyncError,
        match="could not activate Claude credentials exclusively",
    ):
        lifecycle_canonical._remove_stale_claude_credential_artifacts(
            MagicMock(),
            agent_name="claude-code",
            selected_path=selected,
            stale_paths=(stale,),
        )

    assert removals == [(stale,), (selected,)]


def test_stale_credential_transport_failure_removes_staged_artifact(
    monkeypatch: pytest.MonkeyPatch,
):
    stale = "/home/claude-code/.claude/clawrium-credentials.env"
    stage = "/home/claude-code/.claude/.credentials.json.clawrium-stage"
    removals: list[tuple[str, ...]] = []

    def remove(_client, **kwargs):
        paths = kwargs["retired_paths"]
        removals.append(paths)
        if paths == (stale,):
            raise RuntimeError("ssh transport disconnected")

    monkeypatch.setattr(lifecycle_canonical, "_remove_retired_claude_artifacts", remove)

    with pytest.raises(
        lifecycle_canonical.CanonicalSyncError,
        match="could not activate Claude credentials exclusively",
    ):
        lifecycle_canonical._remove_stale_claude_credential_artifacts(
            MagicMock(),
            agent_name="claude-code",
            selected_path=stage,
            stale_paths=(stale,),
        )

    assert removals == [(stale,), (stage,)]


@pytest.mark.parametrize(
    ("os_family", "expected_playbook_suffix"),
    [
        ("linux", "claude/playbooks/configure.yaml"),
        ("darwin", "claude/playbooks/configure_macos.yaml"),
    ],
)
def test_configure_routes_playbook_whose_cleanup_follows_credential_write(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    os_family: str,
    expected_playbook_suffix: str,
):
    """Lifecycle-boundary ordering check for the configure path.

    Goes through ``lifecycle.configure_agent`` so the real
    ``core.playbook_resolver`` picks the OS-specific playbook; then
    re-parses that routed playbook file and asserts the native OAuth
    credentials write precedes both retired-artifact removals. Covers
    #1021 Round 3 W1 (configure-side behavioral migration-order coverage
    for both OS playbooks).
    """
    host = _seed_host(isolated_config, os_family=os_family)
    configure_claude_credentials("claude-code", oauth_token=_SECRET)
    captured: dict[str, object] = {}

    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _: tmp_path / "key")
    monkeypatch.setattr(lifecycle, "_get_logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(
        lifecycle, "update_host", lambda _hostname, updater: updater(host)
    )

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="successful")

    monkeypatch.setattr(lifecycle.ansible_runner, "run", fake_run)
    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _unexpected)

    ok, error = lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    )

    assert (ok, error) == (True, None)
    routed_playbook_path = Path(str(captured["playbook"]))
    assert str(routed_playbook_path).endswith(expected_playbook_suffix)

    routed_playbook = yaml.safe_load(routed_playbook_path.read_text())
    task_names = [t["name"] for t in routed_playbook[0]["tasks"]]
    transition_idx = task_names.index("Replace native Claude OAuth credentials exclusively")
    hook_cleanup_idx = task_names.index("Remove retired Claude profile hook")
    transition = routed_playbook[0]["tasks"][transition_idx]
    transition_names = [t["name"] for t in transition["block"]]
    # The credential write and stale cleanup run in one rescue-capable block;
    # its private backup is removed on both success and rescue paths.
    assert transition_names.index("Atomically replace native Claude OAuth credentials") < (
        transition_names.index("Remove stale Claude API-key environment")
    )
    assert transition_idx < hook_cleanup_idx
    assert transition["rescue"][0]["ansible.builtin.copy"]["remote_src"] is True
    assert transition["rescue"][0]["no_log"] is True
    # And the credential-copy task itself is still no_log + diff: false.
    credential_task = _task(
        routed_playbook, "Atomically replace native Claude OAuth credentials"
    )
    assert credential_task["no_log"] is True
    assert credential_task["diff"] is False


def test_configure_forwards_full_oauth_document_to_playbook(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Configure must pass the full native document to the playbook extravar.

    Regression guard for the UAT finding: when the local credentials
    artifact contains the full native document (refreshToken /
    expiresAt / scopes / subscriptionType / rateLimitTier +
    trustedDeviceToken at root), those fields MUST round-trip into the
    rendered `claude_oauth_credentials` extravar body so Claude Code on
    the host does not report "Not logged in".
    """
    from clawrium.core.claude_credentials import import_claude_oauth_from_local_reader

    _seed_host(isolated_config)
    document = {
        "claudeAiOauth": {
            "accessToken": "oauth-full-" + _SECRET,
            "refreshToken": "refresh-" + _SECRET,
            "expiresAt": 1759600000000,
            "scopes": ["user:inference", "user:profile"],
            "subscriptionType": "max",
            "rateLimitTier": "max_20x",
        },
        "trustedDeviceToken": "trust-" + _SECRET,
    }

    def fake_reader() -> str:
        return json.dumps(document, separators=(",", ":"), sort_keys=True)

    import_claude_oauth_from_local_reader("claude-code", reader=fake_reader)

    captured: dict[str, object] = {}
    monkeypatch.setattr(lifecycle, "get_host", lambda _: _host())
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _: tmp_path / "key")
    monkeypatch.setattr(lifecycle, "_get_logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(
        lifecycle, "update_host", lambda _hostname, updater: updater(_host())
    )
    monkeypatch.setattr(
        lifecycle.ansible_runner,
        "run",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(status="successful"),
    )

    assert lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    ) == (True, None)

    forwarded = json.loads(
        captured["inventory"]["all"]["vars"]["claude_oauth_credentials"]
    )
    # Every known native field round-trips.
    assert forwarded == document

"""Remote Claude credential activation contracts (#998)."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from clawrium.core import agent_shell, lifecycle, lifecycle_canonical
from clawrium.core.claude_credentials import configure_claude_credentials
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
    return next(task for task in playbook[0]["tasks"] if task["name"] == name)


@pytest.mark.parametrize(
    ("os_family", "credential_kwargs", "active_key", "inactive_key", "suffix"),
    [
        (
            "linux",
            {"oauth_token": _SECRET},
            "CLAUDE_CODE_OAUTH_TOKEN",
            "ANTHROPIC_API_KEY",
            "",
        ),
        (
            "darwin",
            {"anthropic_api_key": _SECRET},
            "ANTHROPIC_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "_macos",
        ),
    ],
)
def test_configure_transports_only_active_secret_in_no_log_inventory(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    os_family: str,
    credential_kwargs: dict[str, str],
    active_key: str,
    inactive_key: str,
    suffix: str,
):
    host = _seed_host(isolated_config, os_family=os_family)
    configure_claude_credentials("claude-code", **credential_kwargs)
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
    assert variables["claude_credential_key"] == active_key
    assert variables["claude_credential_value"] == _SECRET
    assert inactive_key not in variables
    assert _SECRET not in json.dumps(host)
    assert str(captured["playbook"]).endswith(
        f"claude/playbooks/configure{suffix}.yaml"
    )
    assert "claude" not in str(captured.get("envvars", {})).lower()
    assert not Path(captured["private_data_dir"]).exists()


def _unexpected(*_args, **_kwargs):
    raise AssertionError("unexpected daemon or command transport")


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


def test_configure_post_credential_playbook_error_is_sanitized(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    configure_claude_credentials("claude-code", anthropic_api_key=_SECRET)
    controller_path = "/controller/private/claude-playbook.yaml"
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(
        "clawrium.core.playbook_resolver.resolve_agent_playbook",
        lambda *_args: (_ for _ in ()).throw(FileNotFoundError(controller_path)),
    )
    monkeypatch.setattr(lifecycle.ansible_runner, "run", _unexpected)

    ok, error = lifecycle.configure_agent(
        "claude-host", "claude", {}, agent_name="claude-code"
    )

    assert (ok, error) == (False, "Claude settings configure unavailable")
    assert controller_path not in (error or "")
    assert _SECRET not in (error or "")


def test_configure_runner_exception_is_redacted_and_removes_artifacts(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    host = _seed_host(isolated_config)
    configure_claude_credentials("claude-code", anthropic_api_key=_SECRET)
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


def test_configure_does_not_report_success_when_private_runner_data_cannot_be_removed(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    host = _seed_host(isolated_config)
    configure_claude_credentials("claude-code", anthropic_api_key=_SECRET)
    captured: dict[str, object] = {}
    monkeypatch.setattr(lifecycle, "get_host", lambda _: host)
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _: tmp_path / "key")
    monkeypatch.setattr(lifecycle, "_get_logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(
        lifecycle, "update_host", lambda _hostname, updater: updater(host)
    )

    def successful_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="successful")

    original_rmtree = lifecycle.shutil.rmtree

    def refuse_cleanup(path, *args, **kwargs):
        if Path(path) == Path(captured["private_data_dir"]):
            raise PermissionError("credential cleanup blocked")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(lifecycle.ansible_runner, "run", successful_run)
    monkeypatch.setattr(lifecycle.shutil, "rmtree", refuse_cleanup)

    try:
        ok, error = lifecycle.configure_agent(
            "claude-host", "claude", {}, agent_name="claude-code"
        )
    finally:
        original_rmtree(Path(captured["private_data_dir"]), ignore_errors=True)

    assert (ok, error) == (False, "Claude settings configure cleanup failed")
    assert _SECRET not in (error or "")


@pytest.mark.parametrize(
    ("filename", "home", "group", "guard"),
    [
        (
            "configure.yaml",
            "/home/{{ agent_name }}",
            "{{ agent_name }}",
            'ansible_os_family == "Darwin"',
        ),
        (
            "configure_macos.yaml",
            "/Users/{{ agent_name }}",
            "staff",
            'ansible_os_family != "Darwin"',
        ),
    ],
)
def test_activation_playbooks_are_private_atomic_and_no_log(
    filename: str, home: str, group: str, guard: str
):
    playbook = yaml.safe_load(
        (Path("src/clawrium/platform/registry/claude/playbooks") / filename).read_text()
    )
    serialized = json.dumps(playbook)

    assert playbook[0]["tasks"][0]["when"] == guard
    assert (
        _task(playbook, "Validate selected Claude credential transport")["no_log"]
        is True
    )
    startup_dir = _task(playbook, "Create managed Claude shell startup directory")[
        "ansible.builtin.file"
    ]
    assert startup_dir == {
        "path": f"{home}/.profile.d",
        "state": "directory",
        "owner": "{{ agent_name }}",
        "group": group,
        "mode": "0700",
    }
    startup = _task(playbook, "Write managed Claude shell startup snippet")[
        "ansible.builtin.copy"
    ]
    assert startup["dest"] == f"{home}/.profile.d/clawrium-claude.sh"
    assert startup["owner"] == "{{ agent_name }}"
    assert startup["group"] == group
    assert startup["mode"] == "0600"
    assert startup["unsafe_writes"] is False
    assert ' . "$HOME/.claude/clawrium-credentials.env"' in startup["content"]

    credential_task = _task(
        playbook, "Atomically replace active Claude credential environment"
    )
    credential = credential_task["ansible.builtin.copy"]
    assert credential_task["no_log"] is True
    assert credential == {
        "content": (
            "unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY\n"
            "export {{ claude_credential_key }}={{ claude_credential_value | quote }}\n"
        ),
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


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_sync_replaces_remote_credential_with_exactly_one_active_export(
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
        assert set(rendered) == {".claude/settings.json"}
        assert "oauth-switch-token" not in rendered[".claude/settings.json"]
        assert _SECRET not in rendered[".claude/settings.json"]
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
            )
        ]

    monkeypatch.setattr(lifecycle_canonical, "diff_files", fake_diff_files)
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_activation_directories",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda _client, **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(lifecycle_canonical, "_restart_unit", _unexpected)
    monkeypatch.setattr(lifecycle_canonical, "_verify_health", _unexpected)

    first = lifecycle_canonical.sync_agent_canonical(
        "claude-code", on_event=lambda stage, message: events.append((stage, message))
    )
    first_credential = next(
        write["body"]
        for write in writes
        if write["remote_path"].endswith("clawrium-credentials.env")
    )
    assert first_credential == (
        "unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY\n"
        "export CLAUDE_CODE_OAUTH_TOKEN=oauth-switch-token\n"
    )
    assert "export ANTHROPIC_API_KEY=" not in first_credential
    assert all("oauth-switch-token" not in message for _, message in events)
    assert all("clawrium-credentials.env" not in message for _, message in events)
    assert all("oauth-switch-token" not in diff.rendered_body for diff in first.diffs)
    assert all("clawrium-credentials.env" not in diff.path for diff in first.diffs)
    assert first.files_written == (".claude/settings.json",)

    configure_claude_credentials("claude-code", anthropic_api_key="api-switch-token")
    writes.clear()
    events.clear()
    second = lifecycle_canonical.sync_agent_canonical(
        "claude-code", on_event=lambda stage, message: events.append((stage, message))
    )
    second_credential = next(
        write["body"]
        for write in writes
        if write["remote_path"].endswith("clawrium-credentials.env")
    )
    assert second_credential == (
        "unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY\n"
        "export ANTHROPIC_API_KEY=api-switch-token\n"
    )
    assert "export CLAUDE_CODE_OAUTH_TOKEN=" not in second_credential
    assert second.files_written == (".claude/settings.json",)
    assert all("api-switch-token" not in message for _, message in events)
    assert all("clawrium-credentials.env" not in message for _, message in events)
    assert all("api-switch-token" not in diff.rendered_body for diff in second.diffs)
    assert all("clawrium-credentials.env" not in diff.path for diff in second.diffs)
    assert all(write["host"]["os_family"] == os_family for write in writes)


def test_sync_rotates_credential_when_settings_are_unchanged(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    configure_claude_credentials("claude-code", anthropic_api_key="api-rotation-token")
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
            )
        ],
    )
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", lambda _: client)
    monkeypatch.setattr(
        lifecycle_canonical,
        "_ensure_claude_activation_directories",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda _client, **kwargs: writes.append(kwargs),
    )

    result = lifecycle_canonical.sync_agent_canonical(
        "claude-code", on_event=lambda stage, message: events.append((stage, message))
    )

    assert result.files_written == ()
    assert result.files_unchanged == (".claude/settings.json",)
    assert [write["remote_path"] for write in writes] == [
        "/home/claude-code/.profile.d/clawrium-claude.sh",
        "/home/claude-code/.claude/clawrium-credentials.env",
    ]
    assert writes[-1]["body"] == (
        "unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY\n"
        "export ANTHROPIC_API_KEY=api-rotation-token\n"
    )
    assert not any(stage == "write" for stage, _ in events)
    assert all("clawrium-credentials.env" not in message for _, message in events)
    assert all("api-rotation-token" not in message for _, message in events)
    client.close.assert_called_once_with()


@pytest.mark.parametrize("failure", ["directory", "startup", "credential"])
def test_sync_activation_failure_closes_ssh_without_completion_event_or_secret_leak(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, failure: str
):
    host = _seed_host(isolated_config)
    record = host["agents"]["claude-code"]
    configure_claude_credentials("claude-code", anthropic_api_key=_SECRET)
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
            "_ensure_claude_activation_directories",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                lifecycle_canonical.CanonicalSyncError(
                    "/home/claude-code/.profile.d private directory failed"
                )
            ),
        )
    else:
        monkeypatch.setattr(
            lifecycle_canonical,
            "_ensure_claude_activation_directories",
            lambda *_args, **_kwargs: None,
        )

        def fail_selected_write(_client, **kwargs):
            target = (
                "clawrium-claude.sh"
                if failure == "startup"
                else "clawrium-credentials.env"
            )
            if kwargs["remote_path"].endswith(target):
                raise lifecycle_canonical.CanonicalSyncError(
                    f"{kwargs['remote_path']} {failure} failed: {_SECRET}"
                )

        monkeypatch.setattr(lifecycle_canonical, "_atomic_write", fail_selected_write)

    with pytest.raises(lifecycle_canonical.CanonicalSyncError) as error:
        lifecycle_canonical.sync_agent_canonical(
            "claude-code",
            on_event=lambda stage, message: events.append((stage, message)),
        )

    assert str(error.value) == "Claude credential activation failed"
    assert _SECRET not in str(error.value)
    assert "clawrium-credentials.env" not in str(error.value)
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
        "_ensure_claude_activation_directories",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda _client, **kwargs: writes.append(kwargs),
    )

    def selected(agent_name: str) -> tuple[str, str]:
        calls.append(agent_name)
        return "ANTHROPIC_API_KEY", "one-selection-test-value"

    monkeypatch.setattr(
        "clawrium.core.claude_credentials.get_active_claude_credential", selected
    )

    lifecycle_canonical.sync_agent_canonical("claude-code")

    assert calls == ["claude-code"]
    assert writes[-1]["body"] == (
        "unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY\n"
        "export ANTHROPIC_API_KEY=one-selection-test-value\n"
    )


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


def test_sync_credential_body_uses_shell_escaping_without_command_arguments(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    _seed_host(isolated_config)
    configure_claude_credentials("claude-code", anthropic_api_key="api'$(unsafe)")
    body = lifecycle_canonical._claude_credential_env_body(
        "ANTHROPIC_API_KEY", "api'$(unsafe)"
    )

    assert body == (
        "unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY\n"
        "export ANTHROPIC_API_KEY='api'\"'\"'$(unsafe)'\n"
    )

    class Stream:
        def __init__(self, body: bytes = b""):
            self._body = body
            self.channel = self

        def read(self):
            return self._body

        def recv_exit_status(self):
            return 0

    class SFTPFile:
        def __init__(self, writes: list[bytes]):
            self._writes = writes

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def write(self, content: bytes):
            self._writes.append(content)

    class SFTP:
        def __init__(self, writes: list[bytes]):
            self._writes = writes

        def file(self, *_args):
            return SFTPFile(self._writes)

        def close(self):
            return None

    class Client:
        def __init__(self):
            self.commands: list[str] = []
            self.writes: list[bytes] = []

        def exec_command(self, command, **_kwargs):
            self.commands.append(command)
            stdout = (
                Stream(b"/tmp/clawrium-sync.safe123\n")
                if command.startswith("mktemp")
                else Stream()
            )
            return None, stdout, Stream()

        def open_sftp(self):
            return SFTP(self.writes)

    client = Client()
    lifecycle_canonical._atomic_write_linux(
        client,
        agent_name="claude-code",
        remote_path="/home/claude-code/.claude/clawrium-credentials.env",
        body=body,
    )

    assert client.writes == [body.encode()]
    assert all("api'$(unsafe)" not in command for command in client.commands)
    assert all("ANTHROPIC_API_KEY" not in command for command in client.commands)


def test_linux_atomic_write_rejects_unsafe_mktemp_path_before_sftp_or_install():
    class Stream:
        channel = None

        def __init__(self, body: bytes):
            self._body = body
            self.channel = self

        def read(self):
            return self._body

        def recv_exit_status(self):
            return 0

    class Client:
        def __init__(self):
            self.commands: list[str] = []
            self.sftp_opened = False

        def exec_command(self, command, **_kwargs):
            self.commands.append(command)
            return None, Stream(b"/etc/clawrium-credentials.env\\n"), Stream(b"")

        def open_sftp(self):
            self.sftp_opened = True
            raise AssertionError("unsafe mktemp result must not reach SFTP")

    client = Client()

    with pytest.raises(lifecycle_canonical.CanonicalSyncError, match="unsafe path"):
        lifecycle_canonical._atomic_write_linux(
            client,
            agent_name="claude-code",
            remote_path="/home/claude-code/.claude/clawrium-credentials.env",
            body="export ANTHROPIC_API_KEY=not-a-secret-test-value\\n",
        )

    assert client.sftp_opened is False
    assert client.commands == ["mktemp /tmp/clawrium-sync.XXXXXX"]


@pytest.mark.parametrize(
    ("os_family", "expected"),
    [("darwin", "darwin"), ("macos", "darwin"), ("osx", "darwin"), ("linux", "linux")],
)
def test_atomic_dispatch_uses_correct_owner_path_for_os_aliases(
    monkeypatch: pytest.MonkeyPatch, os_family: str, expected: str
):
    client = MagicMock()
    calls: list[str] = []
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write_linux",
        lambda *_args, **_kwargs: calls.append("linux"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_macos.atomic_write_macos",
        lambda *_args, **_kwargs: calls.append("darwin"),
    )

    lifecycle_canonical._atomic_write(
        client,
        agent_name="claude-code",
        remote_path="/Users/claude-code/.claude/clawrium-credentials.env",
        body="export ANTHROPIC_API_KEY='value'\n",
        host={"os_family": os_family},
    )

    assert calls == [expected]


def test_agent_shell_sources_managed_claude_snippet_before_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    host = _host()
    monkeypatch.setattr(agent_shell, "get_config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(
        agent_shell.core_keys, "get_host_private_key", lambda _: tmp_path / "key"
    )
    (tmp_path / "key").write_text("key")
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _: host)
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            status="successful",
            events=[
                {
                    "event": "runner_on_ok",
                    "event_data": {"res": {"msg": "SHELL_STDOUT="}},
                },
                {
                    "event": "runner_on_ok",
                    "event_data": {"res": {"msg": "SHELL_STDERR="}},
                },
                {"event": "runner_on_ok", "event_data": {"res": {"msg": "SHELL_RC=0"}}},
            ],
        )

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    assert agent_shell.run_agent_shell(
        "claude-host", "claude-code", ["printf", "ready"]
    ) == ("", "", 0)

    command = base64.b64decode(captured["inventory"]["all"]["vars"]["cmd_b64"]).decode()
    source = '[ -r "$HOME/.profile.d/clawrium-claude.sh" ] && . "$HOME/.profile.d/clawrium-claude.sh";'
    assert source in command
    assert command.index(source) < command.index("printf ready")
    assert _SECRET not in command

    host["agents"]["claude-code"]["type"] = "hermes"
    assert agent_shell._claude_activation_prepend(host, "claude-code") == ""


@pytest.mark.parametrize(
    ("agents", "agent_name"),
    [
        ({"claude-code": {"type": "claude"}}, "claude-code"),
        ({"internal": {"type": "claude", "agent_name": "claude-code"}}, "claude-code"),
        ({"internal": {"type": "claude", "name": "legacy-claude"}}, "legacy-claude"),
    ],
)
def test_agent_shell_activation_resolves_current_and_legacy_claude_names(
    agents: dict, agent_name: str
):
    host = {"agents": agents}

    assert agent_shell._claude_activation_prepend(host, agent_name)


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_managed_snippet_activates_exactly_one_credential_for_finite_command(
    tmp_path: Path, os_family: str
):
    """The exact type-aware prelude makes credentials available to agent shell."""
    home = tmp_path / os_family / "home"
    profile_dir = home / ".profile.d"
    claude_dir = home / ".claude"
    profile_dir.mkdir(parents=True)
    claude_dir.mkdir()
    (claude_dir / "clawrium-credentials.env").write_text(
        "unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY\n"
        "export ANTHROPIC_API_KEY=active-test-value\n"
    )
    (profile_dir / "clawrium-claude.sh").write_text(
        lifecycle_canonical._CLAUDE_SHELL_STARTUP_SNIPPET
    )

    prelude = agent_shell._claude_activation_prepend(
        _host(os_family=os_family), "claude-code"
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'{prelude} [ "$ANTHROPIC_API_KEY" = "active-test-value" ] '
            '&& [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]',
        ],
        env={
            **os.environ,
            "HOME": str(home),
            "CLAUDE_CODE_OAUTH_TOKEN": "stale-oauth-test-value",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "active-test-value" not in result.stdout
    assert "active-test-value" not in result.stderr

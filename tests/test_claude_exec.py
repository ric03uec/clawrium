"""Contracts for bounded Claude native ``agent exec`` (#989)."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import yaml


PLAYBOOK_ROOT = Path("src/clawrium/platform/registry/claude/playbooks")
PLAYBOOKS = ("exec.yaml", "exec_macos.yaml")


def _playbook(filename: str) -> dict[str, Any]:
    loaded = yaml.safe_load((PLAYBOOK_ROOT / filename).read_text())
    assert isinstance(loaded, list) and len(loaded) == 1
    return loaded[0]


def _task(playbook: dict[str, Any], name: str) -> dict[str, Any]:
    return next(task for task in playbook["tasks"] if task["name"] == name)


@pytest.mark.parametrize("filename", PLAYBOOKS)
def test_claude_exec_playbooks_run_only_pinned_binary_with_safe_argv(
    filename: str,
) -> None:
    """No caller value becomes shell text or a controller-side credential."""
    text = (PLAYBOOK_ROOT / filename).read_text()
    playbook = _playbook(filename)
    serialized = yaml.safe_dump(playbook)
    run = _task(playbook, "Run finite Claude Code exec command as dedicated agent user")
    command = run["ansible.builtin.command"]

    assert "ansible.builtin.shell" not in text
    assert "--bare" not in text
    assert "claude_oauth_credentials" not in text
    assert "claude_api_key_environment" not in text
    assert '"$@" >"$tmpdir/stdout" 2>"$tmpdir/stderr"' in text
    assert command["expand_argument_vars"] is False
    assert "CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY" in text
    assert "clawrium-credentials.env" in text
    assert "cmd_argv" in serialized
    assert "claude_binary" in serialized
    assert run["become_user"] == "{{ agent_name }}"
    assert run["no_log"] is True
    assert command["chdir"] == "{{ claude_home }}"
    assert command["argv"].startswith("{{ [")
    assert run["environment"] == {
        "HOME": "{{ claude_home }}",
        "PATH": (
            "{{ claude_home }}/.local/claude/bin:/usr/local/bin:/usr/bin:/bin"
            if filename == "exec.yaml"
            else "{{ claude_home }}/.local/claude/bin:/opt/homebrew/bin:"
            "/usr/local/bin:/opt/local/bin:/usr/bin:/bin"
        ),
        "DISABLE_AUTOUPDATER": "1",
    }
    emit = _task(playbook, "Emit redacted Claude exec result")
    assert "claude_exec_capture_bootstrap" in command["argv"]
    assert "claude_exec_capture_program" in command["argv"]
    assert "claude_exec_safe_result.stdout" in emit["ansible.builtin.debug"]["msg"]
    assert "claude_exec_result.stdout" not in emit["ansible.builtin.debug"]["msg"]
    assert "ANTHROPIC_API_KEY" in playbook["vars"]["claude_exec_capture_program"]
    assert "accessToken" in playbook["vars"]["claude_exec_capture_program"]
    assert '"$@" >"$tmpdir/stdout" 2>"$tmpdir/stderr"' in playbook["vars"][
        "claude_exec_capture_bootstrap"
    ]


@pytest.mark.parametrize("filename", PLAYBOOKS)
@pytest.mark.parametrize("mode", ("api_key", "oauth"))
def test_claude_exec_playbook_redacts_credentials_before_emitting_events(
    filename: str, mode: str, tmp_path: Path
) -> None:
    """Raw reflected credentials never reach Ansible's visible result event."""
    agent_name = os.environ.get("USER", "")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", agent_name):
        pytest.skip("current Unix user cannot be used as an Ansible become_user")
    ansible_playbook = shutil.which("ansible-playbook")
    if ansible_playbook is None:
        pytest.skip("ansible-playbook is required to execute playbook validation")

    claude_home = tmp_path / "claude-home"
    credentials_dir = claude_home / ".claude"
    credentials_dir.mkdir(parents=True)
    secret = "sk-ant-secret-that-must-not-reach-events"
    refresh = "refresh-token-that-must-not-reach-events"
    if mode == "api_key":
        (credentials_dir / "clawrium-credentials.env").write_text(
            f"export ANTHROPIC_API_KEY={secret}\n"
        )
        command = 'printf "%s" "$ANTHROPIC_API_KEY"; printf "%s" "$ANTHROPIC_API_KEY" >&2; exit 7'
        secrets = (secret,)
    else:
        (credentials_dir / ".credentials.json").write_text(
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": secret,
                        "refreshToken": refresh,
                    }
                }
            )
        )
        command = 'cat "$HOME/.claude/.credentials.json"; exit 7'
        secrets = (secret, refresh)

    variables = {
        "agent_name": agent_name,
        "claude_home": str(claude_home),
        "claude_binary": "/bin/sh",
        "cmd_argv": ["-c", command],
        "claude_exec_timeout": 5,
    }
    completed = subprocess.run(
        [
            ansible_playbook,
            "-i",
            "localhost,",
            "-c",
            "local",
            str(PLAYBOOK_ROOT / filename),
            "--extra-vars",
            json.dumps(variables),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    visible = completed.stdout + completed.stderr
    for value in secrets:
        assert value not in visible
        assert base64.b64encode(value.encode()).decode() not in visible
    marker = re.search(r"CLAUDE_EXEC_RESULT=([A-Za-z0-9+/=]+)", visible)
    assert marker is not None, visible
    payload = json.loads(base64.b64decode(marker.group(1)))
    assert payload["rc"] == 7
    for value in secrets:
        assert value not in payload["stdout"]
        assert value not in payload["stderr"]
    assert "[REDACTED]" in payload["stdout"] or "[REDACTED]" in payload["stderr"]


@pytest.mark.parametrize("filename", PLAYBOOKS)
def test_claude_exec_playbook_rejects_each_malformed_transport_input(
    filename: str,
) -> None:
    """The real playbook guard fires before the native binary can run."""
    agent_name = os.environ.get("USER", "")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", agent_name):
        pytest.skip("current Unix user cannot be used as an Ansible become_user")
    ansible_playbook = shutil.which("ansible-playbook")
    if ansible_playbook is None:
        pytest.skip("ansible-playbook is required to execute playbook validation")

    base: dict[str, Any] = {
        "agent_name": agent_name,
        "claude_home": "/tmp",
        "claude_binary": "/bin/true",
        "cmd_argv": ["--version"],
        "claude_exec_timeout": 1,
    }
    cases = (
        ({"cmd_argv": []}, False),
        ({"cmd_argv": "--version"}, False),
        ({"cmd_argv": [None]}, False),
        ({"cmd_argv": [""]}, False),
        ({"claude_exec_timeout": 0}, False),
        ({"claude_exec_timeout": 121}, False),
        ({"claude_exec_timeout": "not-a-number"}, False),
        ({}, True),
    )
    for override, valid in cases:
        variables = {**base, **override}
        completed = subprocess.run(
            [
                ansible_playbook,
                "-i",
                "localhost,",
                "-c",
                "local",
                str(PLAYBOOK_ROOT / filename),
                "--extra-vars",
                json.dumps(variables),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if valid:
            assert completed.returncode == 0, completed.stderr
        else:
            assert completed.returncode != 0
            assert "Claude exec requires a non-empty string argv" in (
                completed.stdout + completed.stderr
            )


@pytest.mark.parametrize("filename", PLAYBOOKS)
def test_exec_wrapper_kills_the_native_claude_process_group(filename: str) -> None:
    playbook = _playbook(filename)
    run = _task(playbook, "Run finite Claude Code exec command as dedicated agent user")
    wrapper = playbook["vars"]["claude_exec_timeout_wrapper"]

    assert "/usr/bin/perl" in run["ansible.builtin.command"]["argv"]
    assert "claude_exec_timeout_wrapper" in run["ansible.builtin.command"]["argv"]
    assert "setsid" in wrapper
    assert "kill 'KILL', -$pid" in wrapper
    assert "exit 124" in wrapper
    assert "/usr/bin/timeout" not in (PLAYBOOK_ROOT / filename).read_text()


@pytest.mark.parametrize("filename", PLAYBOOKS)
def test_claude_exec_timeout_kills_background_process_group(
    filename: str, tmp_path: Path
) -> None:
    """The real wrapper kills a native command's background child at deadline."""
    agent_name = os.environ.get("USER", "")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", agent_name):
        pytest.skip("current Unix user cannot be used as an Ansible become_user")
    ansible_playbook = shutil.which("ansible-playbook")
    if ansible_playbook is None:
        pytest.skip("ansible-playbook is required to execute playbook validation")

    claude_home = tmp_path / "claude-home"
    (claude_home / ".claude").mkdir(parents=True)
    child_marker = tmp_path / "background-child-survived"
    variables = {
        "agent_name": agent_name,
        "claude_home": str(claude_home),
        "claude_binary": "/bin/sh",
        "cmd_argv": [
            "-c",
            f"(sleep 2; touch {child_marker}) & wait",
        ],
        "claude_exec_timeout": 1,
    }
    completed = subprocess.run(
        [
            ansible_playbook,
            "-i",
            "localhost,",
            "-c",
            "local",
            str(PLAYBOOK_ROOT / filename),
            "--extra-vars",
            json.dumps(variables),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    marker = re.search(
        r"CLAUDE_EXEC_RESULT=([A-Za-z0-9+/=]+)", completed.stdout + completed.stderr
    )
    assert marker is not None
    assert json.loads(base64.b64decode(marker.group(1)))["rc"] == 124
    # Let a surviving child reach its write point; correct process-group cleanup
    # leaves the marker absent.
    time.sleep(2.2)
    assert not child_marker.exists()


@pytest.mark.parametrize("filename", ("configure.yaml", "configure_macos.yaml"))
def test_claude_configure_and_sync_runbooks_never_invoke_native_cli(
    filename: str,
) -> None:
    """Configure/sync render credentials; only explicit exec runs Claude."""
    playbook = _playbook(filename)
    executable_modules = {
        "ansible.builtin.command",
        "ansible.builtin.raw",
        "ansible.builtin.script",
        "ansible.builtin.shell",
    }
    assert all(
        module not in task
        for task in playbook["tasks"]
        for module in executable_modules
    )

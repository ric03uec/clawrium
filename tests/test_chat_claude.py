"""Tests for the finite, on-demand Claude Code chat backend (#989)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from clawrium.core import chat_claude
from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
)
from clawrium.core.chat_claude import ClaudeCodeChatBackend


def _result(session_id: str, text: str = "hello", *, is_error: bool = False) -> str:
    return json.dumps(
        {
            "type": "result",
            "is_error": is_error,
            "result": text,
            "session_id": session_id,
        }
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_session_id_then_resume_preserves_repl_conversation() -> None:
    calls: list[tuple[list[str], str]] = []
    ids = iter(
        [
            uuid.UUID("11111111-1111-4111-8111-111111111111"),
            uuid.UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )

    def runner(
        _hostname: str,
        _agent_name: str,
        argv: list[str],
        prompt: str,
        _timeout: int,
        _cancel_event: threading.Event,
    ) -> tuple[str, str, int]:
        calls.append((argv, prompt))
        session_id = argv[-1]
        return _result(session_id, f"reply to {prompt}"), "", 0

    backend = ClaudeCodeChatBackend(
        "wolf",
        "claude-agent",
        command_runner=runner,
        session_id_factory=lambda: next(ids),
    )
    _run(backend.connect())
    assert _run(backend.send_message("one", "main")) == "reply to one"
    assert _run(backend.send_message("two", "main")) == "reply to two"

    session_id = "11111111-1111-4111-8111-111111111111"
    assert calls == [
        (["--print", "--output-format", "json", "--session-id", session_id], "one"),
        (["--print", "--output-format", "json", "--resume", session_id], "two"),
    ]


def test_reset_starts_a_fresh_upstream_session() -> None:
    calls: list[list[str]] = []
    ids = iter(
        [
            uuid.UUID("11111111-1111-4111-8111-111111111111"),
            uuid.UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )

    def runner(
        _host: str,
        _agent: str,
        argv: list[str],
        _prompt: str,
        _timeout: int,
        _cancel_event: threading.Event,
    ):
        calls.append(argv)
        return _result(argv[-1]), "", 0

    backend = ClaudeCodeChatBackend(
        "wolf",
        "claude-agent",
        command_runner=runner,
        session_id_factory=lambda: next(ids),
    )
    _run(backend.connect())
    _run(backend.send_message("before", "main"))
    backend.clear_history()
    _run(backend.send_message("after", "main"))

    assert calls[0][-2:] == ["--session-id", "11111111-1111-4111-8111-111111111111"]
    assert calls[1][-2:] == ["--session-id", "22222222-2222-4222-8222-222222222222"]


def test_changed_session_key_starts_an_independent_claude_session() -> None:
    ids = iter(
        [
            uuid.UUID("11111111-1111-4111-8111-111111111111"),
            uuid.UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )
    calls: list[list[str]] = []

    def runner(
        _host: str,
        _agent: str,
        argv: list[str],
        _prompt: str,
        _timeout: int,
        _cancel_event: threading.Event,
    ):
        calls.append(argv)
        return _result(argv[-1]), "", 0

    backend = ClaudeCodeChatBackend(
        "wolf",
        "claude-agent",
        command_runner=runner,
        session_id_factory=lambda: next(ids),
    )
    _run(backend.connect())
    _run(backend.send_message("first", "main"))
    _run(backend.send_message("second", "another"))

    assert calls[1][-2:] == ["--session-id", "22222222-2222-4222-8222-222222222222"]


def test_backend_uses_json_result_and_sanitizes_terminal_controls() -> None:
    session_id = "11111111-1111-4111-8111-111111111111"

    def runner(*_args: Any) -> tuple[str, str, int]:
        return _result(session_id, "safe\u202edanger\x1b[31m"), "", 0

    backend = ClaudeCodeChatBackend("wolf", "claude-agent", command_runner=runner)
    _run(backend.connect())
    deltas: list[str] = []
    assert (
        _run(backend.send_message("hello", "main", deltas.append)) == "safedanger[31m"
    )
    assert deltas == ["safedanger[31m"]


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        json.dumps({"type": "event", "result": "nope"}),
        json.dumps({"type": "result", "is_error": False, "result": "no id"}),
        json.dumps(
            {
                "type": "result",
                "is_error": False,
                "result": "nope",
                "session_id": "not-a-uuid",
            }
        ),
    ],
)
def test_malformed_claude_output_is_a_protocol_error(stdout: str) -> None:
    def runner(*_args: Any) -> tuple[str, str, int]:
        return stdout, "", 0

    backend = ClaudeCodeChatBackend("wolf", "claude-agent", command_runner=runner)
    _run(backend.connect())
    with pytest.raises(ChatProtocolError):
        _run(backend.send_message("hello", "main"))


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("", "OAuth credential invalid"),
        ("", "ANTHROPIC_API_KEY unauthorized"),
        ("Invalid API key", ""),
    ],
)
def test_oauth_and_api_key_auth_failures_have_the_same_safe_error(
    stdout: str, stderr: str
) -> None:
    def runner(*_args: Any) -> tuple[str, str, int]:
        return stdout, stderr, 1

    backend = ClaudeCodeChatBackend("wolf", "claude-agent", command_runner=runner)
    _run(backend.connect())
    with pytest.raises(ChatAuthenticationError) as excinfo:
        _run(backend.send_message("hello", "main"))
    assert "OAuth" not in str(excinfo.value)
    assert "ANTHROPIC_API_KEY" not in str(excinfo.value)


def test_timeout_and_cancellation_are_not_recast_as_protocol_errors() -> None:
    def timeout_runner(*_args: Any) -> tuple[str, str, int]:
        return "", "", 124

    backend = ClaudeCodeChatBackend(
        "wolf", "claude-agent", command_runner=timeout_runner
    )
    _run(backend.connect())
    with pytest.raises(ChatConnectionError, match="Timed out"):
        _run(backend.send_message("slow", "main", response_timeout_seconds=2.1))

    started = threading.Event()
    cancelled = threading.Event()

    def cancellable_runner(
        _host: str,
        _agent: str,
        _argv: list[str],
        _prompt: str,
        _timeout: int,
        cancel_event: threading.Event,
    ) -> tuple[str, str, int]:
        started.set()
        assert cancel_event.wait(2), "backend did not signal the runner to cancel"
        cancelled.set()
        return "", "", 124

    cancelling = ClaudeCodeChatBackend(
        "wolf", "claude-agent", command_runner=cancellable_runner
    )

    async def cancel_active_turn() -> None:
        await cancelling.connect()
        task = asyncio.create_task(cancelling.send_message("cancel", "main"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(cancel_active_turn())
    assert cancelled.is_set()
    assert cancelling.is_connected is False


def test_cancelled_turn_retries_with_fresh_claude_uuid() -> None:
    """A browser retry must not reuse a UUID created by its cancelled turn."""
    started = threading.Event()
    argv_calls: list[list[str]] = []
    ids = iter(
        [
            uuid.UUID("11111111-1111-4111-8111-111111111111"),
            uuid.UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )

    def runner(
        _host: str,
        _agent: str,
        argv: list[str],
        _prompt: str,
        _timeout: int,
        cancel_event: threading.Event,
    ) -> tuple[str, str, int]:
        argv_calls.append(argv)
        if len(argv_calls) == 1:
            started.set()
            assert cancel_event.wait(2), "backend did not signal the runner to cancel"
            return "", "", 124
        return _result(argv[-1], "retry succeeded"), "", 0

    backend = ClaudeCodeChatBackend(
        "wolf",
        "claude-agent",
        command_runner=runner,
        session_id_factory=lambda: next(ids),
    )

    async def cancel_active_turn() -> None:
        await backend.connect()
        task = asyncio.create_task(backend.send_message("cancel", "gui:one"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(cancel_active_turn())
    _run(backend.connect())
    assert _run(backend.send_message("retry", "gui:one")) == "retry succeeded"
    assert argv_calls == [
        [
            "--print",
            "--output-format",
            "json",
            "--session-id",
            "11111111-1111-4111-8111-111111111111",
        ],
        [
            "--print",
            "--output-format",
            "json",
            "--session-id",
            "22222222-2222-4222-8222-222222222222",
        ],
    ]


def test_transport_keeps_prompt_out_of_argv_and_private_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = {"hostname": "wolf", "key_id": "wolf", "alias": "wolf"}
    captured: dict[str, Any] = {}
    secret_shaped_prompt = "'; touch /tmp/pwn; {{ lookup('env', 'SECRET') }}"

    monkeypatch.setattr(chat_claude, "get_config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(
        chat_claude.core_keys, "get_host_private_key", lambda _: tmp_path / "key"
    )
    (tmp_path / "key").write_text("key")
    from clawrium.core import hosts

    monkeypatch.setattr(hosts, "get_host", lambda _: host)

    def fake_run_async(**kwargs: Any) -> tuple[SimpleNamespace, SimpleNamespace]:
        captured.update(kwargs)
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"msg": "CLAUDE_CHAT_STDOUT="}},
            },
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"msg": "CLAUDE_CHAT_STDERR="}},
            },
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"msg": "CLAUDE_CHAT_RC=0"}},
            },
        ]
        return SimpleNamespace(join=lambda: None), SimpleNamespace(
            status="successful", events=events
        )

    monkeypatch.setattr(chat_claude.ansible_runner, "run_async", fake_run_async)
    cancel_event = threading.Event()
    stdout, stderr, rc = chat_claude.run_claude_code_chat(
        "wolf",
        "claude-agent",
        [
            "--print",
            "--output-format",
            "json",
            "--session-id",
            "11111111-1111-4111-8111-111111111111",
        ],
        secret_shaped_prompt,
        60,
        cancel_event,
    )

    assert (stdout, stderr, rc) == ("", "", 0)
    variables = captured["inventory"]["all"]["vars"]
    assert secret_shaped_prompt not in variables["claude_chat_argv"]
    assert (
        base64.b64decode(variables["claude_chat_prompt_b64"]).decode()
        == secret_shaped_prompt
    )
    assert captured["timeout"] == 90
    assert captured["cancel_callback"]() is False
    cancel_event.set()
    assert captured["cancel_callback"]() is True
    assert not list((tmp_path / "config" / "logs").iterdir())


@pytest.mark.parametrize("filename", ["chat.yaml", "chat_macos.yaml"])
def test_chat_playbooks_use_safe_argv_stdin_and_support_both_auth_modes(
    filename: str,
) -> None:
    path = Path("src/clawrium/platform/registry/claude/playbooks") / filename
    text = path.read_text()
    playbook = yaml.safe_load(text)[0]
    serialized = yaml.safe_dump(playbook)
    validate_task = next(
        task
        for task in playbook["tasks"]
        if task["name"] == "Validate Claude chat argv and prompt transport"
    )

    assert "ansible.builtin.shell" not in text
    assert "--bare" not in text
    assert "CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY" in text
    assert "clawrium-credentials.env" in text
    assert 'exec "$@"' in text
    assert 'stdin: "{{ claude_chat_prompt_b64 | b64decode }}"' in text
    assert "claude_chat_argv" in serialized
    assert "no_log: true" in text
    assert 'become_user: "{{ agent_name }}"' in text
    # Ansible lists under `when` are ANDed; this must reject each absent
    # required input independently rather than only rejecting all three.
    assert isinstance(validate_task["when"], str)
    assert " or " in validate_task["when"]


@pytest.mark.parametrize("filename", ["chat.yaml", "chat_macos.yaml"])
@pytest.mark.parametrize(
    ("override", "valid"),
    [
        ({}, True),
        ({"claude_chat_argv": None}, False),
        ({"claude_chat_prompt_b64": None}, False),
        ({"claude_chat_timeout": None}, False),
        ({"claude_chat_timeout": 0}, False),
        ({"claude_chat_timeout": -1}, False),
        ({"claude_chat_timeout": "not-a-number"}, False),
    ],
)
def test_chat_playbook_validation_executes_each_required_input_path(
    filename: str, override: dict[str, Any], valid: bool
) -> None:
    """Run each real validation task before its Claude command can execute.

    A harmless `/bin/true` substitutes for the pinned binary on the complete
    input path. Each invalid case must fail at the real Ansible `fail` task;
    that protects against Jinja expression or variable-name regressions that a
    YAML-text assertion cannot detect.
    """
    agent_name = os.environ.get("USER", "")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", agent_name):
        pytest.skip("current Unix user cannot be used as an Ansible become_user")
    variables: dict[str, Any] = {
        "agent_name": agent_name,
        "claude_home": "/tmp",
        "claude_binary": "/bin/true",
        "claude_chat_argv": ["--print", "--output-format", "json"],
        "claude_chat_prompt_b64": "aGVsbG8=",
        "claude_chat_timeout": 1,
    }
    variables.update(override)
    variables = {key: value for key, value in variables.items() if value is not None}
    playbook = Path("src/clawrium/platform/registry/claude/playbooks") / filename
    ansible_playbook = shutil.which("ansible-playbook")
    if ansible_playbook is None:
        pytest.skip("ansible-playbook is required to execute playbook validation")

    completed = subprocess.run(
        [
            ansible_playbook,
            "-i",
            "localhost,",
            "-c",
            "local",
            str(playbook),
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
        assert "Claude chat requires argv, prompt, and a positive timeout" in (
            completed.stdout + completed.stderr
        )


def test_macos_chat_playbook_kills_the_remote_claude_process_group_on_timeout() -> None:
    path = Path("src/clawrium/platform/registry/claude/playbooks/chat_macos.yaml")
    playbook = yaml.safe_load(path.read_text())[0]
    run_task = next(
        task
        for task in playbook["tasks"]
        if task["name"] == "Run finite Claude Code chat command as dedicated agent user"
    )
    argv = run_task["ansible.builtin.command"]["argv"]
    wrapper = playbook["vars"]["claude_chat_timeout_wrapper"]

    assert "/usr/bin/perl" in argv
    assert "claude_chat_timeout_wrapper" in argv
    assert "setsid" in wrapper
    assert "kill 'KILL', -$pid" in wrapper
    assert "exit 124" in wrapper
    assert "gtimeout" not in path.read_text()

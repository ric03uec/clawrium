"""Tests for the finite, on-demand Codex JSONL chat backend (#1037)."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from clawrium.core import chat_codex
from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
)
from clawrium.core.chat_codex import CodexChatBackend


def _events(thread_id: str = "thread-1", text: str = "hello") -> str:
    return "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": thread_id}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": text},
                }
            ),
            json.dumps({"type": "turn.completed"}),
        ]
    )


def test_jsonl_session_continuation_and_reset() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(_host, _agent, argv, prompt, _timeout, _cancel):
        calls.append((argv, prompt))
        return _events("native-thread"), "", 0

    backend = CodexChatBackend("wolf", "codex-agent", command_runner=runner)
    asyncio.run(backend.connect())
    assert asyncio.run(backend.send_message("one", "main")) == "hello"
    assert asyncio.run(backend.send_message("two", "main")) == "hello"
    backend.clear_history()
    assert asyncio.run(backend.send_message("fresh", "main")) == "hello"
    assert calls == [
        (["exec", "--json", "-"], "one"),
        (["exec", "resume", "--json", "native-thread", "-"], "two"),
        (["exec", "--json", "-"], "fresh"),
    ]


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        json.dumps({"type": "thread.started", "thread_id": "x"}),
        json.dumps(
            {"type": "item.completed", "item": {"type": "agent_message", "text": "x"}}
        ),
        _events(text="x") + "\n" + "{}",
    ],
)
def test_jsonl_protocol_rejects_malformed_or_incomplete_events(stdout: str) -> None:
    with pytest.raises(ChatProtocolError):
        chat_codex._parse_result(stdout)


def test_jsonl_multiple_messages_are_sanitized_and_joined() -> None:
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "one\u202e"},
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "two\x1b"},
                }
            ),
        ]
    )
    assert chat_codex._parse_result(stdout) == ("one\ntwo", "thread")


@pytest.mark.parametrize(
    "result, expected",
    [
        (("", "unauthorized secret-token", 2), ChatAuthenticationError),
        (("", "", 7), ChatProtocolError),
        (("", "", 124), ChatConnectionError),
    ],
)
def test_exit_errors_are_safe(
    result: tuple[str, str, int], expected: type[Exception]
) -> None:
    backend = CodexChatBackend(
        "wolf", "codex-agent", command_runner=lambda *_args: result
    )
    asyncio.run(backend.connect())
    with pytest.raises(expected):
        asyncio.run(backend.send_message("prompt", "main", response_timeout_seconds=1))


def test_cancellation_resets_native_thread() -> None:
    started = threading.Event()
    released = threading.Event()
    calls: list[list[str]] = []

    def runner(_host, _agent, argv, _prompt, _timeout, cancel):
        calls.append(argv)
        if len(calls) == 1:
            started.set()
            while not cancel.is_set():
                pass
            released.set()
            return "", "", 124
        return _events("new-thread", "retry"), "", 0

    async def exercise() -> None:
        backend = CodexChatBackend("wolf", "codex-agent", command_runner=runner)
        await backend.connect()
        task = asyncio.create_task(backend.send_message("slow", "main"))
        await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert released.is_set()
        await backend.connect()
        assert await backend.send_message("again", "main") == "retry"

    asyncio.run(exercise())
    assert calls == [["exec", "--json", "-"], ["exec", "--json", "-"]]


def test_transport_encodes_prompt_and_removes_runner_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_codex, "get_config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(
        chat_codex.core_keys, "get_host_private_key", lambda _key: tmp_path / "key"
    )
    monkeypatch.setattr(
        "clawrium.core.hosts.get_host",
        lambda _host: {"hostname": "wolf", "alias": "wolf"},
    )
    playbook = tmp_path / "chat.yaml"
    playbook.write_text("---\n")
    monkeypatch.setattr(chat_codex, "resolve_agent_playbook", lambda *_args: playbook)
    captured: dict[str, Any] = {}

    class Result:
        status = "successful"
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "res": {
                        "msg": "CODEX_CHAT_STDOUT="
                        + base64.b64encode(_events().encode()).decode()
                    }
                },
            },
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"msg": "CODEX_CHAT_AUTH_FAILURE=false"}},
            },
            {
                "event": "runner_on_ok",
                "event_data": {"res": {"msg": "CODEX_CHAT_RC=0"}},
            },
        ]

    def fake_run(**kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(chat_codex.ansible_runner, "run", fake_run)
    prompt = "secret prompt {{ lookup('env', 'NOPE') }}"
    assert chat_codex.run_codex_chat(
        "wolf", "codex-agent", ["exec", "--json", "-"], prompt, 3
    ) == (_events(), "", 0)
    variables = captured["inventory"]["all"]["vars"]
    assert prompt not in variables["codex_chat_argv"]
    assert base64.b64decode(variables["codex_chat_prompt_b64"]).decode() == prompt
    assert not list((tmp_path / "config" / "logs").iterdir())


@pytest.mark.parametrize("filename", ["chat.yaml", "chat_macos.yaml"])
def test_chat_playbooks_use_safe_argv_stdin_and_private_codex_home(
    filename: str,
) -> None:
    text = Path("src/clawrium/platform/registry/codex/playbooks", filename).read_text()
    assert "codex_chat_argv" in text
    assert 'stdin: "{{ codex_chat_prompt_b64 | b64decode }}"' in text
    assert "CODEX_HOME:" in text
    assert "CODEX_CHAT_AUTH_FAILURE" in text
    assert "CODEX_CHAT_STDERR" not in text
    assert "no_log: true" in text


def test_macos_chat_timeout_waits_for_process_group_before_arming_alarm() -> None:
    text = Path("src/clawrium/platform/registry/codex/playbooks/chat_macos.yaml").read_text()
    assert "pipe(my $ready_r, my $ready_w)" in text
    assert 'print {$ready_w} "1"' in text
    assert "my $ready = read($ready_r" in text
    assert "kill 'KILL', -$pid; kill 'KILL', $pid" in text

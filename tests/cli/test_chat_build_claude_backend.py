"""CLI dispatch coverage for the on-demand Claude Code chat backend (#989)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import ANY

import pytest
import typer

from clawrium.cli import chat as chat_module
from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
)
from clawrium.core.chat_claude import ClaudeCodeChatBackend


class _FakeClaudeBackend:
    """ChatBackend shim that records the full CLI-facing interaction."""

    def __init__(self, reply: str = "reply", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[object, ...]] = []
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.calls.append(("connect",))
        self.connected = True

    async def close(self) -> None:
        self.calls.append(("close",))
        self.connected = False

    def clear_history(self) -> None:
        self.calls.append(("reset",))

    async def send_message(
        self,
        message: str,
        session_key: str,
        on_delta: Callable[[str], None] | None = None,
        response_timeout_seconds: float = 120.0,
    ) -> str:
        self.calls.append(
            ("send", message, session_key, on_delta, response_timeout_seconds)
        )
        if self.error is not None:
            raise self.error
        return self.reply


def _patch_claude_dispatch(
    monkeypatch: pytest.MonkeyPatch, backend: _FakeClaudeBackend
) -> None:
    monkeypatch.setattr(
        chat_module,
        "get_agent_by_name",
        lambda _name: (
            {"hostname": "wolf", "alias": "wolf"},
            "claude",
            {"agent_name": "claude-agent"},
        ),
    )
    monkeypatch.setattr(chat_module, "_build_claude_backend", lambda **_kwargs: backend)


def test_claude_manifest_advertises_cli_chat_without_a_web_ui() -> None:
    assert chat_module._resolve_chat_type("claude") == "claude"


def test_unknown_agent_error_sanitizes_control_and_bidi_characters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(chat_module, "get_agent_by_name", lambda _name: None)

    with pytest.raises(typer.Exit):
        chat_module.chat(agent_name="claude\u202e-agent", session="main")

    output = capsys.readouterr().out
    assert "\u202e" not in output
    assert "claude -agent" in output


def test_build_claude_backend_uses_dedicated_agent_user() -> None:
    backend = chat_module._build_claude_backend(
        agent_record={"agent_name": "claude-agent"},
        host_record={"hostname": "wolf"},
        agent_name="display-name",
        response_timeout_seconds=42.0,
    )
    assert isinstance(backend, ClaudeCodeChatBackend)
    assert backend.hostname == "wolf"
    assert backend.agent_name == "claude-agent"
    assert backend.timeout_seconds == 42.0


def test_connected_target_sanitizes_agent_and_host_labels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_claude_dispatch(monkeypatch, _FakeClaudeBackend())
    monkeypatch.setattr(
        chat_module,
        "get_agent_by_name",
        lambda _name: (
            {"hostname": "wolf", "alias": "wo\u202elf"},
            "claude",
            {"agent_name": "claude\u202e-agent"},
        ),
    )

    def close_coro(coro: object) -> None:
        coro.close()  # type: ignore[union-attr]

    monkeypatch.setattr(chat_module.asyncio, "run", close_coro)
    chat_module.chat(
        agent_name="claude-agent",
        session="main",
        timeout=120.0,
        idle_timeout=300.0,
        once=None,
    )

    output = capsys.readouterr().out
    assert "\u202e" not in output
    assert "claude -agent on wo lf" in output


def test_chat_once_runs_the_claude_backend_and_prints_its_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = _FakeClaudeBackend(reply="Claude reply")
    _patch_claude_dispatch(monkeypatch, backend)

    chat_module.chat(
        agent_name="claude-agent",
        session="named-thread",
        timeout=42.0,
        idle_timeout=300.0,
        once="hello Claude",
    )

    assert backend.calls == [
        ("connect",),
        ("send", "hello Claude", "named-thread", None, 42.0),
        ("close",),
    ]
    assert "Claude reply" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        (
            ChatAuthenticationError("configured credential rejected"),
            "Re-run 'clawctl agent sync claude-agent'",
        ),
        (
            ChatConnectionError("Timed out waiting for Claude Code response after 42s"),
            "Try a higher --timeout value (current: 42.0s).",
        ),
        (ChatProtocolError("Claude Code returned malformed JSON"), "Protocol error:"),
    ],
)
def test_chat_once_surfaces_claude_errors_and_closes_the_backend(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected_text: str,
) -> None:
    backend = _FakeClaudeBackend(error=error)
    _patch_claude_dispatch(monkeypatch, backend)

    with pytest.raises(typer.Exit) as excinfo:
        chat_module.chat(
            agent_name="claude-agent",
            session="main",
            timeout=42.0,
            idle_timeout=300.0,
            once="hello Claude",
        )

    assert excinfo.value.exit_code == 1
    assert backend.calls[-1] == ("close",)
    assert expected_text in capsys.readouterr().out


def test_claude_repl_reset_clears_history_before_the_next_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _FakeClaudeBackend()
    inputs = iter(["/reset", "new turn"])

    async def read_input(_prompt: str, _timeout: float) -> str:
        try:
            return next(inputs)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr(chat_module, "_read_user_input", read_input)
    asyncio.run(
        chat_module._chat_loop(
            backend=backend,
            session_key="main",
            response_timeout_seconds=42.0,
            idle_timeout_seconds=300.0,
            chat_type="claude",
            agent_label="claude-agent",
        )
    )

    assert backend.calls == [
        ("connect",),
        ("reset",),
        ("send", "new turn", "main", ANY, 42.0),
        ("close",),
    ]

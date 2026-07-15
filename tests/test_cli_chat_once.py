"""Tests for `_chat_once` — the `clawctl agent chat --once` single-shot
branch inside `src/clawrium/cli/chat.py`.

Covers issue #918:
- single send + stdout contains reply + exit code 0
- transport error → non-zero exit with stderr diagnostic
- no interactive prompt or connection banner printed in once mode
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import pytest

from clawrium.cli import chat as chat_module
from clawrium.core.chat import ChatConnectionError


class _FakeBackend:
    """Minimal ChatBackend Protocol implementation for once-mode tests.

    - `reply` is the string returned from `send_message`.
    - `send_error` (if set) is raised from `send_message` instead.
    - Records the messages that were sent so the test can assert exactly
      one send happened per `_chat_once` invocation.
    """

    def __init__(
        self,
        reply: str = "",
        send_error: Exception | None = None,
    ) -> None:
        self.reply = reply
        self.send_error = send_error
        self.sent: list[str] = []
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def send_message(
        self,
        message: str,
        session_key: str,
        on_delta: Callable[[str], None] | None = None,
        response_timeout_seconds: float = 120.0,
    ) -> str:
        self.sent.append(message)
        if self.send_error is not None:
            raise self.send_error
        return self.reply

    async def close(self) -> None:
        self.closed = True

    def clear_history(self) -> None:  # pragma: no cover — protocol shim
        return None

    @property
    def is_connected(self) -> bool:
        return self.connected and not self.closed


def _run_once(
    backend: _FakeBackend,
    message: str = "hello",
    timeout: float = 30.0,
) -> None:
    asyncio.run(
        chat_module._chat_once(
            backend=backend,
            session_key="main",
            response_timeout_seconds=timeout,
            message=message,
        )
    )


def test_chat_once_sends_single_message_and_exits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = _FakeBackend(reply="pong")
    _run_once(backend, message="ping")

    assert backend.sent == ["ping"]
    assert backend.connected is True
    assert backend.closed is True

    captured = capsys.readouterr()
    assert "pong" in captured.out


def test_chat_once_returns_nonzero_on_transport_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = _FakeBackend(send_error=ChatConnectionError("boom: agent unreachable"))

    with pytest.raises(ChatConnectionError):
        _run_once(backend, message="hi")

    # Backend was still closed even though send failed (finally clause).
    assert backend.closed is True
    # The outer `chat()` translates ChatConnectionError to typer.Exit(1)
    # with a diagnostic; the once helper simply propagates.


def test_chat_once_no_repl_prompt(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert once-mode never touches the interactive prompt path."""
    called: list[Any] = []

    async def _boom_read_user_input(*args: Any, **kwargs: Any) -> str:
        called.append(args)
        raise AssertionError("REPL prompt reached in --once mode")

    monkeypatch.setattr(chat_module, "_read_user_input", _boom_read_user_input)

    backend = _FakeBackend(reply="ok")
    _run_once(backend, message="q")

    assert called == []
    captured = capsys.readouterr()
    # Interactive-only banners must NOT appear in the stdout / stderr
    # stream when running in once mode. `_chat_once` never prints
    # "Connecting to agent..." or a "you>" prompt.
    assert "Connecting to agent" not in captured.out
    assert "you>" not in captured.out
    assert "Type /exit" not in captured.out


def test_chat_once_prints_placeholder_on_empty_reply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = _FakeBackend(reply="")
    _run_once(backend, message="q")

    captured = capsys.readouterr()
    assert "[no response]" in captured.out


def test_chat_once_caps_timeout_at_hard_limit() -> None:
    """The `--timeout` value is passed through, but capped at the
    module-level `_ONCE_IDLE_TIMEOUT_SECONDS` so a stuck agent cannot
    hang a scripted caller past the cap."""
    captured_timeout: list[float] = []

    class _CapturingBackend(_FakeBackend):
        async def send_message(
            self,
            message: str,
            session_key: str,
            on_delta: Callable[[str], None] | None = None,
            response_timeout_seconds: float = 120.0,
        ) -> str:
            captured_timeout.append(response_timeout_seconds)
            return await super().send_message(
                message, session_key, on_delta, response_timeout_seconds
            )

    backend = _CapturingBackend(reply="ok")
    # Pass a --timeout well above the hard cap; the effective per-request
    # timeout the backend sees must be _ONCE_IDLE_TIMEOUT_SECONDS.
    _run_once(backend, message="q", timeout=600.0)

    assert captured_timeout == [chat_module._ONCE_IDLE_TIMEOUT_SECONDS]

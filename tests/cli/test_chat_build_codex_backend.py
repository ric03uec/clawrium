"""CLI dispatch coverage for Codex chat (#1037)."""

from __future__ import annotations

import asyncio

import pytest
import typer

from clawrium.cli import chat as chat_module
from clawrium.core.chat import ChatAuthenticationError
from clawrium.core.chat_codex import CodexChatBackend


def test_codex_manifest_dispatch_and_factory() -> None:
    assert chat_module._resolve_chat_type("codex") == "codex"
    backend = chat_module._build_codex_backend(
        agent_record={"agent_name": "codex-agent"},
        host_record={"hostname": "wolf"},
        agent_name="display",
        response_timeout_seconds=42,
    )
    assert isinstance(backend, CodexChatBackend)
    assert (backend.hostname, backend.agent_name, backend.timeout_seconds) == (
        "wolf",
        "codex-agent",
        42,
    )


def test_codex_once_uses_finite_backend_and_safe_sync_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Backend:
        async def connect(self):
            pass

        async def close(self):
            pass

        async def send_message(self, **kwargs):
            assert kwargs["message"] == "hello"
            raise ChatAuthenticationError("credential-secret")

    monkeypatch.setattr(
        chat_module,
        "get_agent_by_name",
        lambda _: ({"hostname": "wolf"}, "codex", {"agent_name": "codex-agent"}),
    )
    monkeypatch.setattr(chat_module, "_build_codex_backend", lambda **_: Backend())
    with pytest.raises(typer.Exit):
        chat_module.chat(
            agent_name="codex-agent",
            session="main",
            timeout=120.0,
            idle_timeout=300.0,
            once="hello",
        )
    output = capsys.readouterr().out
    assert "clawctl agent sync codex-agent" in output
    assert "credential-secret" not in output


def test_codex_repl_reset_clears_native_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Backend:
        async def connect(self):
            pass

        async def close(self):
            pass

        def clear_history(self):
            calls.append("reset")

        async def send_message(self, **_kwargs):
            calls.append("send")
            return "reply"

    inputs = iter(["/reset", "/exit"])

    async def read_input(*_args):
        try:
            return next(inputs)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr(chat_module, "_read_user_input", read_input)
    asyncio.run(chat_module._chat_loop(Backend(), "main", 10, 0, chat_type="codex"))
    assert calls == ["reset"]

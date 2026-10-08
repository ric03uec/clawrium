"""CLI Pi chat dispatch and provider selection across the Codex merge."""

from __future__ import annotations

import asyncio

import pytest

from clawrium.cli import chat as chat_module
from clawrium.core.chat_pi import PiChatBackend


def test_pi_manifest_dispatch_and_backend_factory(monkeypatch: pytest.MonkeyPatch):
    assert chat_module._resolve_chat_type("pi") == "pi"
    monkeypatch.setattr(
        chat_module,
        "get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    backend = chat_module._build_pi_backend(
        agent_record={"agent_name": "pi-demo", "providers": ["router"]},
        host_record={"hostname": "wolf-i"},
        agent_name="pi-demo",
        response_timeout_seconds=42,
    )
    assert isinstance(backend, PiChatBackend)
    assert (backend.hostname, backend.agent_name, backend.model, backend.provider) == (
        "wolf-i",
        "pi-demo",
        "openai/gpt-4o",
        "openrouter",
    )


def test_pi_chat_rejects_multiple_providers_before_backend():
    with pytest.raises(ValueError, match="exactly one attached"):
        chat_module._build_pi_backend(
            agent_record={"providers": ["first", "second"]},
            host_record={"hostname": "wolf-i"},
            agent_name="pi-demo",
            response_timeout_seconds=42,
        )


def test_pi_repl_reset_clears_native_session(monkeypatch: pytest.MonkeyPatch):
    calls = []

    class Backend:
        async def connect(self):
            pass

        async def close(self):
            pass

        def clear_history(self):
            calls.append("reset")

    inputs = iter(["/reset", "/exit"])

    async def read_input(*_args):
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", read_input)
    asyncio.run(chat_module._chat_loop(Backend(), "main", 10, 0, chat_type="pi"))
    assert calls == ["reset"]

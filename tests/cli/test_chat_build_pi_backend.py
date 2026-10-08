"""CLI Pi chat dispatch and provider selection across the Codex merge."""

from __future__ import annotations

import asyncio
import importlib

import pytest
from typer.testing import CliRunner

from clawrium.cli import app, chat as chat_module
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


@pytest.mark.parametrize("agent_type", ["pi", "codex"])
def test_agent_chat_once_dispatches_only_selected_backend(
    fleet_dir, monkeypatch: pytest.MonkeyPatch, agent_type: str
):
    """The public command preserves distinct Pi and Codex dispatch after merge."""
    calls = []
    monkeypatch.setattr(
        chat_module,
        "get_agent_by_name",
        lambda _: (
            {"hostname": "wolf-i", "alias": "wolf-i"},
            agent_type,
            {"agent_name": "demo", "providers": ["router"]},
        ),
    )
    monkeypatch.setattr(
        importlib.import_module("clawrium.cli.clawctl.agent.chat"),
        "safe_resolve_agent",
        lambda _: None,
    )

    def build_backend(**_kwargs):
        calls.append(agent_type)
        return object()

    def wrong_backend(**_kwargs):
        pytest.fail("Dispatched to the other agent's backend")

    monkeypatch.setattr(chat_module, f"_build_{agent_type}_backend", build_backend)
    other_type = "codex" if agent_type == "pi" else "pi"
    monkeypatch.setattr(chat_module, f"_build_{other_type}_backend", wrong_backend)

    async def fake_chat_loop(**kwargs):
        calls.append((kwargs["chat_type"], kwargs["once"]))

    monkeypatch.setattr(chat_module, "_chat_loop", fake_chat_loop)
    result = CliRunner().invoke(app, ["agent", "chat", "demo", "--once", "hello"])
    assert result.exit_code == 0, result.output
    assert calls == [agent_type, (agent_type, "hello")]


def test_agent_chat_pi_rejects_invalid_provider_before_transport(
    fleet_dir, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        chat_module,
        "get_agent_by_name",
        lambda _: (
            {"hostname": "wolf-i"},
            "pi",
            {"agent_name": "demo", "providers": ["router", "other"]},
        ),
    )
    monkeypatch.setattr(
        importlib.import_module("clawrium.cli.clawctl.agent.chat"),
        "safe_resolve_agent",
        lambda _: None,
    )
    monkeypatch.setattr(
        chat_module,
        "_chat_loop",
        lambda **_kwargs: pytest.fail("Invalid provider reached chat transport"),
    )
    result = CliRunner().invoke(app, ["agent", "chat", "demo", "--once", "hello"])
    assert result.exit_code == 1
    assert "exactly one attached" in result.output

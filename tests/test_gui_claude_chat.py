"""Claude Code coverage for the GUI chat SSE route (#989).

The GUI route must reuse the shared finite CLI backend rather than reconstruct
Claude invocation, credentials, or process transport. These tests exercise the
route boundary with an in-memory backend so no remote command or secret is
needed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clawrium.core.chat import ChatAuthenticationError, ChatConnectionError
from clawrium.gui.routes import agents as agents_module
from clawrium.gui.server import app


def _seed_hosts(config_dir: Path, *, status: str = "installed") -> None:
    hosts = [
        {
            "hostname": "192.168.1.100",
            "alias": "box",
            "port": 22,
            "user": "xclm",
            "agents": {
                "claude-demo": {
                    "type": "claude",
                    "agent_name": "claude-demo",
                    "name": "claude-demo",
                    "status": status,
                    "config": {},
                }
            },
        }
    ]
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(json.dumps(hosts))


@pytest.fixture(autouse=True)
def _clear_claude_browser_sessions():
    agents_module._CLAUDE_BROWSER_SESSIONS.clear()
    yield
    agents_module._CLAUDE_BROWSER_SESSIONS.clear()


def _sse_events(response) -> list[str]:
    return [
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _install_backend_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure: Exception | None = None,
) -> type:
    class FakeClaudeBackend:
        instances: list[FakeClaudeBackend] = []

        def __init__(
            self, *, hostname: str, agent_name: str, timeout_seconds: float
        ) -> None:
            self.hostname = hostname
            self.agent_name = agent_name
            self.timeout_seconds = timeout_seconds
            self.calls: list[tuple[str, str, float]] = []
            self.connected = False
            self.closed = False
            self.instances.append(self)

        async def connect(self) -> None:
            self.connected = True

        async def close(self) -> None:
            self.connected = False
            self.closed = True

        async def send_message(
            self,
            *,
            message: str,
            session_key: str,
            response_timeout_seconds: float,
        ) -> str:
            self.calls.append((message, session_key, response_timeout_seconds))
            if failure is not None:
                raise failure
            return f"reply: {message}"

    monkeypatch.setattr(agents_module, "ClaudeCodeChatBackend", FakeClaudeBackend)
    return FakeClaudeBackend


@pytest.mark.parametrize("credential_mode", ["native-oauth", "api-key"])
def test_claude_gui_chat_uses_shared_backend_without_reading_credentials(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    credential_mode: str,
) -> None:
    """Both credential modes stay remote; the GUI receives neither secret."""
    _seed_hosts(isolated_config)
    backend_cls = _install_backend_fake(monkeypatch)

    def unexpected_secret_read(*_args: Any, **_kwargs: Any) -> dict:
        raise AssertionError("Claude GUI chat must not read credential values")

    monkeypatch.setattr(agents_module, "get_instance_secrets", unexpected_secret_read)
    session = f"gui:{credential_mode}-conversation"

    with TestClient(app, base_url="http://localhost:36000") as client:
        response = client.post(
            "/api/agents/claude-demo/chat",
            json={"message": "hello", "session": session},
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response)
    assert json.loads(events[0]) == {"type": "content", "text": "reply: hello"}
    assert events == [events[0], "[DONE]"]
    assert len(backend_cls.instances) == 1
    backend = backend_cls.instances[0]
    assert backend.hostname == "192.168.1.100"
    assert backend.agent_name == "claude-demo"
    assert backend.calls == [("hello", session, 120.0)]
    assert backend.closed is True


def test_claude_gui_chat_reuses_a_backend_per_browser_conversation(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_hosts(isolated_config)
    backend_cls = _install_backend_fake(monkeypatch)

    with TestClient(app, base_url="http://localhost:36000") as client:
        for message in ("first", "second"):
            response = client.post(
                "/api/agents/claude-demo/chat",
                json={"message": message, "session": "gui:one"},
            )
            assert _sse_events(response)[-1] == "[DONE]"

        reset_response = client.post(
            "/api/agents/claude-demo/chat",
            json={"message": "fresh", "session": "gui:two"},
        )

    assert reset_response.status_code == 200
    assert len(backend_cls.instances) == 2
    assert backend_cls.instances[0].calls == [
        ("first", "gui:one", 120.0),
        ("second", "gui:one", 120.0),
    ]
    assert backend_cls.instances[1].calls == [("fresh", "gui:two", 120.0)]


@pytest.mark.parametrize(
    "failure, secret",
    [
        (ChatAuthenticationError("OAuth token oauth-secret-should-not-leak"), "oauth-secret-should-not-leak"),
        (ChatAuthenticationError("ANTHROPIC_API_KEY=api-key-should-not-leak"), "api-key-should-not-leak"),
        (ChatConnectionError("Timed out at /home/claude-demo/.claude"), "/home/claude-demo"),
    ],
)
def test_claude_gui_chat_emits_generic_error_and_done_without_leaks(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    secret: str,
) -> None:
    _seed_hosts(isolated_config)
    _install_backend_fake(monkeypatch, failure=failure)

    with TestClient(app, base_url="http://localhost:36000") as client:
        response = client.post(
            "/api/agents/claude-demo/chat",
            json={"message": "private prompt", "session": "gui:one"},
        )

    assert response.status_code == 200
    events = _sse_events(response)
    assert json.loads(events[0]) == {
        "type": "error",
        "message": "Chat request failed",
    }
    assert events[-1] == "[DONE]"
    assert secret not in response.text
    assert "private prompt" not in response.text


def test_claude_chat_info_is_supported_but_inactive_and_missing_agents_fail_cleanly(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_hosts(isolated_config)
    backend_cls = _install_backend_fake(monkeypatch)

    with TestClient(app, base_url="http://localhost:36000") as client:
        info = client.get("/api/agents/claude-demo/chat/info")
        missing = client.post(
            "/api/agents/nope/chat",
            json={"message": "hello", "session": "gui:one"},
        )

    assert info.status_code == 200
    assert info.json() == {"supported": True, "type": "claude"}
    assert missing.status_code == 404

    _seed_hosts(isolated_config, status="failed")
    with TestClient(app, base_url="http://localhost:36000") as client:
        inactive = client.post(
            "/api/agents/claude-demo/chat",
            json={"message": "hello", "session": "gui:one"},
        )

    assert inactive.status_code == 409
    assert inactive.json()["detail"] == "Agent is not installed"
    assert backend_cls.instances == []


@pytest.mark.anyio
async def test_claude_sse_cancellation_closes_backend_and_allows_same_session_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A browser disconnect must not strand its cached Claude UUID lock."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowThenReadyBackend:
        instances: list[SlowThenReadyBackend] = []

        def __init__(self, **_kwargs: Any) -> None:
            self.calls = 0
            self.closed = 0
            self.instances.append(self)

        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            self.closed += 1

        async def send_message(self, **_kwargs: Any) -> str:
            self.calls += 1
            if self.calls == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return "retry succeeded"

    monkeypatch.setattr(agents_module, "ClaudeCodeChatBackend", SlowThenReadyBackend)
    host = {"hostname": "192.168.1.100"}
    agent = {"agent_name": "claude-demo"}
    request = agents_module.ChatRequest(message="slow", session="gui:one")
    response = await agents_module._chat_claude(host, agent, "claude-demo", request)
    iterator = response.body_iterator

    next_event = asyncio.create_task(anext(iterator))
    await asyncio.wait_for(started.wait(), timeout=1)
    next_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_event
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)

    backend = SlowThenReadyBackend.instances[0]
    session = agents_module._CLAUDE_BROWSER_SESSIONS[("claude-demo", "gui:one")]
    assert cancelled.is_set()
    assert backend.closed == 1
    assert session.lock.locked() is False

    retry_response = await agents_module._chat_claude(
        host,
        agent,
        "claude-demo",
        agents_module.ChatRequest(message="retry", session="gui:one"),
    )
    retry_iterator = retry_response.body_iterator
    content_event = await anext(retry_iterator)
    assert json.loads(content_event.removeprefix("data: ").strip()) == {
        "type": "content",
        "text": "retry succeeded",
    }
    assert await anext(retry_iterator) == "data: [DONE]\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(retry_iterator)
    assert backend.calls == 2
    assert backend.closed == 2


@pytest.mark.anyio
async def test_claude_sse_http_disconnect_cleans_up_and_allows_same_session_retry(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise an actual StreamingResponse disconnect, not only its generator."""
    _seed_hosts(isolated_config)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowThenReadyBackend:
        instances: list[SlowThenReadyBackend] = []

        def __init__(self, **_kwargs: Any) -> None:
            self.calls = 0
            self.closed = 0
            self.instances.append(self)

        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            self.closed += 1

        async def send_message(self, **_kwargs: Any) -> str:
            self.calls += 1
            if self.calls == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return "retry succeeded"

    monkeypatch.setattr(agents_module, "ClaudeCodeChatBackend", SlowThenReadyBackend)
    body = json.dumps({"message": "slow", "session": "gui:one"}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/agents/claude-demo/chat",
        "raw_path": b"/api/agents/claude-demo/chat",
        "query_string": b"",
        "headers": [
            (b"host", b"localhost:36000"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 36000),
        "root_path": "",
    }
    sent: list[dict[str, Any]] = []
    received_body = False

    async def receive_disconnect() -> dict[str, Any]:
        nonlocal received_body
        if not received_body:
            received_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await started.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    request_task = asyncio.create_task(app(scope, receive_disconnect, send))
    await asyncio.wait_for(request_task, timeout=1)

    backend = SlowThenReadyBackend.instances[0]
    session = agents_module._CLAUDE_BROWSER_SESSIONS[("claude-demo", "gui:one")]
    assert cancelled.is_set()
    assert backend.closed == 1
    assert session.lock.locked() is False
    assert not any(
        b"[DONE]" in message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )

    retry_body = json.dumps({"message": "retry", "session": "gui:one"}).encode()
    retry_sent: list[dict[str, Any]] = []
    retry_received_body = False
    never = asyncio.Event()

    async def receive_retry() -> dict[str, Any]:
        nonlocal retry_received_body
        if not retry_received_body:
            retry_received_body = True
            return {
                "type": "http.request",
                "body": retry_body,
                "more_body": False,
            }
        await never.wait()
        raise AssertionError("StreamingResponse should cancel its disconnect listener")

    async def send_retry(message: dict[str, Any]) -> None:
        retry_sent.append(message)

    await asyncio.wait_for(
        app(scope, receive_retry, send_retry),
        timeout=1,
    )

    retry_events = b"".join(
        message.get("body", b"")
        for message in retry_sent
        if message["type"] == "http.response.body"
    )
    assert b'"text": "retry succeeded"' in retry_events
    assert b"data: [DONE]" in retry_events
    assert backend.calls == 2
    assert backend.closed == 2

"""Tests for core OpenClaw chat client."""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.exceptions import WebSocketException

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
    OpenClawChatClient,
    SecretStr,
)


class FakeWebSocket:
    """Deterministic fake websocket for request/response testing."""

    def __init__(self, frames: list[object]):
        self._frames = frames[:]
        self.sent: list[dict] = []
        self.closed = False

    async def recv(self) -> object:
        if not self._frames:
            raise RuntimeError("No more frames")
        next_frame = self._frames.pop(0)
        if isinstance(next_frame, Exception):
            raise next_frame
        if isinstance(next_frame, bytes):
            return next_frame
        if isinstance(next_frame, str):
            return next_frame
        return json.dumps(next_frame)

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self) -> None:
        self.closed = True


def test_connect_success(monkeypatch):
    frames = [
        {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": "abc123", "ts": 1234},
        },
        {
            "type": "res",
            "id": "1",
            "ok": True,
            "payload": {"type": "hello-ok", "protocol": 3},
        },
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    asyncio.run(client.connect())

    assert len(fake_ws.sent) == 1
    req = fake_ws.sent[0]
    assert req["method"] == "connect"
    assert req["params"]["auth"]["token"] == "secret-token"


def test_secret_str_masks_repr():
    secret = SecretStr("very-secret")
    assert repr(secret) == "***"
    assert str(secret) == "***"


def test_send_message_streams_and_returns_final(monkeypatch):
    frames = [
        {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": "abc123", "ts": 1234},
        },
        {
            "type": "res",
            "id": "1",
            "ok": True,
            "payload": {"type": "hello-ok", "protocol": 3},
        },
        {"type": "res", "id": "2", "ok": True, "payload": {"runId": "run-42"}},
        {
            "type": "event",
            "event": "chat",
            "payload": {"runId": "run-42", "state": "delta", "delta": "Hello"},
        },
        {
            "type": "event",
            "event": "chat",
            "payload": {
                "runId": "run-42",
                "state": "final",
                "message": {"content": "Hello from assistant"},
            },
        },
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    asyncio.run(client.connect())

    chunks: list[str] = []
    result = asyncio.run(client.send_message("hello", "main", on_delta=chunks.append))

    assert "Hello" in chunks
    assert result == "Hello from assistant"
    assert fake_ws.sent[1]["method"] == "chat.send"
    assert fake_ws.sent[1]["params"]["message"] == "hello"


def test_connect_raises_auth_error(monkeypatch):
    frames = [
        {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": "abc123", "ts": 1234},
        },
        {
            "type": "res",
            "id": "1",
            "ok": False,
            "error": {"message": "unauthorized"},
        },
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "bad-token")
    with pytest.raises(ChatAuthenticationError):
        asyncio.run(client.connect())


def test_connect_rejects_non_websocket_scheme():
    client = OpenClawChatClient("http://test-host:40123", "token")
    with pytest.raises(ChatConnectionError):
        asyncio.run(client.connect())


def test_send_message_raises_on_failed_response(monkeypatch):
    frames = [
        {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": "abc123", "ts": 1234},
        },
        {
            "type": "res",
            "id": "1",
            "ok": True,
            "payload": {"type": "hello-ok", "protocol": 3},
        },
        {
            "type": "res",
            "id": "2",
            "ok": False,
            "error": {"message": "chat denied"},
        },
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    asyncio.run(client.connect())

    with pytest.raises(ChatProtocolError):
        asyncio.run(client.send_message("hello", "main"))


def test_send_message_raises_on_missing_payload(monkeypatch):
    frames = [
        {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": "abc123", "ts": 1234},
        },
        {
            "type": "res",
            "id": "1",
            "ok": True,
            "payload": {"type": "hello-ok", "protocol": 3},
        },
        {"type": "res", "id": "2", "ok": True},
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    asyncio.run(client.connect())

    with pytest.raises(ChatProtocolError):
        asyncio.run(client.send_message("hello", "main"))


def test_send_message_raises_on_missing_run_id(monkeypatch):
    frames = [
        {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": "abc123", "ts": 1234},
        },
        {
            "type": "res",
            "id": "1",
            "ok": True,
            "payload": {"type": "hello-ok", "protocol": 3},
        },
        {"type": "res", "id": "2", "ok": True, "payload": {}},
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    asyncio.run(client.connect())

    with pytest.raises(ChatProtocolError):
        asyncio.run(client.send_message("hello", "main"))


def test_send_message_raises_on_chat_error_event(monkeypatch):
    frames = [
        {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": "abc123", "ts": 1234},
        },
        {
            "type": "res",
            "id": "1",
            "ok": True,
            "payload": {"type": "hello-ok", "protocol": 3},
        },
        {"type": "res", "id": "2", "ok": True, "payload": {"runId": "run-42"}},
        {
            "type": "event",
            "event": "chat",
            "payload": {
                "runId": "run-42",
                "state": "error",
                "errorMessage": "execution failed",
            },
        },
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    asyncio.run(client.connect())

    with pytest.raises(ChatProtocolError):
        asyncio.run(client.send_message("hello", "main"))


def test_recv_json_rejects_non_text_frame(monkeypatch):
    fake_ws = FakeWebSocket([b"binary-frame"])

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    client._ws = fake_ws

    with pytest.raises(ChatProtocolError):
        asyncio.run(client._recv_json(timeout=1))


def test_recv_json_rejects_invalid_json(monkeypatch):
    fake_ws = FakeWebSocket(["{not-json}"])

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    client._ws = fake_ws

    with pytest.raises(ChatProtocolError):
        asyncio.run(client._recv_json(timeout=1))


def test_recv_json_handles_connection_loss(monkeypatch):
    fake_ws = FakeWebSocket([WebSocketException("lost")])

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    client._ws = fake_ws

    with pytest.raises(ChatConnectionError):
        asyncio.run(client._recv_json(timeout=1))

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


# ---------------------------------------------------------------------------
# B2 + W1 (ATX iter-4 #719): pin the cross-platform pairing invariant
# and the protocol-3..4 negotiation on the wire. A regression that
# reverts `platform` back to a hardcoded string OR drops the
# `maxProtocol` bump from 4 to 3 would otherwise pass every other
# chat test silently and only surface live against openclaw v2026.6.9
# (protocol-4-only) or on a cross-platform operator/agent install.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sys_platform_value, expected_normalized",
    [
        ("linux", "linux"),
        ("darwin", "darwin"),
        ("win32", "win32"),
        # Versioned POSIX shapes must be stripped so the value matches
        # what Node's `process.platform` (= bare family) records on
        # the daemon side at pair time.
        ("freebsd13", "freebsd"),
        ("openbsd6.9", "openbsd"),
    ],
)
def test_connect_sends_normalized_operator_platform(
    monkeypatch, sys_platform_value, expected_normalized
):
    """The `client.platform` field on the wire MUST be the normalized
    operator platform (matching the value the install pair script
    persisted). The openclaw daemon rejects any subsequent connect
    with a different `platform` as 'device identity changed'."""
    import sys as _sys

    monkeypatch.setattr(_sys, "platform", sys_platform_value)

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
            "payload": {"type": "hello-ok", "protocol": 4},
        },
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    asyncio.run(client.connect())

    req = fake_ws.sent[0]
    assert req["params"]["client"]["platform"] == expected_normalized, (
        f"client.platform must match Node's process.platform shape "
        f"(install pair side); sys.platform={sys_platform_value!r} "
        f"normalized → {expected_normalized!r}, got "
        f"{req['params']['client']['platform']!r}"
    )


def test_connect_negotiates_protocol_3_to_4(monkeypatch):
    """W1 (ATX iter-4): openclaw v2026.6.9 dropped protocol 3 — the
    daemon rejects min=3/max=3 handshakes with 'expected=4 probeMin=4'
    (verified live against esper-mac-oc, see
    .itx/719/01_EXECUTION.md). The client must advertise minProtocol=3
    (compat with older daemons still on proto 3) AND maxProtocol=4
    (compat with v2026.6.9+). A revert to max=3 would silently break
    every chat session against a v2026.6.9+ host."""
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
            "payload": {"type": "hello-ok", "protocol": 4},
        },
    ]
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat.websockets.connect", fake_connect)

    client = OpenClawChatClient("ws://test-host:40123", "secret-token")
    asyncio.run(client.connect())

    req = fake_ws.sent[0]
    assert req["params"]["minProtocol"] == 3
    assert req["params"]["maxProtocol"] == 4


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

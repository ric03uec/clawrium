"""Tests for the ZeroClaw chat backend (`core/chat_zeroclaw.py`).

Coverage required by issue #357 (Subtask B, B7):
- connect_success / connect_failure / auth_error
- streaming chunk frames feed on_delta and accumulate
- done frame terminates the turn (prefers full_response)
- error frame raises ChatProtocolError
- aborted frame raises ChatProtocolError (silently ignoring would hang)
- chunk_reset clears the accumulator mid-turn
- approval_request surfaces (raises until inline UX exists)
- protocol_conformance: unknown frame types are dropped, not errored
"""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.exceptions import WebSocketException

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
    SecretStr,
)
from clawrium.core.chat_zeroclaw import ZeroClawChatBackend


class FakeWebSocket:
    """Deterministic fake WebSocket for ZeroClaw frame tests."""

    def __init__(self, frames: list[object]):
        self._frames = list(frames)
        self.sent: list[dict] = []
        self.closed = False

    async def recv(self) -> object:
        if not self._frames:
            raise RuntimeError("No more frames queued")
        frame = self._frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        if isinstance(frame, (str, bytes)):
            return frame
        return json.dumps(frame)

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self) -> None:
        self.closed = True


def _make_backend(monkeypatch, frames):
    fake_ws = FakeWebSocket(frames)

    async def fake_connect(*_args, **_kwargs):
        return fake_ws

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)
    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr("paired-bearer-token"),
        timeout_seconds=5.0,
    )
    return backend, fake_ws


# ---------------------------------------------------------------------------
# Connect tests
# ---------------------------------------------------------------------------


def test_connect_success(monkeypatch):
    """Connect opens the WS and forwards the bearer token in the Auth header."""
    captured: dict[str, object] = {}

    async def fake_connect(url, additional_headers=None, **_kwargs):
        captured["url"] = url
        captured["headers"] = additional_headers
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr("paired-bearer-token"),
    )
    asyncio.run(backend.connect())

    assert captured["url"] == "ws://test-host:4080/ws/chat"
    # Auth header carries the bearer scheme. List-of-tuples form is what
    # the websockets library accepts; assert the token is present and the
    # scheme word stays in place so a future refactor doesn't strip it.
    headers = dict(captured["headers"])
    assert headers["Authorization"] == "Bearer paired-bearer-token"


def test_connect_failure(monkeypatch):
    """OSError during the WS handshake surfaces as ChatConnectionError."""

    async def fake_connect(*_args, **_kwargs):
        raise OSError("Connection refused")

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://nowhere:4080/ws/chat",
        auth_token=SecretStr("bearer"),
    )
    with pytest.raises(ChatConnectionError):
        asyncio.run(backend.connect())


def test_auth_error(monkeypatch):
    """A 401 from the gateway surfaces as ChatAuthenticationError so the
    CLI can route the user to `clawctl agent configure`."""
    from websockets.exceptions import InvalidStatus

    class _FakeResponse:
        status_code = 401
        headers: dict = {}
        body = b""

    async def fake_connect(*_args, **_kwargs):
        raise InvalidStatus(_FakeResponse())

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr("wrong-token"),
    )
    with pytest.raises(ChatAuthenticationError):
        asyncio.run(backend.connect())


def test_connect_rejects_empty_bearer():
    """An empty bearer must fail before opening the socket — the gateway
    would 401 anyway, but failing early surfaces a clearer error message."""
    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr(""),
    )
    with pytest.raises(ChatAuthenticationError):
        asyncio.run(backend.connect())


def test_backend_appends_agent_alias_query(monkeypatch):
    """#817: zeroclaw ≥0.8.2 requires `?agent=<alias>` on the /ws/chat
    upgrade. The backend must synthesize the query param from the
    caller-supplied alias — the CLI passes the agent instance name."""
    captured: dict[str, object] = {}

    async def fake_connect(url, additional_headers=None, **_kwargs):
        captured["url"] = url
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr("bearer"),
        agent_alias="my-agent",
    )
    asyncio.run(backend.connect())

    assert captured["url"] == "ws://test-host:4080/ws/chat?agent=my-agent"
    # Public attribute reflects the mutation so operators inspecting
    # the backend after construction see the URL that will actually be
    # dialed. Prevents "silent divergence" between the field and the
    # `websockets.connect` argument.
    assert backend.gateway_url == "ws://test-host:4080/ws/chat?agent=my-agent"


def test_backend_agent_alias_is_idempotent(monkeypatch):
    """If the persisted URL already has `?agent=…`, don't double-append."""
    captured: dict[str, object] = {}

    async def fake_connect(url, additional_headers=None, **_kwargs):
        captured["url"] = url
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat?agent=preset",
        auth_token=SecretStr("bearer"),
        agent_alias="my-agent",
    )
    asyncio.run(backend.connect())

    # `preset` wins because the persisted URL is the operator's stated
    # intent. Rewriting it would violate least-surprise.
    assert captured["url"] == "ws://test-host:4080/ws/chat?agent=preset"


def test_backend_no_alias_leaves_url_untouched(monkeypatch):
    """`agent_alias=None` preserves legacy 0.7.5 URLs verbatim — the daemon
    on that pin has no `?agent=` requirement, so appending would be a
    silent behavior change for pre-0.8.2 hosts."""
    captured: dict[str, object] = {}

    async def fake_connect(url, additional_headers=None, **_kwargs):
        captured["url"] = url
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr("bearer"),
    )
    asyncio.run(backend.connect())

    assert captured["url"] == "ws://test-host:4080/ws/chat"


# ---------------------------------------------------------------------------
# Frame parsing tests
# ---------------------------------------------------------------------------


def test_streaming_chunk_frames(monkeypatch):
    """chunk frames feed on_delta in order and accumulate for the return."""
    frames = [
        {"type": "session_start"},
        {"type": "chunk", "content": "Hello"},
        {"type": "chunk", "content": ", "},
        {"type": "chunk", "content": "world!"},
        {"type": "done"},  # no full_response — fall back to accumulator
    ]
    backend, fake_ws = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    deltas: list[str] = []
    result = asyncio.run(
        backend.send_message("hi", on_delta=lambda d: deltas.append(d))
    )

    assert deltas == ["Hello", ", ", "world!"]
    assert result == "Hello, world!"
    assert fake_ws.sent == [{"type": "message", "content": "hi"}]


def test_done_frame_terminates(monkeypatch):
    """done with full_response is used as the return value even when
    chunks were streamed (mirrors the server having authoritative text)."""
    frames = [
        {"type": "chunk", "content": "Hel"},
        {"type": "chunk", "content": "lo"},
        {
            "type": "done",
            "full_response": "Hello, world! (authoritative)",
            "tokens_in": 5,
            "tokens_out": 10,
        },
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    result = asyncio.run(backend.send_message("hi"))
    assert result == "Hello, world! (authoritative)"


def test_error_frame_raises(monkeypatch):
    """error frames raise ChatProtocolError with the server message."""
    frames = [
        {"type": "chunk", "content": "Partial..."},
        {"type": "error", "message": "Provider rate limited"},
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatProtocolError, match="rate limited"):
        asyncio.run(backend.send_message("hi"))


def test_aborted_frame_raises_ChatProtocolError(monkeypatch):
    """aborted MUST raise — silently ignoring it would cause the REPL to
    hang waiting for a `done` that never arrives."""
    frames = [
        {"type": "chunk", "content": "Partial..."},
        {"type": "aborted", "reason": "user cancelled"},
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatProtocolError, match="aborted"):
        asyncio.run(backend.send_message("hi"))


def test_chunk_reset_clears_accumulator(monkeypatch):
    """chunk_reset drops everything streamed before it. The final return
    must reflect post-reset content only.

    `on_delta` callers can't un-print, but the accumulator is the source
    of truth for the return value when `done` lacks full_response. A
    correct return is what gets persisted in REPL state / piped to
    follow-on tooling, so it must be the post-reset text."""
    frames = [
        {"type": "chunk", "content": "throwaway-A "},
        {"type": "chunk", "content": "throwaway-B"},
        {"type": "chunk_reset"},
        {"type": "chunk", "content": "kept-1 "},
        {"type": "chunk", "content": "kept-2"},
        {"type": "done"},
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    deltas: list[str] = []
    result = asyncio.run(
        backend.send_message("hi", on_delta=lambda d: deltas.append(d))
    )

    # on_delta was called for the pre-reset chunks too (we can't un-print).
    assert "throwaway-A " in deltas
    # But the accumulator-based return value must NOT include them.
    assert result == "kept-1 kept-2"


def test_approval_request_surfaces_or_raises(monkeypatch):
    """approval_request raises ChatProtocolError until inline approval UX
    exists. The decision is documented in .itx/357/01_EXECUTION.md."""
    frames = [
        {"type": "chunk", "content": "Looking at the codebase..."},
        {
            "type": "approval_request",
            "request_id": "req-1",
            "tool": "shell",
            "command": "rm -rf /",
        },
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatProtocolError, match="approval"):
        asyncio.run(backend.send_message("hi"))


def test_approval_request_closes_socket_before_raising(monkeypatch):
    """ATX Round 1 W2 / Round 3 W11: approval_request must close the
    WebSocket before raising so the REPL can't loop into a half-broken
    connection.

    Without the close, the server is blocked awaiting an
    `approval_response` frame and the next user message either hits a
    repeated approval_request (infinite loop) or a silent hang."""
    frames = [
        {
            "type": "approval_request",
            "request_id": "req-1",
            "tool": "shell",
        },
    ]
    backend, fake_ws = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatProtocolError):
        asyncio.run(backend.send_message("hi"))

    # close() must have fired before the raise so the REPL's `except
    # ChatProtocolError` branch doesn't keep using a stuck socket.
    assert fake_ws.closed is True
    # ATX Round 3 W11: ALSO assert is_connected — the REPL break
    # contract reads `getattr(backend, 'is_connected', True)`, not
    # the underlying WS attribute. A refactor that keeps `_ws` set
    # while flagging `closed=True` would silently break the REPL.
    assert backend.is_connected is False


def test_approval_request_sanitizes_prompt_field(monkeypatch):
    """ATX Round 1 B6: the `prompt` field on approval_request must pass
    through bidi/control-char sanitization before reaching the error
    message. A malicious server could otherwise smuggle bidi marks
    into the terminal via the surfaced exception."""
    # RLO embedded in a "harmless" prompt.
    poisoned_prompt = "run this command‮; rm -rf / ;"
    frames = [
        {
            "type": "approval_request",
            "request_id": "req-1",
            "tool": "shell",
            "prompt": poisoned_prompt,
        },
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatProtocolError) as excinfo:
        asyncio.run(backend.send_message("hi"))

    # The bidi codepoint must NOT appear in the exception text.
    assert "‮" not in str(excinfo.value)
    # But the prompt content (post-sanitization) does, so the user can
    # still identify which approval was triggered.
    assert "rm -rf" in str(excinfo.value)


def test_cleartext_warning_emitted_for_non_loopback_ws(monkeypatch, caplog):
    """ATX Round 1 W9: a non-TLS WebSocket to a non-loopback host emits
    a warning (the bearer token would traverse the LAN cleartext)."""
    import logging

    async def fake_connect(*_args, **_kwargs):
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://pi-edge.lan:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )

    with caplog.at_level(logging.WARNING, logger="clawrium.core.chat_zeroclaw"):
        asyncio.run(backend.connect())

    assert any("cleartext" in rec.message for rec in caplog.records)


def test_cleartext_warning_suppressed_for_loopback(monkeypatch, caplog):
    """ATX Round 1 W9: loopback hosts must NOT trigger the cleartext
    warning — the LAN-exposure threat doesn't apply on 127.0.0.1."""
    import logging

    async def fake_connect(*_args, **_kwargs):
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://127.0.0.1:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )

    with caplog.at_level(logging.WARNING, logger="clawrium.core.chat_zeroclaw"):
        asyncio.run(backend.connect())

    assert not any("cleartext" in rec.message for rec in caplog.records)


def test_protocol_conformance(monkeypatch):
    """Unknown frame types are dropped (forward-compat) rather than
    raising. ZeroClaw may add frame types between releases; the REPL
    should not crash on a tag it doesn't recognize."""
    frames = [
        {"type": "unknown-future-event", "payload": "ignored"},
        {"type": "chunk", "content": "Hello"},
        {"type": "another-future", "data": {"x": 1}},
        {"type": "done"},
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    result = asyncio.run(backend.send_message("hi"))
    assert result == "Hello"


def test_thinking_frame_does_not_pollute_accumulator(monkeypatch):
    """thinking frames are advisory — they reach on_delta but must NOT
    feed the assistant-text accumulator (the return value should be the
    reply, not the chain-of-thought)."""
    frames = [
        {"type": "thinking", "content": "Let me consider..."},
        {"type": "chunk", "content": "The answer is 42."},
        {"type": "done"},
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    deltas: list[str] = []
    result = asyncio.run(
        backend.send_message("hi", on_delta=lambda d: deltas.append(d))
    )

    # Thinking surfaced to the user with a discoverable prefix.
    assert any("thinking" in d.lower() for d in deltas)
    # Return value is the chunk text only, not the thinking text.
    assert result == "The answer is 42."


def test_sanitizes_bidi_in_chunk_content(monkeypatch):
    """A `chunk` carrying bidi/zero-width characters must be stripped
    before reaching on_delta — same coverage as chat_hermes' sanitizer.
    Closes the "malicious server smuggles RLO/LRM into the terminal"
    threat."""
    # U+202E (RLO) + U+200B (ZWSP) embedded in legitimate text.
    poisoned = "safe‮DANGER​text"
    frames = [
        {"type": "chunk", "content": poisoned},
        {"type": "done"},
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    deltas: list[str] = []
    result = asyncio.run(
        backend.send_message("hi", on_delta=lambda d: deltas.append(d))
    )

    # Both bidi codepoints are stripped.
    assert "‮" not in deltas[0]
    assert "​" not in deltas[0]
    # The non-control characters survive.
    assert "safe" in result and "DANGER" in result and "text" in result


def test_send_message_not_connected_raises():
    """Calling send_message before connect() raises a clear error."""
    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )
    with pytest.raises(ChatConnectionError):
        asyncio.run(backend.send_message("hi"))


def test_malformed_json_frame_raises_protocol_error(monkeypatch):
    """A non-JSON frame from the gateway raises ChatProtocolError so the
    REPL can show a clean error rather than a JSONDecodeError stack."""
    frames = ["not valid json {"]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatProtocolError):
        asyncio.run(backend.send_message("hi"))


def test_non_dict_frame_raises_protocol_error(monkeypatch):
    """A JSON-array frame (legal JSON but not the expected envelope)
    raises ChatProtocolError. Guards against a malformed server."""
    frames = ['["chunk", "content"]']
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatProtocolError):
        asyncio.run(backend.send_message("hi"))


def test_connection_lost_during_send_raises(monkeypatch):
    """WS connection drop during send_message raises ChatConnectionError."""
    frames = [WebSocketException("connection lost")]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatConnectionError):
        asyncio.run(backend.send_message("hi"))


def test_close_is_idempotent(monkeypatch):
    """Multiple close() calls must not raise."""
    backend, fake_ws = _make_backend(monkeypatch, [])
    asyncio.run(backend.connect())
    asyncio.run(backend.close())
    asyncio.run(backend.close())
    assert fake_ws.closed is True


def test_is_connected_reflects_socket_state(monkeypatch):
    """ATX Round 2 W2: `is_connected` is the contract the REPL uses to
    decide between continuing the chat session and breaking. It must
    track the WebSocket's actual state."""
    backend, _ = _make_backend(monkeypatch, [])
    assert backend.is_connected is False
    asyncio.run(backend.connect())
    assert backend.is_connected is True
    asyncio.run(backend.close())
    assert backend.is_connected is False


def test_connect_asyncio_timeout_raises_ChatConnectionError(monkeypatch):
    """ATX Round 2 W3 (pins B5): explicitly raise asyncio.TimeoutError
    (the class distinct from builtins.TimeoutError on Python 3.10) and
    verify the connect path catches it. Without this test, removing
    `asyncio.TimeoutError` from the catch tuple would pass all other
    tests on Python 3.11+ (where the two classes are aliased) but
    crash production on 3.10."""

    async def fake_connect(*_args, **_kwargs):
        raise asyncio.TimeoutError("simulated open_timeout")

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr("bearer"),
    )
    with pytest.raises(ChatConnectionError):
        asyncio.run(backend.connect())


def test_recv_asyncio_timeout_raises_ChatConnectionError(monkeypatch):
    """ATX Round 2 W3 (pins B5) for the recv path. asyncio.wait_for()
    raises asyncio.TimeoutError, not builtins.TimeoutError, on 3.10."""
    backend, _ = _make_backend(monkeypatch, [])
    asyncio.run(backend.connect())

    async def fake_recv():
        raise asyncio.TimeoutError("simulated recv timeout")

    # Replace the WS recv with one that raises asyncio.TimeoutError so
    # _recv_json's `except (TimeoutError, asyncio.TimeoutError)` is the
    # only thing standing between the test and an unhandled exception.
    backend._ws.recv = fake_recv  # type: ignore[attr-defined]

    # The send_message path goes through _send_json (which succeeds —
    # the fake WebSocket buffers the send) and then awaits _recv_json,
    # which will raise the timeout above.
    with pytest.raises(ChatConnectionError, match="Timed out"):
        asyncio.run(backend.send_message("hi"))


def test_non_auth_http_error_raises_ChatConnectionError(monkeypatch):
    """ATX Round 2 S6: 503/500-class InvalidStatus must surface as
    ChatConnectionError, NOT ChatAuthenticationError. Only 401/403
    means "auth is wrong"; other HTTP errors mean the gateway is up
    but unhappy."""
    from websockets.exceptions import InvalidStatus

    class _FakeResponse:
        status_code = 503
        headers: dict = {}
        body = b""

    async def fake_connect(*_args, **_kwargs):
        raise InvalidStatus(_FakeResponse())

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://test-host:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )
    with pytest.raises(ChatConnectionError, match="503"):
        asyncio.run(backend.connect())


def test_cleartext_warning_suppressed_for_localhost_string(monkeypatch, caplog):
    """ATX Round 3 W7: `localhost` (the string literal) is a loopback
    form even though it isn't a valid `ipaddress.ip_address()` argument.
    Pre-fix, a naive `ipaddress` check would raise ValueError and the
    warning helper would either crash or fall through to emit a false
    cleartext warning."""
    import logging

    async def fake_connect(*_args, **_kwargs):
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://localhost:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )

    with caplog.at_level(logging.WARNING, logger="clawrium.core.chat_zeroclaw"):
        asyncio.run(backend.connect())

    assert not any("cleartext" in rec.message for rec in caplog.records)


def test_cleartext_warning_suppressed_for_ipv6_loopback(monkeypatch, caplog):
    """ATX Round 3 W7: `::1` is the IPv6 loopback and must be recognized."""
    import logging

    async def fake_connect(*_args, **_kwargs):
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="ws://[::1]:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )

    with caplog.at_level(logging.WARNING, logger="clawrium.core.chat_zeroclaw"):
        asyncio.run(backend.connect())

    assert not any("cleartext" in rec.message for rec in caplog.records)


def test_cleartext_warning_suppressed_for_etc_hosts_loopback(monkeypatch, caplog):
    """ATX Round 4 W-C / Round 5 W-3: a hostname that resolves to a
    loopback address (e.g. `mydev.local` in /etc/hosts) must skip the
    cleartext warning. The negative assertion (no warning emitted) is
    fragile on its own — code that short-circuits before the resolver
    call would satisfy it vacuously. Pin the contract by also asserting
    `getaddrinfo` was actually invoked with the expected host."""
    import logging
    import socket

    async def fake_connect(*_args, **_kwargs):
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    resolver_calls: list[str] = []

    def fake_getaddrinfo(host, *_args, **_kwargs):
        resolver_calls.append(host)
        # Resolve mydev.local -> 127.0.0.1 (mirrors /etc/hosts behavior).
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(
        "clawrium.core.chat_zeroclaw.socket.getaddrinfo", fake_getaddrinfo
    )

    backend = ZeroClawChatBackend(
        gateway_url="ws://mydev.local:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )

    with caplog.at_level(logging.WARNING, logger="clawrium.core.chat_zeroclaw"):
        asyncio.run(backend.connect())

    # No cleartext warning landed in the log stream.
    assert not any("cleartext" in rec.message for rec in caplog.records)
    # Resolver actually ran against the configured host — the negative
    # assertion above isn't a vacuous pass.
    assert "mydev.local" in resolver_calls, (
        f"Expected getaddrinfo to be called with 'mydev.local'; saw {resolver_calls!r}"
    )


def test_cleartext_warning_emitted_when_resolver_fails(monkeypatch, caplog):
    """ATX Round 4 W-C: when getaddrinfo fails (DNS hiccup, isolated
    container, etc.) for a non-literal-loopback host, the warning MUST
    still fire — false positive is preferable to silent miss of a real
    cleartext exposure."""
    import logging
    import socket

    async def fake_connect(*_args, **_kwargs):
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    def fake_getaddrinfo(*_args, **_kwargs):
        raise socket.gaierror("no resolver available")

    monkeypatch.setattr(
        "clawrium.core.chat_zeroclaw.socket.getaddrinfo", fake_getaddrinfo
    )

    backend = ZeroClawChatBackend(
        gateway_url="ws://some-host.lan:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )

    with caplog.at_level(logging.WARNING, logger="clawrium.core.chat_zeroclaw"):
        asyncio.run(backend.connect())

    assert any("cleartext" in rec.message for rec in caplog.records), (
        "Expected the cleartext warning to fire when resolver fails; "
        "silent suppression would mask a real LAN exposure."
    )


def test_tool_call_frame_sanitizes_name_and_args(monkeypatch):
    """ATX Round 4 W-D / Round 5 W-2: tool_call frames pass through
    on_delta with the tool name + JSON-encoded arguments. RLO codepoints
    embedded in EITHER the `name` field OR any `arguments` value MUST
    be stripped before reaching the renderer."""
    frames = [
        {
            "type": "tool_call",
            "name": "shell‮tool",  # RLO embedded in name
            "arguments": {
                "cmd": "ls‮ -la",  # RLO embedded in an argument VALUE
                "cwd": "/tmp",
            },
        },
        {"type": "done"},
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    deltas: list[str] = []
    asyncio.run(backend.send_message("hi", on_delta=lambda d: deltas.append(d)))

    # NO RLO codepoint anywhere in any emitted delta — neither from the
    # name field nor from the argument values. A regression that drops
    # sanitization from the JSON-encoded arguments path would surface
    # the RLO here.
    assert not any("‮" in d for d in deltas), deltas
    # The legitimate tool name parts survive sanitization.
    assert any("shell" in d and "tool" in d for d in deltas), deltas
    # The arguments JSON renders into the delta line (legitimate text
    # survives, RLO is gone).
    assert any("ls" in d and "-la" in d for d in deltas), deltas


def test_tool_result_frame_delivered_via_on_delta(monkeypatch):
    """ATX Round 4 W-D: tool_result frames are advisory output and
    must reach on_delta with the [tool_result] prefix."""
    frames = [
        {"type": "tool_result", "content": "command output here"},
        {"type": "done"},
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    deltas: list[str] = []
    asyncio.run(backend.send_message("hi", on_delta=lambda d: deltas.append(d)))

    assert any("[tool_result]" in d and "command output here" in d for d in deltas), (
        deltas
    )


def test_valid_utf8_bytes_frame_is_decoded(monkeypatch):
    """ATX Round 4 W-E: a `bytes` WebSocket frame carrying valid UTF-8
    must be decoded and parsed transparently. Servers occasionally send
    text frames as binary depending on the proxy chain."""
    frames = [
        b'{"type": "chunk", "content": "Hello"}',
        b'{"type": "done"}',
    ]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    result = asyncio.run(backend.send_message("hi"))
    assert result == "Hello"


def test_invalid_utf8_bytes_frame_raises_protocol_error(monkeypatch):
    """ATX Round 4 W-E: a `bytes` frame with invalid UTF-8 surfaces as
    ChatProtocolError, not a raw UnicodeDecodeError."""
    frames = [b"\xff\xfe invalid utf-8"]
    backend, _ = _make_backend(monkeypatch, frames)
    asyncio.run(backend.connect())

    with pytest.raises(ChatProtocolError):
        asyncio.run(backend.send_message("hi"))


def test_cleartext_warning_suppressed_for_wss_non_loopback(monkeypatch, caplog):
    """ATX Round 2 S6: a `wss://` URL to a non-loopback host must NOT
    trigger the cleartext warning — TLS protects the bearer token in
    transit."""
    import logging

    async def fake_connect(*_args, **_kwargs):
        return FakeWebSocket([])

    monkeypatch.setattr("clawrium.core.chat_zeroclaw.websockets.connect", fake_connect)

    backend = ZeroClawChatBackend(
        gateway_url="wss://pi-edge.lan:4080/ws/chat",
        auth_token=SecretStr("paired"),
    )

    with caplog.at_level(logging.WARNING, logger="clawrium.core.chat_zeroclaw"):
        asyncio.run(backend.connect())

    assert not any("cleartext" in rec.message for rec in caplog.records)

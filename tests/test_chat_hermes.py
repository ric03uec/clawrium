"""Unit tests for HermesOpenAIBackend — phases 1, 2, 3.

Covers:
  - Single-turn non-streaming behavior (phase 1).
  - Client-side conversation history accumulation, /reset semantics, and
    failure-atomicity of history mutations (phase 2).
  - SSE streaming with delta accumulation, `[DONE]` sentinel,
    `:keep-alive`/comment handling, multi-line `data:` fields, and
    mid-stream failure surfaces (phase 3).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
    SecretStr,
)
from clawrium.core.chat_hermes import HermesOpenAIBackend


def _build_backend(transport: httpx.MockTransport, **overrides: Any) -> HermesOpenAIBackend:
    backend = HermesOpenAIBackend(
        base_url=overrides.pop("base_url", "http://hermes.test:8642/v1"),
        auth_token=overrides.pop("auth_token", SecretStr("token-abc")),
        model=overrides.pop("model", "hermes"),
        timeout_seconds=overrides.pop("timeout_seconds", 30.0),
    )
    # Replace the client created in connect() with one bound to the mock transport.
    backend._client = httpx.AsyncClient(transport=transport, timeout=30.0)
    return backend


def _run(coro):
    return asyncio.run(coro)


def test_happy_path_returns_assistant_content():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "hi from hermes"}}
                ]
            },
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hello"))
    finally:
        _run(backend.close())

    assert result == "hi from hermes"
    assert captured["url"] == "http://hermes.test:8642/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer token-abc"
    assert captured["body"]["model"] == "hermes"
    assert captured["body"]["stream"] is True
    assert captured["body"]["messages"] == [
        {"role": "user", "content": "hello"}
    ]


def test_send_message_invokes_on_delta_with_full_text():
    """Non-SSE responses fire on_delta once with the entire reply so the
    existing renderer in cli/chat.py works unchanged."""
    deltas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "complete reply"}}]},
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        _run(backend.send_message("ping", on_delta=deltas.append))
    finally:
        _run(backend.close())

    assert deltas == ["complete reply"]


def test_unauthorized_response_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad token")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatAuthenticationError) as excinfo:
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())

    # The exception message must not echo the raw HTTP status — the type
    # alone discriminates auth failures from other errors.
    assert "401" not in str(excinfo.value)
    assert "rejected bearer token" in str(excinfo.value)


def test_forbidden_response_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatAuthenticationError) as excinfo:
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())

    assert "403" not in str(excinfo.value)
    assert "rejected bearer token" in str(excinfo.value)


def test_server_error_raises_protocol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatProtocolError, match="500"):
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())


def test_connect_error_raises_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatConnectionError, match="Failed to reach hermes"):
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())


def test_timeout_raises_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatConnectionError, match="Timed out"):
            _run(backend.send_message("ping", response_timeout_seconds=0.5))
    finally:
        _run(backend.close())


def test_send_without_connect_raises_connection_error():
    backend = HermesOpenAIBackend(
        base_url="http://hermes.test:8642/v1",
        auth_token=SecretStr("tok"),
    )
    with pytest.raises(ChatConnectionError, match="not connected"):
        _run(backend.send_message("ping"))


def test_missing_choices_raises_protocol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatProtocolError, match="missing assistant content"):
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())


def test_non_json_response_raises_protocol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not json at all",
            headers={"content-type": "text/plain"},
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatProtocolError, match="non-JSON"):
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())


def test_base_url_trailing_slash_is_normalized():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    backend = _build_backend(
        httpx.MockTransport(handler), base_url="http://hermes.test:8642/v1/"
    )
    try:
        _run(backend.send_message("ping"))
    finally:
        _run(backend.close())

    assert captured["url"] == "http://hermes.test:8642/v1/chat/completions"


def test_content_blocks_list_is_concatenated():
    """OpenAI-style content blocks (list of {type, text}) collapse to a string."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "part one "},
                                {"type": "text", "text": "part two"},
                            ]
                        }
                    }
                ]
            },
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("ping"))
    finally:
        _run(backend.close())

    assert result == "part one part two"


def test_history_grows_across_turns():
    """Each subsequent request body must carry all prior user+assistant turns."""
    captured_bodies: list[list[dict[str, str]]] = []
    replies = iter(["4", "8", "16"])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        captured_bodies.append(body["messages"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": next(replies)}}]},
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        assert _run(backend.send_message("what's 2+2?")) == "4"
        assert _run(backend.send_message("double that")) == "8"
        assert _run(backend.send_message("double again")) == "16"
    finally:
        _run(backend.close())

    assert captured_bodies[0] == [{"role": "user", "content": "what's 2+2?"}]
    assert captured_bodies[1] == [
        {"role": "user", "content": "what's 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "double that"},
    ]
    assert captured_bodies[2] == [
        {"role": "user", "content": "what's 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "double that"},
        {"role": "assistant", "content": "8"},
        {"role": "user", "content": "double again"},
    ]


def test_history_resumes_accumulating_after_reset():
    """After clear_history(), new turns must accumulate cleanly with no
    pre-reset bleed-through on turn 1 and a correct pair on turn 2."""
    captured_bodies: list[list[dict[str, str]]] = []
    replies = iter(["4", "fresh", "still-fresh"])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        captured_bodies.append(body["messages"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": next(replies)}}]},
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        _run(backend.send_message("what's 2+2?"))
        assert backend._history
        backend.clear_history()
        assert backend._history == []
        _run(backend.send_message("new topic"))
        _run(backend.send_message("follow-up"))
    finally:
        _run(backend.close())

    # Turn after reset: single user message, no pre-reset content.
    assert captured_bodies[1] == [{"role": "user", "content": "new topic"}]
    # Second turn after reset: the freshly-accumulated pair plus the new user
    # message — and crucially, none of the pre-reset history.
    assert captured_bodies[2] == [
        {"role": "user", "content": "new topic"},
        {"role": "assistant", "content": "fresh"},
        {"role": "user", "content": "follow-up"},
    ]


def test_reset_on_empty_history_is_noop():
    """clear_history() before any turn must not raise."""
    backend = HermesOpenAIBackend(
        base_url="http://hermes.test:8642/v1",
        auth_token=SecretStr("tok"),
    )
    backend.clear_history()
    backend.clear_history()
    assert backend._history == []


def test_history_not_appended_on_failure():
    """A failed turn must not corrupt history — a retry sees the original state."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatProtocolError):
            _run(backend.send_message("ping"))
        assert backend._history == []
    finally:
        _run(backend.close())


def test_history_not_corrupted_on_mid_conversation_failure():
    """Two successful turns then a 500 — history must equal pre-failure state."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": f"reply{call_count['n']}"}}]},
            )
        return httpx.Response(500, text="boom")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        _run(backend.send_message("one"))
        _run(backend.send_message("two"))
        pre_failure_snapshot = list(backend._history)
        with pytest.raises(ChatProtocolError):
            _run(backend.send_message("three"))
        assert backend._history == pre_failure_snapshot
        assert len(backend._history) == 4
    finally:
        _run(backend.close())


def test_history_caps_at_max_turns():
    """Once cap is exceeded, oldest entries are dropped while preserving
    user/assistant pair alignment."""
    from clawrium.core.chat_hermes import MAX_HISTORY_TURNS

    captured_bodies: list[list[dict[str, str]]] = []
    n = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        captured_bodies.append(body["messages"])
        n["i"] += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": f"r{n['i']}"}}]},
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        for i in range(MAX_HISTORY_TURNS + 5):
            _run(backend.send_message(f"u{i}"))
    finally:
        _run(backend.close())

    # In-memory state is bounded.
    assert len(backend._history) == MAX_HISTORY_TURNS * 2
    assert backend._history[0]["role"] == "user"
    assert backend._history[1]["role"] == "assistant"
    # Oldest preserved turn is u5 (first 5 turns dropped).
    assert backend._history[0]["content"] == "u5"

    # Wire payload size is bounded too — the request body must never exceed
    # the cap (prior history) + 1 new user message. The overshoot is exactly
    # 1 message because truncation runs *after* the request is sent; that
    # transient overshoot is the documented behavior.
    for i, msgs in enumerate(captured_bodies):
        assert len(msgs) <= MAX_HISTORY_TURNS * 2 + 1, (
            f"turn {i} sent {len(msgs)} messages, exceeds cap+1"
        )

    # Turn 101 (index 100) is the first call where the cap matters: history
    # is full (200 entries) and the new user message makes 201 on the wire.
    assert len(captured_bodies[100]) == MAX_HISTORY_TURNS * 2 + 1
    # Subsequent turns hold steady at the cap+1 size — they don't grow.
    assert len(captured_bodies[104]) == MAX_HISTORY_TURNS * 2 + 1


def test_truncation_notifies_via_last_send_dropped_turns():
    """The REPL polls last_send_dropped_turns after each call; the backend
    must report the number of turns it just trimmed, and reset to 0 on the
    next clean call."""
    from clawrium.core.chat_hermes import MAX_HISTORY_TURNS

    n = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["i"] += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": f"r{n['i']}"}}]},
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        for i in range(MAX_HISTORY_TURNS):
            _run(backend.send_message(f"u{i}"))
            assert backend.last_send_dropped_turns == 0, (
                f"turn {i} should not have dropped anything"
            )
        # Turn 101: history full → exactly 1 pair dropped.
        _run(backend.send_message("u100"))
        assert backend.last_send_dropped_turns == 1
        # Turn 102: still 1 pair dropped per turn.
        _run(backend.send_message("u101"))
        assert backend.last_send_dropped_turns == 1
        # clear_history() resets the counter too.
        backend.clear_history()
        assert backend.last_send_dropped_turns == 0
        _run(backend.send_message("u-fresh"))
        assert backend.last_send_dropped_turns == 0
    finally:
        _run(backend.close())


def test_on_delta_failure_does_not_pollute_history():
    """If on_delta raises (e.g. broken pipe, TUI disconnect), history must
    remain untouched so the next request does not carry a phantom turn."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "would-be-reply"}}]},
        )

    backend = _build_backend(httpx.MockTransport(handler))

    def boom(_text: str) -> None:
        raise RuntimeError("broken pipe")

    try:
        # First turn succeeds and commits history.
        _run(backend.send_message("hello"))
        pre_failure_history = list(backend._history)
        assert len(pre_failure_history) == 2

        # Second turn: on_delta raises. The reply was received but we must
        # not commit the turn — otherwise a retry duplicates it server-side.
        with pytest.raises(RuntimeError, match="broken pipe"):
            _run(backend.send_message("second", on_delta=boom))

        assert backend._history == pre_failure_history, (
            "history was mutated despite on_delta failure"
        )
    finally:
        _run(backend.close())


def test_connection_error_does_not_leak_httpx_internals():
    """httpx exception text (errno codes, file paths, internal types) MUST NOT
    appear in the ChatConnectionError message. The CLI surfaces the error
    string verbatim, so any leakage reaches the user."""
    leaky_message = (
        "[Errno 111] Connection refused; "
        "/usr/lib/python3/dist-packages/httpx/_transports/default.py"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(leaky_message)

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatConnectionError) as excinfo:
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())

    message = str(excinfo.value)
    assert "Errno" not in message
    assert "httpx" not in message
    assert "/usr/lib" not in message
    assert "Failed to reach hermes" in message


def test_protocol_error_body_strips_control_chars():
    """ChatProtocolError messages route response bodies through _short_body,
    which must drop ANSI/control sequences as defence in depth — a future
    caller that bypasses the CLI sanitizer should still not be able to
    smuggle terminal escapes via a 4xx/5xx response body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            content=b"boom\r\x1b[31mred\x1b[0m\x07bell",
            headers={"content-type": "text/plain"},
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatProtocolError) as excinfo:
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())

    message = str(excinfo.value)
    assert "\x1b" not in message
    assert "\r" not in message
    assert "\x07" not in message


def test_http_error_does_not_leak_httpx_internals():
    """Generic httpx.HTTPError (non-connect, non-timeout) also gets sanitized."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.HTTPError("internal httpx error: pool_timeout etc")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatConnectionError) as excinfo:
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())

    message = str(excinfo.value)
    assert "pool_timeout" not in message
    assert "httpx" not in message


def test_connect_is_idempotent():
    """Repeated connect() calls do not replace an existing client (resource leak guard)."""
    backend = HermesOpenAIBackend(
        base_url="http://hermes.test:8642/v1",
        auth_token=SecretStr("tok"),
    )
    _run(backend.connect())
    first_client = backend._client
    _run(backend.connect())
    assert backend._client is first_client
    _run(backend.close())


def _sse_response(body: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream; charset=utf-8"},
        content=body,
    )


def test_streaming_deltas():
    """Canned SSE chunks → on_delta called per delta; final text is concatenation.

    Also pins the streaming request contract: `Accept: text/event-stream`
    header and `stream: true` body field MUST be present so a future
    accidental regression that drops either is caught at unit-test time.
    """
    deltas: list[str] = []
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["accept"] = request.headers.get("accept")
        captured["body"] = json.loads(request.content.decode())
        body = (
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":", "}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"world!"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return _sse_response(body)

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hi", on_delta=deltas.append))
    finally:
        _run(backend.close())

    assert deltas == ["Hello", ", ", "world!"]
    assert result == "Hello, world!"
    assert captured["accept"] == "text/event-stream"
    assert captured["body"]["stream"] is True


def test_sse_edge_cases():
    """[DONE] terminates the stream; :keep-alive comments and other non-data
    lines are ignored without spurious on_delta calls; bytes after [DONE]
    are not parsed."""
    deltas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b":keep-alive\n\n"
            b'data: {"choices":[{"delta":{"content":"alpha"}}]}\n\n'
            b": another comment\n\n"
            b"event: ping\n\n"
            b'data: {"choices":[{"delta":{"content":"beta"}}]}\n\n'
            b"data: [DONE]\n\n"
            b'data: {"choices":[{"delta":{"content":"should-not-appear"}}]}\n\n'
        )
        return _sse_response(body)

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hi", on_delta=deltas.append))
    finally:
        _run(backend.close())

    assert deltas == ["alpha", "beta"]
    assert result == "alphabeta"


def test_non_streaming_fallback():
    """Non-SSE content-type → falls back to single-JSON-response path and emits
    one on_delta with the full reply."""
    captured: dict[str, Any] = {}
    deltas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "fallback reply"}}
                ]
            },
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hi", on_delta=deltas.append))
    finally:
        _run(backend.close())

    assert captured["body"]["stream"] is True
    assert deltas == ["fallback reply"]
    assert result == "fallback reply"


def test_sse_empty_stream_raises_protocol_error():
    """A stream that only contains [DONE] (no content deltas) is a protocol
    violation — we raise rather than return an empty string so the CLI
    surfaces it instead of silently rendering nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response(b"data: [DONE]\n\n")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatProtocolError, match="missing assistant content"):
            _run(backend.send_message("hi"))
    finally:
        _run(backend.close())


def test_sse_malformed_chunk_raises_protocol_error():
    """A `data:` line that isn't valid JSON is a protocol error, not a silent skip."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response(b"data: not-json\n\n")

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatProtocolError, match="malformed SSE chunk"):
            _run(backend.send_message("hi"))
    finally:
        _run(backend.close())


def test_sse_multiline_data_field_concatenates_per_spec():
    """SSE §9.2.6: multiple `data:` lines in one event accumulate joined by \\n.

    OpenAI sends single-line JSON today, but a buffering proxy may chunk a
    JSON payload across `data:` continuations. The parser must reassemble
    the event before json.loads.
    """
    multi_line_payload = (
        b'data: {"choices":[{"delta":\n'
        b'data: {"content":"reassembled"}}]}\n'
        b"\n"
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response(multi_line_payload)

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hi"))
    finally:
        _run(backend.close())

    assert result == "reassembled"


class _RaiseAfterChunkStream(httpx.AsyncByteStream):
    """Yields a fixed prefix then raises — emulates mid-body TCP reset."""

    def __init__(self, prefix: bytes, exc: BaseException) -> None:
        self._prefix = prefix
        self._exc = exc

    async def __aiter__(self):
        yield self._prefix
        raise self._exc

    async def aclose(self) -> None:
        return None


def test_sse_delta_content_is_sanitized_at_backend_boundary():
    """Crafted SSE chunks containing terminal-manipulation control chars
    (ANSI clear-screen, CR, bell, ESC, backspace, DEL, C1) must reach
    `on_delta` already scrubbed.

    The CLI writer (`console.print(delta, end="", markup=False)`) and the
    TUI's `RichLog.write(escape(delta))` both pass through control bytes
    unmodified — `rich.markup.escape` only neutralises `[` markup. Stripping
    at the backend boundary is the only line of defense; this test pins it.
    """
    deltas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # [2J  = ANSI clear screen (visible terminal manipulation)
        # \r         = carriage return (overwrites earlier output)
        #      = bell
        # \b         = backspace
        #      = DEL
        #      = C1 NEL (Next Line) — must also be stripped
        # \n and \t  = MUST be preserved (legitimate LLM output)
        body = (
            b'data: {"choices":[{"delta":'
            b'{"content":"hi\\u001b[2Jworld\\r\\u0007"}}]}\n\n'
            b'data: {"choices":[{"delta":'
            b'{"content":"x\\by\\u007fz\\u0085"}}]}\n\n'
            b'data: {"choices":[{"delta":'
            b'{"content":"line1\\nline2\\tindented"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return _sse_response(body)

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hi", on_delta=deltas.append))
    finally:
        _run(backend.close())

    # The ESC, CR, bell, backspace, DEL, NEL are all stripped; the
    # surrounding text — including the `[2J` letters that *followed* ESC —
    # is now inert text rather than an escape sequence.
    assert deltas == ["hi[2Jworld", "xyz", "line1\nline2\tindented"]
    assert result == "hi[2Jworldxyzline1\nline2\tindented"
    # Defensive: none of the stripped bytes survived anywhere in the
    # assembled reply.
    for forbidden in ("\x1b", "\r", "\x07", "\x08", "\x7f", "\x85"):
        assert forbidden not in result


def test_json_fallback_content_is_sanitized_at_backend_boundary():
    """Same protection on the non-SSE path: a server that returns a single
    JSON body with control chars in `message.content` must not leak them
    to the renderer."""
    deltas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "ok\x1b[31mRED\x1b[0m\rdone\n",
                        }
                    }
                ]
            },
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hi", on_delta=deltas.append))
    finally:
        _run(backend.close())

    assert deltas == ["ok[31mRED[0mdone\n"]
    assert result == "ok[31mRED[0mdone\n"
    assert "\x1b" not in result
    assert "\r" not in result


def test_sse_delta_of_only_control_chars_is_skipped():
    """A chunk whose content sanitizes to "" is treated like a content-less
    delta (e.g. a `role`-only first frame) — no on_delta call, no spurious
    blank chunk in the assembled reply."""
    deltas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'data: {"choices":[{"delta":{"content":"\\u001b\\u0007"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return _sse_response(body)

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hi", on_delta=deltas.append))
    finally:
        _run(backend.close())

    assert deltas == ["hello"]
    assert result == "hello"


def test_sse_read_error_mid_stream_raises_connection_error():
    """A mid-stream TCP reset (httpx.ReadError after first SSE chunk lands)
    must surface as ChatConnectionError, not bubble raw httpx exceptions
    to the caller. This is the most realistic LAN failure mode."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_RaiseAfterChunkStream(
                b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
                httpx.ReadError("connection reset"),
            ),
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        with pytest.raises(ChatConnectionError, match="HTTP error talking to hermes"):
            _run(backend.send_message("ping"))
    finally:
        _run(backend.close())


def test_sse_on_delta_failure_mid_stream_does_not_pollute_history():
    """The "render before history" invariant must hold for the SSE path,
    not just the JSON fallback. Returns N SSE chunks; on_delta raises on
    chunk 2. After the failure, history must equal its pre-call snapshot —
    no phantom partial turn (which would inflate every subsequent request).
    """
    chunk_count = {"n": 0}

    def boom_on_chunk_two(_text: str) -> None:
        chunk_count["n"] += 1
        if chunk_count["n"] == 2:
            raise RuntimeError("broken pipe mid-stream")

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"second"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"third"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return _sse_response(body)

    backend = _build_backend(httpx.MockTransport(handler))

    try:
        # First, prime history with one successful turn so we have a non-empty
        # snapshot to assert against.
        def first_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "prime"}}]}
            )

        backend._client = httpx.AsyncClient(
            transport=httpx.MockTransport(first_handler), timeout=30.0
        )
        _run(backend.send_message("warmup"))
        pre_failure_snapshot = list(backend._history)
        assert len(pre_failure_snapshot) == 2

        # Swap to the SSE handler and trigger the mid-stream raise.
        backend._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=30.0
        )
        with pytest.raises(RuntimeError, match="broken pipe mid-stream"):
            _run(backend.send_message("failing", on_delta=boom_on_chunk_two))

        assert backend._history == pre_failure_snapshot, (
            "SSE path corrupted _history despite on_delta raising mid-stream"
        )
    finally:
        _run(backend.close())


def test_assistant_text_bidi_overrides_are_stripped():
    """Unicode bidi-override characters (RTLO, ZWSP, etc.) can flip the
    visual order of displayed text or hide invisible payloads in
    copy-pasted output. Strip them at the backend boundary so neither the
    CLI's console.print nor the TUI's RichLog.write is fooled.
    """
    leaky = "rm -rf /‮tmp‬"  # RTLO + PDF — visual reverse
    invisible = "before​after"  # ZWSP — invisible in terminal
    bom = "﻿trailing"  # BOM/ZWNBSP — invisible
    payload = leaky + invisible + bom

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": payload}}]}
        )

    backend = _build_backend(httpx.MockTransport(handler))
    try:
        result = _run(backend.send_message("hi"))
    finally:
        _run(backend.close())

    # Each bidi/zero-width char must be gone.
    for char in ("‮", "‬", "​", "﻿"):
        assert char not in result, f"{hex(ord(char))} survived sanitizer"


def test_response_timeout_seconds_defaults_to_instance_timeout():
    """Constructor's `timeout_seconds` must control per-request timeout when
    no explicit value is passed to send_message. The prior signature hardcoded
    120s in the kwarg default, silently overriding any caller-supplied
    instance timeout (W4 in the v2 review).
    """
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # httpx exposes the request timeout via extensions when set
        captured["timeout"] = request.extensions.get("timeout")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    backend = HermesOpenAIBackend(
        base_url="http://hermes.test:8642/v1",
        auth_token=SecretStr("tok"),
        timeout_seconds=7.5,
    )
    backend._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=7.5
    )
    try:
        _run(backend.send_message("ping"))
    finally:
        _run(backend.close())

    # httpx records per-call timeout under all four phases when explicitly set
    timeout = captured["timeout"]
    assert timeout is not None
    # All four phases set to the instance default (7.5s), not 120s
    for phase in ("connect", "read", "write", "pool"):
        if phase in timeout and timeout[phase] is not None:
            assert timeout[phase] == 7.5, (
                f"{phase} timeout was {timeout[phase]}, expected 7.5"
            )

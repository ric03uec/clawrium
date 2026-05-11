"""Unit tests for HermesOpenAIBackend (phase 1: non-streaming, single-turn)."""

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
    assert captured["body"]["stream"] is False
    assert captured["body"]["messages"] == [
        {"role": "user", "content": "hello"}
    ]


def test_send_message_invokes_on_delta_with_full_text():
    """Phase 1 is non-streaming; on_delta is fired once with the entire reply so
    the existing renderer in cli/chat.py works unchanged."""
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

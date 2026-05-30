"""Unit tests for the ethos OpenAI-compatible HTTP chat backend.

Covers:
- SSE stream parsing (happy path, multi-chunk, [DONE] sentinel)
- JSON (non-streaming) fallback path
- HTTP error handling: 401 → ChatAuthenticationError, 4xx → ChatProtocolError
- Network errors → ChatConnectionError
- History accumulation and MAX_HISTORY_TURNS cap
- Assistant-text sanitization (control / bidi chars stripped)
"""

from __future__ import annotations

import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from clawrium.core.chat import ChatAuthenticationError, ChatConnectionError, ChatProtocolError
from clawrium.core.chat_ethos import (
    MAX_HISTORY_TURNS,
    EthosOpenAIBackend,
    _sanitize_assistant_text,
    _short_body,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _sse_lines(*chunks: str, done: bool = True) -> list[str]:
    """Build the raw line sequence an SSE stream would produce."""
    lines: list[str] = []
    for chunk in chunks:
        payload = json.dumps({"choices": [{"delta": {"content": chunk}}]})
        lines.append(f"data: {payload}")
        lines.append("")  # blank line = event boundary
    if done:
        lines.append("data: [DONE]")
        lines.append("")
    return lines


def _make_sse_response(lines: list[str], status_code: int = 200) -> MagicMock:
    """Return a mock httpx.Response that streams `lines` as SSE."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": "text/event-stream"}

    async def _aiter_lines() -> AsyncIterator[str]:
        for line in lines:
            yield line

    response.aiter_lines = _aiter_lines
    response.aread = AsyncMock()
    return response


def _make_json_response(content: str, status_code: int = 200) -> MagicMock:
    """Return a mock httpx.Response that returns a single JSON completion."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": "application/json"}
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    response.json = MagicMock(return_value=body)
    response.text = json.dumps(body)
    response.aread = AsyncMock()
    return response


def _make_error_response(status_code: int, body: str = "error") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": "application/json"}
    response.text = body
    response.aread = AsyncMock()
    return response


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def backend() -> EthosOpenAIBackend:
    return EthosOpenAIBackend(
        base_url="http://127.0.0.1:56000/v1",
        auth_token="sk-ethos-" + "a" * 64,
        model="ethos-default",
        timeout_seconds=5.0,
    )


# ── connect / close ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_connect_creates_client(backend: EthosOpenAIBackend) -> None:
    assert not backend.is_connected
    await backend.connect()
    assert backend.is_connected
    await backend.close()
    assert not backend.is_connected


@pytest.mark.anyio
async def test_double_connect_is_idempotent(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    client_before = backend._client
    await backend.connect()
    assert backend._client is client_before
    await backend.close()


# ── SSE parsing ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_send_message_sse_single_chunk(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_sse_response(_sse_lines("Hello!"))

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await backend.send_message("hi")

    assert result == "Hello!"
    await backend.close()


@pytest.mark.anyio
async def test_send_message_sse_multi_chunk(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_sse_response(_sse_lines("Hel", "lo", "!"))

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await backend.send_message("hi")

    assert result == "Hello!"
    await backend.close()


@pytest.mark.anyio
async def test_send_message_sse_calls_on_delta(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_sse_response(_sse_lines("A", "B"))
    deltas: list[str] = []

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        await backend.send_message("hi", on_delta=deltas.append)

    assert deltas == ["A", "B"]
    await backend.close()


# ── JSON fallback ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_send_message_json_fallback(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_json_response("Hello from JSON")

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await backend.send_message("hi")

    assert result == "Hello from JSON"
    await backend.close()


# ── error handling ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_401_raises_auth_error(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_error_response(401)

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(ChatAuthenticationError):
            await backend.send_message("hi")
    await backend.close()


@pytest.mark.anyio
async def test_403_raises_auth_error(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_error_response(403)

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(ChatAuthenticationError):
            await backend.send_message("hi")
    await backend.close()


@pytest.mark.anyio
async def test_503_raises_protocol_error(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_error_response(503, '{"error":"degraded"}')

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(ChatProtocolError, match="503"):
            await backend.send_message("hi")
    await backend.close()


@pytest.mark.anyio
async def test_connect_error_raises_connection_error(backend: EthosOpenAIBackend) -> None:
    await backend.connect()

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(ChatConnectionError, match="reach ethos"):
            await backend.send_message("hi")
    await backend.close()


@pytest.mark.anyio
async def test_timeout_raises_connection_error(backend: EthosOpenAIBackend) -> None:
    await backend.connect()

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(
            side_effect=httpx.ReadTimeout("timed out")
        )
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(ChatConnectionError, match="[Tt]imed out"):
            await backend.send_message("hi")
    await backend.close()


@pytest.mark.anyio
async def test_send_before_connect_raises(backend: EthosOpenAIBackend) -> None:
    with pytest.raises(ChatConnectionError, match="not connected"):
        await backend.send_message("hi")


# ── history management ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_history_accumulates(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_sse_response(_sse_lines("reply"))

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        await backend.send_message("hello")

    assert len(backend._history) == 2
    assert backend._history[0] == {"role": "user", "content": "hello"}
    assert backend._history[1] == {"role": "assistant", "content": "reply"}
    await backend.close()


@pytest.mark.anyio
async def test_history_not_appended_on_error(backend: EthosOpenAIBackend) -> None:
    await backend.connect()
    response = _make_error_response(401)

    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(ChatAuthenticationError):
            await backend.send_message("hi")

    assert backend._history == []
    await backend.close()


@pytest.mark.anyio
async def test_history_capped_at_max_turns(backend: EthosOpenAIBackend) -> None:
    await backend.connect()

    # Pre-fill history to just over the cap
    overflow = 10
    pairs = MAX_HISTORY_TURNS + overflow
    backend._history = [
        msg
        for i in range(pairs)
        for msg in (
            {"role": "user", "content": f"u{i}"},
            {"role": "assistant", "content": f"a{i}"},
        )
    ]

    response = _make_sse_response(_sse_lines("final"))
    with patch.object(backend._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)
        await backend.send_message("last")

    assert len(backend._history) == MAX_HISTORY_TURNS * 2
    assert backend.last_send_dropped_turns == overflow + 1
    await backend.close()


def test_clear_history(backend: EthosOpenAIBackend) -> None:
    backend._history = [{"role": "user", "content": "x"}]
    backend.last_send_dropped_turns = 3
    backend.clear_history()
    assert backend._history == []
    assert backend.last_send_dropped_turns == 0


# ── sanitization ─────────────────────────────────────────────────────────────

def test_sanitize_strips_control_chars() -> None:
    assert _sanitize_assistant_text("hel\x00lo") == "hello"
    assert _sanitize_assistant_text("hel\x1flo") == "hello"


def test_sanitize_strips_bidi_chars() -> None:
    # RLO (U+202E) and LRE (U+202A)
    assert _sanitize_assistant_text("hel‮lo") == "hello"
    assert _sanitize_assistant_text("hel‪lo") == "hello"


def test_sanitize_preserves_normal_text() -> None:
    text = "Hello, world! How are you?\nFine, thanks."
    assert _sanitize_assistant_text(text) == text


def test_short_body_truncates() -> None:
    long = "x" * 300
    result = _short_body(long, limit=200)
    assert len(result) == 203  # 200 + "..."
    assert result.endswith("...")


def test_short_body_strips_control_chars() -> None:
    assert _short_body("hel\x00lo") == "hel lo"

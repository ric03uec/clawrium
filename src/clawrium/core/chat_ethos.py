"""Ethos chat backend (OpenAI-compatible HTTP).

Mirrors the hermes chat backend (chat_hermes.py) for the ethos agent type.
The ethos gateway exposes an OpenAI-compatible HTTP API on
127.0.0.1:<gateway_port>/v1, bearer-token protected via ETHOS_GATEWAY_API_KEY.

Auth: the bearer token is stored in secrets.json under ETHOS_GATEWAY_API_KEY.
Port: read from agent_record["config"]["gateway"]["port"].

On 401: reloads hosts.json, compares gateway.api_key in memory vs disk, and
rebuilds the backend with the fresh token if they differ (same local-reconnect
pattern as zeroclaw).
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

import httpx

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
    SecretStr,
)

__all__ = ["EthosOpenAIBackend"]

# Cap accumulated turns to bound memory and per-request payload size.
# Mirrors the hermes backend cap.
MAX_HISTORY_TURNS = 100


class EthosOpenAIBackend:
    """OpenAI-compatible HTTP chat client for ethos.

    `base_url` is the gateway origin including the `/v1` suffix
    (e.g. `http://127.0.0.1:43012/v1`; the port is per-instance, picked at
    ethos web-api port 3000, persisted at install as `config.gateway.port`).
    The backend appends `/chat/completions`
    for each request.

    `model` is forwarded as the OpenAI `model` field. Must match a valid
    ethos model id (e.g. "ethos-default", "engineer"); defaults to "ethos-default".
    """

    def __init__(
        self,
        base_url: str,
        auth_token: SecretStr | str,
        model: str = "ethos-default",
        timeout_seconds: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_token = (
            auth_token if isinstance(auth_token, SecretStr) else SecretStr(auth_token)
        )
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._history: list[dict[str, str]] = []
        # Number of full (user, assistant) pairs dropped by the most recent
        # send_message call due to the MAX_HISTORY_TURNS cap. Reset to 0 at
        # the start of every send_message.
        self.last_send_dropped_turns: int = 0

    def clear_history(self) -> None:
        """Drop accumulated turns so the next send_message starts fresh."""
        self._history.clear()
        self.last_send_dropped_turns = 0

    async def connect(self) -> None:
        """Open the underlying HTTP client.

        No network call yet — keep the connect step cheap.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    @property
    def is_connected(self) -> bool:
        """Whether `send_message` would succeed without a fresh connect."""
        return self._client is not None

    async def send_message(
        self,
        message: str,
        session_key: str = "main",
        on_delta: Callable[[str], None] | None = None,
        response_timeout_seconds: float | None = None,
    ) -> str:
        """POST a user message with accumulated history and return the reply.

        The running `self._history` (prior user+assistant turns) is sent with
        each request so ethos can resolve back-references.

        On a successful reply the user message and assistant reply are both
        appended; on any failure neither is appended so a retry sees the same
        state the failed call started from.

        Requests `stream: true` and parses SSE chunks via the OpenAI
        `chat.completions` delta protocol; falls back to the single-JSON
        path when the server responds without `text/event-stream`.

        `session_key` is accepted for signature parity with the openclaw
        backend; it is ignored for OpenAI-typed agents.
        """
        if self._client is None:
            raise ChatConnectionError("Ethos chat backend not connected")

        if response_timeout_seconds is None:
            response_timeout_seconds = self._timeout_seconds

        self.last_send_dropped_turns = 0
        outgoing_messages = self._history + [{"role": "user", "content": message}]
        body: dict[str, Any] = {
            "model": self._model,
            "messages": outgoing_messages,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self._auth_token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        url = f"{self._base_url}/chat/completions"
        try:
            async with self._client.stream(
                "POST",
                url,
                json=body,
                headers=headers,
                timeout=response_timeout_seconds,
            ) as response:
                if response.status_code in (401, 403):
                    raise ChatAuthenticationError("Ethos rejected bearer token")
                if response.status_code >= 400:
                    await response.aread()
                    raise ChatProtocolError(
                        f"Ethos returned HTTP {response.status_code}: "
                        f"{_short_body(response.text)}"
                    )

                content_type = response.headers.get("content-type", "")
                if "text/event-stream" in content_type.lower():
                    text = await _consume_sse_stream(response, on_delta)
                else:
                    text = await _consume_json_response(response, on_delta)
        except httpx.ConnectError as exc:
            raise ChatConnectionError(
                f"Failed to reach ethos at {self._base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ChatConnectionError(
                f"Timed out waiting for ethos response after "
                f"{response_timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ChatConnectionError("HTTP error talking to ethos") from exc

        # Stream completed without raising — append the turn.
        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": text})
        max_entries = MAX_HISTORY_TURNS * 2
        if len(self._history) > max_entries:
            overflow = len(self._history) - max_entries
            del self._history[:overflow]
            self.last_send_dropped_turns = overflow // 2
        return text


async def _consume_sse_stream(
    response: httpx.Response,
    on_delta: Callable[[str], None] | None,
) -> str:
    """Parse an OpenAI-style SSE stream into an assembled reply."""
    parts: list[str] = []
    data_lines: list[str] = []
    done = False

    def _dispatch_event() -> bool:
        if not data_lines:
            return False
        payload = "\n".join(data_lines)
        data_lines.clear()
        if payload == "[DONE]":
            return True
        try:
            chunk = json.loads(payload)
        except ValueError as exc:
            raise ChatProtocolError(
                f"Ethos returned malformed SSE chunk: {_short_body(payload)}"
            ) from exc
        delta = _extract_delta_content(chunk)
        if not delta:
            return False
        parts.append(delta)
        if on_delta is not None:
            on_delta(delta)
        return False

    async for line in response.aiter_lines():
        if not line:
            done = _dispatch_event()
            if done:
                break
            continue
        if line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data_lines.append(line[len("data:"):].lstrip(" "))

    if not done and data_lines:
        _dispatch_event()

    text = "".join(parts)
    if not text:
        raise ChatProtocolError("Ethos response missing assistant content")
    return text


async def _consume_json_response(
    response: httpx.Response,
    on_delta: Callable[[str], None] | None,
) -> str:
    """Read a non-streamed chat.completions body and emit a single delta."""
    await response.aread()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ChatProtocolError(
            "Ethos returned non-JSON response to chat.completions"
        ) from exc

    text = _extract_assistant_text(payload)
    if not text:
        raise ChatProtocolError("Ethos response missing assistant content")

    if on_delta is not None:
        on_delta(text)
    return text


def _extract_assistant_text(payload: Any) -> str:
    """Pull assistant text from an OpenAI-shaped chat.completions response."""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return _sanitize_assistant_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return _sanitize_assistant_text("".join(parts))
    return ""


def _extract_delta_content(chunk: Any) -> str:
    """Pull `choices[0].delta.content` from a streamed chat.completions chunk."""
    if not isinstance(chunk, dict):
        return ""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    if isinstance(content, str):
        return _sanitize_assistant_text(content)
    return ""


_CONTROL_CHARS_RE = re.compile(
    "["
    "\x00-\x1f\x7f-\x9f"
    "؜"
    "​-‏"
    " - "
    "‪-‮"
    "⁠"
    "⁦-⁩"
    "﻿"
    "]"
)
_WHITESPACE_RUN_RE = re.compile(r" +")

_ASSISTANT_TEXT_STRIP_RE = re.compile(
    "["
    "\x00-\x08\x0b-\x1f\x7f-\x9f"
    "؜"
    "​-‏"
    " - "
    "‪-‮"
    "⁠"
    "⁦-⁩"
    "﻿"
    "]"
)


def _sanitize_assistant_text(text: str) -> str:
    return _ASSISTANT_TEXT_STRIP_RE.sub("", text)


def _short_body(body: str, limit: int = 200) -> str:
    """Strip C0/C1 control chars and collapse runs of spaces."""
    cleaned = _CONTROL_CHARS_RE.sub(" ", body.strip())
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()
    if len(cleaned) > limit:
        return cleaned[:limit] + "..."
    return cleaned

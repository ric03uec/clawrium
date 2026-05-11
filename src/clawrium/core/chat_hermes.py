"""Hermes chat backend (OpenAI-compatible HTTP).

Combines phases 1-4 of #322:
  Phase 1 — single-turn POST to /v1/chat/completions.
  Phase 2 — client-side conversation history accumulates across calls in
            `self._history` and is sent with each request.
  Phase 3 — SSE streaming via httpx.AsyncClient.stream() with graceful
            fallback to the single-JSON-response path for non-SSE servers.
  Phase 4 — polished error messaging + sanitization (in cli/chat.py).
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

__all__ = ["HermesOpenAIBackend"]

# Cap accumulated turns to bound memory and per-request payload size on long
# sessions. Each "turn" is a user+assistant pair (2 history entries); 100 turns
# ≈ 200 entries. When the cap is exceeded the oldest pair is dropped to keep
# the wire format aligned. The number of *pairs* dropped during the most
# recent send_message is exposed via `last_send_dropped_turns` so the REPL
# layer can surface a user-visible notice (the backend itself stays quiet —
# UI concerns belong in the CLI).
MAX_HISTORY_TURNS = 100


class HermesOpenAIBackend:
    """OpenAI-compatible HTTP chat client for hermes.

    `base_url` is the gateway origin including the `/v1` suffix
    (e.g. `http://wolf-i.local:8642/v1`). The backend appends
    `/chat/completions` for each request.

    `model` is forwarded as the OpenAI `model` field. Hermes ignores it for
    routing today but the wire format requires it; pass whatever string the
    server is configured to accept (defaults to "hermes").
    """

    def __init__(
        self,
        base_url: str,
        auth_token: SecretStr | str,
        model: str = "hermes",
        timeout_seconds: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_token = (
            auth_token
            if isinstance(auth_token, SecretStr)
            else SecretStr(auth_token)
        )
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._history: list[dict[str, str]] = []
        # Number of full (user, assistant) pairs dropped by the most recent
        # send_message call due to the MAX_HISTORY_TURNS cap. Reset to 0 at
        # the start of every send_message. The REPL reads this after each
        # turn to print a one-line truncation notice.
        self.last_send_dropped_turns: int = 0

    def clear_history(self) -> None:
        """Drop accumulated turns so the next send_message starts fresh."""
        self._history.clear()
        self.last_send_dropped_turns = 0

    async def connect(self) -> None:
        """Open the underlying HTTP client.

        No network call yet — keep the connect step cheap and let the first
        `send_message` surface auth/connectivity errors. Slice 4 adds an
        explicit health probe with a friendly remediation hint.
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

    async def send_message(
        self,
        message: str,
        session_key: str = "main",
        on_delta: Callable[[str], None] | None = None,
        response_timeout_seconds: float = 120.0,
    ) -> str:
        """POST a user message with accumulated history and return the reply.

        The running `self._history` (prior user+assistant turns) is sent with
        each request so hermes can resolve back-references like "double that".
        On a successful reply the user message and assistant reply are both
        appended; on any failure (HTTP error, transport error, or an
        `on_delta` callback that raises) neither is appended so a retry sees
        the same state the failed call started from.

        Ordering contract: `on_delta` is invoked **before** `_history` is
        mutated. A broken-pipe / TUI-disconnect inside the callback aborts
        the turn cleanly — no "ghost half-turn" inflates the wire payload of
        every subsequent request. This matters under streaming where
        `on_delta` is called many times mid-response.

        Requests `stream: true` and parses SSE chunks via the OpenAI
        `chat.completions` delta protocol; falls back to the single-JSON
        path when the server responds without `text/event-stream`.

        `on_delta` semantics:
          - SSE path: called once per non-empty content chunk (N times). Empty
            chunks (`role`-only first frame, finish_reason-only last frame,
            heartbeats) are skipped. `[DONE]` terminates without calling it.
          - JSON fallback: called exactly once with the full reply.
          - Callers should not rely on call count; use the return value for
            the assembled final text.

        `session_key` is accepted for signature parity with the openclaw
        backend; it is ignored for OpenAI-typed agents.
        """
        if self._client is None:
            raise ChatConnectionError("Hermes chat backend not connected")

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
                    raise ChatAuthenticationError(
                        f"Hermes rejected bearer token ({response.status_code})"
                    )
                if response.status_code >= 400:
                    await response.aread()
                    raise ChatProtocolError(
                        f"Hermes returned HTTP {response.status_code}: "
                        f"{_short_body(response.text)}"
                    )

                content_type = response.headers.get("content-type", "")
                if "text/event-stream" in content_type.lower():
                    text = await _consume_sse_stream(response, on_delta)
                else:
                    text = await _consume_json_response(response, on_delta)
        except httpx.ConnectError as exc:
            # Drop raw httpx text — it leaks transport internals (e.g. errno,
            # socket addrs) into user-facing errors. Slice 4 owns the friendly
            # remediation hint at the CLI layer.
            raise ChatConnectionError(
                f"Failed to reach hermes at {self._base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ChatConnectionError(
                f"Timed out waiting for hermes response after "
                f"{response_timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ChatConnectionError("HTTP error talking to hermes") from exc

        # Stream completed without raising — append the turn. Truncation keeps
        # entries aligned to user/assistant pairs so the wire format never
        # starts mid-pair.
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
    """Parse an OpenAI-style SSE stream into an assembled reply.

    Recognized line shapes (SSE / W3C EventSource §9.2.6):
      - `data: <value>` → field value appended to the current event's data
        buffer. Multiple `data:` lines in the same event accumulate joined
        by `\\n` before parsing — required by the spec even though OpenAI
        sends single-line JSON today.
      - empty line      → event terminator; the assembled data buffer is
        decoded as JSON, `[DONE]` short-circuits termination.
      - `:<comment>`    → ignored (heartbeat / `:keep-alive`).
      - any other line  → ignored (forward-compat for unknown event names,
        `event:`, `id:`, `retry:`).
    """
    parts: list[str] = []
    data_lines: list[str] = []
    done = False

    def _dispatch_event() -> bool:
        """Decode the accumulated event buffer; return True to stop the stream."""
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
                f"Hermes returned malformed SSE chunk: {_short_body(payload)}"
            ) from exc
        delta = _extract_delta_content(chunk)
        if not delta:
            return False
        parts.append(delta)
        # Render first — if on_delta raises (broken pipe / TUI disconnect),
        # the turn is aborted before history is touched so the next request
        # does not carry a phantom user+assistant pair. History append lives
        # in `send_message` after this function returns.
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
        # Per spec, a single leading space after the colon is stripped;
        # we use lstrip() so common "data:foo" (no space) variants work too.
        data_lines.append(line[len("data:"):].lstrip(" "))

    # Servers that close the connection without a trailing blank line still
    # delivered a complete event — flush whatever sits in the buffer.
    if not done and data_lines:
        _dispatch_event()

    text = "".join(parts)
    if not text:
        raise ChatProtocolError("Hermes response missing assistant content")
    return text


async def _consume_json_response(
    response: httpx.Response,
    on_delta: Callable[[str], None] | None,
) -> str:
    """Read a non-streamed chat.completions body and emit a single delta.

    Servers that don't advertise `text/event-stream` (older builds, proxies
    that buffer) fall through here so the CLI still works end-to-end.
    """
    await response.aread()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ChatProtocolError(
            "Hermes returned non-JSON response to chat.completions"
        ) from exc

    text = _extract_assistant_text(payload)
    if not text:
        raise ChatProtocolError("Hermes response missing assistant content")

    if on_delta is not None:
        on_delta(text)
    return text


def _extract_assistant_text(payload: Any) -> str:
    """Pull assistant text from an OpenAI-shaped chat.completions response.

    Output is sanitized (C0/C1 controls stripped, `\\n`/`\\t` preserved)
    so renderers can write it directly without trusting the server.
    """
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
    """Pull `choices[0].delta.content` from a streamed chat.completions chunk.

    Output is sanitized (C0/C1 controls stripped, `\\n`/`\\t` preserved)
    so the on_delta callback can write it directly without trusting the
    server. A chunk whose content is *entirely* control characters
    sanitizes to "" and is then skipped by the caller, exactly as if the
    server had sent an empty content field.
    """
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


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_WHITESPACE_RUN_RE = re.compile(r" +")

# Strip C0/C1 control characters from server-supplied assistant text before it
# reaches any renderer. Preserves only \t (\x09) and \n (\x0a) — LLM replies
# legitimately contain newlines (markdown, code, paragraphs) and occasional
# tabs (indented code). Everything else — including \r (overwrite), \x1b
# (ANSI escape), \x07 (bell), \x08 (backspace), and the C1 block — is
# stripped at the backend boundary so neither the CLI's direct console.print
# nor the TUI's RichLog.write can be tricked into terminal manipulation by a
# malicious or compromised hermes server.
_ASSISTANT_TEXT_STRIP_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _sanitize_assistant_text(text: str) -> str:
    return _ASSISTANT_TEXT_STRIP_RE.sub("", text)


def _short_body(body: str, limit: int = 200) -> str:
    """Strip C0/C1 control chars (incl. CR/ANSI) and collapse runs of spaces.

    Error text from a remote server is interpolated into exception messages
    and may be rendered by callers that do not run their own sanitizer
    (e.g. the TUI's `_add_system_message`). Sanitizing at the source keeps
    `\\r` from rewriting earlier output and ANSI escapes from re-colouring
    the terminal.
    """
    cleaned = _CONTROL_CHARS_RE.sub(" ", body.strip())
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()
    if len(cleaned) > limit:
        return cleaned[:limit] + "..."
    return cleaned

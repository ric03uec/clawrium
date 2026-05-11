"""Hermes chat backend (OpenAI-compatible HTTP).

Phase 1 scope: single-turn, non-streaming POST to /v1/chat/completions.
Multi-turn history (phase 2), SSE streaming (phase 3), and polished error
messaging (phase 4) land in follow-up slices of #322.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
    SecretStr,
)

__all__ = ["HermesOpenAIBackend"]


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
        """POST a single user message and return the assistant reply.

        Phase 1 does not retain history across calls and does not stream.
        `session_key` is accepted for signature parity with the openclaw
        backend; it is ignored for OpenAI-typed agents (Slice 4 will surface a
        dim warning for non-default values at the CLI layer).
        `on_delta` is also accepted for signature parity and is invoked once
        with the full reply so the existing renderer in `cli/chat.py` works
        unchanged.
        """
        if self._client is None:
            raise ChatConnectionError("Hermes chat backend not connected")

        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": message}],
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._auth_token.get_secret_value()}",
            "Content-Type": "application/json",
        }

        url = f"{self._base_url}/chat/completions"
        try:
            response = await self._client.post(
                url,
                json=body,
                headers=headers,
                timeout=response_timeout_seconds,
            )
        except httpx.ConnectError as exc:
            raise ChatConnectionError(
                f"Failed to reach hermes at {self._base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ChatConnectionError(
                f"Timed out waiting for hermes response after "
                f"{response_timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ChatConnectionError(f"HTTP error talking to hermes: {exc}") from exc

        if response.status_code in (401, 403):
            raise ChatAuthenticationError(
                f"Hermes rejected bearer token ({response.status_code})"
            )
        if response.status_code >= 400:
            raise ChatProtocolError(
                f"Hermes returned HTTP {response.status_code}: "
                f"{_short_body(response.text)}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ChatProtocolError(
                "Hermes returned non-JSON response to chat.completions"
            ) from exc

        text = _extract_assistant_text(payload)
        if not text:
            raise ChatProtocolError(
                "Hermes response missing assistant content"
            )

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
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def _short_body(body: str, limit: int = 200) -> str:
    cleaned = body.strip().replace("\n", " ")
    if len(cleaned) > limit:
        return cleaned[:limit] + "..."
    return cleaned

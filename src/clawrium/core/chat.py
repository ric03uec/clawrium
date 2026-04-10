"""OpenClaw gateway chat client for interactive CLI sessions."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from typing import Any, Callable
from urllib.parse import urlparse

import websockets
from websockets.exceptions import WebSocketException

from clawrium import __version__

__all__ = [
    "ChatError",
    "ChatConnectionError",
    "ChatAuthenticationError",
    "ChatProtocolError",
    "SecretStr",
    "OpenClawChatClient",
]


class ChatError(Exception):
    """Base exception for chat failures."""


class ChatConnectionError(ChatError):
    """Raised when gateway connection fails."""


class ChatAuthenticationError(ChatError):
    """Raised when gateway authentication fails."""


class ChatProtocolError(ChatError):
    """Raised when gateway protocol validation fails."""


class SecretStr:
    """String-like secret container with masked representation."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        """Return raw secret value for protocol payloads."""
        return self._value

    def __repr__(self) -> str:
        return "***"

    def __str__(self) -> str:
        return "***"


class OpenClawChatClient:
    """Minimal WebSocket client for OpenClaw gateway chat RPC."""

    def __init__(
        self,
        gateway_url: str,
        auth_token: SecretStr | str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.gateway_url = gateway_url
        if isinstance(auth_token, SecretStr):
            self._auth_token = auth_token
        else:
            self._auth_token = SecretStr(auth_token)
        self.timeout_seconds = timeout_seconds
        self._ws: Any | None = None
        self._request_id = 0
        self._event_buffer: deque[dict[str, Any]] = deque(maxlen=100)

    async def connect(self) -> None:
        """Connect and authenticate with the gateway."""
        parsed_url = urlparse(self.gateway_url)
        if parsed_url.scheme not in {"ws", "wss"}:
            raise ChatConnectionError("Gateway URL must use ws:// or wss://")

        try:
            self._ws = await websockets.connect(
                self.gateway_url,
                open_timeout=self.timeout_seconds,
                close_timeout=self.timeout_seconds,
            )
        except OSError as exc:
            raise ChatConnectionError(f"Failed to reach gateway: {exc}") from exc
        except WebSocketException as exc:
            raise ChatConnectionError(f"WebSocket connection failed: {exc}") from exc

        try:
            first_frame = await self._recv_json(timeout=self.timeout_seconds)
            nonce = None
            if (
                first_frame.get("type") == "event"
                and first_frame.get("event") == "connect.challenge"
            ):
                payload = first_frame.get("payload")
                if isinstance(payload, dict):
                    nonce = payload.get("nonce")

            req_id = self._next_id()
            connect_params: dict[str, Any] = {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "clawrium-cli",
                    "version": __version__,
                    "platform": "python",
                    "mode": "operator",
                },
                "role": "operator",
                "scopes": ["operator.read", "operator.write"],
                "caps": [],
                "commands": [],
                "permissions": {},
                "auth": {"token": self._auth_token.get_secret_value()},
                "userAgent": f"clawrium/{__version__}",
            }
            if isinstance(nonce, str) and nonce:
                connect_params["nonce"] = nonce

            await self._send_json(
                {
                    "type": "req",
                    "id": req_id,
                    "method": "connect",
                    "params": connect_params,
                }
            )

            response = await self._wait_for_response(req_id)
            if not response.get("ok"):
                error_msg = _extract_error(response)
                if "AUTH" in error_msg.upper() or "unauthorized" in error_msg.lower():
                    raise ChatAuthenticationError(error_msg)
                raise ChatProtocolError(error_msg)
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Close gateway connection."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def send_message(
        self,
        message: str,
        session_key: str,
        on_delta: Callable[[str], None] | None = None,
        response_timeout_seconds: float = 120.0,
    ) -> str:
        """Send a user message and stream assistant response until completion."""
        if self._ws is None:
            raise ChatConnectionError("Not connected to gateway")

        self._event_buffer.clear()

        req_id = self._next_id()
        idempotency_key = str(uuid.uuid4())
        await self._send_json(
            {
                "type": "req",
                "id": req_id,
                "method": "chat.send",
                "params": {
                    "sessionKey": session_key,
                    "message": message,
                    "idempotencyKey": idempotency_key,
                },
            }
        )

        response = await self._wait_for_response(
            req_id,
            timeout=response_timeout_seconds,
        )
        if not response.get("ok"):
            raise ChatProtocolError(_extract_error(response))

        payload = response.get("payload")
        if not isinstance(payload, dict):
            raise ChatProtocolError("chat.send returned invalid payload")

        run_id = payload.get("runId")
        if not isinstance(run_id, str) or not run_id:
            raise ChatProtocolError("chat.send did not return runId")

        chunks: list[str] = []
        while True:
            event = await self._next_event(timeout=response_timeout_seconds)
            if event.get("type") != "event" or event.get("event") != "chat":
                continue

            event_payload = event.get("payload")
            if not isinstance(event_payload, dict):
                continue
            if event_payload.get("runId") != run_id:
                continue

            state = event_payload.get("state")
            delta = _extract_delta(event_payload)
            if delta:
                chunks.append(delta)
                if on_delta:
                    on_delta(delta)

            if state == "error":
                raise ChatProtocolError(
                    event_payload.get("errorMessage") or "chat failed"
                )
            if state == "final":
                final_text = _extract_final_text(event_payload)
                if final_text:
                    return final_text
                return "".join(chunks).strip()

    def _next_id(self) -> str:
        self._request_id += 1
        return str(self._request_id)

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise ChatConnectionError("WebSocket is not connected")
        try:
            await self._ws.send(json.dumps(payload))
        except WebSocketException as exc:
            raise ChatConnectionError(f"Failed to send message: {exc}") from exc

    async def _recv_json(self, timeout: float) -> dict[str, Any]:
        if self._ws is None:
            raise ChatConnectionError("WebSocket is not connected")
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except TimeoutError as exc:
            raise ChatConnectionError("Timed out waiting for gateway response") from exc
        except WebSocketException as exc:
            raise ChatConnectionError(f"Connection lost: {exc}") from exc

        if not isinstance(raw, str):
            raise ChatProtocolError("Gateway sent non-text WebSocket frame")
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChatProtocolError("Gateway sent invalid JSON frame") from exc
        if not isinstance(frame, dict):
            raise ChatProtocolError("Gateway frame must be a JSON object")
        return frame

    async def _wait_for_response(
        self,
        req_id: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        wait_timeout = timeout if timeout is not None else self.timeout_seconds
        while True:
            frame = await self._recv_json(timeout=wait_timeout)
            if frame.get("type") == "res" and frame.get("id") == req_id:
                return frame
            if frame.get("type") == "event":
                self._event_buffer.append(frame)

    async def _next_event(self, timeout: float) -> dict[str, Any]:
        if self._event_buffer:
            return self._event_buffer.popleft()
        while True:
            frame = await self._recv_json(timeout=timeout)
            if frame.get("type") == "event":
                return frame


def _extract_error(response: dict[str, Any]) -> str:
    error = response.get("error")
    if isinstance(error, dict):
        if isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(error.get("code"), str):
            return error["code"]
    if isinstance(error, str):
        return error
    return "Gateway request failed"


def _extract_delta(payload: dict[str, Any]) -> str:
    for key in ("delta", "textDelta", "chunk", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _extract_final_text(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
            if text_parts:
                return "".join(text_parts)
        if isinstance(message.get("text"), str):
            return message["text"]
    return ""

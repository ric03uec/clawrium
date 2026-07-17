"""ZeroClaw gateway chat backend (WebSocket, bearer-token paired).

The ZeroClaw gateway speaks tagged-JSON envelopes over a single WebSocket
connection (`GET /ws/chat`). Auth happens by sending the paired bearer
token in the `Authorization: Bearer <token>` upgrade header. The frame
schema is documented inline below.

This file deliberately does NOT reuse openclaw's `OpenClawChatClient`
because the wire formats differ:

- openclaw: req/res RPC-style envelopes with `id`, `method`, `params`;
  event frames carry `event`/`payload`. Server emits assistant text via
  `chat` events with `state="streaming"|"final"`.
- zeroclaw: tagged-JSON server frames keyed by a single top-level
  `type` field (`chunk`, `thinking`, `tool_call`, `tool_result`, `done`,
  `error`, `aborted`, `chunk_reset`, `approval_request`, `session_start`,
  `connected`). The client sends `{"type":"message","content":"..."}`.

Conversation state is owned by the gateway: one WebSocket connection is
one session, the daemon retains turns internally, and `clear_history()`
is a no-op (matching openclaw — the REPL `/reset` command prints an
explicit notice for gateway-owned backends so the user is not misled).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from typing import Any, Callable

import websockets
from websockets.exceptions import (
    ConnectionClosed,
    InvalidStatus,
    WebSocketException,
)

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
    SecretStr,
)

# Reuse the sanitizer + control-char regex from chat_hermes so all
# server-supplied text passes through the same bidi/zero-width strip
# before reaching any Rich renderer. Keeps the four sanitizer call sites
# (cli/chat.py, core/chat_hermes.py, here, and the future memory CLI)
# in lockstep — a fix in chat_hermes propagates here for free.
from clawrium.core.chat_hermes import _sanitize_assistant_text

__all__ = [
    "RECV_TIMEOUT_MSG_PREFIX",
    "ZeroClawChatBackend",
    "sanitize_server_text",
]

logger = logging.getLogger(__name__)


# Frame types the server is allowed to emit. Anything outside this set is
# logged and dropped (forward-compat — upstream may add new event types
# without bumping a protocol version, and we don't want unrelated tooling
# events to crash the REPL).
_KNOWN_SERVER_FRAMES = frozenset(
    {
        "connected",
        "session_start",
        "chunk",
        "thinking",
        "tool_call",
        "tool_result",
        "approval_request",
        "chunk_reset",
        "done",
        "error",
        "aborted",
    }
)


def sanitize_server_text(text: Any) -> str:
    """Strip C0/C1, zero-width, bidi, line/paragraph-separator codepoints.

    Returns "" for non-string inputs so callers can safely pass any field
    pulled out of the parsed JSON frame without an `isinstance` ladder.
    """
    if not isinstance(text, str):
        return ""
    return _sanitize_assistant_text(text)


# ATX Round 2 W2 / Round 3 W2: shared string constant for the recv-
# timeout discriminator. cli/chat.py uses this to distinguish recv-
# timeout (route to --timeout hint) from connect-timeout / reachability
# errors. Importing the constant avoids the string-coupling failure mode
# where a reworded exception message silently misroutes the hint.
RECV_TIMEOUT_MSG_PREFIX = "Timed out waiting for ZeroClaw response"


# ATX Round 1 W9 / Round 3 W7: a non-TLS WebSocket against a non-loopback
# host means the bearer token traverses the network in cleartext. Surface
# a one-shot warning so a misconfigured deployment is noisy at chat-start.
#
# Loopback recognition:
#  - String literal matches for the common forms: localhost, 127.0.0.1,
#    ::1, and the bare "" that urlparse occasionally returns for malformed
#    inputs.
#  - Optional getaddrinfo resolution for hostnames that pointed at
#    loopback via /etc/hosts (e.g. `local.dev`). Skipped on resolution
#    failure so a transient DNS hiccup never SUPPRESSES the warning.
def _warn_if_token_in_cleartext(gateway_url: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(gateway_url)
    if parsed.scheme != "ws":
        return
    host = (parsed.hostname or "").lower()
    # Literal loopback forms — handles the canonical configure-time URL.
    if host in {"localhost", "localhost.localdomain", "127.0.0.1", "::1", ""}:
        return
    # Best-effort resolution: a hostname pointed at loopback via
    # /etc/hosts (common in dev VMs) should not trigger the warning.
    # Defensive: any resolver failure means we DO emit the warning —
    # mis-warning is preferable to silently dropping a real exposure.
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, OSError, UnicodeError):
        infos = []
    if infos:
        try:
            if all(ipaddress.ip_address(info[4][0]).is_loopback for info in infos):
                return
        except (ValueError, IndexError):
            pass
    logger.warning(
        "ZeroClaw chat is using a non-TLS WebSocket (ws://) to a "
        "non-loopback host (%s). The bearer token will travel in "
        "cleartext on the LAN — consider tunneling over SSH or "
        "switching the gateway to wss://.",
        host,
    )


def _with_agent_alias_query(gateway_url: str, agent_alias: str | None) -> str:
    """Append `?agent=<alias>` to `gateway_url` if `agent_alias` is set.

    ZeroClaw ≥0.8.2 rejects `GET /ws/chat` with HTTP 400 unless the
    upgrade carries a non-empty `agent` query parameter matching a
    `[agents.<alias>]` entry in config.toml
    (crates/zeroclaw-gateway/src/ws.rs line 204). `agent_alias=None`
    preserves the legacy 0.7.5 URL untouched so a hosts.json record
    pointing at an older daemon keeps working; callers on 0.8.2+
    supply the agent instance name and get the required `?agent=`.

    Idempotent: if the URL already carries an `agent` query key we
    leave it alone rather than double-appending.
    """
    if not agent_alias:
        return gateway_url
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(gateway_url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if any(k == "agent" for k, _ in query_pairs):
        return gateway_url
    query_pairs.append(("agent", agent_alias))
    return urlunparse(parsed._replace(query=urlencode(query_pairs)))


class ZeroClawChatBackend:
    """WebSocket chat client for ZeroClaw's `/ws/chat` endpoint.

    Implements the `ChatBackend` protocol from `core/chat.py`. One
    instance corresponds to one chat REPL session; `connect` opens the
    socket, `send_message` round-trips a single user message, and `close`
    tears the connection down.

    Conversation history lives server-side. `clear_history()` is a no-op
    by design — the REPL routes /reset to an explicit "gateway owns
    session state" notice when history_capable is False.
    """

    def __init__(
        self,
        gateway_url: str,
        auth_token: SecretStr | str,
        timeout_seconds: float = 120.0,
        agent_alias: str | None = None,
    ) -> None:
        self.gateway_url = _with_agent_alias_query(gateway_url, agent_alias)
        self._auth_token = (
            auth_token if isinstance(auth_token, SecretStr) else SecretStr(auth_token)
        )
        self._timeout_seconds = timeout_seconds
        self._agent_alias = agent_alias
        self._ws: Any | None = None

    async def connect(self) -> None:
        """Open the WebSocket and authenticate via the bearer header.

        Auth: `Authorization: Bearer <token>` upgrade header (verified
        against `crates/zeroclaw-gateway/src/ws.rs` —
        ZeroClaw also accepts `Sec-WebSocket-Protocol: bearer.<token>`
        and `?token=` query, but the header form is the canonical one
        and avoids leaking the token into proxy logs or URL caches).

        ATX Round 1 W9: emits a stderr warning when the configured URL
        is non-TLS (`ws://`) AND the host portion is non-loopback. The
        pairing flow always writes `ws://` against the daemon's loopback
        bind, so a non-loopback `ws://` URL is operator-introduced (e.g.
        hand-edited hosts.json or LAN-exposed daemon) and means the
        bearer token would travel cleartext over the LAN.
        """
        token = self._auth_token.get_secret_value()
        if not token:
            raise ChatAuthenticationError(
                "ZeroClaw gateway auth token is empty. "
                "Re-run `clawctl agent configure <name>`."
            )

        _warn_if_token_in_cleartext(self.gateway_url)

        # ATX Round 1 W5: drop the redundant `asyncio.wait_for` wrapper.
        # `websockets.connect(open_timeout=...)` is the canonical timeout
        # mechanism; wrapping it in `wait_for` adds a second cancellation
        # boundary whose interaction with `open_timeout` differs across
        # Python versions, creating a 3.10-vs-3.12 edge-case footgun for
        # zero functional gain.
        try:
            self._ws = await websockets.connect(
                self.gateway_url,
                additional_headers=[("Authorization", f"Bearer {token}")],
                open_timeout=self._timeout_seconds,
                close_timeout=self._timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            # ATX Round 1 B5: catch both TimeoutError and
            # asyncio.TimeoutError. They are aliased on Python 3.11+ but
            # remain distinct classes on 3.10 (our declared minimum
            # runtime), where `websockets.connect(open_timeout=...)`
            # raises `asyncio.TimeoutError` which would NOT match `except
            # TimeoutError` alone — a guaranteed crash on 3.10.
            raise ChatConnectionError(
                f"Timed out connecting to ZeroClaw gateway at {self.gateway_url}"
            ) from exc
        except InvalidStatus as exc:
            # 401/403 surface as a dedicated auth error so the CLI can
            # route the user to `clawctl agent configure`. websockets ≥14
            # raises InvalidStatus carrying a `.response` (Response object
            # with `.status_code`); older releases used `.status_code`
            # directly. Probe both shapes.
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if status is None:
                status = getattr(exc, "status_code", None)
            if status in (401, 403):
                raise ChatAuthenticationError(
                    "ZeroClaw gateway rejected the bearer token. "
                    "Re-run `clawctl agent configure <name>` to re-pair."
                ) from exc
            raise ChatConnectionError(
                f"ZeroClaw gateway returned HTTP {status} during connect"
            ) from exc
        except OSError as exc:
            raise ChatConnectionError(
                f"Failed to reach ZeroClaw gateway at {self.gateway_url}: {exc}"
            ) from exc
        except WebSocketException as exc:
            raise ChatConnectionError(f"WebSocket connection failed: {exc}") from exc

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    @property
    def is_connected(self) -> bool:
        """Whether `send_message()` would succeed without a new connect.

        ATX Round 2 W2: the REPL reads this after catching
        `ChatProtocolError` to decide between "continue" and "session
        ended". `approval_request` tears down the socket before raising
        so the REPL can see is_connected == False and break instead of
        looping into a stuck connection.
        """
        return self._ws is not None

    def clear_history(self) -> None:
        """No-op: ZeroClaw's gateway owns conversation state."""

    async def send_message(
        self,
        message: str,
        session_key: str = "main",
        on_delta: Callable[[str], None] | None = None,
        response_timeout_seconds: float = 120.0,
    ) -> str:
        """Send one user message and stream the assistant's reply.

        Reads server frames until a terminal frame (`done` / `error` /
        `aborted`) arrives. Streaming `chunk` frames feed `on_delta` and
        accumulate into a local buffer used as a fallback when `done`
        does not carry `full_response`. `chunk_reset` clears the local
        buffer mid-turn so the eventual fallback (or return value) only
        reflects post-reset content.

        `session_key` is accepted for signature parity with the openclaw
        backend; it is ignored — one WebSocket connection IS the session
        and is established at `connect()`.
        """
        if self._ws is None:
            raise ChatConnectionError("ZeroClaw chat backend not connected")

        await self._send_json({"type": "message", "content": message})

        accumulator: list[str] = []
        while True:
            frame = await self._recv_json(timeout=response_timeout_seconds)
            frame_type = frame.get("type")

            if frame_type not in _KNOWN_SERVER_FRAMES:
                # Forward-compat: log and skip. ZeroClaw may add frame
                # types (e.g. richer tool envelopes); the REPL should
                # not crash on a tag it doesn't recognize.
                logger.debug("Ignoring unknown ZeroClaw frame type: %r", frame_type)
                continue

            if frame_type in ("connected", "session_start"):
                continue

            if frame_type == "chunk":
                delta = sanitize_server_text(frame.get("content"))
                if not delta:
                    continue
                accumulator.append(delta)
                if on_delta is not None:
                    on_delta(delta)
                continue

            if frame_type == "thinking":
                # Thinking frames are advisory — surface via on_delta in
                # a discoverable way without polluting the accumulator
                # (the final return value should be the assistant reply,
                # not the chain-of-thought).
                thought = sanitize_server_text(frame.get("content"))
                if thought and on_delta is not None:
                    # Wrapped so the REPL can distinguish thoughts from
                    # assistant text. The CLI renderer prints deltas
                    # verbatim; an unobtrusive prefix keeps thoughts
                    # readable but distinct.
                    on_delta(f"[thinking] {thought}\n")
                continue

            if frame_type == "tool_call":
                # Tool call frames carry `name` + JSON `arguments`.
                # Sanitize both before surfacing so a malicious tool
                # name / argument blob can't smuggle bidi marks or rich
                # markup into the terminal.
                tool_name = sanitize_server_text(frame.get("name"))
                raw_args = frame.get("arguments")
                if isinstance(raw_args, (dict, list)):
                    args_text = sanitize_server_text(json.dumps(raw_args))
                else:
                    args_text = sanitize_server_text(raw_args)
                if on_delta is not None and tool_name:
                    on_delta(f"[tool_call] {tool_name}({args_text})\n")
                continue

            if frame_type == "tool_result":
                result_text = sanitize_server_text(frame.get("content"))
                if result_text and on_delta is not None:
                    on_delta(f"[tool_result] {result_text}\n")
                continue

            if frame_type == "chunk_reset":
                # Mid-turn reset: the server is telling us to throw away
                # the chunks emitted before this frame (e.g. provider
                # retry, soft abort). Drop the local buffer so the
                # eventual fallback only reflects post-reset content.
                # The renderer can't un-print, but the final return
                # value will be correct.
                accumulator.clear()
                continue

            if frame_type == "approval_request":
                # Inline tool-approval UX is out of scope for #357. ATX
                # Round 1 W2: the server holds the connection open
                # waiting for an `approval_response` frame. If we raise
                # without closing, the REPL's inner try/except catches
                # the error, prints "Continuing chat session.", and the
                # *next* user message hits a half-broken connection
                # (the server replays the approval request or returns
                # error frames). Explicitly close the socket before
                # raising so the REPL's outer cleanup path drops the
                # connection and the user is forced to re-`connect()`
                # (which today means re-running `clawctl chat`).
                #
                # ATX Round 1 B6: sanitize EVERY caller-visible field
                # from the approval frame — `tool`, `name`, AND the
                # `prompt`/`command` text the server may include. A
                # malicious server could otherwise smuggle bidi marks /
                # Rich markup through the prompt field.
                request_label = sanitize_server_text(
                    frame.get("tool") or frame.get("name") or "tool"
                )
                request_prompt = sanitize_server_text(frame.get("prompt"))
                # `prompt` is optional in the wire format; if present we
                # include a truncated form in the error so the user can
                # tell which approval was triggered. Truncation bounds
                # the error-message length even if the server sends a
                # multi-kilobyte prompt.
                detail = f" (tool='{request_label}')"
                if request_prompt:
                    detail += f" prompt={request_prompt[:200]!r}"
                await self.close()
                # ATX Round 2 W9: include a concrete next step. Without
                # a pointer to the config file the user has to guess
                # where tool-allow lists live.
                raise ChatProtocolError(
                    "ZeroClaw requested tool approval" + detail + ". "
                    "Inline approval is not supported yet; either "
                    "pre-approve the tool in ~/.zeroclaw/config.toml "
                    "on the agent host, or disable the tool there and "
                    "re-run `clawctl agent configure <name>`."
                )

            if frame_type == "done":
                # `done` carries `full_response`, token counts, cost,
                # provider, model. Prefer the server-provided full text
                # when present (it accounts for chunk_reset cleanly);
                # fall back to the local accumulator otherwise.
                full = sanitize_server_text(frame.get("full_response"))
                if full:
                    return full
                return "".join(accumulator).strip()

            if frame_type == "error":
                msg = (
                    sanitize_server_text(frame.get("message"))
                    or sanitize_server_text(frame.get("error"))
                    or "ZeroClaw reported an unspecified error"
                )
                raise ChatProtocolError(msg)

            if frame_type == "aborted":
                # Silently ignoring aborted would cause the REPL to hang
                # waiting for `done` that will never come. Surface as a
                # protocol error so the REPL can move to the next turn.
                reason = sanitize_server_text(frame.get("reason")) or "no reason given"
                raise ChatProtocolError(f"ZeroClaw aborted the turn: {reason}")

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise ChatConnectionError("WebSocket is not connected")
        try:
            await self._ws.send(json.dumps(payload))
        except ConnectionClosed as exc:
            raise ChatConnectionError("ZeroClaw gateway closed the connection") from exc
        except WebSocketException as exc:
            raise ChatConnectionError(
                f"Failed to send to ZeroClaw gateway: {exc}"
            ) from exc

    async def _recv_json(self, timeout: float) -> dict[str, Any]:
        if self._ws is None:
            raise ChatConnectionError("WebSocket is not connected")
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            # ATX Round 1 B5: see connect() comment — 3.10 distinguishes
            # TimeoutError and asyncio.TimeoutError. asyncio.wait_for
            # raises the asyncio variant on 3.10 which slips past a bare
            # `except TimeoutError`.
            raise ChatConnectionError(
                f"Timed out waiting for ZeroClaw response after {timeout}s"
            ) from exc
        except ConnectionClosed as exc:
            raise ChatConnectionError("ZeroClaw gateway closed the connection") from exc
        except WebSocketException as exc:
            raise ChatConnectionError(f"Connection lost: {exc}") from exc

        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ChatProtocolError(
                    "ZeroClaw sent non-UTF-8 WebSocket frame"
                ) from exc
        if not isinstance(raw, str):
            raise ChatProtocolError("ZeroClaw sent non-text WebSocket frame")
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChatProtocolError("ZeroClaw sent malformed JSON frame") from exc
        if not isinstance(frame, dict):
            raise ChatProtocolError("ZeroClaw frame must be a JSON object")
        return frame

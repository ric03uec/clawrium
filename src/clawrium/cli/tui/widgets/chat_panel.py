"""Chat panel widget for agent conversation in TUI."""

from __future__ import annotations

import asyncio
from typing import Any

from rich.markup import escape

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, RichLog
from textual.worker import get_current_worker

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
    OpenClawChatClient,
    SecretStr,
)


class ChatPanel(Widget):
    """Chat panel widget with message history and input field."""

    DEFAULT_CSS = """
    ChatPanel {
        height: 1fr;
        border: round $primary-darken-2;
        padding: 0 1;
    }
    ChatPanel > Vertical {
        height: 1fr;
    }
    ChatPanel RichLog {
        height: 1fr;
        border: none;
        padding: 0;
        scrollbar-gutter: stable;
    }
    ChatPanel Input {
        dock: bottom;
        height: 3;
        margin-top: 1;
    }
    """

    class ChatError(Message):
        """Message emitted when a chat error occurs."""

        def __init__(self, error: str) -> None:
            self.error = error
            super().__init__()

    def __init__(
        self,
        agent_name: str,
        gateway_url: str,
        gateway_auth: str,
        device_id: str | None = None,
        device_private_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._agent_name = agent_name
        self._gateway_url = gateway_url
        self._gateway_auth = gateway_auth
        self._device_id = device_id
        self._device_private_key = device_private_key
        self._client: OpenClawChatClient | None = None
        self._connected = False
        self._session_key = "tui"
        self._messages: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
            yield Input(
                placeholder="Type a message...",
                id="chat-input",
            )

    def on_mount(self) -> None:
        self._connect_async()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return
        event.input.value = ""
        self._add_user_message(message)
        self._send_message_async(message)

    def _add_user_message(self, message: str) -> None:
        self._messages.append(("user", message))
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold cyan]you>[/bold cyan] {escape(message)}")

    def _add_agent_message(self, message: str) -> None:
        self._messages.append(("agent", message))
        log = self.query_one("#chat-log", RichLog)
        log.write(
            f"[bold green]{escape(self._agent_name)}>[/bold green] {escape(message)}"
        )

    def _add_agent_delta(self, delta: str, is_first: bool = False) -> None:
        log = self.query_one("#chat-log", RichLog)
        if is_first:
            log.write(
                f"[bold green]{escape(self._agent_name)}>[/bold green] {escape(delta)}",
                scroll_end=True,
            )
        else:
            # Append to current line by clearing and rewriting
            # RichLog doesn't support inline appending, so we accumulate in _pending_response
            pass

    def _add_system_message(self, message: str, severity: str = "info") -> None:
        log = self.query_one("#chat-log", RichLog)
        color = {"error": "red", "warning": "yellow", "info": "dim"}.get(severity, "dim")
        log.write(f"[{color}]{escape(message)}[/{color}]")

    @work(thread=True)
    def _connect_async(self) -> None:
        worker = get_current_worker()

        async def _connect() -> None:
            self._client = OpenClawChatClient(
                gateway_url=self._gateway_url,
                auth_token=SecretStr(self._gateway_auth),
                device_id=self._device_id,
                device_private_key=self._device_private_key,
                timeout_seconds=30.0,
            )
            await self._client.connect()

        try:
            asyncio.run(_connect())
            if worker.is_cancelled:
                return
            self._connected = True
            self.app.call_from_thread(
                self._add_system_message, "Connected to agent", "info"
            )
        except ChatAuthenticationError:
            if worker.is_cancelled:
                return
            self.app.call_from_thread(
                self._add_system_message, "Authentication failed", "error"
            )
            self.app.call_from_thread(
                self.post_message, self.ChatError("Authentication failed")
            )
        except ChatConnectionError:
            if worker.is_cancelled:
                return
            self.app.call_from_thread(
                self._add_system_message,
                "Connection failed - check agent status",
                "error",
            )
            self.app.call_from_thread(
                self.post_message, self.ChatError("Connection failed")
            )
        except Exception:
            if worker.is_cancelled:
                return
            self.app.call_from_thread(
                self._add_system_message, "Connection error", "error"
            )
            self.app.call_from_thread(
                self.post_message, self.ChatError("Connection error")
            )

    @work(thread=True)
    def _send_message_async(self, message: str) -> None:
        worker = get_current_worker()
        if not self._connected or self._client is None:
            self.app.call_from_thread(
                self._add_system_message, "Not connected to agent", "warning"
            )
            return

        response_chunks: list[str] = []
        first_chunk = True

        def on_delta(delta: str) -> None:
            nonlocal first_chunk
            response_chunks.append(delta)
            if first_chunk:
                self.app.call_from_thread(self._add_agent_delta, delta, True)
                first_chunk = False

        async def _send() -> str:
            if self._client is None:
                raise ChatConnectionError("Client not initialized")
            return await self._client.send_message(
                message=message,
                session_key=self._session_key,
                on_delta=on_delta,
                response_timeout_seconds=120.0,
            )

        try:
            final_response = asyncio.run(_send())
            if worker.is_cancelled:
                return
            # If we didn't get any deltas, show the full response
            if not response_chunks:
                self.app.call_from_thread(self._add_agent_message, final_response)
            else:
                # Store the complete response
                self._messages.append(("agent", final_response))
        except ChatProtocolError:
            if worker.is_cancelled:
                return
            self.app.call_from_thread(
                self._add_system_message, "Message failed - protocol error", "error"
            )
        except ChatConnectionError:
            if worker.is_cancelled:
                return
            self.app.call_from_thread(
                self._add_system_message, "Connection lost", "error"
            )
            self._connected = False
        except Exception:
            if worker.is_cancelled:
                return
            self.app.call_from_thread(
                self._add_system_message, "Message failed", "error"
            )

    def on_unmount(self) -> None:
        if self._client is not None:
            # Close the client connection in a background task
            self._close_client_async()

    @work(thread=True)
    def _close_client_async(self) -> None:
        async def _close() -> None:
            if self._client is not None:
                await self._client.close()

        try:
            asyncio.run(_close())
        except Exception:
            pass
        finally:
            self._client = None
            self._connected = False

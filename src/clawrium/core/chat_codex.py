"""On-demand Codex chat backend.

Codex is a local CLI, not a Clawrium daemon. Each turn runs the pinned
``codex exec --json -`` protocol on the agent host through an Ansible
``command.argv`` transport. Prompts arrive on stdin; native thread IDs remain
individual argv elements, never shell fragments. Continuation uses
``codex exec resume --json <thread-id> -``. No daemon, gateway, tunnel, or
controller-side credential is introduced.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import math
import os
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import ansible_runner

from clawrium.core import keys as core_keys
from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
)
from clawrium.core.config import get_config_dir
from clawrium.core.names import RESERVED_UNIX_NAMES
from clawrium.core.playbook_resolver import normalize_os_family, resolve_agent_playbook

__all__ = [
    "CodexChatBackend",
    "CodexChatTransportError",
    "run_codex_chat",
]

# The chat CLI accepts a float timeout but Ansible's remote ``timeout(1)``
# wrapper takes whole seconds.  Round up so callers never get less time than
# requested, then retain the same hard cap used by the bounded shell path.
_HARD_TIMEOUT_CAP = 1800
_RUNNER_GRACE_SECONDS = 30
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_LOG_DIR_SAFE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTROL_AND_BIDI_RE = re.compile(
    "["
    "\x00-\x08\x0b-\x1f\x7f-\x9f"
    "\u061c"
    "\u200b-\u200f"
    "\u2028-\u2029"
    "\u202a-\u202e"
    "\u2060"
    "\u2066-\u2069"
    "\ufeff"
    "]"
)
_AUTH_FAILURE_RE = re.compile(
    r"\b(auth(?:entication|orization)?|unauthori[sz]ed|forbidden|"
    r"not logged in|api[ _-]?key|oauth|credential)\b",
    re.IGNORECASE,
)

# Callable boundary deliberately has no credential argument.  OAuth is read by
# Codex from its native agent-home file; the API-key mode is read only by
# the fixed remote bootstrap from its mode-0600 agent-owned environment file.
CodexChatRunner = Callable[
    [str, str, list[str], str, int, threading.Event], tuple[str, str, int]
]


class CodexChatTransportError(Exception):
    """Raised for pre-flight errors in the private Codex chat transport."""


def _effective_timeout(value: float) -> int:
    """Convert a response timeout to the bounded remote kill window."""
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return 120
    if not math.isfinite(timeout) or timeout <= 0:
        return 120
    return min(max(1, math.ceil(timeout)), _HARD_TIMEOUT_CAP)


def _logs_dir() -> Path:
    path = get_config_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cleanup_artifacts(path: Path) -> None:
    """Remove the private runner directory, including prompt-containing vars."""
    shutil.rmtree(path, ignore_errors=True)


def _build_inventory(
    host: dict[str, Any], ssh_key: Path, extra_vars: dict[str, Any]
) -> dict:
    return {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": extra_vars,
        }
    }


def _parse_events(result: Any) -> tuple[str, str, int | None]:
    """Extract the private chat command result from runner events."""
    stdout = ""
    stderr = ""
    rc: int | None = None
    for event in result.events:
        if event.get("event") != "runner_on_ok":
            continue
        message = event.get("event_data", {}).get("res", {}).get("msg")
        if not isinstance(message, str):
            continue
        if message.startswith("CODEX_CHAT_STDOUT="):
            try:
                stdout = base64.b64decode(
                    message[len("CODEX_CHAT_STDOUT=") :], validate=True
                ).decode("utf-8", errors="replace")
            except (ValueError, TypeError, binascii.Error):
                stdout = ""
        elif message == "CODEX_CHAT_AUTH_FAILURE=true":
            # The playbook deliberately exports only this opaque
            # classification, never remote stderr or diagnostic text.
            stderr = "authentication failed"
        elif message.startswith("CODEX_CHAT_RC="):
            try:
                rc = int(message[len("CODEX_CHAT_RC=") :])
            except ValueError:
                rc = None
    return stdout, stderr, rc


def run_codex_chat(
    hostname: str,
    agent_name: str,
    codex_argv: list[str],
    prompt: str,
    timeout_seconds: int,
    cancel_event: threading.Event | None = None,
) -> tuple[str, str, int]:
    """Run one Codex print-mode turn as its dedicated Unix user.

    ``codex_argv`` is a list of fixed Codex flags plus a validated UUID.
    ``prompt`` is base64 encoded for Ansible transport and decoded into the
    command module's stdin field; it never becomes a shell fragment or argv
    value.  The selected credential is not read or copied by this function.
    """
    if not _AGENT_NAME_RE.fullmatch(agent_name) or agent_name in RESERVED_UNIX_NAMES:
        raise CodexChatTransportError(f"invalid Codex agent user: {agent_name!r}")
    if not isinstance(prompt, str):
        raise CodexChatTransportError("Codex chat prompt must be text")
    if (
        not isinstance(codex_argv, list)
        or not codex_argv
        or any(not isinstance(item, str) or not item for item in codex_argv)
    ):
        raise CodexChatTransportError("Codex chat argv must be a non-empty string list")

    from clawrium.core.hosts import get_host

    host = get_host(hostname)
    if not host:
        return "", "", 255

    os_family = normalize_os_family(host)
    try:
        playbook = resolve_agent_playbook("codex", "chat", os_family)
    except (FileNotFoundError, ValueError):
        return "", "", 255

    key_id = host.get("key_id") or host.get("hostname")
    ssh_key = core_keys.get_host_private_key(key_id)
    if not ssh_key:
        return "", "", 255

    effective_timeout = _effective_timeout(timeout_seconds)
    # b64decode happens once inside the Ansible command module.  That avoids
    # recursive Jinja evaluation of prompt text such as ``{{ lookup(...) }}``.
    prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    extra_vars = {
        "agent_name": agent_name,
        "codex_chat_argv": codex_argv,
        "codex_chat_prompt_b64": prompt_b64,
        "codex_chat_timeout": effective_timeout,
    }

    try:
        inventory = _build_inventory(host, ssh_key, extra_vars)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        raw_display = host.get("alias") or host.get("key_id") or host["hostname"]
        display = (
            raw_display if _LOG_DIR_SAFE_RE.fullmatch(raw_display or "") else "host"
        )
        work_dir = (
            _logs_dir() / f"codex-chat-{display}-{timestamp}-{uuid.uuid4().hex[:8]}"
        )
        work_dir.mkdir(parents=True, exist_ok=False)
        os.chmod(work_dir, 0o700)
    except OSError:
        return "", "", 255

    try:
        runner_kwargs = {
            "private_data_dir": str(work_dir),
            "inventory": inventory,
            "playbook": str(playbook),
            "quiet": True,
            "timeout": effective_timeout + _RUNNER_GRACE_SECONDS,
        }
        if cancel_event is None:
            result = ansible_runner.run(**runner_kwargs)
        else:
            runner_thread, result = ansible_runner.run_async(
                **runner_kwargs,
                cancel_callback=cancel_event.is_set,
            )
            runner_thread.join()
    except Exception:
        _cleanup_artifacts(work_dir)
        return "", "", 255

    try:
        if result.status == "timeout":
            return "", "", 124
        if result.status != "successful":
            return "", "", 255
        stdout, stderr, rc = _parse_events(result)
        if rc is None:
            return stdout, stderr, 255
        return stdout, stderr, rc
    finally:
        _cleanup_artifacts(work_dir)


def _sanitize_codex_text(value: str) -> str:
    """Remove terminal-control and bidi characters while preserving markdown."""
    # Keep tabs and newlines: Codex answers legitimately contain code blocks,
    # lists, and paragraphs. Carriage returns and escape bytes remain stripped.
    return _CONTROL_AND_BIDI_RE.sub("", value)


def _parse_result(stdout: str) -> tuple[str, str]:
    """Parse Codex's bounded JSONL event stream without relaying raw events.

    The pinned CLI emits ``thread.started`` followed by item events. Only the
    native thread ID and completed agent-message text cross this boundary.
    """
    if not isinstance(stdout, str) or not stdout.strip():
        raise ChatProtocolError("Codex returned an empty JSONL response")
    thread_id: str | None = None
    messages: list[str] = []
    turn_completed = False
    lines = stdout.splitlines()
    if len(lines) > 2048:
        raise ChatProtocolError("Codex returned too many JSONL events")
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ChatProtocolError("Codex returned malformed JSONL") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ChatProtocolError("Codex returned an invalid JSONL event")
        if turn_completed:
            raise ChatProtocolError("Codex returned events after turn completion")
        if event["type"] in {"turn.failed", "error"}:
            raise ChatProtocolError("Codex turn failed")
        if event["type"] == "thread.started":
            if thread_id is not None:
                raise ChatProtocolError("Codex returned multiple thread IDs")
            value = event.get("thread_id")
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ChatProtocolError("Codex returned an invalid thread ID")
            thread_id = value
        elif event["type"] == "item.completed":
            if thread_id is None:
                raise ChatProtocolError("Codex returned an item before its thread ID")
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if not isinstance(text, str):
                    raise ChatProtocolError("Codex agent message is invalid")
                messages.append(text)
        elif event["type"] == "turn.completed":
            turn_completed = True
    if thread_id is None or not messages or not turn_completed:
        raise ChatProtocolError("Codex response is missing text, thread ID, or completion")
    return _sanitize_codex_text("\n".join(messages)), thread_id


class CodexChatBackend:
    """A finite, on-demand Codex implementation of ``ChatBackend``.

    ``connect`` only establishes local backend state.  Each ``send_message``
    launches a finite remote Codex process through ``run_codex_chat``;
    no daemon, gateway, port, tunnel, or persistent controller-side credential
    is introduced.
    """

    def __init__(
        self,
        hostname: str,
        agent_name: str,
        timeout_seconds: float = 120.0,
        command_runner: CodexChatRunner = run_codex_chat,
    ) -> None:
        self.hostname = hostname
        self.agent_name = agent_name
        self.timeout_seconds = timeout_seconds
        self._command_runner = command_runner
        self._thread_id: str | None = None
        self._session_key: str | None = None
        self._started = False
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    def clear_history(self) -> None:
        """Start a fresh native thread without deleting agent-owned history."""
        self._thread_id = None
        self._started = False
        self._session_key = None

    def _argv_for_turn(self, session_key: str) -> list[str]:
        # The browser/CLI key never reaches Codex. It only selects this
        # backend's native thread, preserving independent conversations.
        if self._session_key is not None and session_key != self._session_key:
            self.clear_history()
        self._session_key = session_key
        if self._started and self._thread_id:
            return [
                "exec",
                "resume",
                "--json",
                "--skip-git-repo-check",
                self._thread_id,
                "-",
            ]
        # An isolated agent's home is not a Git repository. Codex otherwise
        # exits before processing the prompt, even with valid OAuth credentials.
        return ["exec", "--json", "--skip-git-repo-check", "-"]

    async def send_message(
        self,
        message: str,
        session_key: str,
        on_delta: Callable[[str], None] | None = None,
        response_timeout_seconds: float = 120.0,
    ) -> str:
        if not self._connected:
            raise ChatConnectionError("Codex chat backend not connected")
        if not isinstance(message, str):
            raise ChatProtocolError("Codex chat message must be text")

        timeout = _effective_timeout(
            response_timeout_seconds
            if response_timeout_seconds
            else self.timeout_seconds
        )
        argv = self._argv_for_turn(session_key)
        cancel_event = threading.Event()
        completed = threading.Event()
        result: tuple[str, str, int] | None = None
        runner_error: Exception | None = None

        def run_turn() -> None:
            nonlocal result, runner_error
            try:
                result = self._command_runner(
                    self.hostname,
                    self.agent_name,
                    argv,
                    message,
                    timeout,
                    cancel_event,
                )
            except Exception as exc:  # surfaced below on the async caller
                runner_error = exc
            finally:
                completed.set()

        threading.Thread(target=run_turn, daemon=True).start()
        try:
            while not completed.is_set():
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            # `ansible_runner.run_async(..., cancel_callback=...)` kills its
            # local Ansible process group. The remote command itself is also
            # process-group-bounded by the platform playbook. Wait until the
            # runner returns and deletes its prompt-bearing artifacts before
            # reporting the interrupted turn to the user.
            cancel_event.set()
            while not completed.is_set():
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    continue
            # A disconnect can race after Codex creates a native thread but
            # before we receive its result. Start the browser key fresh rather
            # than resuming a turn the browser abandoned.
            self.clear_history()
            self._connected = False
            raise

        if runner_error is not None:
            if isinstance(runner_error, CodexChatTransportError):
                raise ChatConnectionError(
                    "Could not start Codex chat"
                ) from runner_error
            raise ChatConnectionError(
                "Could not run Codex chat remotely"
            ) from runner_error
        if result is None:
            raise ChatConnectionError("Could not run Codex chat remotely")
        stdout, stderr, rc = result

        if rc == 124:
            raise ChatConnectionError(
                f"Timed out waiting for Codex response after {timeout}s"
            )
        if rc != 0:
            # Codex's print mode may write an authentication diagnostic to
            # stdout before returning non-zero (the native exec path observes
            # this for rejected API keys); classify either stream without
            # relaying its content to CLI or GUI callers.
            if _AUTH_FAILURE_RE.search(stdout) or _AUTH_FAILURE_RE.search(stderr):
                raise ChatAuthenticationError(
                    "Codex rejected the configured credential"
                )
            if rc == 255:
                raise ChatConnectionError("Could not run Codex chat remotely")
            raise ChatProtocolError(f"Codex exited with status {rc}")

        response, thread_id = _parse_result(stdout)
        self._thread_id = thread_id
        self._started = True
        if on_delta and response:
            on_delta(response)
        return response

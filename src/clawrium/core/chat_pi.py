"""Finite on-demand Pi chat backend using a provisioned OpenRouter selection."""

from __future__ import annotations

import asyncio
import base64
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
from clawrium.core.pi import PiProvisioningError, pi_chat_argv
from clawrium.core.playbook_resolver import normalize_os_family, resolve_agent_playbook

__all__ = ["PiChatBackend", "PiChatTransportError", "run_pi_chat"]

_HARD_TIMEOUT_CAP = 1800
_RUNNER_GRACE_SECONDS = 30
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_LOG_DIR_SAFE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTROL_RE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200b-\u200f\u2028-\u2029\u202a-\u202e\u2060\u2066-\u2069\ufeff]"
)
_AUTH_RE = re.compile(
    r"\b(auth(?:entication|orization)?|unauthori[sz]ed|forbidden|api[ _-]?key|credential)\b",
    re.I,
)
PiChatRunner = Callable[
    [str, str, list[str], str, int, threading.Event], tuple[str, str, int]
]


class PiChatTransportError(Exception):
    pass


def _timeout(value: float) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 120
    return (
        min(max(1, math.ceil(parsed)), _HARD_TIMEOUT_CAP)
        if math.isfinite(parsed) and parsed > 0
        else 120
    )


def _logs_dir() -> Path:
    path = get_config_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_events(result: Any, private_key: Path) -> tuple[str, str, int | None]:
    """Decrypt the opaque Pi result without logging native output."""
    from clawrium.core.agent_exec import _parse_pi_secure_result

    class _ChatResult:
        events = []

    encrypted = _ChatResult()
    for event in result.events:
        message = event.get("event_data", {}).get("res", {}).get("msg")
        if isinstance(message, str) and message.startswith("PI_CHAT_RESULT="):
            encrypted.events.append(
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "res": {
                            "msg": "PI_EXEC_RESULT=" + message[len("PI_CHAT_RESULT=") :]
                        }
                    },
                }
            )
    return _parse_pi_secure_result(encrypted, private_key)


def run_pi_chat(
    hostname: str,
    agent_name: str,
    pi_argv: list[str],
    prompt: str,
    timeout_seconds: int,
    cancel_event: threading.Event | None = None,
) -> tuple[str, str, int]:
    """Run one Pi print-mode turn without copying its credential to controller state."""
    if not _AGENT_NAME_RE.fullmatch(agent_name) or agent_name in RESERVED_UNIX_NAMES:
        raise PiChatTransportError("invalid Pi agent user")
    if (
        not isinstance(prompt, str)
        or not pi_argv
        or any(not isinstance(v, str) or not v for v in pi_argv)
    ):
        raise PiChatTransportError("Pi chat requires text and a non-empty argv")
    from clawrium.core.hosts import get_host

    host = get_host(hostname)
    if not host:
        return "", "", 255
    try:
        playbook = resolve_agent_playbook("pi", "chat", normalize_os_family(host))
    except (FileNotFoundError, ValueError):
        return "", "", 255
    ssh_key = core_keys.get_host_private_key(host.get("key_id") or host.get("hostname"))
    if not ssh_key:
        return "", "", 255
    timeout = _timeout(timeout_seconds)
    extra_vars = {
        "agent_name": agent_name,
        "pi_chat_argv": pi_argv,
        "pi_chat_prompt_b64": base64.b64encode(prompt.encode()).decode(),
        "pi_chat_timeout": timeout,
    }
    raw = host.get("alias") or host.get("key_id") or host["hostname"]
    display = raw if _LOG_DIR_SAFE_RE.fullmatch(raw or "") else "host"
    work_dir = (
        _logs_dir()
        / f"pi-chat-{display}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    try:
        work_dir.mkdir(parents=True, exist_ok=False)
        os.chmod(work_dir, 0o700)
        from clawrium.core.agent_exec import _create_pi_exec_keypair

        private_key, certificate = _create_pi_exec_keypair(work_dir)
        extra_vars["pi_chat_recipient_certificate"] = certificate
        inventory = {
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
        kwargs = {
            "private_data_dir": str(work_dir),
            "inventory": inventory,
            "playbook": str(playbook),
            "quiet": True,
            "timeout": timeout + _RUNNER_GRACE_SECONDS,
        }
        if cancel_event is None:
            result = ansible_runner.run(**kwargs)
        else:
            thread, result = ansible_runner.run_async(
                **kwargs, cancel_callback=cancel_event.is_set
            )
            thread.join()
        if result.status == "timeout":
            return "", "", 124
        if result.status != "successful":
            return "", "", 255
        stdout, stderr, rc = _parse_events(result, private_key)
        return stdout, stderr, rc if rc is not None else 255
    except Exception:
        return "", "", 255
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


class PiChatBackend:
    """A session-preserving Pi print-mode backend; each turn is a bounded SSH job."""

    def __init__(
        self,
        hostname: str,
        agent_name: str,
        model: str,
        timeout_seconds: float = 120.0,
        command_runner: PiChatRunner = run_pi_chat,
        session_id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self.hostname, self.agent_name, self.model = hostname, agent_name, model
        self.timeout_seconds, self._runner, self._factory = (
            timeout_seconds,
            command_runner,
            session_id_factory,
        )
        self._session_id = str(session_id_factory())
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
        self._session_id = str(self._factory())
        self._session_key = None
        self._started = False

    async def send_message(
        self,
        message: str,
        session_key: str,
        on_delta: Callable[[str], None] | None = None,
        response_timeout_seconds: float = 120.0,
    ) -> str:
        if not self._connected:
            raise ChatConnectionError("Pi chat backend not connected")
        if not isinstance(message, str):
            raise ChatProtocolError("Pi chat message must be text")
        if self._session_key is not None and self._session_key != session_key:
            self.clear_history()
        self._session_key = session_key
        try:
            argv = pi_chat_argv(self.model, self._session_id, resume=self._started)
        except PiProvisioningError as exc:
            raise ChatProtocolError(str(exc)) from exc

        timeout = _timeout(response_timeout_seconds or self.timeout_seconds)
        cancel, done = threading.Event(), threading.Event()
        result: tuple[str, str, int] | None = None

        def run() -> None:
            nonlocal result
            result = self._runner(
                self.hostname, self.agent_name, argv, message, timeout, cancel
            )
            done.set()

        threading.Thread(target=run, daemon=True).start()
        try:
            while not done.is_set():
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            cancel.set()
            while not done.is_set():
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    continue
            self.clear_history()
            self._connected = False
            raise

        if result is None:
            raise ChatConnectionError("Could not run Pi chat remotely")
        stdout, stderr, rc = result
        if rc == 124:
            raise ChatConnectionError(
                f"Timed out waiting for Pi response after {timeout}s"
            )
        if rc != 0:
            if _AUTH_RE.search(stdout) or _AUTH_RE.search(stderr):
                raise ChatAuthenticationError(
                    "Pi rejected the configured OpenRouter credential"
                )
            if rc == 255:
                raise ChatConnectionError("Could not run Pi chat remotely")
            raise ChatProtocolError(f"Pi exited with status {rc}")

        response = _CONTROL_RE.sub("", stdout).strip()
        if not response:
            raise ChatProtocolError("Pi returned an empty response")
        self._started = True
        if on_delta:
            on_delta(response)
        return response

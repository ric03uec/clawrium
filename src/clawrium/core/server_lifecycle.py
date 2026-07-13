"""GUI server lifecycle: detached spawn, PID/state file, TCP probe.

This module powers `clawctl server {start,stop,status,run}`. It exists
outside the CLI layer so its logic is unit-testable without CliRunner.

Contract:
  - The GUI server binds `127.0.0.1:36000` — port is fixed by design
    (see .itx/874/00_PLAN.md). If the port is occupied by a foreign
    process, `start_detached` raises `PortInUseError`.
  - State (PID + host + port + URL + started_at) persists at
    `<config_dir>/server.json`.
  - Detached spawn uses `subprocess.Popen(..., start_new_session=True)`
    — the standard POSIX daemon pattern, works on Linux and macOS.
    PR 1 restricts to Linux only; PR 2 lifts the guard.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from clawrium.core.config import init_config_dir

__all__ = [
    "GUI_HOST",
    "GUI_PORT",
    "PortInUseError",
    "ServerAlreadyRunningError",
    "ServerNotRunningError",
    "ServerStartupError",
    "ServerState",
    "read_state",
    "write_state",
    "clear_state",
    "state_file_path",
    "log_file_path",
    "is_pid_alive",
    "is_port_free",
    "wait_for_port",
    "start_detached",
    "stop_running",
    "read_status",
]

GUI_HOST = "127.0.0.1"
GUI_PORT = 36000
_STARTUP_TIMEOUT_SECONDS = 5.0
_STARTUP_POLL_INTERVAL_SECONDS = 0.1
_STOP_TIMEOUT_SECONDS = 5.0
_STOP_POLL_INTERVAL_SECONDS = 0.1


class PortInUseError(RuntimeError):
    """Raised when port 36000 is occupied by a foreign process."""


class ServerAlreadyRunningError(RuntimeError):
    """Raised when start is called and the server is already running.

    Carries the current `ServerState` so the CLI can print the URL.
    """

    def __init__(self, state: "ServerState") -> None:
        super().__init__(f"Server already running at {state.url}")
        self.state = state


class ServerNotRunningError(RuntimeError):
    """Raised when stop is called and the server is not running."""


class ServerStartupError(RuntimeError):
    """Raised when the child process failed to bind within the timeout."""


@dataclass(frozen=True)
class ServerState:
    """Persisted state of a running detached GUI server."""

    pid: int
    host: str
    port: int
    url: str
    started_at: str  # ISO-8601 UTC

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "host": self.host,
            "port": self.port,
            "url": self.url,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ServerState":
        return cls(
            pid=int(data["pid"]),
            host=str(data["host"]),
            port=int(data["port"]),
            url=str(data["url"]),
            started_at=str(data["started_at"]),
        )


def state_file_path() -> Path:
    """Path to the server state file (does not create parents)."""
    from clawrium.core.config import get_config_dir

    return get_config_dir() / "server.json"


def log_file_path() -> Path:
    """Path to the detached server log file (does not create parents)."""
    from clawrium.core.config import get_config_dir

    return get_config_dir() / "logs" / "server.log"


def read_state() -> Optional[ServerState]:
    """Read the state file; return None if it is absent or malformed."""
    path = state_file_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return ServerState.from_dict(data)
    except (OSError, ValueError, KeyError):
        return None


def write_state(state: ServerState) -> None:
    """Write the state file atomically with 0o600 mode."""
    init_config_dir()
    path = state_file_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2))
    tmp.chmod(0o600)
    os.replace(tmp, path)


def clear_state() -> None:
    """Delete the state file if it exists."""
    path = state_file_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def is_pid_alive(pid: int) -> bool:
    """Return True if the given PID exists and is signalable."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it; treat as alive.
        return True
    return True


def is_port_free(host: str, port: int) -> bool:
    """Return True if a TCP listener could bind (host, port)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, errno.EACCES):
                return False
            raise
    return True


def _port_accepting(host: str, port: int, timeout: float = 0.25) -> bool:
    """Return True if a TCP connection to (host, port) is accepted."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return False
    return True


def wait_for_port(
    host: str,
    port: int,
    timeout: float = _STARTUP_TIMEOUT_SECONDS,
    proc: Optional["subprocess.Popen"] = None,
) -> bool:
    """Poll until a listener accepts on (host, port) or timeout expires.

    If `proc` is passed, the loop short-circuits when the child exits so
    a crashed child doesn't burn the full timeout window (ATX B2).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        if _port_accepting(host, port):
            return True
        time.sleep(_STARTUP_POLL_INTERVAL_SECONDS)
    return _port_accepting(host, port)


def _spawn_command() -> list[str]:
    """Command line for the detached uvicorn process."""
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "clawrium.gui.server:app",
        "--host",
        GUI_HOST,
        "--port",
        str(GUI_PORT),
        "--log-level",
        "info",
    ]


def _read_log_tail(path: Path, lines: int = 20) -> str:
    try:
        text = path.read_text()
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _assert_supported_platform() -> None:
    """PR 1 platform gate — Linux only. Removed in PR 2."""
    if sys.platform != "linux":
        raise RuntimeError(
            "clawctl server is Linux-only in this release; "
            "macOS support ships in a follow-up PR."
        )


def start_detached() -> ServerState:
    """Spawn the GUI server detached from the current shell.

    Returns the persisted `ServerState`. Raises:
      - `ServerAlreadyRunningError` if a live state file already exists.
      - `PortInUseError` if :36000 is occupied by a foreign process.
      - `ServerStartupError` if the child failed to bind within timeout.
    """
    _assert_supported_platform()

    existing = read_state()
    if existing is not None and is_pid_alive(existing.pid):
        raise ServerAlreadyRunningError(existing)
    if existing is not None and not is_pid_alive(existing.pid):
        # Stale state file: previous process died. Clear and continue.
        clear_state()

    if not is_port_free(GUI_HOST, GUI_PORT):
        raise PortInUseError(
            f"port {GUI_PORT} already in use by another process"
        )

    init_config_dir()
    log_path = log_file_path()
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Truncate on start; no rotation in v1. 0o600 keeps request paths
    # and startup timing out of world-readable files. Failure here
    # (log dir unwritable) is a start failure — wrap as
    # ServerStartupError so the CLI catch ladder renders cleanly.
    try:
        log_fh = open(
            log_path,
            "w",
            opener=lambda p, f: os.open(p, f, 0o600),
        )
    except OSError as exc:
        raise ServerStartupError(f"cannot open server log: {exc}") from exc
    try:
        try:
            proc = subprocess.Popen(
                _spawn_command(),
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            # sys.executable missing, uvicorn shim unexecutable, etc.
            # Re-raise as a domain error so the CLI catch ladder can
            # render it cleanly instead of a raw traceback.
            raise ServerStartupError(
                f"failed to launch server process: {exc}"
            ) from exc
    finally:
        log_fh.close()

    if not wait_for_port(GUI_HOST, GUI_PORT, proc=proc):
        # Health check failed — clean up.
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        tail = _read_log_tail(log_path)
        exit_code = proc.poll()
        if exit_code is not None:
            raise ServerStartupError(
                f"server process exited (code {exit_code}) before binding "
                f"{GUI_HOST}:{GUI_PORT}\n{tail}"
            )
        raise ServerStartupError(
            f"server failed to bind {GUI_HOST}:{GUI_PORT} within "
            f"{_STARTUP_TIMEOUT_SECONDS:.0f}s\n{tail}"
        )

    # ATX B1: confirm the child is still alive after wait_for_port
    # succeeded. Guards against the "child crashed then a foreign
    # process grabbed :36000" race that would otherwise let us persist
    # a dead child's PID.
    exit_code = proc.poll()
    if exit_code is not None:
        tail = _read_log_tail(log_path)
        raise ServerStartupError(
            f"server process exited (code {exit_code}) before port "
            f"was confirmed\n{tail}"
        )

    url = f"http://{GUI_HOST}:{GUI_PORT}"
    state = ServerState(
        pid=proc.pid,
        host=GUI_HOST,
        port=GUI_PORT,
        url=url,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    write_state(state)
    return state


def stop_running() -> ServerState:
    """Stop the running server; return the state that was stopped.

    Raises `ServerNotRunningError` if there is no live server.
    """
    state = read_state()
    if state is None:
        raise ServerNotRunningError("server is not running")
    if not is_pid_alive(state.pid):
        # Stale state — clean and treat as not-running.
        clear_state()
        raise ServerNotRunningError("server is not running")

    try:
        os.kill(state.pid, signal.SIGTERM)
    except ProcessLookupError:
        clear_state()
        return state

    deadline = time.monotonic() + _STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not is_pid_alive(state.pid):
            break
        time.sleep(_STOP_POLL_INTERVAL_SECONDS)

    if is_pid_alive(state.pid):
        try:
            os.kill(state.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    clear_state()
    return state


@dataclass(frozen=True)
class ServerStatus:
    """Snapshot status derived once inside `read_status`.

    Both `pid_alive` and `port_accepting` are eagerly resolved so the
    dataclass tells one consistent story across all fields. Callers
    that need a fresh probe must call `read_status()` again.
    """

    running: bool
    state: Optional[ServerState]
    pid_alive: bool = False
    port_accepting: bool = False


def read_status() -> ServerStatus:
    """Compute live status from the state file and process/port probes.

    A stale state file (PID gone or port dead) is auto-cleaned so the
    next `start` is not blocked by leftover state from a crashed run.
    """
    state = read_state()
    if state is None:
        return ServerStatus(running=False, state=None)
    pid_alive = is_pid_alive(state.pid)
    if not pid_alive:
        clear_state()
        return ServerStatus(running=False, state=None)
    # ATX W1: PID space wraps at ~32768 on Linux. If the recorded PID
    # was reused by an unrelated process the port probe is the tie
    # breaker — a live PID that no longer answers on :36000 means the
    # server we recorded is gone.
    port_accepting = _port_accepting(state.host, state.port)
    if not port_accepting:
        clear_state()
        return ServerStatus(running=False, state=None)
    return ServerStatus(
        running=True,
        state=state,
        pid_alive=True,
        port_accepting=True,
    )

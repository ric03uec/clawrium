"""Unit tests for `clawrium.core.server_lifecycle`.

These tests exercise the state file, PID probe, port probe, and the
start/stop control flow with a mocked `subprocess.Popen`. No child
process is actually spawned.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from clawrium.core import server_lifecycle as sl


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point config_dir at a tmp dir so state files don't collide."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "clawrium"


def test_state_roundtrip() -> None:
    state = sl.ServerState(
        pid=12345,
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="2026-07-12T10:30:00+00:00",
    )
    sl.write_state(state)

    loaded = sl.read_state()
    assert loaded == state
    # Pin the 0o600 security contract documented on write_state.
    mode = sl.state_file_path().stat().st_mode & 0o777
    assert mode == 0o600


def test_read_state_absent_returns_none() -> None:
    assert sl.read_state() is None


def test_read_state_malformed_returns_none(_isolated_config_dir: Path) -> None:
    sl.init_config_dir()
    sl.state_file_path().write_text("not json")
    assert sl.read_state() is None


def test_clear_state_is_idempotent() -> None:
    sl.clear_state()  # missing → no error
    state = sl.ServerState(1, "127.0.0.1", 36000, "u", "t")
    sl.write_state(state)
    sl.clear_state()
    assert not sl.state_file_path().exists()


def test_is_pid_alive_current_process() -> None:
    assert sl.is_pid_alive(os.getpid()) is True


def test_is_pid_alive_bogus_pid() -> None:
    # PID 1 is init, guaranteed alive on POSIX; use a large impossible value.
    assert sl.is_pid_alive(0) is False
    assert sl.is_pid_alive(-1) is False


def test_is_pid_alive_dead_pid() -> None:
    # 2**22 is well above default pid_max on Linux — very likely dead.
    assert sl.is_pid_alive(2**22) is False


def test_is_port_free_when_bound_returns_false() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        _, port = sock.getsockname()
        assert sl.is_port_free("127.0.0.1", port) is False


def test_is_port_free_treats_eacces_as_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4 (iter-8): EACCES on bind (privileged port) → not free."""
    import errno as _errno

    class _FakeSock:
        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *a):  # noqa: ANN204
            return False

        def setsockopt(self, *a):  # noqa: ANN201, ANN002
            pass

        def bind(self, addr):  # noqa: ANN001
            err = OSError()
            err.errno = _errno.EACCES
            raise err

    monkeypatch.setattr(sl.socket, "socket", lambda *a, **k: _FakeSock())
    assert sl.is_port_free("127.0.0.1", 80) is False


def test_is_port_free_when_unbound_returns_true() -> None:
    # Bind and immediately close to get a likely-free port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()
    assert sl.is_port_free("127.0.0.1", port) is True


def test_wait_for_port_returns_false_on_timeout() -> None:
    # Pick a port that is very unlikely to have a listener.
    assert sl.wait_for_port("127.0.0.1", 1, timeout=0.2) is False


def test_stop_when_not_running_raises() -> None:
    with pytest.raises(sl.ServerNotRunningError):
        sl.stop_running()


def test_stop_stale_state_raises_and_cleans() -> None:
    stale = sl.ServerState(2**22, "127.0.0.1", 36000, "u", "t")
    sl.write_state(stale)
    with pytest.raises(sl.ServerNotRunningError):
        sl.stop_running()
    assert sl.read_state() is None


def test_stop_running_escalates_to_sigkill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W3 (tests): SIGTERM → wait → SIGKILL when the process ignores TERM."""
    import signal as _signal

    state = sl.ServerState(
        pid=os.getpid(),
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="t",
    )
    sl.write_state(state)

    signals: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        signals.append((pid, sig))

    # Process refuses to die until we send SIGKILL.
    killed = {"done": False}

    def fake_is_alive(pid: int) -> bool:
        if any(sig == _signal.SIGKILL for _, sig in signals):
            killed["done"] = True
            return False
        return True

    monkeypatch.setattr(sl.os, "kill", fake_kill)
    monkeypatch.setattr(sl, "is_pid_alive", fake_is_alive)
    # Bypass the port tiebreaker (mirrors the read_status pattern).
    monkeypatch.setattr(sl, "_port_accepting", lambda h, p, timeout=0.25: True)
    # Speed up the wait loop so the test completes fast.
    monkeypatch.setattr(sl, "_STOP_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(sl, "_STOP_POLL_INTERVAL_SECONDS", 0.05)

    result = sl.stop_running()
    assert result == state
    assert (os.getpid(), _signal.SIGTERM) in signals
    assert (os.getpid(), _signal.SIGKILL) in signals
    # SIGTERM must come before SIGKILL.
    term_idx = signals.index((os.getpid(), _signal.SIGTERM))
    kill_idx = signals.index((os.getpid(), _signal.SIGKILL))
    assert term_idx < kill_idx
    assert sl.read_state() is None


def test_stop_running_process_disappears_between_alive_check_and_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3: SIGTERM raises ProcessLookupError (TOCTOU) → clear + return."""
    import signal as _signal

    state = sl.ServerState(
        pid=os.getpid(),
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="t",
    )
    sl.write_state(state)

    # is_pid_alive says yes; os.kill raises ProcessLookupError.
    monkeypatch.setattr(sl, "is_pid_alive", lambda pid: True)
    monkeypatch.setattr(sl, "_port_accepting", lambda h, p, timeout=0.25: True)

    def racy_kill(pid: int, sig: int) -> None:
        assert sig == _signal.SIGTERM
        raise ProcessLookupError()

    monkeypatch.setattr(sl.os, "kill", racy_kill)

    result = sl.stop_running()
    assert result == state
    assert sl.read_state() is None


def test_start_detached_log_open_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B4: unwritable log dir → ServerStartupError, no state written."""
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: True)

    real_open = open

    def boom(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if str(path).endswith("server.log"):
            raise PermissionError("log unwritable")
        return real_open(path, *args, **kwargs)

    import builtins as _b

    monkeypatch.setattr(_b, "open", boom)

    with pytest.raises(sl.ServerStartupError) as exc:
        sl.start_detached()
    assert "log" in str(exc.value).lower()
    assert sl.read_state() is None


def test_start_detached_wraps_popen_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Popen failures (missing binary etc.) surface as ServerStartupError."""
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: True)

    def boom(*a, **k):  # noqa: ANN001, ANN002, ANN003
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(sl.subprocess, "Popen", boom)

    with pytest.raises(sl.ServerStartupError) as exc:
        sl.start_detached()
    assert "failed to launch" in str(exc.value)
    assert sl.read_state() is None


def test_stop_running_bails_when_pid_alive_but_port_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Iter-6 W1: PID recycled to unrelated process → refuse to SIGTERM."""
    state = sl.ServerState(
        pid=os.getpid(),
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="t",
    )
    sl.write_state(state)
    monkeypatch.setattr(sl, "is_pid_alive", lambda pid: True)
    monkeypatch.setattr(sl, "_port_accepting", lambda h, p, timeout=0.25: False)

    signaled: list[int] = []
    monkeypatch.setattr(sl.os, "kill", lambda pid, sig: signaled.append(sig))

    with pytest.raises(sl.ServerNotRunningError):
        sl.stop_running()
    # Critical: no signal sent to a possibly-unrelated process.
    assert signaled == []
    assert sl.read_state() is None


def test_read_status_when_stopped() -> None:
    live = sl.read_status()
    assert live.running is False
    assert live.state is None


def test_read_status_cleans_stale_state() -> None:
    stale = sl.ServerState(2**22, "127.0.0.1", 36000, "u", "t")
    sl.write_state(stale)
    live = sl.read_status()
    assert live.running is False
    assert sl.read_state() is None


def test_read_status_running_when_pid_alive_and_port_accepting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = sl.ServerState(
        pid=os.getpid(),
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="t",
    )
    sl.write_state(state)
    monkeypatch.setattr(sl, "_port_accepting", lambda h, p, timeout=0.25: True)
    live = sl.read_status()
    assert live.running is True
    assert live.state == state


def test_read_status_cleans_when_pid_alive_but_port_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1: PID reused by unrelated process → port not accepting → clear."""
    state = sl.ServerState(
        pid=os.getpid(),
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="t",
    )
    sl.write_state(state)
    monkeypatch.setattr(sl, "_port_accepting", lambda h, p, timeout=0.25: False)
    live = sl.read_status()
    assert live.running is False
    assert sl.read_state() is None


def test_is_pid_alive_permission_error_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4 (iter-5): EPERM from os.kill(pid, 0) → process exists, treat alive."""

    def eperm(pid: int, sig: int) -> None:
        raise PermissionError()

    monkeypatch.setattr(sl.os, "kill", eperm)
    assert sl.is_pid_alive(12345) is True


def test_start_detached_clears_stale_state_and_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W3 (iter-5): a state file with a dead PID must not block start.

    This is the crash-then-restart scenario — the most operationally
    common path — and had zero coverage.
    """
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: True)
    monkeypatch.setattr(
        sl, "wait_for_port", lambda h, p, timeout=5.0, proc=None: True
    )

    # Leave a state file pointing at a definitely-dead PID.
    stale = sl.ServerState(
        pid=2**22, host="127.0.0.1", port=36000, url="http://127.0.0.1:36000",
        started_at="t",
    )
    sl.write_state(stale)

    class _FakeProc:
        pid = 55555

        def poll(self) -> None:
            return None

    monkeypatch.setattr(sl.subprocess, "Popen", lambda *a, **k: _FakeProc())

    result = sl.start_detached()
    assert result.pid == 55555
    assert sl.read_state() is not None
    assert sl.read_state().pid == 55555


def test_start_detached_clears_recycled_pid_and_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """iter-8 B1: live PID but port dead (recycled) → clear stale state.

    Otherwise `clawctl server start` prints "already running" pointing
    at a URL that goes nowhere, and the user is stranded.
    """
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: True)
    monkeypatch.setattr(
        sl, "wait_for_port", lambda h, p, timeout=5.0, proc=None: True
    )
    monkeypatch.setattr(sl, "_port_accepting", lambda h, p, timeout=0.25: False)

    # Live PID (this test process) — but simulated port-dead.
    recycled = sl.ServerState(
        pid=os.getpid(), host="127.0.0.1", port=36000,
        url="http://127.0.0.1:36000", started_at="t",
    )
    sl.write_state(recycled)

    class _FakeProc:
        pid = 66666

        def poll(self) -> None:
            return None

    monkeypatch.setattr(sl.subprocess, "Popen", lambda *a, **k: _FakeProc())

    result = sl.start_detached()
    assert result.pid == 66666
    assert sl.read_state().pid == 66666


def test_start_detached_already_running_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    # Port accepting → recorded state is really our server.
    monkeypatch.setattr(sl, "_port_accepting", lambda h, p, timeout=0.25: True)
    state = sl.ServerState(
        pid=os.getpid(),
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="t",
    )
    sl.write_state(state)

    with pytest.raises(sl.ServerAlreadyRunningError) as exc:
        sl.start_detached()
    assert exc.value.state == state


def test_start_detached_port_in_use_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: False)

    with pytest.raises(sl.PortInUseError):
        sl.start_detached()


def test_start_detached_uses_new_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detached spawn MUST pass start_new_session=True."""
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: True)
    monkeypatch.setattr(
        sl, "wait_for_port", lambda h, p, timeout=5.0, proc=None: True
    )

    captured: dict = {}

    class _FakeProc:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self) -> None:  # child still running
            return None

    def fake_popen(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProc(pid=99999)

    monkeypatch.setattr(sl.subprocess, "Popen", fake_popen)

    state = sl.start_detached()

    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["stdin"] is sl.subprocess.DEVNULL
    # Pin the exact command shape so a mutated layout that still
    # happens to contain the substring "uvicorn" cannot slip through.
    # Pin the whole command tail so a silent switch to `0.0.0.0` or a
    # different port cannot slip through the assertion.
    assert captured["cmd"] == sl._spawn_command()
    assert state.pid == 99999
    assert state.host == "127.0.0.1"
    assert state.port == 36000
    # State file was persisted.
    persisted = json.loads(sl.state_file_path().read_text())
    assert persisted["pid"] == 99999


def test_wait_for_port_short_circuits_on_dead_child() -> None:
    """B2: wait_for_port must exit fast when the child has died."""

    class _DeadProc:
        def poll(self) -> int:  # non-None → exited
            return 1

    import time as _time

    start = _time.monotonic()
    result = sl.wait_for_port("127.0.0.1", 1, timeout=5.0, proc=_DeadProc())
    elapsed = _time.monotonic() - start
    assert result is False
    # Must return well before the timeout — no more than one poll cycle.
    assert elapsed < 1.0


def test_start_detached_child_exit_after_port_bind_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1: child that dies between wait_for_port() and write_state()
    must NOT be persisted (the port could now belong to a foreign
    process that reused :36000)."""
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: True)
    monkeypatch.setattr(sl, "wait_for_port", lambda h, p, timeout=5.0, proc=None: True)

    class _CrashedAfterBind:
        pid = 42424

        def poll(self) -> int:
            return 137

    monkeypatch.setattr(sl.subprocess, "Popen", lambda *a, **k: _CrashedAfterBind())

    with pytest.raises(sl.ServerStartupError) as exc:
        sl.start_detached()
    assert "exited" in str(exc.value)
    # Critical: no state file may be written for a dead child.
    assert sl.read_state() is None


def test_start_detached_health_check_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: True)
    monkeypatch.setattr(
        sl, "wait_for_port", lambda h, p, timeout=5.0, proc=None: False
    )

    class _FakeProc:
        pid = 99998

        def poll(self) -> None:
            return None

    monkeypatch.setattr(sl.subprocess, "Popen", lambda *a, **k: _FakeProc())

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(sl.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    # Health check failure now escalates TERM → wait → KILL (iter-7 W3).
    monkeypatch.setattr(sl, "_STOP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(sl, "_STOP_POLL_INTERVAL_SECONDS", 0.01)

    with pytest.raises(sl.ServerStartupError) as exc:
        sl.start_detached()
    # Pin the exact branch — two distinct paths raise this exception.
    assert "failed to bind" in str(exc.value)

    import signal as _signal

    assert killed == [(99998, _signal.SIGTERM), (99998, _signal.SIGKILL)]
    # No state file left behind.
    assert sl.read_state() is None

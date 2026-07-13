"""CliRunner smoke tests for `clawctl server {start,stop,status,run}`."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core import server_lifecycle as sl

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def test_server_help_lists_verbs() -> None:
    result = runner.invoke(app, ["server", "--help"])
    assert result.exit_code == 0
    for verb in ("start", "stop", "status", "run"):
        assert verb in result.output


def test_status_stopped_by_default() -> None:
    result = runner.invoke(app, ["server", "status"])
    assert result.exit_code == 0
    assert "stopped" in result.output


def test_stop_when_not_running_is_noop() -> None:
    result = runner.invoke(app, ["server", "stop"])
    assert result.exit_code == 0
    assert "not running" in result.output.lower()


def test_start_reports_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    state = sl.ServerState(
        pid=os.getpid(),
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="t",
    )
    sl.write_state(state)
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)

    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 0
    assert "already running" in result.output
    assert "http://127.0.0.1:36000" in result.output


def test_start_port_in_use_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: False)

    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 1
    assert "port" in result.output.lower() or "port" in (result.stderr or "").lower()


def test_status_running_shows_url(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    state = sl.ServerState(
        pid=os.getpid(),
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="2026-07-12T10:30:00+00:00",
    )
    sl.write_state(state)
    # read_status() also checks port_accepting (ATX W1). Pretend the
    # port is answering so the running-branch is exercised.
    monkeypatch.setattr(sl, "_port_accepting", lambda h, p, timeout=0.25: True)

    result = runner.invoke(app, ["server", "status"])
    assert result.exit_code == 0
    assert "running" in result.output
    assert "http://127.0.0.1:36000" in result.output
    assert str(state.pid) in result.output


def test_start_lifecycle_writes_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sl, "_assert_supported_platform", lambda: None)
    monkeypatch.setattr(sl, "is_port_free", lambda h, p: True)
    monkeypatch.setattr(
        sl, "wait_for_port", lambda h, p, timeout=5.0, proc=None: True
    )

    class _FakeProc:
        pid = 77777

        def poll(self) -> None:
            return None

    monkeypatch.setattr(sl.subprocess, "Popen", lambda *a, **k: _FakeProc())

    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:36000" in result.output
    assert sl.read_state() is not None
    assert sl.read_state().pid == 77777


def test_stop_running_prints_pid_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """B4: `stop` happy-path prints the stopped pid and URL."""
    state = sl.ServerState(
        pid=99123,
        host="127.0.0.1",
        port=36000,
        url="http://127.0.0.1:36000",
        started_at="t",
    )
    import importlib

    stop_module = importlib.import_module("clawrium.cli.clawctl.server.stop")
    monkeypatch.setattr(stop_module, "stop_running", lambda: state)

    result = runner.invoke(app, ["server", "stop"])
    assert result.exit_code == 0
    assert "99123" in result.output
    assert "http://127.0.0.1:36000" in result.output


def test_start_reports_server_startup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1 (tests): CLI must render ServerStartupError → exit 1 cleanly."""
    import importlib

    start_module = importlib.import_module("clawrium.cli.clawctl.server.start")

    def boom() -> None:
        raise sl.ServerStartupError("startup timed out")

    monkeypatch.setattr(start_module, "start_detached", boom)

    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 1
    combined = result.output + (result.stderr or "")
    assert "server failed to start" in combined


def test_start_platform_gate_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """W2 (tests): platform gate on non-Linux → exit 1."""
    monkeypatch.setattr(sl.sys, "platform", "darwin")

    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 1
    combined = result.output + (result.stderr or "")
    assert "Linux-only" in combined


def test_run_missing_uvicorn_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """B3: `run` with no uvicorn installed must exit 1 with a clear error."""
    import builtins
    import sys

    real_import = builtins.__import__

    def deny_uvicorn(name, *args, **kwargs):  # noqa: ANN001
        if name == "uvicorn":
            raise ImportError("uvicorn not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "uvicorn", raising=False)
    monkeypatch.setattr(builtins, "__import__", deny_uvicorn)

    result = runner.invoke(app, ["server", "run"])
    assert result.exit_code == 1
    combined = result.output + (result.stderr or "")
    assert "GUI dependencies" in combined


def test_run_invokes_uvicorn_with_loopback_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3: `run` foreground path calls uvicorn.run with 127.0.0.1:36000."""
    import sys

    calls: dict = {}

    class _FakeUvicorn:
        @staticmethod
        def run(app_ref, host, port, log_level):  # noqa: ANN001
            calls["app"] = app_ref
            calls["host"] = host
            calls["port"] = port
            calls["log_level"] = log_level

    monkeypatch.setitem(sys.modules, "uvicorn", _FakeUvicorn)

    result = runner.invoke(app, ["server", "run"])
    assert result.exit_code == 0
    assert calls == {
        "app": "clawrium.gui.server:app",
        "host": "127.0.0.1",
        "port": 36000,
        "log_level": "info",
    }

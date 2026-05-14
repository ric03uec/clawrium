"""Tests for the `clm gui` CLI entry point."""

import builtins
import sys

import pytest
import typer

from clawrium.cli import gui as gui_module


@pytest.fixture(autouse=True)
def _reset_gui_module(monkeypatch):
    # `gui()` imports uvicorn lazily inside the function body, so a cached
    # entry in sys.modules can leak across tests and hide the ImportError path.
    # Drop it before each test so every run exercises a fresh import.
    monkeypatch.delitem(sys.modules, "uvicorn", raising=False)
    yield


def _stub_uvicorn(monkeypatch):
    """Inject a fake uvicorn module that records the run() call."""
    calls: dict = {}

    class _Fake:
        @staticmethod
        def run(app, host, port, log_level):
            calls["app"] = app
            calls["host"] = host
            calls["port"] = port
            calls["log_level"] = log_level

    monkeypatch.setitem(sys.modules, "uvicorn", _Fake)
    return calls


def test_missing_uvicorn_exits_with_code_one(monkeypatch):
    real_import = builtins.__import__

    def deny_uvicorn(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError("uvicorn not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "uvicorn", raising=False)
    monkeypatch.setattr(builtins, "__import__", deny_uvicorn)

    with pytest.raises(typer.Exit) as exc:
        gui_module.gui(port=36000, no_open=True)

    assert exc.value.exit_code == 1


def test_no_open_skips_browser_and_timer(monkeypatch):
    _stub_uvicorn(monkeypatch)

    called = {"open": 0, "timer": 0}

    def fake_open(url):
        called["open"] += 1

    class FakeTimer:
        def __init__(self, *args, **kwargs):
            called["timer"] += 1

        def start(self):
            called["timer"] += 1

    monkeypatch.setattr(
        gui_module, "threading", type("T", (), {"Timer": FakeTimer})
    )
    monkeypatch.setitem(sys.modules, "webbrowser", type("W", (), {"open": fake_open}))

    gui_module.gui(port=36000, no_open=True)

    assert called["open"] == 0
    assert called["timer"] == 0


def test_runs_uvicorn_with_localhost_bind_and_configured_port(monkeypatch):
    calls = _stub_uvicorn(monkeypatch)

    class _NoopTimer:
        def __init__(self, *_, **__):
            pass

        def start(self):
            pass

    monkeypatch.setattr(
        gui_module, "threading", type("T", (), {"Timer": _NoopTimer})
    )
    monkeypatch.setitem(
        sys.modules, "webbrowser", type("W", (), {"open": lambda *_: None})
    )

    gui_module.gui(port=44321, no_open=False)

    assert calls["host"] == "127.0.0.1"
    assert calls["host"] == gui_module.GUI_HOST
    assert calls["port"] == 44321
    assert calls["app"] == "clawrium.gui.server:app"
    assert calls["log_level"] == "info"


def test_default_port_is_36000_when_omitted(monkeypatch):
    """Default-value drift is otherwise silent — pin the contract here."""
    calls = _stub_uvicorn(monkeypatch)

    gui_module.gui(no_open=True)

    assert calls["port"] == 36000


def test_browser_open_uses_timer_not_synchronous_call(monkeypatch):
    """Synchronous webbrowser.open before uvicorn.run guarantees a race.

    The implementation must schedule the open via threading.Timer so uvicorn
    has a chance to bind first.
    """
    _stub_uvicorn(monkeypatch)

    timer_args: dict = {}

    class FakeTimer:
        def __init__(self, delay, target, args=None):
            timer_args["delay"] = delay
            timer_args["target"] = target
            timer_args["args"] = args

        def start(self):
            timer_args["started"] = True

    def fail_if_called_directly(*_):
        raise AssertionError("webbrowser.open must be deferred, not direct")

    monkeypatch.setattr(
        gui_module, "threading", type("T", (), {"Timer": FakeTimer})
    )
    monkeypatch.setitem(
        sys.modules,
        "webbrowser",
        type("W", (), {"open": fail_if_called_directly}),
    )

    gui_module.gui(port=36000, no_open=False)

    assert timer_args.get("started") is True
    assert timer_args["delay"] > 0
    assert timer_args["args"] == ["http://127.0.0.1:36000"]

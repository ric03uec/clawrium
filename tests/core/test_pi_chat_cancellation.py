"""Cancellation and runner-failure boundaries for finite Pi chat."""

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawrium.core.chat import ChatConnectionError
from clawrium.core.chat_pi import PiChatBackend, run_pi_chat


def _setup_transport(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "clawrium.core.hosts.get_host",
        lambda _: {
            "hostname": "wolf-i",
            "alias": "wolf-i",
            "key_id": "key-id",
        },
    )
    monkeypatch.setattr(
        "clawrium.core.chat_pi.resolve_agent_playbook", lambda *_: Path("/chat.yaml")
    )
    monkeypatch.setattr(
        "clawrium.core.chat_pi.core_keys.get_host_private_key", lambda _: Path("/key")
    )
    monkeypatch.setattr("clawrium.core.chat_pi._logs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "clawrium.core.agent_exec._create_pi_exec_keypair",
        lambda directory: (directory / "private.pem", "CERT"),
    )


def test_run_pi_chat_cancelled_stuck_runner_returns_without_unbounded_join(
    monkeypatch, tmp_path
):
    """Cancellation returns while a non-cooperative ansible worker remains alive."""
    _setup_transport(monkeypatch, tmp_path)
    callback_seen = threading.Event()
    release_runner = threading.Event()
    cleanup_joined = threading.Event()
    joins = []

    class StuckThread:
        def is_alive(self):
            return not release_runner.is_set()

        def join(self, timeout=None):
            joins.append(timeout)
            release_runner.wait(timeout)
            if timeout is None:
                cleanup_joined.set()

    cancel = threading.Event()
    cancel.set()

    def run_async(**kwargs):
        callback_seen.set()
        assert kwargs["cancel_callback"]() is True
        return StuckThread(), SimpleNamespace(status="successful", events=[])

    monkeypatch.setattr("clawrium.core.chat_pi.ansible_runner.run_async", run_async)
    monkeypatch.setattr("clawrium.core.chat_pi._CANCEL_CLEANUP_SECONDS", 0)

    started = time.monotonic()
    assert run_pi_chat("wolf-i", "pi-demo", ["--print"], "hello", 1, cancel) == (
        "",
        "",
        124,
    )
    assert time.monotonic() - started < 0.5
    assert callback_seen.is_set()
    assert joins and joins[0] == 0.05
    # The deferred daemon cleaner must not outlive this test: release the
    # intentionally stuck runner and observe its unbounded cleanup join finish.
    release_runner.set()
    assert cleanup_joined.wait(0.5)


@pytest.mark.anyio
async def test_backend_cancellation_signals_runner_and_returns_while_runner_stuck(
    monkeypatch,
):
    """A cancelled caller is not held by an uncooperative command runner."""
    monkeypatch.setattr("clawrium.core.chat_pi._CANCEL_CLEANUP_SECONDS", 0.01)
    started = threading.Event()
    cancelled = threading.Event()
    never_finish = threading.Event()

    def stuck_runner(_host, _agent, _argv, _prompt, _timeout, cancel):
        started.set()
        assert cancel.wait(1), "backend did not signal cancellation"
        cancelled.set()
        never_finish.wait()
        return "", "", 124

    backend = PiChatBackend(
        "wolf-i", "pi-demo", "openai/gpt-4o", command_runner=stuck_runner
    )
    await backend.connect()
    task = asyncio.create_task(backend.send_message("hello", "session"))
    while not started.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.5)

    assert cancelled.is_set()
    assert backend.is_connected is False
    never_finish.set()
    # Let the daemon worker complete before the test event loop closes.
    await asyncio.sleep(0.05)


@pytest.mark.anyio
async def test_backend_runner_exception_signals_completion_instead_of_hanging():
    """Runner exceptions set done through finally and become a transport error."""

    def failing_runner(*_args):
        raise RuntimeError("runner failed")

    backend = PiChatBackend(
        "wolf-i", "pi-demo", "openai/gpt-4o", command_runner=failing_runner
    )
    await backend.connect()
    with pytest.raises(ChatConnectionError, match="Could not run Pi chat remotely"):
        await asyncio.wait_for(backend.send_message("hello", "session"), timeout=0.5)

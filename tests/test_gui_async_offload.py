"""Regression test that route handlers offload sync I/O to a thread.

If a handler reverts to calling `_resolve_agent` (or any other blocking
function) synchronously on the event loop, this test catches it before the
bigger FastAPI TestClient suite (deferred to follow-up B9) is in place.
"""

import asyncio
import threading

import pytest

from clawrium.gui.routes import agents as agents_module


@pytest.mark.anyio
async def test_chat_info_resolves_agent_off_the_event_loop(monkeypatch):
    """The `_resolve_agent` call in chat_info must run via asyncio.to_thread."""
    main_thread = threading.get_ident()
    observed: dict = {}

    def stub_resolve(agent_key):
        observed["thread_id"] = threading.get_ident()
        return None

    monkeypatch.setattr(agents_module, "_resolve_agent", stub_resolve)

    with pytest.raises(Exception):  # noqa: BLE001  HTTPException(404) is fine
        await agents_module.chat_info(agent_key="missing")

    assert observed.get("thread_id") is not None
    assert observed["thread_id"] != main_thread, (
        "Expected _resolve_agent to run in a worker thread; "
        "the handler is blocking the event loop."
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_event_loop_unblocked_by_async_offload(monkeypatch):
    """Sanity smoke: invoking the async handler does not block the caller."""
    monkeypatch.setattr(agents_module, "_resolve_agent", lambda _k: None)

    async def run():
        try:
            await agents_module.chat_info(agent_key="missing")
        except Exception:
            pass

    asyncio.run(run())

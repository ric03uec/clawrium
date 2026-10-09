"""Pi GUI cache generations prevent stale identity requests (#1038)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from clawrium.gui.routes import agents as agents_module


@pytest.fixture(autouse=True)
def clear_pi_sessions():
    agents_module._PI_BROWSER_SESSIONS.clear()
    yield
    agents_module._PI_BROWSER_SESSIONS.clear()


def _record(*, provider: str, installation_id: str) -> dict:
    return {
        "agent_name": "pi-demo",
        "providers": [provider],
        "installed_at": installation_id,
    }


def test_pi_identity_replacement_retires_active_generation_without_stale_requests(
    monkeypatch: pytest.MonkeyPatch,
):
    """Old in-flight and queued turns cannot become requests to a new identity."""
    asyncio.run(_exercise_identity_replacement(monkeypatch))


def test_pi_same_hostname_new_host_key_retires_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePiBackend:
        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(agents_module, "PiChatBackend", FakePiBackend)
    common = dict(
        agent_key="pi-demo",
        session_key="browser:one",
        hostname="shared-hostname",
        agent_name="pi-demo",
        model="openai/gpt-4o",
        provider_name="provider",
        installation_id="installed-once",
    )
    old_session = agents_module._get_pi_browser_session(
        **common, host_key="old-host-key"
    )
    replacement = agents_module._get_pi_browser_session(
        **common, host_key="new-host-key"
    )
    assert old_session.invalidated
    assert replacement is not old_session
    assert replacement.generation > old_session.generation
    assert agents_module._PI_BROWSER_SESSIONS[("pi-demo", "browser:one")] is replacement


async def _exercise_identity_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class FakePiBackend:
        instances: list["FakePiBackend"] = []

        def __init__(
            self,
            hostname: str,
            agent_name: str,
            model: str,
            provider: str = "openrouter",
        ):
            self.hostname = hostname
            self.agent_name = agent_name
            self.model = model
            self.provider = provider
            self.calls: list[str] = []
            self.close_calls = 0
            self.instances.append(self)

        async def connect(self):
            return None

        async def close(self):
            self.close_calls += 1

        async def send_message(self, message, session_key, response_timeout_seconds=120):
            self.calls.append(message)
            if self.hostname == "old-host":
                started.set()
                await release.wait()
            return f"reply from {self.hostname}"

    monkeypatch.setattr(agents_module, "PiChatBackend", FakePiBackend)
    monkeypatch.setattr(
        agents_module,
        "get_provider",
        lambda _provider: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )

    old_host = {"hostname": "old-host"}
    new_host = {"hostname": "new-host"}
    old_record = _record(provider="old-provider", installation_id="old-install")
    new_record = _record(provider="new-provider", installation_id="new-install")
    body = agents_module.ChatRequest(message="hello", session="browser:one")
    old_task = asyncio.create_task(
        agents_module._chat_pi(old_host, old_record, "pi-demo", body)
    )
    await started.wait()

    cache_key = ("pi-demo", "browser:one")
    old_session = agents_module._PI_BROWSER_SESSIONS[cache_key]
    assert old_session.lock.locked()
    # This second request resolved before the reinstall, then queued on the
    # old lock. It must fail before it can connect to old-host after release.
    queued_old_task = asyncio.create_task(
        agents_module._chat_pi(old_host, old_record, "pi-demo", body)
    )
    await asyncio.sleep(0)

    new_session = agents_module._get_pi_browser_session(
        agent_key="pi-demo",
        session_key="browser:one",
        hostname="new-host",
        agent_name="pi-demo",
        model="openai/gpt-4o",
        provider_name="new-provider",
        installation_id="new-install",
    )
    assert new_session is agents_module._PI_BROWSER_SESSIONS[cache_key]
    assert new_session.generation > old_session.generation
    assert old_session.invalidated is True
    assert old_session.backend.close_calls == 0  # defer active cleanup

    release.set()
    for task in (old_task, queued_old_task):
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == 409

    assert old_session.backend.calls == ["hello"]
    assert old_session.backend.close_calls == 2
    assert agents_module._PI_BROWSER_SESSIONS[cache_key] is new_session

    response = await agents_module._chat_pi(new_host, new_record, "pi-demo", body)
    assert response.status_code == 200
    assert new_session.backend.calls == ["hello"]
    assert new_session.backend.close_calls == 1

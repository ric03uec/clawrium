"""GUI coverage for shared finite Codex chat backend (#1037)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawrium.core.chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatProtocolError,
)
from clawrium.gui.routes import agents as agents_module
from clawrium.gui.server import app


def _seed(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "box",
                    "agents": {
                        "codex-demo": {
                            "type": "codex",
                            "agent_name": "codex-demo",
                            "status": "installed",
                            "installed_at": "2026-10-08T00:00:00Z",
                            "config": {},
                        }
                    },
                }
            ]
        )
    )


@pytest.fixture(autouse=True)
def clear_sessions():
    agents_module._CODEX_BROWSER_SESSIONS.clear()
    yield
    agents_module._CODEX_BROWSER_SESSIONS.clear()


def _events(response) -> list[str]:
    return [
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_codex_gui_reuses_shared_backend_and_keeps_sessions_independent(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(isolated_config)

    class FakeBackend:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs, self.calls, self.closed = kwargs, [], 0
            self.instances.append(self)

        async def connect(self):
            pass

        async def close(self):
            self.closed += 1

        async def send_message(self, *, message, session_key, response_timeout_seconds):
            self.calls.append((message, session_key, response_timeout_seconds))
            return f"reply {message}"

    monkeypatch.setattr(agents_module, "CodexChatBackend", FakeBackend)
    with TestClient(app, base_url="http://localhost:36000") as client:
        assert (
            client.post(
                "/api/agents/codex-demo/chat",
                json={"message": "one", "session": "gui:a"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/agents/codex-demo/chat",
                json={"message": "two", "session": "gui:a"},
            ).status_code
            == 200
        )
        response = client.post(
            "/api/agents/codex-demo/chat", json={"message": "fresh", "session": "gui:b"}
        )
    assert json.loads(_events(response)[0]) == {
        "type": "content",
        "text": "reply fresh",
    }
    assert len(FakeBackend.instances) == 2
    assert FakeBackend.instances[0].calls == [
        ("one", "gui:a", 120.0),
        ("two", "gui:a", 120.0),
    ]
    assert all(instance.closed for instance in FakeBackend.instances)


@pytest.mark.parametrize(
    "error_type", [ChatAuthenticationError, ChatConnectionError, ChatProtocolError]
)
def test_codex_gui_errors_are_generic_and_do_not_leak_prompt_or_credentials(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    _seed(isolated_config)

    class FailingBackend:
        def __init__(self, **_kwargs):
            pass

        async def connect(self):
            pass

        async def close(self):
            pass

        async def send_message(self, **_kwargs):
            raise error_type("oauth-secret /home/codex-demo")

    monkeypatch.setattr(agents_module, "CodexChatBackend", FailingBackend)
    with TestClient(app, base_url="http://localhost:36000") as client:
        response = client.post(
            "/api/agents/codex-demo/chat",
            json={"message": "private prompt", "session": "gui:a"},
        )
    assert response.status_code == 502
    assert response.json() == {"detail": "Chat request failed"}
    assert "oauth-secret" not in response.text and "private prompt" not in response.text


def test_codex_gui_rejects_invalid_input(isolated_config: Path) -> None:
    _seed(isolated_config)
    with TestClient(app, base_url="http://localhost:36000") as client:
        assert (
            client.post(
                "/api/agents/codex-demo/chat", json={"message": " ", "session": "gui:a"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/agents/codex-demo/chat", json={"message": "ok", "session": "!"}
            ).status_code
            == 422
        )
        assert client.get("/api/agents/codex-demo/chat/info").json() == {
            "supported": True,
            "type": "codex",
        }


@pytest.mark.anyio
async def test_codex_browser_sessions_reject_over_capacity_without_growth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = asyncio.Lock()
    await lock.acquire()
    monkeypatch.setattr(agents_module, "_CODEX_BROWSER_SESSION_MAX", 1)
    agents_module._CODEX_BROWSER_SESSIONS[("agent", "busy")] = (
        agents_module._CodexBrowserSession(
            backend=None,
            identity=("key", "host", "codex", "install"),
            generation=1,
            lock=lock,
            last_used=0.0,
        )
    )
    with pytest.raises(agents_module._CodexSessionCapacityError):
        agents_module._get_codex_browser_session(
            agent_key="agent",
            session_key="new",
            hostname="host",
            host_key="key",
            agent_name="codex",
            installation_id="install",
        )
    assert len(agents_module._CODEX_BROWSER_SESSIONS) == 1


def test_codex_reinstall_invalidates_inflight_and_queued_old_host_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_exercise_codex_reinstall(monkeypatch))


async def _exercise_codex_reinstall(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class Backend:
        instances: list["Backend"] = []

        def __init__(self, **kwargs):
            self.hostname = kwargs["hostname"]
            self.calls: list[str] = []
            self.close_calls = 0
            self.instances.append(self)

        async def connect(self):
            pass

        async def close(self):
            self.close_calls += 1

        async def send_message(self, *, message, **_kwargs):
            self.calls.append(message)
            if self.hostname == "old-host":
                started.set()
                await release.wait()
            return f"reply from {self.hostname}"

    monkeypatch.setattr(agents_module, "CodexChatBackend", Backend)
    old_host = {"hostname": "old-host", "key_id": "old-key"}
    new_host = {"hostname": "new-host", "key_id": "new-key"}
    old_agent = {"agent_name": "codex-demo", "installed_at": "old-install"}
    new_agent = {"agent_name": "codex-demo", "installed_at": "new-install"}
    current = [old_host, "codex", old_agent]
    monkeypatch.setattr(agents_module, "_resolve_agent", lambda _key: tuple(current))
    body = agents_module.ChatRequest(message="hello", session="browser:one")
    old_task = asyncio.create_task(
        agents_module._chat_codex(old_host, old_agent, "codex-demo", body)
    )
    await started.wait()
    cache_key = ("codex-demo", "browser:one")
    old_session = agents_module._CODEX_BROWSER_SESSIONS[cache_key]
    queued_task = asyncio.create_task(
        agents_module._chat_codex(old_host, old_agent, "codex-demo", body)
    )
    await asyncio.sleep(0)
    new_session = agents_module._get_codex_browser_session(
        agent_key="codex-demo",
        session_key="browser:one",
        hostname="new-host",
        host_key="new-key",
        agent_name="codex-demo",
        installation_id="new-install",
    )
    assert new_session.generation > old_session.generation
    assert old_session.invalidated
    assert old_session.backend.close_calls == 0
    current[:] = [new_host, "codex", new_agent]
    release.set()
    for task in (old_task, queued_task):
        with pytest.raises(agents_module.HTTPException) as error:
            await task
        assert error.value.status_code == 409
    assert old_session.backend.calls == ["hello"]
    assert old_session.backend.close_calls == 2
    assert agents_module._CODEX_BROWSER_SESSIONS[cache_key] is new_session
    response = await agents_module._chat_codex(
        new_host, new_agent, "codex-demo", body
    )
    assert response.status_code == 200
    assert new_session.backend.calls == ["hello"]


def test_codex_inflight_turn_rejects_registry_reassignment_without_new_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_exercise_codex_unobserved_reassignment(monkeypatch))


async def _exercise_codex_unobserved_reassignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = asyncio.Event(), asyncio.Event()

    class Backend:
        def __init__(self, **_kwargs):
            self.closed = 0

        async def connect(self):
            pass

        async def close(self):
            self.closed += 1

        async def send_message(self, **_kwargs):
            started.set()
            await release.wait()
            return "response from retired host"

    monkeypatch.setattr(agents_module, "CodexChatBackend", Backend)
    old_host = {"hostname": "same-host", "key_id": "old-key"}
    replacement = {"hostname": "same-host", "key_id": "new-key"}
    agent = {"agent_name": "codex-demo", "installed_at": "install"}
    current = [old_host, "codex", agent]
    monkeypatch.setattr(agents_module, "_resolve_agent", lambda _key: tuple(current))
    task = asyncio.create_task(
        agents_module._chat_codex(
            old_host,
            agent,
            "codex-demo",
            agents_module.ChatRequest(message="secret", session="browser:one"),
        )
    )
    await started.wait()
    current[0] = replacement
    release.set()
    with pytest.raises(agents_module.HTTPException) as error:
        await task
    assert error.value.status_code == 409
    assert "response from retired host" not in str(error.value.detail)
    assert not agents_module._CODEX_BROWSER_SESSIONS


def test_codex_legacy_record_does_not_reuse_native_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Backend:
        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr(agents_module, "CodexChatBackend", Backend)
    kwargs = {
        "agent_key": "codex-demo",
        "session_key": "browser:one",
        "hostname": "host",
        "host_key": "key",
        "agent_name": "codex-demo",
        "installation_id": "",
    }
    first = agents_module._get_codex_browser_session(**kwargs)
    second = agents_module._get_codex_browser_session(**kwargs)
    assert first is not second
    assert first.invalidated

"""GUI coverage for shared finite Codex chat backend (#1037)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawrium.core.chat import ChatAuthenticationError
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


def test_codex_gui_errors_are_generic_and_do_not_leak_prompt_or_credentials(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
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
            raise ChatAuthenticationError("oauth-secret /home/codex-demo")

    monkeypatch.setattr(agents_module, "CodexChatBackend", FailingBackend)
    with TestClient(app, base_url="http://localhost:36000") as client:
        response = client.post(
            "/api/agents/codex-demo/chat",
            json={"message": "private prompt", "session": "gui:a"},
        )
    assert json.loads(_events(response)[0]) == {
        "type": "error",
        "message": "Chat request failed",
    }
    assert _events(response)[-1] == "[DONE]"
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
        agents_module._CodexBrowserSession(backend=None, lock=lock, last_used=0.0)
    )
    with pytest.raises(agents_module._CodexSessionCapacityError):
        agents_module._get_codex_browser_session(
            agent_key="agent", session_key="new", hostname="host", agent_name="codex"
        )
    assert len(agents_module._CODEX_BROWSER_SESSIONS) == 1

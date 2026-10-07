"""Pi GUI chat uses finite native CLI sessions (#1038)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawrium.gui.routes import agents as agents_module
from clawrium.gui.server import app


@pytest.fixture(autouse=True)
def clear_pi_sessions():
    agents_module._PI_BROWSER_SESSIONS.clear()
    yield
    agents_module._PI_BROWSER_SESSIONS.clear()


def _seed_hosts(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "wolf-i",
                    "alias": "wolf-i",
                    "port": 22,
                    "user": "xclm",
                    "agents": {
                        "pi-demo": {
                            "type": "pi",
                            "agent_name": "pi-demo",
                            "name": "pi-demo",
                            "status": "installed",
                            "installed_at": "2026-10-06T00:00:00+00:00",
                            "config": {},
                            "providers": ["router"],
                        }
                    },
                }
            ]
        )
    )


def _install_fake(monkeypatch, *, failure: Exception | None = None):
    class FakePiBackend:
        instances = []

        def __init__(self, hostname, agent_name, model):
            self.hostname, self.agent_name, self.model = hostname, agent_name, model
            self.calls = []
            self.instances.append(self)

        async def connect(self):
            pass

        async def close(self):
            pass

        async def send_message(
            self, message, session_key, response_timeout_seconds=120
        ):
            self.calls.append((message, session_key, response_timeout_seconds))
            if failure:
                raise failure
            return f"reply: {message}"

    monkeypatch.setattr(agents_module, "PiChatBackend", FakePiBackend)
    return FakePiBackend


def test_pi_gui_chat_reuses_then_resets_native_cli_session(
    isolated_config, monkeypatch
):
    _seed_hosts(isolated_config)
    monkeypatch.setattr(
        agents_module,
        "get_provider",
        lambda _: {"type": "openrouter", "default_model": "moonshotai/kimi-k2.6"},
    )
    backend_cls = _install_fake(monkeypatch)
    with TestClient(app, base_url="http://localhost:36000") as client:
        for message in ("first", "second"):
            response = client.post(
                "/api/agents/pi-demo/chat",
                json={"message": message, "session": "gui:one"},
            )
            assert response.status_code == 200
        reset = client.post(
            "/api/agents/pi-demo/chat",
            json={"message": "fresh", "session": "gui:two"},
        )

    assert reset.status_code == 200
    assert len(backend_cls.instances) == 2
    assert backend_cls.instances[0].calls == [
        ("first", "gui:one", 120.0),
        ("second", "gui:one", 120.0),
    ]
    assert backend_cls.instances[1].calls == [("fresh", "gui:two", 120.0)]


def test_pi_gui_chat_replaces_stale_agent_identity(monkeypatch):
    backend_cls = _install_fake(monkeypatch)
    first = agents_module._get_pi_browser_session(
        agent_key="pi-demo",
        session_key="gui:one",
        hostname="old-host",
        agent_name="pi-demo",
        model="openai/gpt-4o",
        provider_name="old-provider",
        installation_id="first-install",
    )
    second = agents_module._get_pi_browser_session(
        agent_key="pi-demo",
        session_key="gui:one",
        hostname="new-host",
        agent_name="pi-demo",
        model="openai/gpt-4o",
        provider_name="new-provider",
        installation_id="second-install",
    )
    assert first is not second
    assert len(backend_cls.instances) == 2
    assert second.backend.hostname == "new-host"


def test_pi_gui_chat_replaces_expired_matching_identity(monkeypatch):
    backend_cls = _install_fake(monkeypatch)
    first = agents_module._get_pi_browser_session(
        agent_key="pi-demo",
        session_key="gui:one",
        hostname="host",
        agent_name="pi-demo",
        model="openai/gpt-4o",
        provider_name="router",
        installation_id="install",
    )
    first.last_used = 0
    monkeypatch.setattr(agents_module.time, "monotonic", lambda: 1_900)
    second = agents_module._get_pi_browser_session(
        agent_key="pi-demo",
        session_key="gui:one",
        hostname="host",
        agent_name="pi-demo",
        model="openai/gpt-4o",
        provider_name="router",
        installation_id="install",
    )
    assert first is not second
    assert len(backend_cls.instances) == 2


def test_pi_gui_chat_does_not_reuse_legacy_record_session(monkeypatch):
    backend_cls = _install_fake(monkeypatch)
    first = agents_module._get_pi_browser_session(
        agent_key="pi-demo",
        session_key="gui:one",
        hostname="host",
        agent_name="pi-demo",
        model="openai/gpt-4o",
        provider_name="router",
        installation_id="",
    )
    second = agents_module._get_pi_browser_session(
        agent_key="pi-demo",
        session_key="gui:one",
        hostname="host",
        agent_name="pi-demo",
        model="openai/gpt-4o",
        provider_name="router",
        installation_id="",
    )
    assert first is not second
    assert len(backend_cls.instances) == 2


def test_pi_gui_chat_returns_http_error_when_native_backend_fails(
    isolated_config, monkeypatch
):
    _seed_hosts(isolated_config)
    monkeypatch.setattr(
        agents_module,
        "get_provider",
        lambda _: {"type": "openrouter", "default_model": "moonshotai/kimi-k2.6"},
    )
    _install_fake(monkeypatch, failure=RuntimeError("remote failure"))
    with TestClient(app, base_url="http://localhost:36000") as client:
        response = client.post(
            "/api/agents/pi-demo/chat",
            json={"message": "private prompt", "session": "gui:one"},
        )
    assert response.status_code == 502
    assert response.json() == {"detail": "Chat request failed"}
    assert "private prompt" not in response.text

"""Tests for chat CLI command."""

from __future__ import annotations

import asyncio

from typer.testing import CliRunner

from clawrium.cli import chat as chat_module
from clawrium.cli.main import app
from clawrium.core.chat import ChatProtocolError
from clawrium.core.hosts import HostsFileCorruptedError


runner = CliRunner()


def test_chat_agent_not_found(monkeypatch):
    monkeypatch.setattr("clawrium.cli.chat.get_agent_by_name", lambda _name: None)

    result = runner.invoke(app, ["chat", "missing-agent"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_chat_missing_gateway_token(monkeypatch):
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent = {
        "agent_name": "opc-work",
        "config": {"gateway": {"url": "ws://192.168.1.100:40123"}},
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    result = runner.invoke(app, ["chat", "opc-work"])

    assert result.exit_code == 1
    assert "token is missing" in result.output.lower()


def test_chat_reconstructs_gateway_url_from_current_host(monkeypatch):
    """Verify gateway URL is reconstructed using host's current primary address.

    When the stored URL has a different IP than the host's current primary address
    (e.g., LAN IP vs Tailscale IP), the URL should be rebuilt using the current
    primary address to ensure connectivity across networks.
    """
    # Host's current primary address is Tailscale IP, but stored URL has LAN IP
    host = {"hostname": "100.79.149.29", "alias": "wolf-i"}
    agent = {
        "agent_name": "maurice",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.36:40317",  # Old LAN IP
                "auth": "test-token",
                "port": 40317,
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    captured_args: dict[str, object] = {}

    async def mock_chat_loop(backend, **kwargs):
        captured_args["backend"] = backend
        captured_args["gateway_url"] = backend.gateway_url

    monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

    result = runner.invoke(app, ["chat", "maurice"])

    assert result.exit_code == 0
    # Verify URL was reconstructed with current host address, not stored IP
    assert captured_args["gateway_url"] == "ws://100.79.149.29:40317"


def test_chat_reconstructs_gateway_url_preserves_wss_scheme(monkeypatch):
    """Verify wss:// scheme is preserved when reconstructing gateway URL."""
    host = {"hostname": "secure.example.com", "alias": "secure-host"}
    agent = {
        "agent_name": "secure-agent",
        "config": {
            "gateway": {
                "url": "wss://old-ip:40443",
                "auth": "test-token",
                "port": 40443,
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    captured_args: dict[str, object] = {}

    async def mock_chat_loop(backend, **kwargs):
        captured_args["backend"] = backend
        captured_args["gateway_url"] = backend.gateway_url

    monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

    result = runner.invoke(app, ["chat", "secure-agent"])

    assert result.exit_code == 0
    assert captured_args["gateway_url"] == "wss://secure.example.com:40443"


def test_chat_extracts_port_from_url_when_not_in_config(monkeypatch):
    """Verify port is extracted from stored URL when not in gateway config."""
    host = {"hostname": "new-host.local", "alias": "host1"}
    agent = {
        "agent_name": "agent1",
        "config": {
            "gateway": {
                "url": "ws://old-host:12345",  # Port only in URL, not config
                "auth": "test-token",
                # No explicit 'port' key
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    captured_args: dict[str, object] = {}

    async def mock_chat_loop(backend, **kwargs):
        captured_args["backend"] = backend
        captured_args["gateway_url"] = backend.gateway_url

    monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

    result = runner.invoke(app, ["chat", "agent1"])

    assert result.exit_code == 0
    # Port 12345 should be extracted from URL
    assert captured_args["gateway_url"] == "ws://new-host.local:12345"


def test_chat_gateway_url_reconstruction_missing_port(monkeypatch):
    """Verify error when port cannot be extracted from URL or config."""
    host = {"hostname": "example.com", "alias": "host1"}
    agent = {
        "agent_name": "agent1",
        "config": {
            "gateway": {
                "url": "ws://old-host/",  # No port in URL
                "auth": "test-token",
                # No explicit 'port' key in config either
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    result = runner.invoke(app, ["chat", "agent1"])

    assert result.exit_code == 1
    assert "gateway port not found" in result.output.lower()


def test_chat_gateway_url_reconstruction_missing_hostname(monkeypatch):
    """Verify error when host record has no hostname."""
    host = {"alias": "host1"}  # No 'hostname' key
    agent = {
        "agent_name": "agent1",
        "config": {
            "gateway": {
                "url": "ws://old-host:40317",
                "auth": "test-token",
                "port": 40317,
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    result = runner.invoke(app, ["chat", "agent1"])

    assert result.exit_code == 1
    assert "host primary address not found" in result.output.lower()


def test_chat_gateway_url_reconstruction_defaults_scheme_to_ws(monkeypatch):
    """Verify schemeless URL defaults to ws:// scheme."""
    host = {"hostname": "example.com", "alias": "host1"}
    agent = {
        "agent_name": "agent1",
        "config": {
            "gateway": {
                "url": "//old-host:40317",  # Schemeless URL
                "auth": "test-token",
                "port": 40317,
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    captured_args: dict[str, object] = {}

    async def mock_chat_loop(backend, **kwargs):
        captured_args["backend"] = backend
        captured_args["gateway_url"] = backend.gateway_url

    monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

    result = runner.invoke(app, ["chat", "agent1"])

    assert result.exit_code == 0
    # Should default to ws:// scheme
    assert captured_args["gateway_url"] == "ws://example.com:40317"


def test_chat_handles_hosts_file_corrupted(monkeypatch):
    def fake_get_agent_by_name(_name: str):
        raise HostsFileCorruptedError("hosts file is corrupted")

    monkeypatch.setattr("clawrium.cli.chat.get_agent_by_name", fake_get_agent_by_name)

    result = runner.invoke(app, ["chat", "opc-work"])

    assert result.exit_code == 1
    assert "corrupted" in result.output.lower()


def test_chat_handles_ambiguous_agent_name(monkeypatch):
    def fake_get_agent_by_name(_name: str):
        raise ValueError("agent is ambiguous")

    monkeypatch.setattr("clawrium.cli.chat.get_agent_by_name", fake_get_agent_by_name)

    result = runner.invoke(app, ["chat", "opc-work"])

    assert result.exit_code == 1
    assert "ambiguous" in result.output.lower()


def test_chat_rejects_agent_without_chat_feature(monkeypatch):
    """Agent types whose manifest does not declare `features.chat.type` are rejected."""
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent = {
        "agent_name": "zc-work",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123",
                "auth": "test-token",
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "zeroclaw", agent)
    )
    # Force the resolver to behave as if zeroclaw advertises no chat feature, so
    # this test stays meaningful even if zeroclaw's bundled manifest later opts
    # into chat.
    monkeypatch.setattr(
        "clawrium.cli.chat._resolve_chat_type",
        lambda agent_type: (_ for _ in ()).throw(
            ValueError(f"Chat is not supported for agent type '{agent_type}'.")
        ),
    )

    result = runner.invoke(app, ["chat", "zc-work"])

    assert result.exit_code == 1
    assert "not supported" in result.output.lower()


def test_chat_invokes_async_loop(monkeypatch):
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent = {
        "agent_name": "opc-work",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123",
                "auth": "test-token",
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    called: dict[str, object] = {}

    def fake_asyncio_run(coro):
        called["called"] = True
        called["response_timeout_seconds"] = coro.cr_frame.f_locals[
            "response_timeout_seconds"
        ]
        called["idle_timeout_seconds"] = coro.cr_frame.f_locals["idle_timeout_seconds"]
        coro.close()

    monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

    result = runner.invoke(
        app,
        [
            "chat",
            "opc-work",
            "--session",
            "main",
            "--timeout",
            "30",
            "--idle-timeout",
            "0",
        ],
    )

    assert result.exit_code == 0
    assert called.get("called") is True
    assert called.get("response_timeout_seconds") == 30.0
    assert called.get("idle_timeout_seconds") == 0.0


def test_chat_invokes_async_loop_with_default_timeouts(monkeypatch):
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent = {
        "agent_name": "opc-work",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123",
                "auth": "test-token",
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    called: dict[str, object] = {}

    def fake_asyncio_run(coro):
        called["called"] = True
        called["response_timeout_seconds"] = coro.cr_frame.f_locals[
            "response_timeout_seconds"
        ]
        called["idle_timeout_seconds"] = coro.cr_frame.f_locals["idle_timeout_seconds"]
        coro.close()

    monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

    result = runner.invoke(app, ["chat", "opc-work", "--session", "main"])

    assert result.exit_code == 0
    assert called.get("called") is True
    assert called.get("response_timeout_seconds") == 120.0
    assert called.get("idle_timeout_seconds") == 300.0


def test_chat_rejects_invalid_session_format(monkeypatch):
    monkeypatch.setattr("clawrium.cli.chat.get_agent_by_name", lambda _name: None)

    result = runner.invoke(app, ["chat", "missing-agent", "--session", "main;evil_cmd"])

    assert result.exit_code == 2
    assert "invalid session format" in result.output.lower()


def test_chat_sanitizes_gateway_error_output(monkeypatch):
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent = {
        "agent_name": "opc-work",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123",
                "auth": "test-token",
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name", lambda _name: (host, "openclaw", agent)
    )

    def fake_asyncio_run(_coro):
        _coro.close()
        raise ChatProtocolError("auth=abc123\n\x00password=secret")

    monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

    result = runner.invoke(app, ["chat", "opc-work", "--session", "main"])

    assert result.exit_code == 1
    assert "auth=***" in result.output.lower()
    assert "password=***" in result.output.lower()
    assert "abc123" not in result.output
    assert "secret" not in result.output


def test_chat_loop_handles_idle_timeout_and_closes_client(monkeypatch):
    fake_client = FakeChatClient()

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        raise TimeoutError

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)

    asyncio.run(
        chat_module._chat_loop(
            backend=fake_client,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
        )
    )

    assert fake_client.connected is True
    assert fake_client.closed is True


class FakeChatClient:
    def __init__(self, *_, **__):
        self.messages: list[str] = []
        self.connected = False
        self.closed = False
        self.last_kwargs: dict[str, object] = {}

    async def connect(self):
        self.connected = True

    async def close(self):
        self.closed = True

    async def send_message(self, message: str, **kwargs):
        self.messages.append(message)
        self.last_kwargs = kwargs
        on_delta = kwargs.get("on_delta")
        if on_delta:
            on_delta("partial")
        return "complete"


def test_chat_loop_sends_message_and_exits_on_command(monkeypatch):
    fake_client = FakeChatClient()

    inputs = iter(["   ", "hello", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)

    asyncio.run(
        chat_module._chat_loop(
            backend=fake_client,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
        )
    )

    assert fake_client.connected is True
    assert fake_client.closed is True
    assert fake_client.messages == ["hello"]
    assert fake_client.last_kwargs.get("response_timeout_seconds") == 30.0


def test_chat_loop_handles_eof_and_closes_client(monkeypatch):
    fake_client = FakeChatClient()

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        raise EOFError

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)

    asyncio.run(
        chat_module._chat_loop(
            backend=fake_client,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
        )
    )

    assert fake_client.connected is True
    assert fake_client.closed is True


def test_chat_loop_handles_keyboard_interrupt_and_closes_client(monkeypatch):
    fake_client = FakeChatClient()

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)

    asyncio.run(
        chat_module._chat_loop(
            backend=fake_client,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
        )
    )

    assert fake_client.connected is True
    assert fake_client.closed is True


# ---------------------------------------------------------------------------
# Hermes chat dispatch — agents whose manifest advertises features.chat.type
# == "openai" route to HermesOpenAIBackend instead of OpenClawChatClient.
# ---------------------------------------------------------------------------


class TestHermesChat:
    """Phase 1 dispatch + secret hydration tests for hermes chat."""

    HOST = {"hostname": "wolf-i.lan", "alias": "wolf-i"}
    AGENT = {
        "agent_name": "hermes-test",
        "config": {
            "api_server": {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 8642,
            }
        },
    }

    def _patch_resolve(self, monkeypatch, agent_type: str = "hermes"):
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (self.HOST, agent_type, self.AGENT),
        )
        monkeypatch.setattr(
            "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "openai"
        )

    def test_dispatches_to_hermes_backend(self, monkeypatch):
        self._patch_resolve(monkeypatch)
        monkeypatch.setattr(
            "clawrium.cli.chat.get_instance_secrets",
            lambda _key: {
                "HERMES_API_SERVER_KEY": {
                    "key": "HERMES_API_SERVER_KEY",
                    "value": "a" * 64,
                }
            },
        )

        captured: dict[str, object] = {}

        async def mock_chat_loop(backend, **kwargs):
            captured["backend"] = backend

        monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 0
        backend = captured["backend"]
        # base_url is reconstructed from host_record.hostname (the reachable
        # address) and api_server.port (the bind port). Note: api_server.host
        # is the bind address, NOT the dial target.
        assert backend._base_url == "http://wolf-i.lan:8642/v1"

    def test_missing_api_server_key(self, monkeypatch):
        """Missing HERMES_API_SERVER_KEY in secrets.json surfaces a friendly error."""
        self._patch_resolve(monkeypatch)
        monkeypatch.setattr(
            "clawrium.cli.chat.get_instance_secrets", lambda _key: {}
        )

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "hermes_api_server_key" in result.output.lower()
        assert "re-run" in result.output.lower()

    def test_missing_api_server_block(self, monkeypatch):
        """Missing api_server config block surfaces a friendly error."""
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (self.HOST, "hermes", {"agent_name": "hermes-test", "config": {}}),
        )
        monkeypatch.setattr(
            "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "openai"
        )

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "api_server" in result.output.lower()
        assert "configure" in result.output.lower()

    def test_url_uses_host_record_hostname_not_bind_address(self, monkeypatch):
        """The dial target must come from host_record.hostname, never api_server.host.
        After the bind migration, api_server.host is "0.0.0.0", which is not a valid
        connect target — this guards the regression where someone might wire the
        wrong field through."""
        agent_with_zero_bind = {
            "agent_name": "hermes-test",
            "config": {
                "api_server": {
                    "enabled": True,
                    "host": "0.0.0.0",  # bind, not reach
                    "port": 8642,
                }
            },
        }
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (self.HOST, "hermes", agent_with_zero_bind),
        )
        monkeypatch.setattr(
            "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "openai"
        )
        monkeypatch.setattr(
            "clawrium.cli.chat.get_instance_secrets",
            lambda _key: {
                "HERMES_API_SERVER_KEY": {
                    "key": "HERMES_API_SERVER_KEY",
                    "value": "b" * 64,
                }
            },
        )

        captured: dict[str, object] = {}

        async def mock_chat_loop(backend, **kwargs):
            captured["backend"] = backend

        monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 0
        assert "0.0.0.0" not in captured["backend"]._base_url
        assert "wolf-i.lan" in captured["backend"]._base_url

    def _setup_resolved_hermes(self, monkeypatch):
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (self.HOST, "hermes", self.AGENT),
        )
        monkeypatch.setattr(
            "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "openai"
        )
        monkeypatch.setattr(
            "clawrium.cli.chat.get_instance_secrets",
            lambda _key: {
                "HERMES_API_SERVER_KEY": {
                    "key": "HERMES_API_SERVER_KEY",
                    "value": "f" * 64,
                }
            },
        )

    def test_service_unreachable(self, monkeypatch):
        """ChatConnectionError from the backend surfaces as exit 1 with a
        remediation hint (mirrors the openclaw connection-failure path)."""
        from clawrium.core.chat import ChatConnectionError

        self._setup_resolved_hermes(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatConnectionError("connection refused on 192.168.1.50:8642")

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "connection failed" in result.output.lower()
        assert "connection refused" in result.output.lower()
        # Remediation hint must be present so the user knows what to do next.
        assert "configure" in result.output.lower() or "install" in result.output.lower()

    def test_authentication_failure(self, monkeypatch):
        """ChatAuthenticationError from the backend surfaces as exit 1."""
        from clawrium.core.chat import ChatAuthenticationError

        self._setup_resolved_hermes(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatAuthenticationError("Hermes rejected bearer token (401)")

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "authentication failed" in result.output.lower()
        assert "401" in result.output


# ---------------------------------------------------------------------------
# ChatBackend Protocol conformance (W5) — both transports satisfy the Protocol
# so the dispatch in cli/chat.py can pass either through `_chat_loop` without
# transport-specific knowledge.
# ---------------------------------------------------------------------------


def test_openclaw_satisfies_chat_backend_protocol():
    from clawrium.core.chat import ChatBackend, OpenClawChatClient, SecretStr

    client = OpenClawChatClient(
        gateway_url="ws://example.test:40123",
        auth_token=SecretStr("token"),
    )
    assert isinstance(client, ChatBackend)


def test_hermes_satisfies_chat_backend_protocol():
    from clawrium.core.chat import ChatBackend, SecretStr
    from clawrium.core.chat_hermes import HermesOpenAIBackend

    backend = HermesOpenAIBackend(
        base_url="http://example.test:8642/v1",
        auth_token=SecretStr("token"),
    )
    assert isinstance(backend, ChatBackend)

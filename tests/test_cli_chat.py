"""Tests for chat CLI command."""

from __future__ import annotations

import asyncio

import pytest
from typer.testing import CliRunner

from clawrium.cli import chat as chat_module
from clawrium.cli.main import app
from clawrium.core.chat import ChatAuthenticationError, ChatProtocolError
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


def test_chat_zeroclaw_reconnects_on_401_when_disk_bearer_rotated(monkeypatch):
    """Issue #437: when ChatAuthenticationError fires and hosts.json has a
    new bearer (e.g. another shell ran `clm agent sync`), the chat REPL
    rebuilds the backend with the fresh token and resumes once."""
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent_initial = {
        "agent_name": "zer-test",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123/ws/chat",
                "auth": "stale-bearer-token-zzzzz",
                "port": 40123,
            }
        },
    }
    agent_rotated = {
        "agent_name": "zer-test",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123/ws/chat",
                "auth": "fresh-bearer-token-zzzzz",
                "port": 40123,
            }
        },
    }

    # Sequence: first lookup returns the stale token (used to build the
    # initial backend); the reload during 401 handling returns the
    # rotated record. Use an iterator so each call advances.
    call_log = {"count": 0}

    def get_agent_by_name(_name: str):
        call_log["count"] += 1
        if call_log["count"] == 1:
            return host, "zeroclaw", agent_initial
        return host, "zeroclaw", agent_rotated

    monkeypatch.setattr("clawrium.cli.chat.get_agent_by_name", get_agent_by_name)

    # `_resolve_chat_type` reads from the manifest registry — short
    # circuit by stubbing the manifest loader.
    monkeypatch.setattr(
        "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "zeroclaw"
    )

    run_call_count = {"n": 0}

    def fake_asyncio_run(coro):
        coro.close()
        run_call_count["n"] += 1
        if run_call_count["n"] == 1:
            raise ChatAuthenticationError("401 gateway rejected the bearer")
        # Second call: success path.
        return None

    monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

    result = runner.invoke(
        app,
        ["chat", "zer-test", "--idle-timeout", "0"],
    )

    assert result.exit_code == 0, result.output
    assert run_call_count["n"] == 2
    assert "Gateway token rotated; reconnected." in result.output


def test_chat_zeroclaw_loop_guard_stops_on_second_401(monkeypatch):
    """ATX B1: the `attempted_reconnect` flag must cap retries at one.
    If the second `asyncio.run` also raises ChatAuthenticationError
    (e.g. the freshly-rotated bearer was ALSO immediately rotated by a
    third actor), exit with code 1 — do not try a third connect."""
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent_v1 = {
        "agent_name": "zer-test",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123/ws/chat",
                "auth": "stale-bearer-v1-zzzzz",
                "port": 40123,
            }
        },
    }
    agent_v2 = {
        "agent_name": "zer-test",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123/ws/chat",
                "auth": "still-rotates-v2-zzzzz",
                "port": 40123,
            }
        },
    }

    call_log = {"count": 0}

    def get_agent_by_name(_name: str):
        call_log["count"] += 1
        return host, "zeroclaw", agent_v1 if call_log["count"] == 1 else agent_v2

    monkeypatch.setattr("clawrium.cli.chat.get_agent_by_name", get_agent_by_name)
    monkeypatch.setattr(
        "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "zeroclaw"
    )

    run_call_count = {"n": 0}

    def fake_asyncio_run(coro):
        coro.close()
        run_call_count["n"] += 1
        # Both attempts raise auth — emulates a token that keeps rotating
        # under us. Loop-guard must prevent a third attempt.
        raise ChatAuthenticationError("401")

    monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

    result = runner.invoke(app, ["chat", "zer-test", "--idle-timeout", "0"])

    # The CLI must exit 1, must have tried exactly 2 connects (initial
    # + 1 reconnect, no third), and must surface the final auth error.
    assert result.exit_code == 1
    assert run_call_count["n"] == 2
    assert "Authentication failed" in result.output


def test_chat_zeroclaw_treats_corrupted_hosts_as_genuine_401(monkeypatch):
    """ATX W-COV-5: when reloading hosts.json during the 401 recovery
    path raises HostsFileCorruptedError, treat the 401 as genuine —
    surface 'Authentication failed' and exit 1, do not retry."""
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent_initial = {
        "agent_name": "zer-test",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123/ws/chat",
                "auth": "stable-bearer-zzzzz",
                "port": 40123,
            }
        },
    }

    call_log = {"count": 0}

    def get_agent_by_name(_name: str):
        call_log["count"] += 1
        if call_log["count"] == 1:
            return host, "zeroclaw", agent_initial
        raise HostsFileCorruptedError("hosts.json malformed")

    monkeypatch.setattr("clawrium.cli.chat.get_agent_by_name", get_agent_by_name)
    monkeypatch.setattr(
        "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "zeroclaw"
    )

    run_call_count = {"n": 0}

    def fake_asyncio_run(coro):
        coro.close()
        run_call_count["n"] += 1
        raise ChatAuthenticationError("401")

    monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

    result = runner.invoke(app, ["chat", "zer-test", "--idle-timeout", "0"])

    assert result.exit_code == 1
    # No retry — only the initial attempt.
    assert run_call_count["n"] == 1
    assert "Authentication failed" in result.output


def test_chat_zeroclaw_does_not_reconnect_when_disk_bearer_unchanged(monkeypatch):
    """Issue #437: an authentic 401 (disk bearer matches in-memory) must
    surface the existing 'Authentication failed' error rather than
    silently looping."""
    host = {"hostname": "192.168.1.100", "alias": "server1"}
    agent_record = {
        "agent_name": "zer-test",
        "config": {
            "gateway": {
                "url": "ws://192.168.1.100:40123/ws/chat",
                "auth": "same-stale-bearer-zzzzz",
                "port": 40123,
            }
        },
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name",
        lambda _name: (host, "zeroclaw", agent_record),
    )
    monkeypatch.setattr(
        "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "zeroclaw"
    )

    run_call_count = {"n": 0}

    def fake_asyncio_run(coro):
        coro.close()
        run_call_count["n"] += 1
        raise ChatAuthenticationError("401 gateway rejected the bearer")

    monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

    result = runner.invoke(
        app,
        ["chat", "zer-test", "--idle-timeout", "0"],
    )

    assert result.exit_code == 1
    assert run_call_count["n"] == 1
    assert "Authentication failed" in result.output
    assert "Gateway token rotated; reconnected." not in result.output


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


@pytest.mark.parametrize(
    "raw,secret",
    [
        # Plain keyword forms (one per new sanitizer keyword).
        ("token=secret-tok-1", "secret-tok-1"),
        ("auth=secret-auth-1", "secret-auth-1"),
        ("password=hunter2", "hunter2"),
        ("key=k-001", "k-001"),
        ("bearer=b-001", "b-001"),
        ("secret=s-001", "s-001"),
        ("apikey=ak-001", "ak-001"),
        ("authorization=auth-001", "auth-001"),
        # Embedded keyword forms — \b alone doesn't fire between _ and K, so
        # the old regex missed these. The replacement pattern must catch them.
        ("HERMES_API_SERVER_KEY=deadbeef-cafef00d", "deadbeef-cafef00d"),
        ("api_key=sk-abc123xyz", "sk-abc123xyz"),
        ("X-Auth-Token: abc-tok-123", "abc-tok-123"),
        # Whitespace separator — matches `Authorization: Bearer <value>`-style
        # headers and `bearer <value>` shorthand.
        ("bearer beartok123", "beartok123"),
    ],
)
def test_sanitize_exception_redacts_secret_keywords(raw, secret):
    """Each new sanitizer keyword (and embedded/space variants) must redact
    the secret value while leaving the keyword identifier visible."""
    redacted = chat_module._sanitize_exception_text(Exception(raw))
    assert secret not in redacted, (
        f"secret '{secret}' leaked through sanitizer: {redacted!r}"
    )
    assert "***" in redacted


def test_sanitize_exception_preserves_non_secret_text():
    """Non-secret text must pass through cleanly so error messages stay
    readable."""
    text = "Hermes returned HTTP 500: internal server error"
    assert chat_module._sanitize_exception_text(Exception(text)) == text


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
        self.clear_history_calls = 0
        # ATX Round 4 W-A / Round 5 W-4: implement the `is_connected`
        # Protocol member explicitly so the REPL can read it directly
        # (no fallback via `getattr(..., True)`). Lifecycle MUST match
        # real backends: starts False, flips to True only after
        # `connect()` succeeds, flips back to False on `close()`.
        # Without this, a test that checks `is_connected` before
        # `connect()` inherits a wrong precondition (the real backend
        # would be False there).
        self.is_connected: bool = False

    async def connect(self):
        self.connected = True
        self.is_connected = True

    async def close(self):
        self.closed = True
        self.is_connected = False

    def clear_history(self) -> None:
        self.clear_history_calls += 1

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


def test_chat_loop_reset_command_invokes_clear_history(monkeypatch, capsys):
    """On openai-typed agents /reset must call clear_history() AND print the
    cleared confirmation. The /reset literal must not be sent as a message."""
    fake_client = FakeChatClient()
    inputs = iter(["hello", "/reset", "world", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)

    asyncio.run(
        chat_module._chat_loop(
            backend=fake_client,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="openai",
        )
    )

    assert fake_client.clear_history_calls == 1
    assert fake_client.messages == ["hello", "world"]
    captured = capsys.readouterr().out
    assert "Conversation history cleared" in captured


def test_chat_loop_reset_on_websocket_backend_is_explicit_noop(monkeypatch, capsys):
    """On websocket-typed agents /reset must NOT call clear_history (the
    gateway owns session state) and must surface a yellow no-op notice so
    the user knows the command didn't do what they expected."""
    backend = FakeChatClient()
    inputs = iter(["/reset", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)

    asyncio.run(
        chat_module._chat_loop(
            backend=backend,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="websocket",
        )
    )

    assert backend.clear_history_calls == 0
    assert backend.messages == []
    captured = capsys.readouterr().out
    assert "Conversation history cleared" not in captured
    assert "no-op for this agent type" in captured


def test_chat_loop_surfaces_history_truncation_notice(monkeypatch, capsys):
    """When the backend reports a non-zero last_send_dropped_turns, the REPL
    must surface a yellow notice so the user knows context was silently
    trimmed."""

    class TruncatingBackend(FakeChatClient):
        def __init__(self):
            super().__init__()
            self.last_send_dropped_turns = 0
            self._call = 0

        async def send_message(self, message: str, **kwargs):
            self._call += 1
            # First call clean, second call reports a 3-turn drop.
            self.last_send_dropped_turns = 0 if self._call == 1 else 3
            return await super().send_message(message, **kwargs)

    backend = TruncatingBackend()
    inputs = iter(["one", "two", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)

    asyncio.run(
        chat_module._chat_loop(
            backend=backend,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="openai",
        )
    )

    captured = capsys.readouterr().out
    assert "dropped 3 oldest turns" in captured
    assert "Use /reset to start fresh" in captured


def test_chat_loop_breaks_when_protocol_error_disconnects_backend(monkeypatch, capsys):
    """ATX Round 2 W2 / Round 3 B1: when a ChatProtocolError leaves the
    backend disconnected (e.g. zeroclaw's approval_request handler
    closes the socket before raising), the REPL must break immediately,
    not print 'Continuing chat session.' and loop back to read.

    This test fails if the `if not getattr(backend, 'is_connected', True)
    : break` branch is removed:
    - the read counter would exceed 1 (the loop would solicit a 2nd input)
    - the captured stdout would contain 'Continuing chat session.'
    - the captured stdout would NOT contain 'Chat session ended'
    """
    from clawrium.cli.chat import _chat_loop

    class DisconnectingClient:
        """Fake backend whose send_message raises ChatProtocolError and
        marks itself disconnected — mirrors ZeroClawChatBackend's
        approval_request behavior."""

        def __init__(self):
            self.is_connected = True
            self.closed = False

        async def connect(self):
            pass

        async def close(self):
            self.closed = True
            self.is_connected = False

        async def send_message(
            self, message, session_key, on_delta, response_timeout_seconds
        ):
            self.is_connected = (
                False  # mirrors `await self.close()` in approval_request
            )
            raise ChatProtocolError("ZeroClaw requested tool approval (tool='shell')")

        def clear_history(self):
            pass

    client = DisconnectingClient()
    # Queue TWO inputs so a non-breaking loop has a second user message
    # to send. The break contract requires read_count == 1; without the
    # break the loop would consume both.
    inputs = iter(["please do something", "another message"])
    read_count = {"n": 0}

    async def fake_read(*_args, **_kwargs):
        read_count["n"] += 1
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read)

    asyncio.run(
        _chat_loop(
            backend=client,
            session_key="main",
            response_timeout_seconds=5.0,
            idle_timeout_seconds=0.0,
            chat_type="zeroclaw",
        )
    )

    captured = capsys.readouterr()

    # Pin contracts:
    #  1. Exactly one prompt was issued — the loop broke before re-reading.
    assert read_count["n"] == 1, (
        f"Expected the loop to break after 1 read; got {read_count['n']}"
    )
    #  2. The session-ended message landed on stdout.
    assert "Chat session ended" in captured.out, captured.out
    #  3. The 'continue' branch did NOT fire.
    assert "Continuing chat session." not in captured.out, captured.out
    #  4. The backend was closed (idempotent — approval_request already
    #     closed; the outer finally re-runs close()).
    assert client.closed is True


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
        monkeypatch.setattr("clawrium.cli.chat.get_instance_secrets", lambda _key: {})

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "hermes_api_server_key" in result.output.lower()
        assert "re-run" in result.output.lower()
        # ATX W3 — the remediation hint must be copy-pasteable; the
        # literal "..." would land in users' shells as an unparseable
        # agent name. The `<name>` placeholder makes the substitution
        # obvious.
        assert "..." not in result.output, (
            "remediation hint contains literal '...' — users will copy "
            "it verbatim. Use '<name>' as a placeholder instead."
        )

    def test_missing_api_server_block(self, monkeypatch):
        """Missing api_server config block surfaces a friendly error."""
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (
                self.HOST,
                "hermes",
                {"agent_name": "hermes-test", "config": {}},
            ),
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
        """ChatConnectionError from the hermes backend surfaces a systemctl
        remediation hint pointing at the agent host's user service unit."""
        from clawrium.core.chat import ChatConnectionError

        self._setup_resolved_hermes(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatConnectionError(
                "Failed to reach hermes at http://wolf-i.lan:8642/v1"
            )

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "connection failed" in result.output.lower()
        # systemctl hint is the canonical remediation for unreachable hermes.
        assert "systemctl --user status hermes-hermes-test" in result.output
        # No legacy-bind hint because the standard fixture binds 0.0.0.0.
        assert "legacy bind" not in result.output.lower()

    def test_service_unreachable_legacy_bind_hint(self, monkeypatch):
        """When the persisted bind is still 127.0.0.1 (pre-migration), surface
        a follow-on hint nudging the user to run `clm agent configure`."""
        from clawrium.core.chat import ChatConnectionError

        legacy_agent = {
            "agent_name": "hermes-test",
            "config": {
                "api_server": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 8642,
                }
            },
        }
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (self.HOST, "hermes", legacy_agent),
        )
        monkeypatch.setattr(
            "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "openai"
        )
        monkeypatch.setattr(
            "clawrium.cli.chat.get_instance_secrets",
            lambda _key: {
                "HERMES_API_SERVER_KEY": {
                    "key": "HERMES_API_SERVER_KEY",
                    "value": "c" * 64,
                }
            },
        )

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatConnectionError(
                "Failed to reach hermes at http://wolf-i.lan:8642/v1"
            )

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "legacy bind" in result.output.lower()
        assert "clawctl agent configure hermes-test" in result.output

    def test_401_remediation(self, monkeypatch):
        """401 path surfaces a 'Re-run clm agent configure' remediation hint.
        The exception message no longer carries the raw HTTP status code; the
        type alone discriminates auth failures from other errors."""
        from clawrium.core.chat import ChatAuthenticationError

        self._setup_resolved_hermes(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatAuthenticationError("Hermes rejected bearer token")

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "authentication failed" in result.output.lower()
        assert "re-run" in result.output.lower()
        assert "clawctl agent configure hermes-test" in result.output
        # Status code MUST NOT appear in user output (exit criterion: no raw
        # HTTP codes dumped). The exception type is the discriminator.
        assert "401" not in result.output
        assert "403" not in result.output

    def test_403_remediation(self, monkeypatch):
        """403 path produces the same remediation as 401 (same exception
        type from the backend — both are 'bearer rejected')."""
        from clawrium.core.chat import ChatAuthenticationError

        self._setup_resolved_hermes(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            # Backend raises the same exception type for 403 as for 401.
            raise ChatAuthenticationError("Hermes rejected bearer token")

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "authentication failed" in result.output.lower()
        assert "re-run" in result.output.lower()
        assert "clawctl agent configure hermes-test" in result.output

    def test_session_flag_warns_for_hermes(self, monkeypatch):
        """Passing `--session <non-default>` to a hermes agent logs a dim
        warning and continues; chat still starts."""
        self._setup_resolved_hermes(monkeypatch)

        captured: dict[str, object] = {}

        async def mock_chat_loop(backend, **kwargs):
            captured["session_key"] = kwargs.get("session_key")

        monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

        result = runner.invoke(
            app, ["chat", "hermes-test", "--session", "custom-session"]
        )

        assert result.exit_code == 0
        # The user-facing copy must use plain language (no "phase 1" jargon)
        # and must not appear before the "Connected target:" line — the
        # warning fires only after backend construction succeeds.
        assert "no effect for this agent type" in result.output
        assert "phase 1" not in result.output.lower()
        warn_idx = result.output.find("no effect for this agent type")
        connected_idx = result.output.find("Connected target")
        assert warn_idx >= 0 and connected_idx >= 0
        assert warn_idx < connected_idx
        # Chat still proceeded — session_key was forwarded verbatim.
        assert captured.get("session_key") == "custom-session"

    def test_session_flag_warning_not_emitted_when_backend_build_fails(
        self, monkeypatch
    ):
        """Backend construction failure (e.g. missing key) must NOT be
        preceded by the --session warning. The warning fires only after a
        successful backend build."""
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (self.HOST, "hermes", self.AGENT),
        )
        monkeypatch.setattr(
            "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "openai"
        )
        # No HERMES_API_SERVER_KEY -> _build_hermes_backend raises ValueError.
        monkeypatch.setattr("clawrium.cli.chat.get_instance_secrets", lambda _key: {})

        result = runner.invoke(
            app, ["chat", "hermes-test", "--session", "custom-session"]
        )

        assert result.exit_code == 1
        assert "no effect for this agent type" not in result.output

    def test_session_flag_default_does_not_warn(self, monkeypatch):
        """Default --session=main must not trigger the no-op warning."""
        self._setup_resolved_hermes(monkeypatch)

        async def mock_chat_loop(backend, **kwargs):
            return None

        monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 0
        assert "no-op" not in result.output.lower()

    def test_connection_error_does_not_leak_httpx_internals(self, monkeypatch):
        """End-to-end: a real httpx ConnectError carrying transport
        internals bubbles through HermesOpenAIBackend → ChatConnectionError
        → CLI without those internals reaching the user.

        The load-bearing protection lives in `chat_hermes.py` exception
        construction (the backend builds ChatConnectionError with a clean
        URL-only message — see `_send_message`). The CLI sanitizer does
        NOT strip `Errno`/`httpx`/path tokens, so this test would fail if a
        future change re-introduced `f"...: {exc}"` to the backend."""
        import httpx as _httpx

        self._setup_resolved_hermes(monkeypatch)

        leaky_text = (
            "[Errno 111] Connection refused; httpx.ConnectError: "
            "_ssl.c:1056 path=/usr/lib/python3/dist-packages/httpx/_transports/default.py"
        )

        def handler(request: _httpx.Request) -> _httpx.Response:
            raise _httpx.ConnectError(leaky_text)

        real_async_client = _httpx.AsyncClient

        def make_client(*args, **kwargs):
            # Discard any transport the backend might pass; wire ours in.
            kwargs.pop("transport", None)
            return real_async_client(transport=_httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr("clawrium.core.chat_hermes.httpx.AsyncClient", make_client)

        # Feed one message into the REPL so send_message() actually runs.
        result = runner.invoke(app, ["chat", "hermes-test"], input="hello\n")

        assert result.exit_code == 1
        # Remediation hint surfaces unconditionally below the error line.
        assert "systemctl --user status hermes-hermes-test" in result.output
        # Absence assertions: these tokens must never reach user output. If
        # any flip in the future, fix `chat_hermes.py` (the backend layer),
        # not the CLI sanitizer — `_sanitize_exception_text` is defence in
        # depth and does NOT strip these patterns.
        assert "Errno" not in result.output
        assert "httpx" not in result.output
        assert "/usr/lib" not in result.output

    def test_service_timeout(self, monkeypatch):
        """Timeout-originated ChatConnectionError surfaces a --timeout hint,
        not a systemctl hint (the service is up but slow, not down)."""
        from clawrium.core.chat import ChatConnectionError

        self._setup_resolved_hermes(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatConnectionError(
                "Timed out waiting for hermes response after 120.0s"
            )

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "connection failed" in result.output.lower()
        assert "--timeout" in result.output
        # systemctl hint is for connect-refused, not timeouts.
        assert "systemctl" not in result.output

    def test_malformed_secret_entry_missing_value(self, monkeypatch):
        """A secrets.json entry missing the 'value' field must surface a
        friendly ValueError-routed error, not a Python KeyError traceback."""
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (self.HOST, "hermes", self.AGENT),
        )
        monkeypatch.setattr(
            "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "openai"
        )
        # Truthy dict, but no "value" field — the old code would KeyError.
        monkeypatch.setattr(
            "clawrium.cli.chat.get_instance_secrets",
            lambda _key: {"HERMES_API_SERVER_KEY": {"key": "HERMES_API_SERVER_KEY"}},
        )

        result = runner.invoke(app, ["chat", "hermes-test"])

        assert result.exit_code == 1
        assert "hermes_api_server_key" in result.output.lower()
        assert "re-run" in result.output.lower()
        # Interpolated remediation must include both agent_type and host.
        assert "--type hermes" in result.output
        assert "--host wolf-i.lan" in result.output
        # KeyError tracebacks contain this token; assert absence as a regression
        # canary against the original `secret_entry["value"]` access.
        assert "KeyError" not in result.output
        assert "Traceback" not in result.output


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


def test_zeroclaw_satisfies_chat_backend_protocol():
    from clawrium.core.chat import ChatBackend, SecretStr
    from clawrium.core.chat_zeroclaw import ZeroClawChatBackend

    backend = ZeroClawChatBackend(
        gateway_url="ws://example.test:4080/ws/chat",
        auth_token=SecretStr("token"),
    )
    assert isinstance(backend, ChatBackend)


# ---------------------------------------------------------------------------
# ZeroClaw chat dispatch — agents whose manifest advertises features.chat.type
# == "zeroclaw" route to ZeroClawChatBackend.
# ---------------------------------------------------------------------------


class TestZeroclawChat:
    """Dispatch + missing-credential tests for the zeroclaw chat path."""

    HOST = {"hostname": "pi-edge.lan", "alias": "pi-edge"}
    AGENT = {
        "agent_name": "zc-test",
        "config": {
            "gateway": {
                "url": "ws://pi-edge.lan:4080/ws/chat",
                "auth": "paired-bearer-token",
                "port": 4080,
            }
        },
    }

    def _patch_resolve(self, monkeypatch, agent=None):
        monkeypatch.setattr(
            "clawrium.cli.chat.get_agent_by_name",
            lambda _name: (self.HOST, "zeroclaw", agent or self.AGENT),
        )
        monkeypatch.setattr(
            "clawrium.cli.chat._resolve_chat_type", lambda _agent_type: "zeroclaw"
        )

    def test_dispatch_to_zeroclaw_backend(self, monkeypatch):
        """A manifest advertising features.chat.type == zeroclaw routes to
        ZeroClawChatBackend with the bearer + URL from hosts.json."""
        self._patch_resolve(monkeypatch)

        captured: dict[str, object] = {}

        async def mock_chat_loop(backend, **_kwargs):
            captured["backend"] = backend

        monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

        result = runner.invoke(app, ["chat", "zc-test"])

        assert result.exit_code == 0, result.output
        backend = captured["backend"]
        # Must be the ZeroClaw backend, not the openclaw client.
        from clawrium.core.chat_zeroclaw import ZeroClawChatBackend

        assert isinstance(backend, ZeroClawChatBackend)
        # URL ends with /ws/chat (idempotent suffix append).
        assert backend.gateway_url.endswith("/ws/chat")

    def test_missing_gateway_token_exits_1(self, monkeypatch):
        """Agent record without gateway.auth surfaces a friendly error."""
        agent_no_token = {
            "agent_name": "zc-test",
            "config": {
                "gateway": {
                    "url": "ws://pi-edge.lan:4080/ws/chat",
                    "port": 4080,
                }
            },
        }
        self._patch_resolve(monkeypatch, agent=agent_no_token)

        result = runner.invoke(app, ["chat", "zc-test"])

        assert result.exit_code == 1
        assert "token is missing" in result.output.lower()

    def test_missing_gateway_url_exits_1(self, monkeypatch):
        """Agent record without gateway.url surfaces a friendly error."""
        agent_no_url = {
            "agent_name": "zc-test",
            "config": {
                "gateway": {
                    "auth": "paired-bearer-token",
                    "port": 4080,
                }
            },
        }
        self._patch_resolve(monkeypatch, agent=agent_no_url)

        result = runner.invoke(app, ["chat", "zc-test"])

        assert result.exit_code == 1
        assert "url is missing" in result.output.lower()

    def test_auth_error_surfaces_configure_hint(self, monkeypatch):
        """A ChatAuthenticationError from the backend surfaces the
        `clm agent configure <name>` remediation hint — the only path
        to recover a rotated pairing token."""
        from clawrium.core.chat import ChatAuthenticationError

        self._patch_resolve(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatAuthenticationError("ZeroClaw gateway rejected the bearer token")

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "zc-test"])

        assert result.exit_code == 1
        assert "authentication failed" in result.output.lower()
        assert "clawctl agent configure zc-test" in result.output

    def test_timeout_surfaces_timeout_hint(self, monkeypatch):
        """ATX Round 1 W6 / Round 4 W-B: a recv-timeout ChatConnectionError
        routes to the --timeout hint. Construct the exception text from
        the same `RECV_TIMEOUT_MSG_PREFIX` constant the CLI imports so a
        rewording of the prefix cannot break the routing test silently."""
        from clawrium.core.chat import ChatConnectionError
        from clawrium.core.chat_zeroclaw import RECV_TIMEOUT_MSG_PREFIX

        self._patch_resolve(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatConnectionError(f"{RECV_TIMEOUT_MSG_PREFIX} after 5s")

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "zc-test"])

        assert result.exit_code == 1
        assert "Try a higher --timeout" in result.output

    def test_unreachable_surfaces_configure_hint(self, monkeypatch):
        """ATX Round 1 W6: a non-timeout ChatConnectionError prints the
        agent-reachability hint pointing at `clm agent configure` (for
        stale pairing tokens)."""
        from clawrium.core.chat import ChatConnectionError

        self._patch_resolve(monkeypatch)

        def fake_asyncio_run(_coro):
            _coro.close()
            raise ChatConnectionError(
                "Failed to reach ZeroClaw gateway at ws://pi-edge.lan:4080/ws/chat"
            )

        monkeypatch.setattr("clawrium.cli.chat.asyncio.run", fake_asyncio_run)

        result = runner.invoke(app, ["chat", "zc-test"])

        assert result.exit_code == 1
        assert "clawctl agent configure zc-test" in result.output
        # The timeout-specific hint must NOT fire on the unreachable path.
        assert "Try a higher --timeout" not in result.output

    def test_session_flag_no_op_notice_emitted_for_zeroclaw(self, monkeypatch):
        """ATX Round 1 W7: `--session` is accepted but has no effect on
        zeroclaw (gateway owns session state). The CLI should print the
        same no-op notice it prints for openai-typed agents."""
        self._patch_resolve(monkeypatch)

        async def mock_chat_loop(backend, **_kwargs):  # noqa: ARG001
            return None

        monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

        result = runner.invoke(app, ["chat", "zc-test", "--session", "custom"])

        assert result.exit_code == 0, result.output
        assert "--session" in result.output

    def test_url_appended_with_ws_chat_path_when_missing(self, monkeypatch):
        """When the persisted URL has no /ws/chat suffix (e.g. host record
        reconstruction strips it), the backend re-appends it idempotently
        so the gateway accepts the upgrade."""
        agent_no_path = {
            "agent_name": "zc-test",
            "config": {
                "gateway": {
                    "url": "ws://pi-edge.lan:4080",
                    "auth": "paired-bearer-token",
                    "port": 4080,
                }
            },
        }
        self._patch_resolve(monkeypatch, agent=agent_no_path)

        captured: dict[str, object] = {}

        async def mock_chat_loop(backend, **_kwargs):
            captured["backend"] = backend

        monkeypatch.setattr(chat_module, "_chat_loop", mock_chat_loop)

        result = runner.invoke(app, ["chat", "zc-test"])

        assert result.exit_code == 0, result.output
        assert captured["backend"].gateway_url.endswith("/ws/chat")


# --- Styled chat prompts (issue #455) ---------------------------------


class _PrintRecorder:
    """Capture every `console.print(...)` call's positional args and
    kwargs so tests can assert on style/markup independent of Rich's
    output stream (which may have been bound at module import time and
    thus escape `capsys`)."""

    def __init__(self, real_print):
        self.calls: list[dict[str, object]] = []
        self._real_print = real_print

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return self._real_print(*args, **kwargs)


def _install_print_recorder(monkeypatch) -> _PrintRecorder:
    recorder = _PrintRecorder(chat_module.console.print)
    monkeypatch.setattr(chat_module.console, "print", recorder)
    return recorder


def test_chat_loop_uses_agent_name_in_prefix(monkeypatch):
    """The agent prefix must surface the resolved agent name, not the
    literal `agent>`, so multi-agent sessions are distinguishable.

    Uses the `console.print` recorder rather than `capsys` because Rich's
    `Console()` captures `sys.stdout` at import time; depending on import
    order, `capsys` may not see Rich output (ATX issue #455 W6).
    """
    fake_client = FakeChatClient()
    inputs = iter(["hello", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)
    recorder = _install_print_recorder(monkeypatch)

    asyncio.run(
        chat_module._chat_loop(
            backend=fake_client,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="websocket",
            agent_label="cuddly-otter",
        )
    )

    rendered_first_args = [call["args"][0] for call in recorder.calls if call["args"]]
    assert "cuddly-otter> " in rendered_first_args
    assert "agent> " not in rendered_first_args


def test_chat_loop_agent_prefix_uses_green_style(monkeypatch):
    """The streaming agent-prefix print must use `style='bold green'`
    AND `markup=False` together. `style=` alone does not disable Rich's
    markup parser — `markup=False` is what actually keeps `[red]…[/red]`
    in `agent_label` from being consumed by the parser (ATX issue #455
    B1 / W4)."""
    fake_client = FakeChatClient()
    inputs = iter(["hi", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)
    recorder = _install_print_recorder(monkeypatch)

    asyncio.run(
        chat_module._chat_loop(
            backend=fake_client,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="websocket",
            agent_label="my-agent",
        )
    )

    prefix_calls = [
        call
        for call in recorder.calls
        if call["args"] and call["args"][0] == "my-agent> "
    ]
    assert prefix_calls, "No print call emitted the agent prefix"
    for call in prefix_calls:
        kwargs = call["kwargs"]
        assert kwargs.get("style") == "bold green", (
            f"prefix call lacks style='bold green': {kwargs!r}"
        )
        # Must be explicit `False` — absent means Rich's default
        # (markup=True) is active, which is exactly the regression W4
        # describes.
        assert kwargs.get("markup") is False, (
            f"prefix call must set markup=False explicitly: {kwargs!r}"
        )


class _NonStreamingFakeClient(FakeChatClient):
    """Drives the `elif final_text` branch in `_chat_loop` — the one
    that emits the styled prefix from the non-streaming path. Unlike
    `FakeChatClient.send_message`, this variant does NOT call
    `on_delta`, so `shown_prefix` stays False and the final-text print
    site is the one that runs."""

    async def send_message(self, message: str, **kwargs):
        self.messages.append(message)
        self.last_kwargs = kwargs
        return "final-response-text"


def test_chat_loop_non_streaming_final_text_uses_green_style(monkeypatch):
    """The non-streaming final-text print site (`elif final_text`) must
    also use `style='bold green'` + `markup=False`. The streaming-only
    test does not cover this branch because `FakeChatClient` always
    streams a delta (ATX issue #455 W5)."""
    backend = _NonStreamingFakeClient()
    inputs = iter(["hello", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)
    recorder = _install_print_recorder(monkeypatch)

    asyncio.run(
        chat_module._chat_loop(
            backend=backend,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="websocket",
            agent_label="nemo",
        )
    )

    prefix_calls = [
        call for call in recorder.calls if call["args"] and call["args"][0] == "nemo> "
    ]
    assert prefix_calls, "non-streaming path did not emit the agent prefix"
    for call in prefix_calls:
        assert call["kwargs"].get("style") == "bold green"
        assert call["kwargs"].get("markup") is False
    # final text body should also be rendered with markup off.
    final_calls = [
        call
        for call in recorder.calls
        if call["args"] and call["args"][0] == "final-response-text"
    ]
    assert final_calls, "final-text body print not observed"
    for call in final_calls:
        assert call["kwargs"].get("markup") is False


def test_chat_loop_agent_label_with_markup_chars_renders_literally(monkeypatch):
    """A hostile (or just unusual) `agent_label` containing Rich-markup
    syntax must reach the recorded print call as a literal string —
    `markup=False` is what guarantees this, and ATX B1 demonstrated
    that `style=` alone was insufficient."""
    backend = FakeChatClient()
    inputs = iter(["hi", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)
    recorder = _install_print_recorder(monkeypatch)

    asyncio.run(
        chat_module._chat_loop(
            backend=backend,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="websocket",
            agent_label="[red]hack[/red]",
        )
    )

    prefix_calls = [
        call
        for call in recorder.calls
        if call["args"] and call["args"][0] == "[red]hack[/red]> "
    ]
    assert prefix_calls, (
        "markup chars must reach the print call as a literal, not get "
        "consumed by Rich's parser"
    )
    for call in prefix_calls:
        assert call["kwargs"].get("markup") is False


def test_chat_loop_strips_bidi_chars_from_agent_label(monkeypatch):
    """Hand-edited `hosts.json` could smuggle bidi/zero-width chars into
    `agent_record.agent_name`. The label seen at the prefix print site
    must be the sanitized form, matching the parity guarantee enforced
    on exception bodies (ATX issue #455 W2)."""
    backend = FakeChatClient()
    inputs = iter(["hi", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)
    recorder = _install_print_recorder(monkeypatch)

    # U+202E RIGHT-TO-LEFT OVERRIDE between "neat" and "agent"
    spoofed = "neat‮agent"
    asyncio.run(
        chat_module._chat_loop(
            backend=backend,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="websocket",
            agent_label=spoofed,
        )
    )

    first_args = [c["args"][0] for c in recorder.calls if c["args"]]
    # No print call's first arg should still contain the bidi char.
    assert not any("‮" in arg for arg in first_args if isinstance(arg, str)), (
        "RLO U+202E leaked into a print call's first positional arg"
    )
    # Positive assertion (ATX round-2 gap #3): the sanitized prefix
    # must actually be present — a sanitizer that drops the entire
    # label would silently satisfy the negative assertion above.
    assert "neat agent> " in first_args, (
        "expected sanitized prefix 'neat agent> ' was not emitted; "
        f"observed first args: {first_args!r}"
    )


def test_read_user_input_signature_preserved():
    """The `_read_user_input` signature is part of the test surface —
    `tests/test_cli_chat.py` monkeypatches it with the exact
    `(prompt, idle_timeout_seconds) -> str` shape. Guard against
    accidental signature drift."""
    import inspect

    sig = inspect.signature(chat_module._read_user_input)
    params = list(sig.parameters)
    assert params == ["prompt", "idle_timeout_seconds"]
    # `from __future__ import annotations` turns annotations into strings,
    # so compare by name to stay robust to that.
    prompt_ann = sig.parameters["prompt"].annotation
    idle_ann = sig.parameters["idle_timeout_seconds"].annotation
    assert prompt_ann in (str, "str")
    assert idle_ann in (float, "float")
    assert asyncio.iscoroutinefunction(chat_module._read_user_input)


def test_read_user_input_non_tty_uses_input_fallback(monkeypatch):
    """When stdin is not a TTY, `_read_user_input` must fall back to
    the bare `input()` path so piped invocations
    (`echo hi | clm chat ...`) keep working. prompt_toolkit's
    `PromptSession` must NOT be touched in this branch (ATX issue #455
    B2 non-TTY half).
    """
    import sys as _sys

    # Force the non-TTY branch.
    class _FakeStdin:
        def isatty(self):
            return False

    monkeypatch.setattr(_sys, "stdin", _FakeStdin())
    monkeypatch.setattr("builtins.input", lambda _prompt: "piped-line")

    # Sentinel: if the TTY branch is taken, this raises.
    def _fail_get_session():
        raise AssertionError(
            "_get_prompt_session must not be called when stdin is non-TTY"
        )

    monkeypatch.setattr(chat_module, "_get_prompt_session", _fail_get_session)

    result = asyncio.run(chat_module._read_user_input("you> ", 0.0))
    assert result == "piped-line"


def test_read_user_input_non_tty_handles_stdin_none(monkeypatch):
    """`sys.stdin` can be `None` (Windows GUI hosts, Popen with
    stdin=DEVNULL). `_read_user_input` must not crash with
    AttributeError before the fallback runs (ATX issue #455 W1)."""
    import sys as _sys

    monkeypatch.setattr(_sys, "stdin", None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "fallback")
    monkeypatch.setattr(
        chat_module,
        "_get_prompt_session",
        lambda: (_ for _ in ()).throw(
            AssertionError("PromptSession touched while stdin is None")
        ),
    )

    result = asyncio.run(chat_module._read_user_input("you> ", 0.0))
    assert result == "fallback"


def test_read_user_input_tty_uses_prompt_session_with_formatted_text(monkeypatch):
    """When stdin is a TTY, `_read_user_input` must drive
    `PromptSession.prompt_async` with a `FormattedText([(...)])` styled
    in `ansiblue bold`. Covers the TTY half of ATX B2 — the feature this
    PR exists to deliver."""
    import sys as _sys

    class _FakeStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(_sys, "stdin", _FakeStdin())
    # Reset the cached PromptSession so the test sees a clean state.
    monkeypatch.setattr(chat_module, "_PROMPT_SESSION", None)

    captured: dict[str, object] = {}

    class _FakeSession:
        async def prompt_async(self, styled):
            captured["styled"] = styled
            return "typed-line"

    monkeypatch.setattr(chat_module, "_get_prompt_session", lambda: _FakeSession())

    result = asyncio.run(chat_module._read_user_input("you> ", 0.0))
    assert result == "typed-line"
    styled = captured["styled"]
    from prompt_toolkit.formatted_text import FormattedText

    assert isinstance(styled, FormattedText)
    assert list(styled) == [("ansiblue bold", "you> ")]


def test_read_user_input_tty_honors_idle_timeout(monkeypatch):
    """Idle-timeout wrap (`asyncio.wait_for`) must apply to the TTY
    branch too — otherwise the `--idle-timeout` behavior silently
    disappears on real terminals (the same path users actually exercise).
    """
    import sys as _sys

    class _FakeStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(_sys, "stdin", _FakeStdin())
    monkeypatch.setattr(chat_module, "_PROMPT_SESSION", None)

    class _SlowSession:
        async def prompt_async(self, styled):
            # Sleep longer than the timeout; wait_for must cancel us.
            await asyncio.sleep(5)
            return "never"

    monkeypatch.setattr(chat_module, "_get_prompt_session", lambda: _SlowSession())

    with pytest.raises(TimeoutError):
        asyncio.run(chat_module._read_user_input("you> ", 0.05))


def test_sanitize_agent_label_strips_bidi_and_control(monkeypatch):
    """Direct coverage of the sanitizer used in `_chat_loop` so a
    refactor that swaps the regex out is caught without going through
    the whole loop."""
    assert chat_module._sanitize_agent_label("cuddly-otter") == "cuddly-otter"
    assert chat_module._sanitize_agent_label("a‮b") == "a b"
    assert chat_module._sanitize_agent_label("a​b") == "a b"
    assert chat_module._sanitize_agent_label("a\x07b") == "a b"
    # Collapses to empty → returns literal fallback so the prefix is
    # never just `> `.
    assert chat_module._sanitize_agent_label("‮​") == "agent"


def test_reset_prompt_session_clears_global():
    """`_reset_prompt_session` is called on every reconnect iteration of
    `chat()`; the contract is that the next `_get_prompt_session()`
    constructs a fresh object."""
    chat_module._PROMPT_SESSION = object()
    chat_module._reset_prompt_session()
    assert chat_module._PROMPT_SESSION is None


class _NullResponseFakeClient(FakeChatClient):
    """Drives the `else` / `[no response]` branch in `_chat_loop` — no
    streaming delta and an empty/falsy final response. `FakeChatClient`
    streams a delta, so this branch is dead code without a dedicated
    variant (ATX round-2 gap #1)."""

    async def send_message(self, message: str, **kwargs):
        self.messages.append(message)
        self.last_kwargs = kwargs
        return ""


def test_chat_loop_no_response_branch_uses_green_style(monkeypatch):
    """The `else` branch that emits `[no response]` is itself a
    Rich-markup-like string. If a future regression removed
    `markup=False` there, Rich would attempt to parse `[no response]`
    as a tag (`[no` → opening) and either crash or render the line
    wrong. Pin both the prefix and body kwargs (ATX round-2 gap #1)."""
    backend = _NullResponseFakeClient()
    inputs = iter(["hello", "/exit"])

    async def fake_read_user_input(prompt: str, idle_timeout_seconds: float) -> str:
        return next(inputs)

    monkeypatch.setattr(chat_module, "_read_user_input", fake_read_user_input)
    recorder = _install_print_recorder(monkeypatch)

    asyncio.run(
        chat_module._chat_loop(
            backend=backend,
            session_key="main",
            response_timeout_seconds=30.0,
            idle_timeout_seconds=10.0,
            chat_type="websocket",
            agent_label="silent",
        )
    )

    prefix_calls = [
        call
        for call in recorder.calls
        if call["args"] and call["args"][0] == "silent> "
    ]
    assert prefix_calls, "no-response path did not emit the agent prefix"
    for call in prefix_calls:
        assert call["kwargs"].get("style") == "bold green"
        assert call["kwargs"].get("markup") is False

    no_response_calls = [
        call
        for call in recorder.calls
        if call["args"] and call["args"][0] == "[no response]"
    ]
    assert no_response_calls, "expected literal '[no response]' body to be printed"
    for call in no_response_calls:
        # markup=False is what guarantees Rich does NOT parse `[no` as
        # an opening tag — the regression this test guards against.
        assert call["kwargs"].get("markup") is False


def test_read_user_input_non_tty_honors_idle_timeout(monkeypatch):
    """`asyncio.wait_for` must wrap the non-TTY arm too, not only the
    TTY one. Otherwise piped invocations with `--idle-timeout` would
    silently hang waiting on `input()` forever (ATX round-2 gap #4)."""
    import sys as _sys

    class _FakeStdin:
        def isatty(self):
            return False

    monkeypatch.setattr(_sys, "stdin", _FakeStdin())

    def _slow_input(_prompt):
        import time

        time.sleep(5)
        return "never"

    monkeypatch.setattr("builtins.input", _slow_input)

    with pytest.raises(TimeoutError):
        asyncio.run(chat_module._read_user_input("you> ", 0.05))


def test_chat_invokes_reset_prompt_session_before_chat_loop(monkeypatch):
    """`chat()` MUST call `_reset_prompt_session` at the top of every
    reconnect iteration so a stale `PromptSession` from a previous
    `asyncio.run()` cannot anchor the new event loop. Pin the call-
    site contract against future regressions, e.g. someone moving the
    reset into the `except` block (ATX round-2 gap #5)."""
    # Patch the get_agent_by_name resolution and backend builder so
    # `chat()` reaches the reconnect loop without doing network I/O.
    host = {"hostname": "host1", "alias": "h1"}
    agent = {
        "agent_name": "spy-agent",
        "config": {"gateway": {"url": "ws://host1:9", "auth": "tok"}},
    }
    monkeypatch.setattr(
        "clawrium.cli.chat.get_agent_by_name",
        lambda _name: (host, "openclaw", agent),
    )

    class _StubBackend:
        async def connect(self):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(
        chat_module,
        "_build_openclaw_backend",
        lambda **_: _StubBackend(),
    )

    # No-op _chat_loop so we observe the reset call without driving
    # the whole REPL.
    async def _noop_chat_loop(**_kwargs):
        return None

    monkeypatch.setattr(chat_module, "_chat_loop", _noop_chat_loop)

    counter = {"calls": 0}

    def _spy_reset():
        counter["calls"] += 1

    monkeypatch.setattr(chat_module, "_reset_prompt_session", _spy_reset)

    result = runner.invoke(app, ["chat", "spy-agent"])
    assert result.exit_code == 0, result.output
    # At least one reset before the first (and only successful) loop run.
    assert counter["calls"] >= 1, (
        "chat() must call _reset_prompt_session before asyncio.run(_chat_loop)"
    )

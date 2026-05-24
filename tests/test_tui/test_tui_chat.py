"""Tests for TUI chat panel widget."""

from clawrium.cli.tui.data import AgentViewModel
from clawrium.cli.tui.screens.detail import DetailScreen
from clawrium.cli.tui.widgets.chat_panel import ChatPanel
from clawrium.core.health import ClawStatus


SAMPLE_OPENCLAW_AGENT = AgentViewModel(
    agent_key="openclaw",
    agent_name="opc-test",
    agent_type="openclaw",
    host="192.168.1.100",
    host_alias="testhost",
    version="1.0.0",
    status=ClawStatus.RUNNING,
    model="gpt-4o",
    uptime="2d 5h",
    missing_secrets=None,
    onboarding_step=None,
    process_running=True,
    health_error=None,
    addresses=[],
    provider="openai",
    provider_type="openai",
    cpu_count=4,
    memory_total_mb=16384,
    gateway_port=40123,
    gateway_url="ws://192.168.1.100:40123",
    gateway_auth="test-auth-token",
    device_id=None,
    device_private_key=None,
)

SAMPLE_ZEROCLAW_AGENT = AgentViewModel(
    agent_key="zeroclaw",
    agent_name="zc-test",
    agent_type="zeroclaw",
    host="192.168.1.100",
    host_alias="testhost",
    version="1.0.0",
    status=ClawStatus.RUNNING,
    model="claude-3",
    uptime="1d 2h",
    missing_secrets=None,
    onboarding_step=None,
    process_running=True,
    health_error=None,
    addresses=[],
    provider="anthropic",
    provider_type="anthropic",
    cpu_count=4,
    memory_total_mb=8192,
    gateway_port=None,
    gateway_url=None,
    gateway_auth=None,
    device_id=None,
    device_private_key=None,
)

SAMPLE_OPENCLAW_NO_GATEWAY = AgentViewModel(
    agent_key="openclaw",
    agent_name="opc-nogate",
    agent_type="openclaw",
    host="192.168.1.100",
    host_alias="testhost",
    version="1.0.0",
    status=ClawStatus.RUNNING,
    model="gpt-4o",
    uptime="1h",
    missing_secrets=None,
    onboarding_step=None,
    process_running=True,
    health_error=None,
    addresses=[],
    provider="openai",
    provider_type="openai",
    cpu_count=2,
    memory_total_mb=4096,
    gateway_port=None,
    gateway_url=None,
    gateway_auth=None,
    device_id=None,
    device_private_key=None,
)


class TestChatPanelInit:
    def test_panel_stores_config(self):
        panel = ChatPanel(
            agent_name="test-agent",
            gateway_url="ws://localhost:40123",
            gateway_auth="test-token",
            device_id="dev-123",
            device_private_key="key-abc",
        )
        assert panel._agent_name == "test-agent"
        assert panel._gateway_url == "ws://localhost:40123"
        assert panel._gateway_auth == "test-token"
        assert panel._device_id == "dev-123"
        assert panel._device_private_key == "key-abc"

    def test_panel_optional_device_credentials(self):
        panel = ChatPanel(
            agent_name="test-agent",
            gateway_url="ws://localhost:40123",
            gateway_auth="test-token",
        )
        assert panel._device_id is None
        assert panel._device_private_key is None

    def test_panel_initial_state(self):
        panel = ChatPanel(
            agent_name="test-agent",
            gateway_url="ws://localhost:40123",
            gateway_auth="test-token",
        )
        assert panel._connected is False
        assert panel._client is None
        assert panel._messages == []
        assert panel._session_key == "tui"


class TestChatPanelMessages:
    def test_messages_stored_in_memory(self):
        panel = ChatPanel(
            agent_name="test-agent",
            gateway_url="ws://localhost:40123",
            gateway_auth="test-token",
        )
        panel._messages.append(("user", "Hello"))
        panel._messages.append(("agent", "Hi!"))
        panel._messages.append(("user", "How are you?"))
        panel._messages.append(("agent", "I'm doing well!"))

        assert len(panel._messages) == 4
        assert panel._messages[0] == ("user", "Hello")
        assert panel._messages[1] == ("agent", "Hi!")

    def test_messages_cleared_on_new_panel(self):
        panel1 = ChatPanel(
            agent_name="test-agent",
            gateway_url="ws://localhost:40123",
            gateway_auth="test-token",
        )
        panel1._messages.append(("user", "Message 1"))

        panel2 = ChatPanel(
            agent_name="test-agent",
            gateway_url="ws://localhost:40123",
            gateway_auth="test-token",
        )
        assert len(panel2._messages) == 0


class TestDetailScreenChatEnabled:
    def test_openclaw_with_full_config(self):
        screen = DetailScreen(agent=SAMPLE_OPENCLAW_AGENT)
        assert screen._is_chat_enabled() is True

    def test_zeroclaw_not_enabled(self):
        screen = DetailScreen(agent=SAMPLE_ZEROCLAW_AGENT)
        assert screen._is_chat_enabled() is False

    def test_openclaw_without_gateway_url(self):
        screen = DetailScreen(agent=SAMPLE_OPENCLAW_NO_GATEWAY)
        assert screen._is_chat_enabled() is False

    def test_openclaw_without_gateway_auth(self):
        agent = AgentViewModel(
            **{
                **SAMPLE_OPENCLAW_AGENT,
                "gateway_url": "ws://localhost:40123",
                "gateway_auth": None,
            }
        )
        screen = DetailScreen(agent=agent)
        assert screen._is_chat_enabled() is False

    def test_non_openclaw_with_gateway_not_enabled(self):
        agent = AgentViewModel(
            **{
                **SAMPLE_ZEROCLAW_AGENT,
                "gateway_url": "ws://localhost:40123",
                "gateway_auth": "token",
            }
        )
        screen = DetailScreen(agent=agent)
        assert screen._is_chat_enabled() is False


class TestScrubException:
    """`_scrub_exception` in chat_panel.py must redact credentials AND strip
    display-manipulating chars — parity with the CLI's `_sanitize_exception_text`.
    """

    def test_strips_control_and_bidi_chars(self):
        from clawrium.cli.tui.widgets.chat_panel import _scrub_exception

        exc = Exception("ok\x1bbad\rmore‮flip‬end")
        cleaned = _scrub_exception(exc)
        assert "\x1b" not in cleaned
        assert "\r" not in cleaned
        assert "‮" not in cleaned
        assert "‬" not in cleaned
        # Positive: surrounding ASCII preserved.
        assert "ok" in cleaned
        assert "bad" in cleaned
        assert "end" in cleaned

    def test_strips_line_paragraph_separators(self):
        """U+2028 / U+2029 break line-oriented parsing in some renderers."""
        from clawrium.cli.tui.widgets.chat_panel import _scrub_exception

        cleaned = _scrub_exception(Exception("line1 line2 end"))
        assert " " not in cleaned
        assert " " not in cleaned
        assert "line1" in cleaned
        assert "line2" in cleaned
        assert "end" in cleaned

    def test_redacts_bearer_tokens(self):
        """B2 fix: TUI path must redact bearer/api_key/etc just like CLI path.

        Without this, a server-returned `Authorization: Bearer <real-token>`
        in an exception body reaches the TUI log verbatim.
        """
        from clawrium.cli.tui.widgets.chat_panel import _scrub_exception

        exc = Exception("HTTP 401: Authorization: Bearer abc-very-secret-token-123")
        cleaned = _scrub_exception(exc)
        assert "abc-very-secret-token-123" not in cleaned
        assert "***" in cleaned

    def test_redacts_keyword_anchored_tokens(self):
        """Keyword-anchored tokens (HERMES_API_SERVER_KEY=..., api_key=...) too."""
        from clawrium.cli.tui.widgets.chat_panel import _scrub_exception

        for body in (
            "HERMES_API_SERVER_KEY=ffffffffffffffff",
            "api_key=user-supplied-secret-value",
            "secret: hunter2-very-secret",
        ):
            cleaned = _scrub_exception(Exception(body))
            # The credential value must be redacted; the keyword may stay.
            assert "ffffffffffffffff" not in cleaned, body
            assert "user-supplied-secret-value" not in cleaned, body
            assert "hunter2-very-secret" not in cleaned, body

    def test_respects_limit(self):
        from clawrium.cli.tui.widgets.chat_panel import _scrub_exception

        long = "x" * 1000
        cleaned = _scrub_exception(Exception(long), limit=50)
        assert len(cleaned) <= 50

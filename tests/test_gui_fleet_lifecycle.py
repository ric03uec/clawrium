"""Tests for GUI fleet lifecycle endpoints (start/stop/restart).

Issue #459: the restart button was returning 500 due to wrong argument order
in the fleet.py endpoint handlers. These tests mock the underlying lifecycle
functions to verify correct argument passing and error handling.
"""

import pytest
from fastapi import HTTPException

from clawrium.gui.routes import fleet as fleet_mod
from clawrium.core.lifecycle import LifecycleError


@pytest.fixture
def anyio_backend():
    return "asyncio"


class TestStartAgentEndpoint:
    """Tests for POST /api/agents/{agent_key}/start."""

    @pytest.mark.anyio
    async def test_start_agent_calls_lifecycle_with_correct_args(self, monkeypatch):
        """start_agent_endpoint must pass (hostname, agent_type, agent_name=agent_key)."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        # Mock resolve_agent to return a valid host record
        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        # Mock start_agent to capture arguments
        captured_args = {}

        def mock_start_agent(hostname_arg, claw_name_arg, agent_name=None):
            captured_args["hostname"] = hostname_arg
            captured_args["claw_name"] = claw_name_arg
            captured_args["agent_name"] = agent_name
            return {
                "success": True,
                "agent": agent_key,
                "host": hostname,
                "operation": "start",
                "pid": None,
                "started_at": None,
                "error": None,
            }

        monkeypatch.setattr(fleet_mod, "start_agent", mock_start_agent)

        result = await fleet_mod.start_agent_endpoint(agent_key)

        assert result["success"] is True
        assert result["operation"] == "start"
        assert result["agent"] == agent_key
        assert captured_args["hostname"] == hostname
        assert captured_args["claw_name"] == agent_type
        assert captured_args["agent_name"] == agent_key

    @pytest.mark.anyio
    async def test_start_agent_returns_404_when_agent_not_found(self, monkeypatch):
        """When resolve_agent returns None, endpoint must raise 404."""
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: None)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.start_agent_endpoint("nonexistent-agent")

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_start_agent_returns_500_on_lifecycle_error(self, monkeypatch):
        """LifecycleError must be caught and returned as 500 with detail."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_start_agent(hostname_arg, claw_name_arg, agent_name=None):
            raise LifecycleError("SSH connection failed")

        monkeypatch.setattr(fleet_mod, "start_agent", mock_start_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.start_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 500
        # (#714) LifecycleError now returns a constant message
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "SSH connection failed" not in exc_info.value.detail

    @pytest.mark.anyio
    async def test_start_agent_returns_500_on_unexpected_error(self, monkeypatch):
        """Unexpected exceptions must be caught, logged, and returned as 500."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_start_agent(hostname_arg, claw_name_arg, agent_name=None):
            raise RuntimeError("Unexpected failure")

        monkeypatch.setattr(fleet_mod, "start_agent", mock_start_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.start_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR

    @pytest.mark.anyio
    async def test_start_agent_returns_502_when_success_false(self, monkeypatch):
        """When lifecycle returns success=False, endpoint must raise HTTP 502."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_start_agent(hostname_arg, claw_name_arg, agent_name=None):
            return {
                "success": False,
                "error": "SSH key not found",
                "agent": agent_key,
                "host": hostname,
                "operation": "start",
            }

        monkeypatch.setattr(fleet_mod, "start_agent", mock_start_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.start_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 502
        # (#714) constant message, never raw error text
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "SSH key not found" not in exc_info.value.detail

    @pytest.mark.anyio
    async def test_start_agent_success_false_no_path_leak(self, monkeypatch):
        """(#714) Error strings with filesystem paths must not reach the browser on the 502 path."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_start_agent(hostname_arg, claw_name_arg, agent_name=None):
            return {
                "success": False,
                "error": "failed at /home/user/.config/clawrium/secrets.json",
            }

        monkeypatch.setattr(fleet_mod, "start_agent", mock_start_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.start_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 502
        # (#714) constant message, never raw error text
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "/home/user/.config" not in exc_info.value.detail


class TestStopAgentEndpoint:
    """Tests for POST /api/agents/{agent_key}/stop."""

    @pytest.mark.anyio
    async def test_stop_agent_calls_lifecycle_with_correct_args(self, monkeypatch):
        """stop_agent_endpoint must pass (hostname, agent_type, agent_name=agent_key)."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        captured_args = {}

        def mock_stop_agent(hostname_arg, claw_name_arg, agent_name=None, timeout=30):
            captured_args["hostname"] = hostname_arg
            captured_args["claw_name"] = claw_name_arg
            captured_args["agent_name"] = agent_name
            return {
                "success": True,
                "agent": agent_key,
                "host": hostname,
                "operation": "stop",
                "pid": None,
                "started_at": None,
                "error": None,
            }

        monkeypatch.setattr(fleet_mod, "stop_agent", mock_stop_agent)

        result = await fleet_mod.stop_agent_endpoint(agent_key)

        assert result["success"] is True
        assert result["operation"] == "stop"
        assert result["agent"] == agent_key
        assert captured_args["hostname"] == hostname
        assert captured_args["claw_name"] == agent_type
        assert captured_args["agent_name"] == agent_key

    @pytest.mark.anyio
    async def test_stop_agent_returns_404_when_agent_not_found(self, monkeypatch):
        """When resolve_agent returns None, endpoint must raise 404."""
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: None)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.stop_agent_endpoint("nonexistent-agent")

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_stop_agent_returns_500_on_lifecycle_error(self, monkeypatch):
        """LifecycleError must be caught and returned as 500 with detail."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_stop_agent(hostname_arg, claw_name_arg, agent_name=None, timeout=30):
            raise LifecycleError("Agent not running")

        monkeypatch.setattr(fleet_mod, "stop_agent", mock_stop_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.stop_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 500
        # (#714) LifecycleError now returns a constant message
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "Agent not running" not in exc_info.value.detail

    @pytest.mark.anyio
    async def test_stop_agent_returns_500_on_unexpected_error(self, monkeypatch):
        """Unexpected exceptions must be caught, logged, and returned as 500."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_stop_agent(hostname_arg, claw_name_arg, agent_name=None, timeout=30):
            raise ValueError("Bad value")

        monkeypatch.setattr(fleet_mod, "stop_agent", mock_stop_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.stop_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR

    @pytest.mark.anyio
    async def test_stop_agent_returns_502_when_success_false(self, monkeypatch):
        """When lifecycle returns success=False, endpoint must raise HTTP 502."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_stop_agent(hostname_arg, claw_name_arg, agent_name=None, timeout=30):
            return {
                "success": False,
                "error": "Agent not running",
                "agent": agent_key,
                "host": hostname,
                "operation": "stop",
            }

        monkeypatch.setattr(fleet_mod, "stop_agent", mock_stop_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.stop_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 502
        # (#714) constant message, never raw error text
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "Agent not running" not in exc_info.value.detail

    @pytest.mark.anyio
    async def test_stop_agent_success_false_no_path_leak(self, monkeypatch):
        """(#714) Error strings with filesystem paths must not reach the browser on the 502 path."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_stop_agent(hostname_arg, claw_name_arg, agent_name=None, timeout=30):
            return {
                "success": False,
                "error": "failed at /home/user/.config/clawrium/hosts.json",
            }

        monkeypatch.setattr(fleet_mod, "stop_agent", mock_stop_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.stop_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 502
        # (#714) constant message, never raw error text
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "/home/user/.config" not in exc_info.value.detail


class TestRestartAgentEndpoint:
    """Tests for POST /api/agents/{agent_key}/restart."""

    @pytest.mark.anyio
    async def test_restart_agent_calls_lifecycle_with_correct_args(self, monkeypatch):
        """restart_agent_endpoint must pass (hostname, agent_type, agent_name=agent_key)."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        captured_args = {}

        def mock_restart_agent(hostname_arg, claw_name_arg, agent_name=None):
            captured_args["hostname"] = hostname_arg
            captured_args["claw_name"] = claw_name_arg
            captured_args["agent_name"] = agent_name
            return {
                "success": True,
                "agent": agent_key,
                "host": hostname,
                "operation": "restart",
                "pid": None,
                "started_at": None,
                "error": None,
            }

        monkeypatch.setattr(fleet_mod, "restart_agent", mock_restart_agent)

        result = await fleet_mod.restart_agent_endpoint(agent_key)

        assert result["success"] is True
        assert result["operation"] == "restart"
        assert result["agent"] == agent_key
        assert captured_args["hostname"] == hostname
        assert captured_args["claw_name"] == agent_type
        assert captured_args["agent_name"] == agent_key

    @pytest.mark.anyio
    async def test_restart_agent_returns_500_on_lifecycle_error(self, monkeypatch):
        """LifecycleError must be caught and returned as 500 with detail."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_restart_agent(hostname_arg, claw_name_arg, agent_name=None):
            raise LifecycleError("Stop failed: timeout")

        monkeypatch.setattr(fleet_mod, "restart_agent", mock_restart_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.restart_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 500
        # (#714) LifecycleError now returns a constant message
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "Stop failed" not in exc_info.value.detail

    @pytest.mark.anyio
    async def test_restart_agent_returns_500_on_unexpected_error(self, monkeypatch):
        """Unexpected exceptions must be caught, logged, and returned as 500.

        This is the exact failure mode from issue #459: before the fix,
        wrong argument order caused a bare 500 with no detail because the
        exception was not LifecycleError and fell through silently.
        """
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_restart_agent(hostname_arg, claw_name_arg, agent_name=None):
            raise RuntimeError("Unexpected error during restart")

        monkeypatch.setattr(fleet_mod, "restart_agent", mock_restart_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.restart_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR

    @pytest.mark.anyio
    async def test_restart_agent_returns_404_when_agent_not_found(self, monkeypatch):
        """When resolve_agent returns None, endpoint must raise 404."""
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: None)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.restart_agent_endpoint("nonexistent-agent")

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_restart_agent_returns_502_when_success_false(self, monkeypatch):
        """When lifecycle returns success=False, endpoint must raise HTTP 502."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_restart_agent(hostname_arg, claw_name_arg, agent_name=None):
            return {
                "success": False,
                "error": "Stop failed: timeout",
                "agent": agent_key,
                "host": hostname,
                "operation": "restart",
            }

        monkeypatch.setattr(fleet_mod, "restart_agent", mock_restart_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.restart_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 502
        # (#714) constant message, never raw error text
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "Stop failed" not in exc_info.value.detail

    @pytest.mark.anyio
    async def test_restart_agent_success_false_no_path_leak(self, monkeypatch):
        """(#714) Error strings with filesystem paths must not reach the browser on the 502 path."""
        agent_key = "test-agent"
        hostname = "192.168.1.100"
        agent_type = "zeroclaw"

        mock_resolved = (
            {"hostname": hostname, "user": "xclm"},
            agent_type,
            {"type": agent_type},
        )
        monkeypatch.setattr(fleet_mod, "resolve_agent", lambda _key: mock_resolved)

        def mock_restart_agent(hostname_arg, claw_name_arg, agent_name=None):
            return {
                "success": False,
                "error": "failed at /home/user/.config/clawrium/restart.log",
            }

        monkeypatch.setattr(fleet_mod, "restart_agent", mock_restart_agent)

        with pytest.raises(HTTPException) as exc_info:
            await fleet_mod.restart_agent_endpoint(agent_key)

        assert exc_info.value.status_code == 502
        # (#714) constant message, never raw error text
        assert exc_info.value.detail == fleet_mod._LIFECYCLE_GENERIC_ERROR
        assert "/home/user/.config" not in exc_info.value.detail
        assert "restart.log" not in exc_info.value.detail

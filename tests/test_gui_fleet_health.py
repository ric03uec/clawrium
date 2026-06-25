"""Tests for issue #410: local-only fleet data and health endpoint separation.

Validates that:
1. get_fleet_data_local() returns agents with CHECKING status (no SSH)
2. GET /api/fleet uses local-only data
3. GET /api/fleet/health uses full health checks
4. ClawStatus.CHECKING enum value exists
"""

import asyncio
import json
from unittest.mock import patch

from clawrium.cli.tui.data import get_fleet_data_local
from clawrium.core.health import ClawStatus
from clawrium.gui.routes import fleet as fleet_mod


class TestClawStatusChecking:
    """Verify the CHECKING enum value exists and serializes correctly."""

    def test_checking_status_exists(self):
        assert ClawStatus.CHECKING == "checking"
        assert ClawStatus.CHECKING.value == "checking"

    def test_checking_is_string_enum(self):
        assert isinstance(ClawStatus.CHECKING, str)


class TestGetFleetDataLocal:
    """Test the fast local-only fleet data function."""

    def test_empty_hosts(self, isolated_config):
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / "hosts.json").write_text("[]")

        agents, summary = get_fleet_data_local()
        assert agents == []
        assert summary["total"] == 0
        assert summary["running"] == 0
        assert summary["hosts"] == 0

    def test_agent_without_onboarding_gets_checking_status(self, isolated_config):
        """Agent with no onboarding record (legacy) gets CHECKING status."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "testhost",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "version": "1.0.0",
                        "agent_name": "opc-testhost",
                        "config": {"provider": {"default_model": "gpt-4o"}},
                        "onboarding": {"state": "ready"},
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        agents, summary = get_fleet_data_local()
        assert len(agents) == 1
        assert agents[0]["status"] == ClawStatus.CHECKING
        assert agents[0]["process_running"] is None
        assert agents[0]["health_error"] is None
        assert agents[0]["cpu_count"] is None
        assert agents[0]["memory_total_mb"] is None

    def test_onboarding_agent_gets_real_status(self, isolated_config):
        """Agent in onboarding state gets its actual status, not CHECKING."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "testhost",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "version": "1.0.0",
                        "agent_name": "opc-testhost",
                        "config": {},
                        "onboarding": {"state": "pending"},
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        agents, summary = get_fleet_data_local()
        assert len(agents) == 1
        assert agents[0]["status"] == ClawStatus.PENDING_ONBOARD
        assert summary["provisioning"] == 1

    def test_onboarding_in_progress_gets_real_status(self, isolated_config):
        """Agent actively onboarding gets ONBOARDING status."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "testhost",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "version": "1.0.0",
                        "agent_name": "opc-testhost",
                        "config": {},
                        "onboarding": {"state": "install"},
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        agents, summary = get_fleet_data_local()
        assert len(agents) == 1
        assert agents[0]["status"] == ClawStatus.ONBOARDING
        assert summary["provisioning"] == 1

    def test_no_ssh_calls_made(self, isolated_config):
        """get_fleet_data_local must NOT invoke any SSH health checks."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "testhost",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "version": "1.0.0",
                        "config": {},
                        "onboarding": {"state": "ready"},
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        with patch("clawrium.cli.tui.data.check_claw_health") as mock_health:
            get_fleet_data_local()
            mock_health.assert_not_called()

    def test_host_filter_works(self, isolated_config):
        """Host filter should restrict results."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "host1",
                "alias": "alpha",
                "agents": {
                    "agent1": {
                        "type": "openclaw",
                        "version": "1.0.0",
                        "config": {},
                        "onboarding": {"state": "ready"},
                    }
                },
            },
            {
                "hostname": "host2",
                "alias": "beta",
                "agents": {
                    "agent2": {
                        "type": "openclaw",
                        "version": "1.0.0",
                        "config": {},
                        "onboarding": {"state": "ready"},
                    }
                },
            },
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        agents, summary = get_fleet_data_local(host_filter="host1")
        assert len(agents) == 1
        assert agents[0]["agent_key"] == "agent1"
        assert summary["hosts"] == 1

    def test_running_count_is_zero(self, isolated_config):
        """Running count should always be 0 since we can't confirm without SSH."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "testhost",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "version": "1.0.0",
                        "config": {},
                        "onboarding": {"state": "ready"},
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        _, summary = get_fleet_data_local()
        assert summary["running"] == 0

    def test_local_fields_populated(self, isolated_config):
        """Local fields (model, provider, gateway, uptime) should be present.

        Post-#790 the provider/model are resolved from the tier-1
        attachment list + providers.json — not from the stale
        ``config.provider`` mirror — so this fixture seeds both files.
        """
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "testhost",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "version": "2.1.0",
                        "agent_name": "my-agent",
                        "providers": [{"name": "my-provider"}],
                        "config": {
                            "gateway": {"port": 8080},
                        },
                        "onboarding": {"state": "ready"},
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))
        (isolated_config / "providers.json").write_text(
            json.dumps(
                [
                    {
                        "name": "my-provider",
                        "type": "bedrock",
                        "default_model": "claude-3",
                    }
                ]
            )
        )

        agents, _ = get_fleet_data_local()
        agent = agents[0]
        assert agent["agent_name"] == "my-agent"
        assert agent["model"] == "claude-3"
        assert agent["provider"] == "my-provider"
        assert agent["provider_type"] == "bedrock"
        assert agent["gateway_port"] == 8080
        assert agent["version"] == "2.1.0"


class TestFleetEndpointUsesLocalData:
    """Verify GET /api/fleet now uses get_fleet_data_local."""

    def test_fleet_overview_calls_local(self, monkeypatch):
        """The fleet overview endpoint should call get_fleet_data_local."""
        called_with = {}
        ssh_called = {"value": False}

        def mock_local(host_filter):
            called_with["host_filter"] = host_filter
            return [], {"total": 0, "running": 0, "provisioning": 0, "hosts": 0}

        def mock_ssh(host_filter):  # pragma: no cover - must not be called
            ssh_called["value"] = True
            return [], {"total": 0, "running": 0, "provisioning": 0, "hosts": 0}

        monkeypatch.setattr(fleet_mod, "get_fleet_data_local", mock_local)
        monkeypatch.setattr(fleet_mod, "get_fleet_data", mock_ssh)

        result = asyncio.run(fleet_mod.fleet_overview(host=None))
        assert "host_filter" in called_with
        assert called_with["host_filter"] is None
        assert result["summary"]["total"] == 0
        # The optimistic-render path must never hit SSH.
        assert ssh_called["value"] is False

    def test_fleet_overview_serializes_checking_status(self, monkeypatch):
        """ClawStatus.CHECKING should serialize as 'checking' over the wire."""
        from clawrium.core.health import ClawStatus

        def mock_local(host_filter):
            agents = [
                {
                    "agent_key": "a1",
                    "agent_name": "a1",
                    "agent_type": "openclaw",
                    "host": "h1",
                    "host_alias": "h1",
                    "version": "v",
                    "status": ClawStatus.CHECKING,
                    "model": "m",
                    "uptime": "1m",
                    "missing_secrets": None,
                    "onboarding_step": "",
                    "process_running": None,
                    "health_error": None,
                    "addresses": [],
                    "provider": None,
                    "provider_type": None,
                    "cpu_count": None,
                    "memory_total_mb": None,
                    "gateway_port": None,
                    "gateway_url": None,
                    "gateway_auth": None,
                    "device_id": None,
                }
            ]
            return agents, {
                "total": 1,
                "running": 0,
                "provisioning": 0,
                "hosts": 1,
            }

        monkeypatch.setattr(fleet_mod, "get_fleet_data_local", mock_local)

        result = asyncio.run(fleet_mod.fleet_overview(host=None))
        assert result["agents"][0]["status"] == "checking"


class TestFleetHealthEndpoint:
    """Verify GET /api/fleet/health calls full health checks."""

    def test_health_endpoint_calls_get_fleet_data(self, monkeypatch):
        """The health endpoint should call the full get_fleet_data (with SSH)."""
        agents = [
            {
                "agent_key": "openclaw",
                "agent_name": "openclaw",
                "agent_type": "openclaw",
                "host": "192.168.1.100",
                "host_alias": "testhost",
                "version": "1.0.0",
                "status": ClawStatus.RUNNING,
                "model": "gpt-4o",
                "uptime": "1h",
                "missing_secrets": None,
                "onboarding_step": None,
                "process_running": True,
                "health_error": None,
                "addresses": [],
                "provider": "openai",
                "provider_type": "openai",
                "cpu_count": 8,
                "memory_total_mb": 16384,
                "gateway_port": None,
                "gateway_url": None,
                "gateway_auth": None,
                "device_id": None,
                "device_private_key": None,
            }
        ]
        summary = {"total": 1, "running": 1, "provisioning": 0, "hosts": 1}

        monkeypatch.setattr(
            fleet_mod, "get_fleet_data", lambda _host: (agents, summary)
        )

        result = asyncio.run(fleet_mod.fleet_health(host=None))
        assert result["summary"]["running"] == 1
        assert len(result["agents"]) == 1
        assert result["agents"][0]["status"] == "running"
        assert result["agents"][0]["process_running"] is True
        assert result["agents"][0]["cpu_count"] == 8
        assert result["agents"][0]["memory_total_mb"] == 16384

    def test_health_endpoint_returns_checking_fields(self, monkeypatch):
        """Health response includes only health-relevant fields."""
        agents = [
            {
                "agent_key": "openclaw",
                "agent_name": "openclaw",
                "agent_type": "openclaw",
                "host": "192.168.1.100",
                "host_alias": "testhost",
                "version": "1.0.0",
                "status": ClawStatus.STOPPED,
                "model": "gpt-4o",
                "uptime": "0m",
                "missing_secrets": ["OPENAI_API_KEY"],
                "onboarding_step": None,
                "process_running": False,
                "health_error": "Connection refused",
                "addresses": [],
                "provider": "openai",
                "provider_type": "openai",
                "cpu_count": None,
                "memory_total_mb": None,
                "gateway_port": None,
                "gateway_url": None,
                "gateway_auth": None,
                "device_id": None,
                "device_private_key": None,
            }
        ]
        summary = {"total": 1, "running": 0, "provisioning": 0, "hosts": 1}

        monkeypatch.setattr(
            fleet_mod, "get_fleet_data", lambda _host: (agents, summary)
        )

        result = asyncio.run(fleet_mod.fleet_health(host=None))
        agent_health = result["agents"][0]
        assert agent_health["status"] == "stopped"
        assert agent_health["health_error"] == "Connection refused"
        assert agent_health["missing_secrets"] == ["OPENAI_API_KEY"]
        # Verify non-health fields are NOT in the response
        assert "model" not in agent_health
        assert "uptime" not in agent_health
        assert "host_alias" not in agent_health


class TestSanitizeHealthError:
    """The /fleet/health wire response must strip filesystem paths."""

    def test_strips_absolute_path_from_health_error(self, monkeypatch):
        from clawrium.gui.routes.fleet import _sanitize_health_error

        msg = "Secrets file corrupted: /home/devashish/.config/clawrium/secrets.json is not a dict"
        sanitized = _sanitize_health_error(msg)
        assert "/home/devashish" not in sanitized
        assert "<path>" in sanitized

    def test_none_and_empty_pass_through(self):
        from clawrium.gui.routes.fleet import _sanitize_health_error

        assert _sanitize_health_error(None) is None
        assert _sanitize_health_error("") == ""

    def test_strips_path_in_fleet_health_response(self, monkeypatch):
        agents = [
            {
                "agent_key": "openclaw",
                "agent_name": "openclaw",
                "agent_type": "openclaw",
                "host": "192.168.1.100",
                "host_alias": "testhost",
                "version": "1.0.0",
                "status": ClawStatus.DEGRADED,
                "model": "gpt-4o",
                "uptime": "1h",
                "missing_secrets": None,
                "onboarding_step": None,
                "process_running": True,
                "health_error": "Secrets file corrupted: /home/devashish/.config/clawrium/secrets.json",
                "addresses": [],
                "provider": "openai",
                "provider_type": "openai",
                "cpu_count": 8,
                "memory_total_mb": 16384,
                "gateway_port": None,
                "gateway_url": None,
                "gateway_auth": None,
                "device_id": None,
                "device_private_key": None,
            }
        ]
        summary = {"total": 1, "running": 0, "provisioning": 0, "hosts": 1}

        monkeypatch.setattr(
            fleet_mod, "get_fleet_data", lambda _host: (agents, summary)
        )

        result = asyncio.run(fleet_mod.fleet_health(host=None))
        assert "/home/devashish" not in result["agents"][0]["health_error"]
        assert "<path>" in result["agents"][0]["health_error"]

"""Tests for TUI data transformation layer."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch


from clawrium.cli.tui.data import (
    calculate_uptime,
    get_fleet_data,
    get_agent_detail,
    load_hosts_safe,
    check_claw_health_safe,
)
from clawrium.core.health import ClawStatus


class TestCalculateUptime:
    def test_none_returns_dash(self):
        assert calculate_uptime(None) == "-"

    def test_valid_iso_timestamp(self):
        now = datetime.now(timezone.utc) - timedelta(days=2, hours=5, minutes=30)
        result = calculate_uptime(now.isoformat())
        assert "2d" in result
        assert "5h" in result
        assert "30m" in result

    def test_zero_duration(self):
        now = datetime.now(timezone.utc)
        result = calculate_uptime(now.isoformat())
        assert result == "0m"

    def test_only_minutes(self):
        now = datetime.now(timezone.utc) - timedelta(minutes=45)
        result = calculate_uptime(now.isoformat())
        assert result == "45m"

    def test_only_hours(self):
        now = datetime.now(timezone.utc) - timedelta(hours=3)
        result = calculate_uptime(now.isoformat())
        assert "3h" in result

    def test_invalid_timestamp(self):
        result = calculate_uptime("not-a-date")
        assert result == "-"

    def test_naive_timestamp_treated_as_utc(self):
        now = datetime.now(timezone.utc) - timedelta(hours=1)
        naive = now.replace(tzinfo=None)
        result = calculate_uptime(naive.isoformat())
        assert "1h" in result


class TestLoadHostsSafe:
    def test_returns_empty_on_corrupted(self, isolated_config):
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / "hosts.json").write_text("not json")
        assert load_hosts_safe() == []

    def test_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert load_hosts_safe() == []

    def test_returns_hosts(self, isolated_config):
        import json

        hosts = [{"hostname": "10.0.0.1", "alias": "test"}]
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))
        result = load_hosts_safe()
        assert len(result) == 1


class TestCheckClawHealthSafe:
    def test_returns_unknown_on_exception(self):
        host = {"hostname": "10.0.0.1"}
        with patch(
            "clawrium.cli.tui.data.check_claw_health", side_effect=Exception("boom")
        ):
            result = check_claw_health_safe("openclaw", host)
        assert result["status"] == ClawStatus.UNKNOWN
        assert "boom" in result["error"]


class TestGetFleetData:
    def test_empty_hosts(self, isolated_config):
        isolated_config.mkdir(parents=True, exist_ok=True)

        (isolated_config / "hosts.json").write_text("[]")
        agents, summary = get_fleet_data()
        assert agents == []
        assert summary["total"] == 0
        assert summary["hosts"] == 0

    def test_with_agents(self, isolated_config):
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "testhost",
                "port": 22,
                "agents": {
                    "openclaw": {
                        "version": "0.1.0",
                        "status": "installed",
                        "agent_name": "opc-testhost",
                        "type": "openclaw",
                        "config": {"provider": {"default_model": "gpt-4o"}},
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        mock_result = {
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "user": None,
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, summary = get_fleet_data()

        assert len(agents) == 1
        assert agents[0]["agent_name"] == "opc-testhost"
        assert agents[0]["status"] == ClawStatus.RUNNING
        assert agents[0]["model"] == "gpt-4o"
        assert summary["total"] == 1
        assert summary["running"] == 1
        assert summary["hosts"] == 1

    def test_host_filter(self, isolated_config):
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {"hostname": "192.168.1.100", "alias": "host1", "agents": {}},
            {"hostname": "192.168.1.101", "alias": "host2", "agents": {}},
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        _, summary = get_fleet_data(host_filter="host1")
        assert summary["hosts"] == 1

    def test_provisioning_count(self, isolated_config):
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "testhost",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "agent_name": "opc-test",
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        mock_result = {
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.ONBOARDING,
            "user": None,
            "error": None,
            "missing_secrets": None,
            "onboarding_step": "2/4",
            "process_running": False,
            "onboarding_stages": None,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            _, summary = get_fleet_data()

        assert summary["provisioning"] == 1

    def test_missing_model_shows_dash(self, isolated_config):
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "zeroclaw": {
                        "type": "zeroclaw",
                        "agent_name": "zc-test",
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        mock_result = {
            "agent": "zeroclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "user": None,
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["model"] == "-"


class TestGetAgentDetail:
    def test_found(self, isolated_config):
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "alias": "myhost",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "agent_name": "opc-test",
                        "version": "1.0.0",
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        mock_result = {
            "agent": "openclaw",
            "host": "192.168.1.100",
            "status": ClawStatus.RUNNING,
            "user": None,
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            detail = get_agent_detail("openclaw", "192.168.1.100")

        assert detail is not None
        assert detail["agent_key"] == "openclaw"
        assert detail["version"] == "1.0.0"

    def test_not_found(self, isolated_config):
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / "hosts.json").write_text("[]")
        result = get_agent_detail("nonexistent", "nohost")
        assert result is None

    def test_invalid_agent_key_rejected(self):
        result = get_agent_detail("../../../etc/passwd", "somehost")
        assert result is None

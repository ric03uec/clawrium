"""Tests for TUI data transformation layer."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch


from clawrium.cli.tui.data import (
    _gateway_scheme,
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


class TestGatewayScheme:
    def test_stored_ws_returns_ws(self):
        assert _gateway_scheme("ws://192.168.1.36:40198") == "ws"

    def test_stored_wss_returns_wss(self):
        assert _gateway_scheme("wss://gateway.example.com:443") == "wss"

    def test_none_returns_default_ws(self):
        assert _gateway_scheme(None) == "ws"

    def test_empty_string_returns_default_ws(self):
        assert _gateway_scheme("") == "ws"

    def test_non_string_returns_default_ws(self):
        assert _gateway_scheme(12345) == "ws"

    def test_no_scheme_returns_default_ws(self):
        assert _gateway_scheme("192.168.1.36:40198") == "ws"

    def test_unsupported_scheme_returns_default_ws(self):
        assert _gateway_scheme("http://192.168.1.36:40198") == "ws"
        assert _gateway_scheme("https://gateway.example.com") == "ws"


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
            "cpu_count": 8,
            "memory_total_mb": 32768,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, summary = get_fleet_data()

        assert len(agents) == 1
        assert agents[0]["agent_name"] == "opc-testhost"
        assert agents[0]["status"] == ClawStatus.RUNNING
        assert agents[0]["model"] == "gpt-4o"
        assert agents[0]["cpu_count"] == 8
        assert agents[0]["memory_total_mb"] == 32768
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
            "cpu_count": None,
            "memory_total_mb": None,
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
            "cpu_count": 2,
            "memory_total_mb": 4096,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["model"] == "-"
        assert agents[0]["provider"] is None
        assert agents[0]["provider_type"] is None

    def test_provider_type_extracted_from_config(self, isolated_config):
        """Provider type should be extracted from config.provider.type."""
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
                        "config": {
                            "provider": {
                                "name": "my-openai",
                                "type": "openai",
                                "default_model": "gpt-4o",
                            }
                        },
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
            "cpu_count": 8,
            "memory_total_mb": 32768,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["provider"] == "my-openai"
        assert agents[0]["provider_type"] == "openai"
        assert agents[0]["model"] == "gpt-4o"

    def test_provider_name_fallback_to_type(self, isolated_config):
        """Provider name should fallback to type if name is not set."""
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "zeroclaw": {
                        "type": "zeroclaw",
                        "agent_name": "zc-test",
                        "config": {"provider": {"type": "anthropic"}},
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
            "cpu_count": 2,
            "memory_total_mb": 4096,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        # provider fallbacks to type when name is not set
        assert agents[0]["provider"] == "anthropic"
        assert agents[0]["provider_type"] == "anthropic"

    def test_gateway_port_extracted_from_config(self, isolated_config):
        """Gateway port should be extracted from config.gateway.port."""
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
                        "config": {
                            "gateway": {"port": 40123},
                        },
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
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["gateway_port"] == 40123

    def test_gateway_port_none_when_not_configured(self, isolated_config):
        """Gateway port should be None when not configured."""
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
            "cpu_count": 2,
            "memory_total_mb": 4096,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["gateway_port"] is None

    def test_gateway_port_string_value_ignored(self, isolated_config):
        """String port value should be ignored (type validation)."""
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "agent_name": "opc-test",
                        "config": {
                            "gateway": {"port": "40123"},  # String instead of int
                        },
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
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        # String port value should be rejected, resulting in None
        assert agents[0]["gateway_port"] is None

    def test_gateway_port_empty_gateway_config(self, isolated_config):
        """Empty gateway config should result in None port."""
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "agent_name": "opc-test",
                        "config": {
                            "gateway": {},  # Empty gateway config
                        },
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
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["gateway_port"] is None

    def test_gateway_url_preserves_stored_ws_scheme(self, isolated_config):
        """Gateway URL should preserve ws:// from stored config (matches CLI)."""
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "agent_name": "opc-test",
                        "config": {
                            "gateway": {
                                "port": 40123,
                                "url": "ws://192.168.1.100:40123",
                            },
                        },
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
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["gateway_url"] == "ws://192.168.1.100:40123"

    def test_gateway_url_preserves_stored_wss_scheme(self, isolated_config):
        """Gateway URL should preserve wss:// from stored config."""
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "gateway.example.com",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "agent_name": "opc-test",
                        "config": {
                            "gateway": {
                                "port": 443,
                                "url": "wss://gateway.example.com:443",
                            },
                        },
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        mock_result = {
            "agent": "openclaw",
            "host": "gateway.example.com",
            "status": ClawStatus.RUNNING,
            "user": None,
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["gateway_url"] == "wss://gateway.example.com:443"

    def test_gateway_url_defaults_to_ws_when_no_stored_url(self, isolated_config):
        """Gateway URL falls back to ws:// when stored URL is missing."""
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "agent_name": "opc-test",
                        "config": {
                            "gateway": {"port": 40123},
                        },
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
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            agents, _ = get_fleet_data()

        assert agents[0]["gateway_url"] == "ws://192.168.1.100:40123"


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
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            detail = get_agent_detail("openclaw", "192.168.1.100")

        assert detail is not None
        assert detail["agent_key"] == "openclaw"
        assert detail["version"] == "1.0.0"
        assert detail["cpu_count"] == 4
        assert detail["memory_total_mb"] == 8192

    def test_not_found(self, isolated_config):
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / "hosts.json").write_text("[]")
        result = get_agent_detail("nonexistent", "nohost")
        assert result is None

    def test_invalid_agent_key_rejected(self):
        result = get_agent_detail("../../../etc/passwd", "somehost")
        assert result is None

    def test_gateway_port_extracted(self, isolated_config):
        """Gateway port should be extracted in get_agent_detail."""
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
                        "config": {
                            "gateway": {"port": 40456},
                        },
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
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            detail = get_agent_detail("openclaw", "192.168.1.100")

        assert detail is not None
        assert detail["gateway_port"] == 40456

    def test_gateway_url_preserves_stored_ws_scheme(self, isolated_config):
        """get_agent_detail should preserve ws:// from stored config."""
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
                        "config": {
                            "gateway": {
                                "port": 40456,
                                "url": "ws://192.168.1.100:40456",
                            },
                        },
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
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            detail = get_agent_detail("openclaw", "192.168.1.100")

        assert detail is not None
        assert detail["gateway_url"] == "ws://192.168.1.100:40456"

    def test_gateway_url_preserves_stored_wss_scheme(self, isolated_config):
        """get_agent_detail should preserve wss:// from stored config."""
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "gateway.example.com",
                "alias": "remote",
                "agents": {
                    "openclaw": {
                        "type": "openclaw",
                        "agent_name": "opc-test",
                        "version": "1.0.0",
                        "config": {
                            "gateway": {
                                "port": 443,
                                "url": "wss://gateway.example.com:443",
                            },
                        },
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))

        mock_result = {
            "agent": "openclaw",
            "host": "gateway.example.com",
            "status": ClawStatus.RUNNING,
            "user": None,
            "error": None,
            "missing_secrets": None,
            "onboarding_step": None,
            "process_running": True,
            "onboarding_stages": None,
            "cpu_count": 4,
            "memory_total_mb": 8192,
        }

        with patch("clawrium.cli.tui.data.check_claw_health", return_value=mock_result):
            detail = get_agent_detail("openclaw", "gateway.example.com")

        assert detail is not None
        assert detail["gateway_url"] == "wss://gateway.example.com:443"

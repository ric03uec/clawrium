"""Tests for TUI data transformation layer."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from clawrium.cli.tui.data import (
    _build_agent_identity,
    _gateway_scheme,
    _resolve_provider_display,
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
        # Generic label is surfaced; raw exception text is not leaked.
        assert result["error"] == "health probe failed"
        assert "boom" not in result["error"]

    def test_filenotfound_returns_generic_label(self):
        host = {"hostname": "10.0.0.1"}
        with patch(
            "clawrium.cli.tui.data.check_claw_health",
            side_effect=FileNotFoundError("/home/user/.config/clawrium/keys/secret"),
        ):
            result = check_claw_health_safe("openclaw", host)
        assert result["status"] == ClawStatus.UNKNOWN
        assert result["error"] == "ssh key or config not found"
        assert "/home/user" not in result["error"]


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
                        "providers": [{"name": "my-openai"}],
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))
        (isolated_config / "providers.json").write_text(
            json.dumps(
                [
                    {
                        "name": "my-openai",
                        "type": "openai",
                        "default_model": "gpt-4o",
                    }
                ]
            )
        )

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

    def test_provider_type_extracted_from_providers_json(self, isolated_config):
        """Provider type is sourced from providers.json (#790)."""
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
                        "providers": [{"name": "my-openai"}],
                    }
                },
            }
        ]
        (isolated_config / "hosts.json").write_text(json.dumps(hosts))
        (isolated_config / "providers.json").write_text(
            json.dumps(
                [
                    {
                        "name": "my-openai",
                        "type": "openai",
                        "default_model": "gpt-4o",
                    }
                ]
            )
        )

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

    def test_no_tier1_attachment_ignores_stale_tier2(self, isolated_config):
        """No tier-1 attachment + stale tier-2 mirror → all None/"-" (#790).

        The pre-#790 code path fell back to ``config.provider.type`` /
        ``config.provider.default_model`` when no tier-1 attachment
        existed. The fixture deliberately seeds a stale ``config.provider``
        mirror so the assertions fail if that fallback regresses.
        """
        import json

        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts = [
            {
                "hostname": "192.168.1.100",
                "agents": {
                    "zeroclaw": {
                        "type": "zeroclaw",
                        "agent_name": "zc-test",
                        "config": {
                            # Stale mirror from before the operator detached
                            # the provider. The new resolver must ignore it.
                            "provider": {
                                "name": "stale-anthropic",
                                "type": "anthropic",
                                "default_model": "claude-opus-4",
                            },
                        },
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

        assert agents[0]["provider"] is None
        assert agents[0]["provider_type"] is None
        assert agents[0]["model"] == "-"

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


class TestResolveProviderDisplay:
    """Unit tests for the tier-1 + providers.json display helper (#790)."""

    def test_resolve_provider_display_attachment_override(self):
        """Tier-1 entry ``model`` override wins over providers.json default."""
        claw_record = {
            "providers": [{"name": "openai-prod", "model": "gpt-4o-mini"}]
        }
        with patch(
            "clawrium.cli.tui.data.get_provider",
            return_value={
                "name": "openai-prod",
                "type": "openai",
                "default_model": "gpt-4o",
            },
        ):
            name, ptype, model = _resolve_provider_display(claw_record)
        assert name == "openai-prod"
        assert ptype == "openai"
        assert model == "gpt-4o-mini"

    def test_resolve_provider_display_falls_back_to_providers_json(self):
        """When the attachment lacks ``model``, default_model is used."""
        claw_record = {"providers": [{"name": "openai-prod"}]}
        with patch(
            "clawrium.cli.tui.data.get_provider",
            return_value={
                "name": "openai-prod",
                "type": "openai",
                "default_model": "gpt-4o",
            },
        ):
            name, ptype, model = _resolve_provider_display(claw_record)
        assert name == "openai-prod"
        assert ptype == "openai"
        assert model == "gpt-4o"

    def test_resolve_provider_display_missing_provider_record(self, caplog):
        """Unresolved tier-1 attachment → ("-", None, "-") + warning.

        The caplog assertion pins logger, level, and full message so the
        missing-record branch cannot be confused with the IO-error branch
        below — they emit distinct warnings.
        """
        import logging

        claw_record = {"providers": [{"name": "unregistered"}]}
        with patch("clawrium.cli.tui.data.get_provider", return_value=None):
            with caplog.at_level(logging.WARNING, logger="clawrium.cli.tui.data"):
                name, ptype, model = _resolve_provider_display(claw_record)
        assert (name, ptype, model) == ("-", None, "-")
        assert any(
            rec.name == "clawrium.cli.tui.data"
            and rec.levelno == logging.WARNING
            and "is not registered in providers.json" in rec.getMessage()
            and "unregistered" in rec.getMessage()
            for rec in caplog.records
        )

    def test_resolve_provider_display_get_provider_raises(self, caplog):
        """Storage IO error → ("-", None, "-") + distinct warning, no crash."""
        import logging

        claw_record = {"providers": [{"name": "openai-prod"}]}
        with patch(
            "clawrium.cli.tui.data.get_provider",
            side_effect=OSError("disk error"),
        ):
            with caplog.at_level(logging.WARNING, logger="clawrium.cli.tui.data"):
                name, ptype, model = _resolve_provider_display(claw_record)
        assert (name, ptype, model) == ("-", None, "-")
        assert any(
            rec.name == "clawrium.cli.tui.data"
            and rec.levelno == logging.WARNING
            and "Failed to look up provider" in rec.getMessage()
            and "openai-prod" in rec.getMessage()
            and "disk error" in rec.getMessage()
            for rec in caplog.records
        )

    def test_resolve_provider_display_no_attachment(self):
        """No tier-1 attachment → (None, None, "-")."""
        claw_record: dict = {}
        name, ptype, model = _resolve_provider_display(claw_record)
        assert (name, ptype, model) == (None, None, "-")

    def test_resolve_provider_display_record_missing_type(self):
        """providers.json entry without ``type`` → provider_type is None."""
        claw_record = {"providers": [{"name": "p"}]}
        with patch(
            "clawrium.cli.tui.data.get_provider",
            return_value={"name": "p", "default_model": "m"},
        ):
            name, ptype, model = _resolve_provider_display(claw_record)
        assert (name, ptype, model) == ("p", None, "m")

    def test_resolve_provider_display_record_missing_default_model(self):
        """Attached but no model anywhere → model is "-"."""
        claw_record = {"providers": [{"name": "p"}]}
        with patch(
            "clawrium.cli.tui.data.get_provider",
            return_value={"name": "p", "type": "openai"},
        ):
            name, ptype, model = _resolve_provider_display(claw_record)
        assert (name, ptype, model) == ("p", "openai", "-")

    @pytest.mark.parametrize(
        "bad_name",
        ["1leading", "Bad-Name!", "has space", "", "ALLCAPS"],
    )
    def test_resolve_provider_display_invalid_name_rejected(self, bad_name):
        """Attachment names that fail the regex → silent (None, None, "-").

        get_provider must NOT be called for an invalid name. This branch
        is distinguishable from the missing-record branch because no
        warning is logged.
        """
        claw_record = {"providers": [{"name": bad_name}]}
        called = {"value": False}

        def fake_get_provider(_):
            called["value"] = True
            return None

        with patch(
            "clawrium.cli.tui.data.get_provider", side_effect=fake_get_provider
        ):
            name, ptype, model = _resolve_provider_display(claw_record)
        assert (name, ptype, model) == (None, None, "-")
        assert called["value"] is False

    @pytest.mark.parametrize("garbage", [42, None, ["nested"], 3.14])
    def test_resolve_provider_display_garbage_entry(self, garbage):
        """Non-dict / non-str first attachment entry → (None, None, "-")."""
        claw_record = {"providers": [garbage]}
        name, ptype, model = _resolve_provider_display(claw_record)
        assert (name, ptype, model) == (None, None, "-")

    def test_resolve_provider_display_ignores_tier2_provider(self):
        """A leftover ``config.provider`` mirror is NEVER consulted (#790)."""
        claw_record = {
            "providers": [{"name": "glm51"}],
            "config": {
                "provider": {
                    "name": "openai-prod",
                    "type": "openai",
                    "default_model": "openai/gpt-4o",
                }
            },
        }
        with patch(
            "clawrium.cli.tui.data.get_provider",
            return_value={
                "name": "glm51",
                "type": "litellm",
                "default_model": "z-ai/glm-5.1",
            },
        ):
            name, ptype, model = _resolve_provider_display(claw_record)
        assert name == "glm51"
        assert ptype == "litellm"
        assert model == "z-ai/glm-5.1"


class TestBuildAgentIdentityRegression:
    """Regression coverage for the original #790 bug.

    The GUI agent landing page (and ``clawctl agent get``) were reading
    the model from the stale ``config.provider.default_model`` mirror in
    ``hosts.json`` instead of the live tier-1 attachment + providers.json.
    After a provider swap that the user had not yet ``sync``'d, the
    operator saw the old model. Keep this test forever — it is the gate.
    """

    def test_build_agent_identity_ignores_stale_tier2_provider(self):
        """Tier-1 = glm51, tier-2 leftover = openai/gpt-4o → glm-5.1 wins."""
        host = {
            "hostname": "192.168.1.100",
            "alias": "wolf-i",
            "addresses": [],
        }
        claw_record = {
            "type": "openclaw",
            "agent_name": "clawrium-exec",
            "version": "1.0.0",
            "providers": [{"name": "glm51"}],
            "config": {
                # Pre-#790 lifecycle.sync_agent mirror — must be ignored.
                "provider": {
                    "name": "openai-prod",
                    "type": "openai",
                    "default_model": "openai/gpt-4o",
                },
            },
        }
        with patch(
            "clawrium.cli.tui.data.get_provider",
            return_value={
                "name": "glm51",
                "type": "litellm",
                "default_model": "z-ai/glm-5.1",
            },
        ):
            identity = _build_agent_identity("clawrium-exec", host, claw_record)

        assert identity["provider"] == "glm51"
        assert identity["provider_type"] == "litellm"
        assert identity["model"] == "z-ai/glm-5.1"

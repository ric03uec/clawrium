"""Tests for configure_claw function."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from jinja2 import Environment, FileSystemLoader

from clawrium.core.lifecycle import configure_agent, LifecycleError


class TestConfigureClaw:
    """Tests for configure_claw function."""

    def test_raises_error_when_host_not_found(self):
        """Test that LifecycleError is raised when host doesn't exist."""
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                configure_agent("nonexistent", "zeroclaw", {})

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self):
        """Test that LifecycleError is raised when claw not installed."""
        host = {"hostname": "test-host", "agents": {}}

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                configure_agent("test-host", "zeroclaw", {})

        assert "not installed" in str(exc_info.value)

    def test_returns_false_when_invalid_model_name(self):
        """Test that invalid Ollama model names are rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        config_data = {
            "provider": {
                "name": "test-provider",
                "type": "ollama",
                "default_model": "malicious\nINJECTED=value",
            }
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent("test-host", "zeroclaw", config_data)

        assert success is False
        assert "Invalid model name" in error

    def test_returns_false_when_update_host_fails_after_ansible(self, tmp_path: Path):
        """Test that failure to update hosts.json after Ansible is handled."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        # Issue #357: configure_agent reads pairing token + gateway URL out
        # of the Ansible fact cache for zeroclaw. Set up a fact file so the
        # extraction succeeds and the failure path under test (update_host
        # returning False) is what surfaces — not the new fact-missing
        # fail-fast path.
        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        (fact_cache_dir / "test-host").write_text(
            json.dumps(
                {
                    "__payload__": json.dumps(
                        {
                            "zeroclaw_gateway_token": "paired-bearer-token",
                            "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
                        }
                    ),
                }
            )
        )

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []
        mock_runner.config.artifact_dir = str(artifacts_dir)

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host", return_value=False
                        ):
                            success, error = configure_agent(
                                "test-host", "zeroclaw", config_data
                            )

        assert success is False
        assert "failed to update local state" in error

    def test_no_rotation_event_emitted_when_update_host_fails_with_prior_token(
        self, tmp_path: Path
    ):
        """ATX W-COV-3: when configure's hosts.json write fails AFTER
        the pair handshake minted a new token, the rotation event must
        NOT be emitted — that's the W2 ordering invariant. Without this
        test, moving the emit back before the write would silently
        regress."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "zer-test": {
                    "type": "zeroclaw",
                    "config": {
                        "gateway": {
                            "auth": "stable-prior-token-zzzzzzz",
                            "url": "ws://test-host:40000/ws/chat",
                        }
                    },
                }
            },
        }
        config_data = {
            "gateway": {"host": "0.0.0.0", "port": 40000, "allow_public_bind": True},
            "provider": {
                "name": "test-provider",
                "type": "anthropic",
                "default_model": "claude-sonnet-4-5",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        (fact_cache_dir / "test-host").write_text(
            json.dumps(
                {
                    "__payload__": json.dumps(
                        {
                            "zeroclaw_gateway_token": "freshly-minted-token-but-not-persisted",
                            "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
                        }
                    ),
                }
            )
        )

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []
        mock_runner.config.artifact_dir = str(artifacts_dir)

        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host",
                            return_value=False,
                        ):
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="",
                            ):
                                success, _ = configure_agent(
                                    "test-host",
                                    "zeroclaw",
                                    config_data,
                                    on_event=on_event,
                                )

        assert success is False
        rotation = [m for s, m in events if s == "gateway_token_rotated"]
        assert not rotation, (
            f"rotation event leaked despite update_host failure: {rotation!r}"
        )

    def test_returns_false_when_playbook_missing(self, tmp_path: Path):
        """Test that missing configure playbook is detected."""
        host = {
            "hostname": "test-host",
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path"
            ) as mock_playbook:
                mock_playbook.return_value = tmp_path / "nonexistent.yaml"

                success, error = configure_agent("test-host", "zeroclaw", config_data)

        assert success is False
        assert "playbook not found" in error

    def test_returns_false_when_ssh_key_missing(self, tmp_path: Path):
        """Test that missing SSH key is detected."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key", return_value=None
                ):
                    success, error = configure_agent(
                        "test-host", "zeroclaw", config_data
                    )

        assert success is False
        assert "SSH key not found" in error

    def test_returns_false_when_invalid_claw_user_format(self, tmp_path: Path):
        """Test that invalid agent_name format is detected."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {"Invalid User!": {"type": "zeroclaw"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    success, error = configure_agent(
                        "test-host", "zeroclaw", config_data, agent_name="Invalid User!"
                    )

        assert success is False
        assert "Invalid agent_name format" in error

    def test_returns_false_when_ansible_times_out(self, tmp_path: Path):
        """Test that Ansible timeout is handled."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "timeout"

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        success, error = configure_agent(
                            "test-host", "zeroclaw", config_data
                        )

        assert success is False
        assert "timed out" in error

    def test_returns_false_when_ansible_fails(self, tmp_path: Path):
        """Test that Ansible failure is handled and hosts.json is NOT updated."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "failed"
        mock_runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "Task failed"}},
            }
        ]

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
                            success, error = configure_agent(
                                "test-host", "zeroclaw", config_data
                            )

                            # Verify hosts.json was NOT updated since Ansible failed
                            mock_update.assert_not_called()

        assert success is False
        assert "Task failed" in error

    def test_happy_path_returns_true(self, tmp_path: Path):
        """Test successful configuration flow."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        config_data = {
            "gateway": {"host": "0.0.0.0", "port": 40000, "allow_public_bind": True},
            "provider": {
                "name": "test-provider",
                "type": "ollama",
                "endpoint": "http://localhost:11434",
                "default_model": "llama3",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        # Issue #357: configure_agent reads pairing token + gateway URL out
        # of the Ansible fact cache for zeroclaw. Set up a fact file so the
        # happy path can complete fact extraction.
        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        (fact_cache_dir / "test-host").write_text(
            json.dumps(
                {
                    "__payload__": json.dumps(
                        {
                            "zeroclaw_gateway_token": "paired-bearer-token",
                            "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
                        }
                    ),
                }
            )
        )

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []
        mock_runner.config.artifact_dir = str(artifacts_dir)

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="",
                            ):
                                mock_update.return_value = True
                                success, error = configure_agent(
                                    "test-host", "zeroclaw", config_data
                                )

                                # Verify hosts.json WAS updated after Ansible succeeded
                                mock_update.assert_called_once()

        assert success is True
        assert error is None


class TestConfigureZeroclawFactExtraction:
    """Coverage for the bearer-token fact-extraction path added by issue #357.

    `configure_agent()` reads `zeroclaw_gateway_token` + `zeroclaw_gateway_url`
    out of the Ansible fact cache after a successful configure run, and
    persists them to `hosts.json` under `agents.<n>.config.gateway`. These
    tests pin the happy path and the three failure modes ATX flagged as
    "zero test coverage" in Round 1 W1:

    1. Happy path: fact present, hosts.json updated with auth + url
    2. Fact cache absent (missing fact_cache_dir)
    3. __payload__ key missing
    4. Token empty after strip
    """

    HOST = {
        "hostname": "test-host",
        "key_id": "test",
        "agent_name": "xclm",
        "port": 22,
        "agents": {"zer-test": {"type": "zeroclaw"}},
    }
    CONFIG_DATA = {
        "gateway": {"host": "0.0.0.0", "port": 40000, "allow_public_bind": True},
        "provider": {
            "name": "test-provider",
            "type": "anthropic",
            "default_model": "claude-sonnet-4-5",
        },
    }

    def _setup_artifacts(self, tmp_path: Path, payload: dict | None) -> Path:
        """Create an artifacts dir with one fact file carrying `payload`."""
        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        if payload is not None:
            (fact_cache_dir / "test-host").write_text(
                json.dumps(
                    {
                        "__payload__": json.dumps(payload),
                    }
                )
            )
        return artifacts_dir

    def _run_configure(self, tmp_path: Path, artifacts_dir: Path):
        key_path = tmp_path / "key"
        key_path.write_text("key")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []
        mock_runner.config.artifact_dir = str(artifacts_dir)

        captured: dict[str, object] = {}

        def fake_update_host(_hostname, updater):
            # Pull the persisted record by running the updater against a
            # fresh host dict (mirrors update_host's contract — caller
            # gets to inspect what would be written).
            h = {"hostname": "test-host", "agents": {"zer-test": {"type": "zeroclaw"}}}
            captured["host"] = updater(h)
            return True

        with patch("clawrium.core.lifecycle.get_host", return_value=self.HOST):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host",
                            side_effect=fake_update_host,
                        ):
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="",
                            ):
                                success, error = configure_agent(
                                    "test-host", "zeroclaw", dict(self.CONFIG_DATA)
                                )
        return success, error, captured

    def test_happy_path_persists_token_and_url_to_hosts_json(self, tmp_path: Path):
        """Fact present → success → hosts.json carries the gateway block."""
        artifacts_dir = self._setup_artifacts(
            tmp_path,
            {
                "zeroclaw_gateway_token": "freshly-paired-bearer-token-1234",
                "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
            },
        )

        success, error, captured = self._run_configure(tmp_path, artifacts_dir)

        assert success is True, error
        agent_record = captured["host"]["agents"]["zer-test"]
        gateway = agent_record["config"]["gateway"]
        assert gateway["auth"] == "freshly-paired-bearer-token-1234"
        assert gateway["url"] == "ws://test-host:40000/ws/chat"

    def test_returns_false_when_fact_cache_dir_absent(self, tmp_path: Path):
        """No fact_cache directory → fail-fast with operator guidance."""
        # Create artifacts_dir without fact_cache.
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        success, error, _ = self._run_configure(tmp_path, artifacts_dir)

        assert success is False
        assert "pairing token was not captured" in error
        # Operator-visible remediation hint is non-empty.
        assert "clm agent configure" in error

    def test_returns_false_when_payload_key_missing(self, tmp_path: Path):
        """Fact file present but lacking __payload__ → fail-fast."""
        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        # Fact file with arbitrary content but no __payload__ envelope.
        (fact_cache_dir / "test-host").write_text(json.dumps({"other": "data"}))

        success, error, _ = self._run_configure(tmp_path, artifacts_dir)

        assert success is False
        assert "pairing token was not captured" in error
        # ATX Round 2 W10: every failure-mode test asserts the remediation
        # hint too, so a regression that drops the operator guidance can't
        # ship green.
        assert "clm agent configure" in error

    def test_returns_false_when_token_empty_after_strip(self, tmp_path: Path):
        """Whitespace-only token must be rejected — the eventual chat
        client would fail with an empty Bearer header, which is a worse
        error than failing fast here."""
        artifacts_dir = self._setup_artifacts(
            tmp_path,
            {
                "zeroclaw_gateway_token": "   ",
                "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
            },
        )

        success, error, _ = self._run_configure(tmp_path, artifacts_dir)

        assert success is False
        assert "pairing token was not captured" in error
        assert "clm agent configure" in error

    def test_returns_false_when_url_missing(self, tmp_path: Path):
        """Token present but URL missing → also fail-fast (the chat path
        needs both to construct a connection)."""
        artifacts_dir = self._setup_artifacts(
            tmp_path,
            {
                "zeroclaw_gateway_token": "paired-bearer-token-abc",
                # zeroclaw_gateway_url intentionally omitted
            },
        )

        success, error, _ = self._run_configure(tmp_path, artifacts_dir)

        assert success is False
        assert "pairing token was not captured" in error
        assert "clm agent configure" in error

    def test_no_health_warning_when_fact_absent(self, tmp_path: Path):
        """ATX Round 3 W10: when the playbook did NOT set
        zeroclaw_provider_health_warning (i.e. health 200), no warn
        event must fire. Without this negative test, code that
        unconditionally emits the warning would pass the suite."""
        artifacts_dir = self._setup_artifacts(
            tmp_path,
            {
                "zeroclaw_gateway_token": "freshly-paired-bearer-token-1234",
                "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
                # zeroclaw_provider_health_warning intentionally absent
            },
        )

        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        success, error, _ = self._run_configure_with_callback(
            tmp_path, artifacts_dir, on_event
        )

        assert success is True, error
        # ATX Round 4 B1: configure_warnings flow through stage="configure"
        # with a "WARNING:" prefix (matches the integration-warning
        # pattern at lifecycle.py:1046). Pure stage="warn" events were
        # dropped at the terminal by `_print_configure_warnings`.
        warn_events = [
            (s, m) for s, m in events if s == "configure" and m.startswith("WARNING:")
        ]
        assert not warn_events, f"Unexpected warn events: {warn_events!r}"

    def test_no_health_warning_when_fact_false(self, tmp_path: Path):
        """ATX Round 3 W1+W10: a healthy run (status 200) sets
        zeroclaw_provider_health_warning=False — the value MUST be
        respected and the warn event MUST NOT fire. Pre-fix, the
        unconditional-True set_fact left stale `True` in the fact cache,
        causing a phantom warning on healthy reconfigures."""
        artifacts_dir = self._setup_artifacts(
            tmp_path,
            {
                "zeroclaw_gateway_token": "freshly-paired-bearer-token-1234",
                "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
                "zeroclaw_provider_health_warning": False,
            },
        )

        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        success, error, _ = self._run_configure_with_callback(
            tmp_path, artifacts_dir, on_event
        )

        assert success is True, error
        warn_events = [
            (s, m) for s, m in events if s == "configure" and m.startswith("WARNING:")
        ]
        assert not warn_events, f"Unexpected warn events: {warn_events!r}"

    def _run_configure_with_callback(
        self, tmp_path: Path, artifacts_dir: Path, on_event
    ):
        """Variant of _run_configure that wires an on_event callback
        through to configure_agent. Used by the health-warning tests."""
        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []
        mock_runner.config.artifact_dir = str(artifacts_dir)

        with patch("clawrium.core.lifecycle.get_host", return_value=self.HOST):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="",
                            ):
                                success, error = configure_agent(
                                    "test-host",
                                    "zeroclaw",
                                    dict(self.CONFIG_DATA),
                                    on_event=on_event,
                                )
        return success, error, {}

    def test_provider_health_warning_surfaces_via_event_callback(self, tmp_path: Path):
        """ATX Round 2 W1: when the playbook records
        zeroclaw_provider_health_warning = True (set when /health/providers
        returns 401), configure_agent surfaces the warning via the
        on_event callback. Without this, the warning would be silently
        swallowed because `ansible_runner.run(quiet=True)` does not emit
        `runner_on_debug` events to the caller."""
        artifacts_dir = self._setup_artifacts(
            tmp_path,
            {
                "zeroclaw_gateway_token": "freshly-paired-bearer-token-1234",
                "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
                "zeroclaw_provider_health_warning": True,
            },
        )

        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []
        mock_runner.config.artifact_dir = str(artifacts_dir)

        with patch("clawrium.core.lifecycle.get_host", return_value=self.HOST):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="",
                            ):
                                success, error = configure_agent(
                                    "test-host",
                                    "zeroclaw",
                                    dict(self.CONFIG_DATA),
                                    on_event=on_event,
                                )

        assert success is True, error
        # ATX Round 4 B1: warnings flow through stage="configure" with
        # a "WARNING:" prefix so `_print_configure_warnings` actually
        # surfaces them to the user. A bare stage="warn" event would be
        # silently dropped at the terminal.
        warn_events = [
            (s, m) for s, m in events if s == "configure" and m.startswith("WARNING:")
        ]
        assert warn_events, f"Expected a WARNING: event; got {events!r}"
        warn_msg = warn_events[0][1]
        assert "401" in warn_msg
        assert "credentials may be invalid" in warn_msg

    def test_malformed_discord_secret_does_not_raise(self, tmp_path: Path):
        """ATX Round 3 W4: a malformed secrets.json entry (a dict that
        lacks the expected `value` field — e.g. only `created_at`)
        must silently produce an empty token rather than raise
        KeyError. Pre-fix, the bare `instance_secrets["..."]["value"]`
        indexing raised, was swallowed by `except Exception` → empty
        token, but the user got zero indication. Post-fix the same
        empty-token outcome holds AND the .get() guard makes the
        behavior intentional (not accidental)."""
        artifacts_dir = self._setup_artifacts(
            tmp_path,
            {
                "zeroclaw_gateway_token": "freshly-paired-bearer-token-1234",
                "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
            },
        )

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []
        mock_runner.config.artifact_dir = str(artifacts_dir)

        captured: dict[str, object] = {}

        def capture_run(*, inventory, **_kwargs):
            captured["inventory"] = inventory
            return mock_runner

        # Inject a malformed Discord secret: dict without "value".
        malformed_secrets = {
            "DISCORD_BOT_TOKEN": {"created_at": "2026-05-01T00:00:00Z"},
            "SLACK_BOT_TOKEN": {"corrupted": True},
            "SLACK_APP_TOKEN": "raw-string-not-a-dict",
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=self.HOST):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        side_effect=capture_run,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="",
                            ):
                                with patch(
                                    "clawrium.core.lifecycle.get_instance_secrets",
                                    return_value=malformed_secrets,
                                ):
                                    success, error = configure_agent(
                                        "test-host",
                                        "zeroclaw",
                                        dict(self.CONFIG_DATA),
                                    )

        assert success is True, error
        # All three token vars are empty — the W4 guard caught the
        # malformed shape, no KeyError surfaced.
        ansible_vars = captured["inventory"]["all"]["vars"]
        assert ansible_vars["discord_bot_token"] == ""
        assert ansible_vars["slack_bot_token"] == ""
        assert ansible_vars["slack_app_token"] == ""

    def test_value_wrapped_facts_are_unwrapped(self, tmp_path: Path):
        """Ansible occasionally wraps cacheable string facts in
        {"value": ...}. The extraction must tolerate both shapes."""
        artifacts_dir = self._setup_artifacts(
            tmp_path,
            {
                "zeroclaw_gateway_token": {"value": "wrapped-bearer-token-xyz"},
                "zeroclaw_gateway_url": {"value": "ws://test-host:40000/ws/chat"},
            },
        )

        success, error, captured = self._run_configure(tmp_path, artifacts_dir)

        assert success is True, error
        gateway = captured["host"]["agents"]["zer-test"]["config"]["gateway"]
        assert gateway["auth"] == "wrapped-bearer-token-xyz"


class TestConfigureZeroclawAlwaysRepair:
    """Issue #437: configure_agent for zeroclaw always mints a fresh
    bearer. The previous idempotent-skip path is gone — `existing_gateway_token`
    / `force_repair` are no longer plumbed through the inventory."""

    def _build_host_with_existing_token(self, token: str = "x" * 32) -> dict:
        return {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "zer-test": {
                    "type": "zeroclaw",
                    "config": {
                        "gateway": {
                            "auth": token,
                            "url": "ws://test-host:40000/ws/chat",
                        }
                    },
                }
            },
        }

    def _build_config(self) -> dict:
        return {
            "gateway": {"host": "0.0.0.0", "port": 40000, "allow_public_bind": True},
            "provider": {
                "name": "test-provider",
                "type": "anthropic",
                "default_model": "claude-sonnet-4-5",
            },
        }

    def _run_configure(
        self,
        host: dict,
        config_data: dict,
        tmp_path: Path,
        *,
        fact_token: str = "freshly-minted-token-1234567890",
        on_event=None,
        extra_vars=None,
    ):
        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        (fact_cache_dir / "test-host").write_text(
            json.dumps(
                {
                    "__payload__": json.dumps(
                        {
                            "zeroclaw_gateway_token": fact_token,
                            "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
                        }
                    ),
                }
            )
        )

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []
        mock_runner.config.artifact_dir = str(artifacts_dir)

        captured: dict = {}

        def capture_run(*, inventory, **_kwargs):
            captured["inventory"] = inventory
            return mock_runner

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        side_effect=capture_run,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="",
                            ):
                                success, error = configure_agent(
                                    "test-host",
                                    "zeroclaw",
                                    config_data,
                                    on_event=on_event,
                                    extra_vars=extra_vars,
                                )
        return success, error, captured

    def test_no_existing_gateway_token_in_inventory(self, tmp_path: Path):
        """`existing_gateway_token` and `force_repair` MUST NOT appear in
        the Ansible inventory. The playbook no longer reads them — leaving
        them in would be confusing and would let a stale skip-path sneak
        back in via extra_vars."""
        host = self._build_host_with_existing_token()
        success, error, captured = self._run_configure(
            host, self._build_config(), tmp_path
        )
        assert success is True, error
        ansible_vars = captured["inventory"]["all"]["vars"]
        assert "existing_gateway_token" not in ansible_vars
        assert "force_repair" not in ansible_vars

    def test_fresh_token_overwrites_existing_in_config_data(self, tmp_path: Path):
        """After configure runs, config_data['gateway']['auth'] must hold
        the fact-cache token, not the prior persisted one."""
        host = self._build_host_with_existing_token(token="old-token-" + "a" * 22)
        config_data = self._build_config()
        success, error, _ = self._run_configure(
            host,
            config_data,
            tmp_path,
            fact_token="brand-new-token-after-pair-zxy",
        )
        assert success is True, error
        assert config_data["gateway"]["auth"] == "brand-new-token-after-pair-zxy"

    def test_rotation_event_emitted_when_token_changes(self, tmp_path: Path):
        """When the just-minted bearer differs from the persisted one,
        configure_agent must emit a single stage='gateway_token_rotated'
        event carrying a JSON payload with the agent_key + reason."""
        host = self._build_host_with_existing_token(token="stable-old-token-zzz")
        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        success, error, _ = self._run_configure(
            host,
            self._build_config(),
            tmp_path,
            fact_token="brand-new-token-rotation-zxy",
            on_event=on_event,
        )
        assert success is True, error
        rotation_events = [m for s, m in events if s == "gateway_token_rotated"]
        assert len(rotation_events) == 1
        payload = json.loads(rotation_events[0])
        assert payload["agent_key"] == "zer-test"
        assert payload["reason"] == "configure"

    def test_rotation_event_not_emitted_on_first_mint(self, tmp_path: Path):
        """When there is no prior token (first configure), the rotation
        event must be suppressed — that's an install, not a rotation."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        success, error, _ = self._run_configure(
            host,
            self._build_config(),
            tmp_path,
            on_event=on_event,
        )
        assert success is True, error
        assert not [e for e in events if e[0] == "gateway_token_rotated"]


class TestOpenClawTemplate:
    """Tests for OpenClaw openclaw.json.j2 template rendering."""

    def _render_template(self, config):
        """Helper to render the openclaw.json.j2 template."""
        template_dir = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/templates"
        )
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("openclaw.json.j2")
        rendered = template.render(config=config)
        return json.loads(rendered)

    def test_template_renders_minimal_config(self):
        """Test template renders valid JSON with minimal config."""
        config = {
            "provider": {"default_model": "anthropic/claude-sonnet-4-6"},
        }
        result = self._render_template(config)

        assert result["agents"]["defaults"]["model"] == {
            "primary": "anthropic/claude-sonnet-4-6"
        }
        assert result["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"
        assert result["agents"]["defaults"]["maxConcurrent"] == 4
        assert result["gateway"]["port"] == 18789
        assert result["gateway"]["bind"] == "lan"
        assert "browser" in result["tools"]["deny"]
        assert result["browser"]["enabled"] is False
        assert "plugins" not in result

    def test_template_renders_full_config(self):
        """Test template renders with all optional fields."""
        config = {
            "provider": {"default_model": "openai/gpt-5.4"},
            "gateway": {
                "port": 40123,
                "bind": "loopback",
                "auth": {"token": "secret"},
            },
            "max_concurrent": 8,
            "skills": ["researcher", "coder"],
            "sandbox_mode": "all",
            "heartbeat_interval": "15m",
            "session_dm_scope": "per-peer",
            "session_reset_hour": 6,
            "session_idle_minutes": 60,
            "channels": {"telegram": {"enabled": True}},
        }
        result = self._render_template(config)

        assert result["agents"]["defaults"]["model"] == {"primary": "openai/gpt-5.4"}
        assert result["agents"]["defaults"]["maxConcurrent"] == 8
        assert result["agents"]["defaults"]["skills"] == ["researcher", "coder"]
        assert result["gateway"]["port"] == 40123
        assert result["gateway"]["bind"] == "loopback"
        assert result["gateway"]["auth"]["token"] == "secret"
        assert result["tools"]["exec"]["security"] == "full"
        assert result["tools"]["exec"]["ask"] == "off"
        assert result["session"]["dmScope"] == "per-peer"
        assert result["session"]["reset"]["atHour"] == 6
        assert result["session"]["reset"]["idleMinutes"] == 60
        # Verify channels rendered correctly
        assert "channels" in result
        assert result["channels"]["telegram"]["enabled"] is True

    def test_template_enforces_browser_disabled(self):
        """Headless profile always disables browser even when config sets enabled=true."""
        config = {
            "provider": {"default_model": "openai/gpt-5.4"},
            "browser": {"enabled": True, "headless": True},
            "plugins": {"entries": {"browser": {"enabled": True}}},
            "tools": {"deny": ["exec"]},
        }

        result = self._render_template(config)

        assert result["browser"]["enabled"] is False
        assert result["browser"]["headless"] is True
        assert result["plugins"]["entries"]["browser"]["enabled"] is True
        assert "exec" in result["tools"]["deny"]
        assert "browser" in result["tools"]["deny"]

    def test_template_preserves_web_tools_when_browser_disabled(self):
        """Browser deny list should not block web_search/web_fetch alternatives."""
        config = {
            "provider": {"default_model": "openai/gpt-5.4"},
        }

        result = self._render_template(config)

        assert "browser" in result["tools"]["deny"]
        assert "web_search" not in result["tools"]["deny"]
        assert "web_fetch" not in result["tools"]["deny"]

    def test_template_defaults_match_openclaw_docs(self):
        """Test that defaults match OpenClaw official documentation."""
        config = {"provider": {"default_model": "anthropic/claude-opus-4-6"}}
        result = self._render_template(config)

        assert result["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"
        assert result["agents"]["defaults"]["maxConcurrent"] == 4
        assert result["agents"]["defaults"]["sandbox"]["mode"] == "off"
        assert result["agents"]["defaults"]["heartbeat"]["every"] == "30m"
        assert result["agents"]["defaults"]["heartbeat"]["target"] == "last"
        assert result["gateway"]["port"] == 18789
        assert result["gateway"]["bind"] == "lan"
        assert result["gateway"]["reload"]["mode"] == "hybrid"
        assert result["gateway"]["reload"]["debounceMs"] == 300
        assert result["session"]["dmScope"] == "per-channel-peer"
        assert result["session"]["reset"]["mode"] == "daily"
        assert result["session"]["reset"]["atHour"] == 4
        assert result["session"]["reset"]["idleMinutes"] == 120

    def test_template_handles_missing_provider(self):
        """Test template renders without provider (model field omitted)."""
        config = {"gateway": {"port": 40000}}
        result = self._render_template(config)

        # Model field should not be present
        assert "model" not in result["agents"]["defaults"]
        # Other defaults should still be present
        assert result["agents"]["defaults"]["workspace"] == "~/.openclaw/workspace"

    def test_template_handles_missing_gateway(self):
        """Test template renders with missing gateway config."""
        config = {"provider": {"default_model": "anthropic/claude-sonnet-4-6"}}
        result = self._render_template(config)

        # Should use gateway defaults
        assert result["gateway"]["port"] == 18789
        assert result["gateway"]["bind"] == "lan"

    def test_template_handles_empty_optional_fields(self):
        """Test template with empty lists/dicts."""
        config = {
            "provider": {"default_model": "anthropic/claude-sonnet-4-6"},
            "skills": [],
            "agent_list": [],
            "channels": {},
        }
        result = self._render_template(config)

        # Empty arrays/objects should be omitted in rendered output
        assert "skills" not in result["agents"]["defaults"]
        assert "list" not in result["agents"]
        # Empty channels object should still be omitted
        assert "channels" not in result or result.get("channels") == {}

    def test_template_escapes_special_characters(self):
        """Test that special characters in strings are properly escaped."""
        config = {
            "provider": {"default_model": 'model"with"quotes'},
            "gateway": {"bind": "bind\nwith\nnewlines"},
        }
        result = self._render_template(config)

        # Should parse as valid JSON (proves escaping worked)
        assert result["agents"]["defaults"]["model"] == {"primary": 'model"with"quotes'}
        assert result["gateway"]["bind"] == "bind\nwith\nnewlines"

    def test_template_renders_agent_list(self):
        """Test that non-empty agent_list renders correctly."""
        config = {
            "provider": {"default_model": "anthropic/claude-sonnet-4-6"},
            "agent_list": [
                {"id": "main", "default": True},
                {"id": "work", "workspace": "/custom/workspace"},
            ],
        }
        result = self._render_template(config)

        # Verify agent list rendered
        assert "list" in result["agents"]
        assert len(result["agents"]["list"]) == 2
        assert result["agents"]["list"][0]["id"] == "main"
        assert result["agents"]["list"][0]["default"] is True
        assert result["agents"]["list"][1]["id"] == "work"
        assert result["agents"]["list"][1]["workspace"] == "/custom/workspace"

    def test_configure_openclaw_with_model(self, tmp_path: Path):
        """Test that OpenClaw configuration passes correct extra_vars to ansible."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "test-provider",
                "type": "openrouter",
                "default_model": "deepseek/deepseek-chat-v3",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ) as mock_ansible:
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="sk-or-test",
                            ):
                                mock_update.return_value = True
                                success, error = configure_agent(
                                    "test-host", "openclaw", config_data
                                )

                                # Verify ansible was called with correct inventory vars
                                mock_ansible.assert_called_once()
                                call_args = mock_ansible.call_args
                                inventory = call_args.kwargs.get("inventory", {})

                                # Verify config passed includes model and gateway settings
                                ansible_vars = inventory.get("all", {}).get("vars", {})
                                assert "config" in ansible_vars
                                assert (
                                    ansible_vars["config"]["provider"]["default_model"]
                                    == "deepseek/deepseek-chat-v3"
                                )
                                assert (
                                    ansible_vars["config"]["gateway"]["port"] == 40000
                                )
                                assert (
                                    ansible_vars["config"]["gateway"]["bind"] == "lan"
                                )
                                # Verify template_path and agent metadata with exact values
                                assert "template_path" in ansible_vars
                                # Template path should point to openclaw templates directory
                                assert "openclaw/templates" in str(
                                    ansible_vars["template_path"]
                                )
                                assert ansible_vars["agent_name"] == "ocl-test"
                                assert ansible_vars["agent_type"] == "openclaw"
                                # Verify API key is passed in inventory vars
                                assert "provider_api_key" in ansible_vars
                                assert ansible_vars["provider_api_key"] == "sk-or-test"

        assert success is True, f"Configuration failed: {error}"
        assert error is None

    def test_configure_openclaw_with_bedrock_credentials(self, tmp_path: Path):
        """Test that Bedrock AWS credentials are passed to ansible_runner."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "bedrock-provider",
                "type": "bedrock",
                "default_model": "anthropic.claude-3-sonnet-20240229-v1:0",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ) as mock_ansible:
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
                            with patch(
                                "clawrium.core.providers.get_provider_aws_credentials",
                                return_value=(
                                    "AKIAIOSFODNN7EXAMPLE",
                                    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                                ),
                            ):
                                mock_update.return_value = True
                                success, error = configure_agent(
                                    "test-host", "openclaw", config_data
                                )

                                # Verify ansible was called with correct inventory vars
                                mock_ansible.assert_called_once()
                                call_args = mock_ansible.call_args
                                inventory = call_args.kwargs.get("inventory", {})

                                # Verify AWS credentials passed in ansible_vars
                                ansible_vars = inventory.get("all", {}).get("vars", {})
                                assert "aws_access_key" in ansible_vars
                                assert (
                                    ansible_vars["aws_access_key"]
                                    == "AKIAIOSFODNN7EXAMPLE"
                                )
                                assert "aws_secret_key" in ansible_vars
                                assert (
                                    ansible_vars["aws_secret_key"]
                                    == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                                )
                                # Bedrock should NOT use provider_api_key
                                assert ansible_vars["provider_api_key"] == ""
                                # Verify model is correct
                                assert (
                                    ansible_vars["config"]["provider"]["default_model"]
                                    == "anthropic.claude-3-sonnet-20240229-v1:0"
                                )

        assert success is True, f"Configuration failed: {error}"
        assert error is None

    def test_configure_openclaw_with_missing_bedrock_credentials_none(
        self, tmp_path: Path
    ):
        """Test that missing AWS credentials (None, None) result in empty strings."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "bedrock-provider",
                "type": "bedrock",
                "default_model": "anthropic.claude-3-sonnet-20240229-v1:0",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ) as mock_ansible:
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
                            with patch(
                                "clawrium.core.providers.get_provider_aws_credentials",
                                return_value=(None, None),
                            ):
                                mock_update.return_value = True
                                success, error = configure_agent(
                                    "test-host", "openclaw", config_data
                                )

                                mock_ansible.assert_called_once()
                                call_args = mock_ansible.call_args
                                inventory = call_args.kwargs.get("inventory", {})
                                ansible_vars = inventory.get("all", {}).get("vars", {})

                                # Missing credentials should result in empty strings
                                assert ansible_vars["aws_access_key"] == ""
                                assert ansible_vars["aws_secret_key"] == ""
                                assert ansible_vars["provider_api_key"] == ""

        assert success is True, f"Configuration failed: {error}"
        assert error is None

    def test_configure_openclaw_with_missing_bedrock_credentials_empty(
        self, tmp_path: Path
    ):
        """Test that empty string AWS credentials result in empty strings."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "bedrock-provider",
                "type": "bedrock",
                "default_model": "anthropic.claude-3-sonnet-20240229-v1:0",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ) as mock_ansible:
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
                            with patch(
                                "clawrium.core.providers.get_provider_aws_credentials",
                                return_value=("", ""),
                            ):
                                mock_update.return_value = True
                                success, error = configure_agent(
                                    "test-host", "openclaw", config_data
                                )

                                mock_ansible.assert_called_once()
                                call_args = mock_ansible.call_args
                                inventory = call_args.kwargs.get("inventory", {})
                                ansible_vars = inventory.get("all", {}).get("vars", {})

                                # Empty credentials should result in empty strings
                                assert ansible_vars["aws_access_key"] == ""
                                assert ansible_vars["aws_secret_key"] == ""

        assert success is True, f"Configuration failed: {error}"
        assert error is None

    def test_configure_non_bedrock_skips_aws_credentials(self, tmp_path: Path):
        """Test that non-bedrock providers use API key, not AWS credentials."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "anthropic-provider",
                "type": "anthropic",
                "default_model": "claude-3-sonnet-20240229",
            },
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ) as mock_ansible:
                        with patch(
                            "clawrium.core.lifecycle.update_host"
                        ) as mock_update:
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="sk-test-api-key",
                            ):
                                mock_update.return_value = True
                                success, error = configure_agent(
                                    "test-host", "openclaw", config_data
                                )

                                mock_ansible.assert_called_once()
                                call_args = mock_ansible.call_args
                                inventory = call_args.kwargs.get("inventory", {})
                                ansible_vars = inventory.get("all", {}).get("vars", {})

                                # Non-bedrock should use provider_api_key
                                assert (
                                    ansible_vars["provider_api_key"]
                                    == "sk-test-api-key"
                                )
                                # AWS credentials should be empty
                                assert ansible_vars["aws_access_key"] == ""
                                assert ansible_vars["aws_secret_key"] == ""

        assert success is True, f"Configuration failed: {error}"
        assert error is None

    def test_returns_false_when_provider_config_not_dict(self):
        """Test that non-dict provider config is rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000},
            "provider": "invalid-not-a-dict",
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent("test-host", "openclaw", config_data)

        assert success is False
        assert "Invalid provider config" in error

    def test_returns_false_when_provider_missing_name(self):
        """Test that provider missing name is rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "type": "anthropic",
                "default_model": "claude-3-sonnet",
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent("test-host", "openclaw", config_data)

        assert success is False
        assert "missing" in error.lower()
        assert "name" in error.lower()

    def test_returns_false_when_provider_missing_type(self):
        """Test that provider missing type is rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "my-provider",
                "default_model": "claude-3-sonnet",
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent("test-host", "openclaw", config_data)

        assert success is False
        assert "missing" in error.lower()
        assert "type" in error.lower()

    def test_returns_false_when_provider_missing_model(self):
        """Test that provider missing default_model is rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "my-provider",
                "type": "anthropic",
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent("test-host", "openclaw", config_data)

        assert success is False
        assert "missing" in error.lower()
        assert "default_model" in error.lower()

    def test_returns_false_when_ollama_missing_endpoint(self):
        """Test that Ollama provider without endpoint is rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "my-ollama",
                "type": "ollama",
                "default_model": "llama3",
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent("test-host", "openclaw", config_data)

        assert success is False
        assert "endpoint" in error.lower()

    def test_returns_false_when_model_name_empty(self):
        """Test that empty model name is rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "my-provider",
                "type": "anthropic",
                "default_model": "",
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            success, error = configure_agent("test-host", "openclaw", config_data)

        assert success is False
        # Empty model name triggers "missing" validation
        assert "missing" in error.lower() or "invalid" in error.lower()

    def test_returns_false_when_model_name_has_invalid_chars(self):
        """Test that model names with invalid characters are rejected."""
        host = {
            "hostname": "test-host",
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        # Test various invalid patterns
        invalid_models = [
            "model with spaces",
            "model;injection",
            "model`backtick`",
            "model$variable",
            "model$(cmd)",
        ]

        for invalid_model in invalid_models:
            config_data = {
                "gateway": {"port": 40000},
                "provider": {
                    "name": "my-provider",
                    "type": "anthropic",
                    "default_model": invalid_model,
                },
            }

            with patch("clawrium.core.lifecycle.get_host", return_value=host):
                success, error = configure_agent("test-host", "openclaw", config_data)

            assert success is False, f"Should reject model name: {invalid_model}"
            assert "Invalid model name" in error

    def test_configure_openclaw_with_headless_enforces_browser_deny(
        self, tmp_path: Path
    ):
        """configure_agent pipeline should render browser-disabled config for headless hosts."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "provider": {
                "name": "test-provider",
                "type": "openrouter",
                "default_model": "deepseek/deepseek-chat-v3",
            },
            "browser": {"enabled": True, "headless": True},
            "tools": {"deny": ["exec"]},
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ) as mock_ansible:
                        with patch("clawrium.core.lifecycle.update_host"):
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="sk-or-test",
                            ):
                                success, error = configure_agent(
                                    "test-host", "openclaw", config_data
                                )

                                assert success is True
                                assert error is None

                                ansible_vars = mock_ansible.call_args.kwargs[
                                    "inventory"
                                ]["all"]["vars"]
                                rendered = self._render_template(ansible_vars["config"])

                                assert "browser" in rendered["tools"]["deny"]
                                assert "web_search" not in rendered["tools"]["deny"]
                                assert "web_fetch" not in rendered["tools"]["deny"]
                                assert rendered["browser"]["enabled"] is False

    def test_configure_openclaw_template_path_and_config_vars(self, tmp_path: Path):
        """configure_agent should pass template path and config vars to ansible."""
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"ocl-test": {"type": "openclaw"}},
        }
        config_data = {
            "provider": {
                "name": "test-provider",
                "type": "openrouter",
                "default_model": "deepseek/deepseek-chat-v3",
            }
        }

        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ):
                with patch(
                    "clawrium.core.lifecycle.get_host_private_key",
                    return_value=key_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ) as mock_ansible:
                        with patch("clawrium.core.lifecycle.update_host"):
                            with patch(
                                "clawrium.core.providers.get_provider_api_key",
                                return_value="sk-or-test",
                            ):
                                success, error = configure_agent(
                                    "test-host", "openclaw", config_data
                                )

                                assert success is True
                                assert error is None

                                ansible_vars = mock_ansible.call_args.kwargs[
                                    "inventory"
                                ]["all"]["vars"]
                                assert "openclaw/templates" in str(
                                    ansible_vars["template_path"]
                                )
                                assert ansible_vars["config"]["provider"][
                                    "default_model"
                                ] == ("deepseek/deepseek-chat-v3")

    def test_template_ollama_renders_models_block(self):
        """Test that ollama provider generates models.providers.ollama block."""
        config = {
            "provider": {
                "type": "ollama",
                "endpoint": "http://localhost:11434",
                "default_model": "llama3.1:8b",
            },
        }
        result = self._render_template(config)

        # Verify models.providers.ollama structure
        assert "models" in result
        assert "providers" in result["models"]
        assert "ollama" in result["models"]["providers"]
        ollama = result["models"]["providers"]["ollama"]
        assert ollama["baseUrl"] == "http://localhost:11434"
        assert ollama["apiKey"] == "ollama-local"
        assert ollama["api"] == "ollama"
        assert len(ollama["models"]) == 1
        assert ollama["models"][0]["id"] == "llama3.1:8b"
        assert ollama["models"][0]["name"] == "llama3.1:8b"
        assert ollama["models"][0]["contextWindow"] == 131072
        assert ollama["models"][0]["maxTokens"] == 16384

    def test_template_ollama_no_models_block_without_endpoint(self):
        """Test that ollama without endpoint does not generate models block."""
        config = {
            "provider": {
                "type": "ollama",
                "default_model": "llama3.1:8b",
                # No endpoint
            },
        }
        result = self._render_template(config)

        # models block should not exist
        assert "models" not in result

    def test_template_ollama_no_models_block_without_default_model(self):
        """Test that ollama without default_model does not crash."""
        config = {
            "provider": {
                "type": "ollama",
                "endpoint": "http://localhost:11434",
                # No default_model
            },
        }
        result = self._render_template(config)

        # Should not crash, models block should not exist
        assert "models" not in result

    def test_template_ollama_strips_prefix_in_models_id(self):
        """Test that pre-prefixed ollama model has correct id without double prefix."""
        config = {
            "provider": {
                "type": "ollama",
                "endpoint": "http://localhost:11434",
                "default_model": "ollama/llama3.1:8b",  # Already prefixed
            },
        }
        result = self._render_template(config)

        # models[].id should be stripped of ollama/ prefix
        assert (
            result["models"]["providers"]["ollama"]["models"][0]["id"] == "llama3.1:8b"
        )
        # But model.primary should keep the prefix
        assert result["agents"]["defaults"]["model"]["primary"] == "ollama/llama3.1:8b"

    def test_template_ollama_model_gets_prefix(self):
        """Test that unprefixed ollama model gets ollama/ prefix in model.primary."""
        config = {
            "provider": {
                "type": "ollama",
                "endpoint": "http://localhost:11434",
                "default_model": "llama3.1:8b",  # Not prefixed
            },
        }
        result = self._render_template(config)

        assert result["agents"]["defaults"]["model"]["primary"] == "ollama/llama3.1:8b"

    def test_template_exec_defaults_to_yolo_policy(self):
        """Test tools.exec defaults to no-prompt host execution policy."""
        config = {
            "provider": {
                "default_model": "anthropic/claude-sonnet-4-6",
            }
        }
        result = self._render_template(config)

        assert result["tools"]["exec"]["host"] == "gateway"
        assert result["tools"]["exec"]["security"] == "full"
        assert result["tools"]["exec"]["ask"] == "off"

    def test_template_exec_renders_custom_policy_fields(self):
        """Test tools.exec includes security/ask and optional policy knobs."""
        config = {
            "provider": {
                "default_model": "anthropic/claude-sonnet-4-6",
            },
            "tools": {
                "exec": {
                    "host": "node",
                    "security": "allowlist",
                    "ask": "always",
                    "strictInlineEval": True,
                    "safeBins": ["head", "tail"],
                    "safeBinTrustedDirs": ["/usr/bin"],
                    "safeBinProfiles": {"head": {"maxPositional": 0}},
                }
            },
        }
        result = self._render_template(config)

        assert result["tools"]["exec"]["host"] == "node"
        assert result["tools"]["exec"]["security"] == "allowlist"
        assert result["tools"]["exec"]["ask"] == "always"
        assert result["tools"]["exec"]["strictInlineEval"] is True
        assert result["tools"]["exec"]["safeBins"] == ["head", "tail"]
        assert result["tools"]["exec"]["safeBinTrustedDirs"] == ["/usr/bin"]
        assert result["tools"]["exec"]["safeBinProfiles"]["head"]["maxPositional"] == 0


class TestExecApprovalsTemplate:
    """Tests for OpenClaw exec-approvals.json.j2 template rendering."""

    def _render_template(self, config):
        template_dir = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/templates"
        )
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("exec-approvals.json.j2")
        rendered = template.render(config=config)
        return json.loads(rendered)

    def test_exec_approvals_defaults_to_no_prompt_policy(self):
        config = {}
        result = self._render_template(config)

        assert result["version"] == 1
        assert result["defaults"]["security"] == "full"
        assert result["defaults"]["ask"] == "off"
        assert result["defaults"]["askFallback"] == "full"
        assert result["defaults"]["autoAllowSkills"] is False

    def test_exec_approvals_follows_tools_exec_fallbacks(self):
        config = {
            "tools": {
                "exec": {
                    "security": "allowlist",
                    "ask": "on-miss",
                }
            }
        }
        result = self._render_template(config)

        assert result["defaults"]["security"] == "allowlist"
        assert result["defaults"]["ask"] == "on-miss"
        assert result["defaults"]["askFallback"] == "full"
        assert result["defaults"]["autoAllowSkills"] is False

    def test_exec_approvals_honors_explicit_overrides(self):
        config = {
            "tools": {
                "exec": {
                    "security": "allowlist",
                    "ask": "on-miss",
                }
            },
            "exec_approvals": {
                "version": 2,
                "defaults": {
                    "security": "full",
                    "ask": "off",
                    "askFallback": "allowlist",
                    "autoAllowSkills": True,
                },
            },
        }
        result = self._render_template(config)

        assert result["version"] == 2
        assert result["defaults"]["security"] == "full"
        assert result["defaults"]["ask"] == "off"
        assert result["defaults"]["askFallback"] == "allowlist"
        assert result["defaults"]["autoAllowSkills"] is True


class TestEnvTemplate:
    """Tests for OpenClaw .env.j2 template rendering."""

    def _render_env_template(
        self,
        config,
        provider_api_key="",
        discord_bot_token="",
        slack_bot_token="",
        slack_app_token="",
        aws_access_key="",
        aws_secret_key="",
    ):
        """Helper to render the .env.j2 template."""
        template_dir = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/templates"
        )
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template(".env.j2")
        return template.render(
            config=config,
            provider_api_key=provider_api_key,
            discord_bot_token=discord_bot_token,
            slack_bot_token=slack_bot_token,
            slack_app_token=slack_app_token,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
        )

    @staticmethod
    def _parse_env(rendered):
        """Parse rendered env file into key/value map.

        Handles shell-quoted values: 'value' or 'val'"'"'ue' (escaped single quote)
        """
        result = {}
        for line in rendered.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            # Handle shell quoting: strip outer single quotes and unescape inner quotes
            if value.startswith("'") and value.endswith("'"):
                # Remove outer quotes and unescape '"'"' -> '
                value = value[1:-1].replace("'\"'\"'", "'")
            result[key] = value
        return result

    def test_env_anthropic_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "anthropic",
                "default_model": "anthropic/claude-opus-4-6",
            },
        }
        rendered = self._render_env_template(config, provider_api_key="anthropic-key")
        env_map = self._parse_env(rendered)

        assert env_map["ANTHROPIC_API_KEY"] == "anthropic-key"
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "anthropic/claude-opus-4-6"

    def test_env_openai_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {"type": "openai", "default_model": "openai/gpt-5.4"},
        }
        rendered = self._render_env_template(config, provider_api_key="openai-key")
        env_map = self._parse_env(rendered)

        assert env_map["OPENAI_API_KEY"] == "openai-key"
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "openai/gpt-5.4"

    def test_env_ollama_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "ollama",
                "endpoint": "http://localhost:11434",
                "default_model": "llama3.1:8b",
            },
        }
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert env_map["OPENCLAW_OLLAMA_URL"] == "http://localhost:11434"
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "llama3.1:8b"

    def test_env_openrouter_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "openrouter",
                "default_model": "deepseek/deepseek-chat-v3",
            },
        }
        rendered = self._render_env_template(config, provider_api_key="openrouter-key")
        env_map = self._parse_env(rendered)

        assert env_map["OPENROUTER_API_KEY"] == "openrouter-key"
        # OpenRouter models get prefixed with openrouter/
        assert (
            env_map["OPENCLAW_DEFAULT_MODEL"] == "openrouter/deepseek/deepseek-chat-v3"
        )

    def test_env_bedrock_provider_with_credentials(self):
        """Test that Bedrock provider outputs AWS credentials when provided."""
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "bedrock",
                "default_model": "anthropic.claude-3-7-sonnet-20250219-v1:0",
            },
        }
        rendered = self._render_env_template(
            config,
            aws_access_key="AKIAIOSFODNN7EXAMPLE",
            aws_secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        # Credentials are single-quoted for shell safety
        assert "AWS_ACCESS_KEY_ID='AKIAIOSFODNN7EXAMPLE'" in rendered
        assert (
            "AWS_SECRET_ACCESS_KEY='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'"
            in rendered
        )
        env_map = self._parse_env(rendered)
        # Bedrock models get prefixed with bedrock/
        assert (
            env_map["OPENCLAW_DEFAULT_MODEL"]
            == "bedrock/anthropic.claude-3-7-sonnet-20250219-v1:0"
        )

    def test_env_bedrock_credentials_with_special_chars(self):
        """Test that Bedrock credentials with special characters are escaped."""
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "bedrock",
                "default_model": "anthropic.claude-3-7-sonnet-20250219-v1:0",
            },
        }
        # Test with special chars: single quote, hash, equals, spaces
        rendered = self._render_env_template(
            config,
            aws_access_key="AKIA'TEST",
            aws_secret_key="secret#with=special chars'and\"quotes",
        )
        # Single quotes in value should be escaped
        assert "AWS_ACCESS_KEY_ID='AKIA'\"'\"'TEST'" in rendered
        # Other special chars are safe inside single quotes
        assert "secret#with=special" in rendered

    def test_env_bedrock_provider_without_credentials(self):
        """Test that Bedrock provider works without AWS credentials."""
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "bedrock",
                "default_model": "anthropic.claude-3-7-sonnet-20250219-v1:0",
            },
        }
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        # No AWS credentials should be in output when not provided
        assert "AWS_ACCESS_KEY_ID" not in env_map
        assert "AWS_SECRET_ACCESS_KEY" not in env_map
        # Bedrock models get prefixed with bedrock/
        assert (
            env_map["OPENCLAW_DEFAULT_MODEL"]
            == "bedrock/anthropic.claude-3-7-sonnet-20250219-v1:0"
        )

    def test_env_bedrock_provider_with_empty_string_credentials(self):
        """Test that Bedrock with empty string credentials does not emit AWS vars."""
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "bedrock",
                "default_model": "anthropic.claude-3-7-sonnet-20250219-v1:0",
            },
        }
        # Empty strings should be treated as falsy - no AWS vars emitted
        rendered = self._render_env_template(
            config,
            aws_access_key="",
            aws_secret_key="",
        )
        env_map = self._parse_env(rendered)

        # Empty credentials should NOT produce AWS vars
        assert "AWS_ACCESS_KEY_ID" not in env_map
        assert "AWS_SECRET_ACCESS_KEY" not in env_map
        # Model should still be prefixed correctly
        assert (
            env_map["OPENCLAW_DEFAULT_MODEL"]
            == "bedrock/anthropic.claude-3-7-sonnet-20250219-v1:0"
        )

    def test_env_vertex_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "vertex",
                "default_model": "google/gemini-2.5-pro",
            },
        }
        rendered = self._render_env_template(
            config, provider_api_key="/etc/gcp/service-account.json"
        )
        env_map = self._parse_env(rendered)

        assert (
            env_map["GOOGLE_APPLICATION_CREDENTIALS"] == "/etc/gcp/service-account.json"
        )
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "google/gemini-2.5-pro"

    def test_env_zai_provider(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {"type": "zai", "default_model": "zai/glm-4.6"},
        }
        rendered = self._render_env_template(config, provider_api_key="zai-key")
        env_map = self._parse_env(rendered)

        assert env_map["ZAI_API_KEY"] == "zai-key"
        assert env_map["OPENCLAW_DEFAULT_MODEL"] == "zai/glm-4.6"

    def test_env_missing_api_key(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {
                "type": "openrouter",
                "default_model": "deepseek/deepseek-chat-v3",
            },
        }
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert "OPENROUTER_API_KEY" not in env_map
        # OpenRouter models get prefixed with openrouter/ for OpenClaw
        assert (
            env_map["OPENCLAW_DEFAULT_MODEL"] == "openrouter/deepseek/deepseek-chat-v3"
        )

    def test_env_missing_default_model(self):
        config = {
            "gateway": {"bind": "lan", "port": 40209},
            "provider": {"type": "openai"},
        }
        rendered = self._render_env_template(config, provider_api_key="openai-key")
        env_map = self._parse_env(rendered)

        assert env_map["OPENAI_API_KEY"] == "openai-key"
        assert "OPENCLAW_DEFAULT_MODEL" not in env_map

    def test_env_gateway_config(self):
        config = {"gateway": {"bind": "loopback", "port": 40123}}
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert env_map["OPENCLAW_GATEWAY_BIND"] == "loopback"
        assert env_map["OPENCLAW_GATEWAY_PORT"] == "40123"

    def test_env_gateway_auth(self):
        config = {"gateway": {"bind": "lan", "port": 40209, "auth": "secret-token"}}
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert env_map["OPENCLAW_GATEWAY_AUTH_MODE"] == "token"
        assert env_map["OPENCLAW_GATEWAY_AUTH_TOKEN"] == "secret-token"

    def test_env_no_provider(self):
        config = {"gateway": {"bind": "lan", "port": 40209}}
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert env_map["OPENCLAW_GATEWAY_BIND"] == "lan"
        assert env_map["OPENCLAW_GATEWAY_PORT"] == "40209"
        assert "OPENCLAW_DEFAULT_MODEL" not in env_map
        assert "ANTHROPIC_API_KEY" not in env_map
        assert "OPENAI_API_KEY" not in env_map
        assert "OPENROUTER_API_KEY" not in env_map
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in env_map
        assert "ZAI_API_KEY" not in env_map

    def test_env_slack_bot_token_renders(self):
        config = {"gateway": {"bind": "lan", "port": 40000}}
        rendered = self._render_env_template(
            config, slack_bot_token="xoxb-123456789012-123456789012-AbCdEf"
        )
        env_map = self._parse_env(rendered)

        assert env_map["SLACK_BOT_TOKEN"] == "xoxb-123456789012-123456789012-AbCdEf"

    def test_env_slack_app_token_renders(self):
        config = {"gateway": {"bind": "lan", "port": 40000}}
        rendered = self._render_env_template(
            config, slack_app_token="xapp-1-A01BC2DEF-abcdef0123456789"
        )
        env_map = self._parse_env(rendered)

        assert env_map["SLACK_APP_TOKEN"] == "xapp-1-A01BC2DEF-abcdef0123456789"

    def test_env_both_slack_tokens_together(self):
        config = {"gateway": {"bind": "lan", "port": 40000}}
        rendered = self._render_env_template(
            config,
            slack_bot_token="xoxb-123456789012-123456789012-AbCdEf",
            slack_app_token="xapp-1-A01BC2DEF-abcdef0123456789",
        )
        env_map = self._parse_env(rendered)

        assert env_map["SLACK_BOT_TOKEN"] == "xoxb-123456789012-123456789012-AbCdEf"
        assert env_map["SLACK_APP_TOKEN"] == "xapp-1-A01BC2DEF-abcdef0123456789"

    def test_env_slack_tokens_absent_when_not_provided(self):
        config = {"gateway": {"bind": "lan", "port": 40000}}
        rendered = self._render_env_template(config)
        env_map = self._parse_env(rendered)

        assert "SLACK_BOT_TOKEN" not in env_map
        assert "SLACK_APP_TOKEN" not in env_map


class TestDevicePairingValidation:
    """Tests for device pairing credential validation in Ansible playbook."""

    def _load_playbook(self):
        """Load the install playbook."""
        playbook_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/playbooks/install.yaml"
        )
        import yaml

        with open(playbook_path) as f:
            return yaml.safe_load(f)

    def test_playbook_validates_device_token_exists(self):
        """Test that playbook has validation for missing deviceToken."""
        playbook = self._load_playbook()
        tasks = playbook[0]["tasks"]

        # Find the validation task
        validate_task = None
        for task in tasks:
            if task.get("name") == "Validate device credentials":
                validate_task = task
                break

        assert validate_task is not None, "Missing device credentials validation task"
        assert "device_credentials.deviceToken is not defined" in validate_task[
            "ansible.builtin.fail"
        ]["msg"] or "device_credentials.deviceToken" in str(
            validate_task.get("when", "")
        )

    def test_playbook_validates_device_token_length(self):
        """Test that playbook validates deviceToken minimum length."""
        playbook = self._load_playbook()
        tasks = playbook[0]["tasks"]

        # Find the validation task
        validate_task = None
        for task in tasks:
            if task.get("name") == "Validate device credentials":
                validate_task = task
                break

        assert validate_task is not None
        when_condition = str(validate_task.get("when", ""))
        assert "length" in when_condition or "< 10" in when_condition

    def test_pairing_script_handles_malformed_json(self):
        """Test that pair_device.mjs logs parse errors instead of silently ignoring."""
        script_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs"
        )
        content = script_path.read_text()

        # Verify parse errors are logged, not silently ignored
        assert (
            "Failed to parse gateway message" in content or "parse" in content.lower()
        )
        assert "// Ignore parse errors" not in content, (
            "Parse errors should not be silently ignored"
        )

    def test_pairing_script_validates_challenge_nonce(self):
        """Test that pair_device.mjs validates challengeNonce before use."""
        script_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs"
        )
        content = script_path.read_text()

        # Verify null check exists for challengeNonce
        assert "!challengeNonce" in content or "challengeNonce ==" in content, (
            "Missing null check for challengeNonce"
        )

    def test_pairing_script_has_timeout(self):
        """Test that pair_device.mjs has a timeout for pairing."""
        script_path = (
            Path(__file__).parent.parent
            / "src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs"
        )
        content = script_path.read_text()

        assert "setTimeout" in content, "Pairing script should have timeout"
        assert "30000" in content or "timeout" in content.lower()


class TestConfigureTimeoutBudget:
    """ATX iter 2 B_NEW1: pin the configure_timeout selection.

    Hermes (240s) and zeroclaw (180s) each get extended budgets — without
    explicit tests, a rebase that collapses the elif chain would silently
    revert zeroclaw to the legacy 60s and break the configure under load.
    """

    def _setup_paths(self, tmp_path: Path) -> tuple[dict, Path]:
        host = {
            "hostname": "test-host",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"agent-x": {"type": "zeroclaw"}},
        }
        key_path = tmp_path / "key"
        key_path.write_text("key")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        return host, key_path

    def _run_and_capture(
        self, host: dict, key_path: Path, playbook: Path, claw_type: str
    ) -> int | None:
        config_data = {"gateway": {"host": "0.0.0.0", "port": 40000}}
        mock_runner = MagicMock()
        mock_runner.status = "failed"  # don't matter — we just want call_args
        mock_runner.events = []
        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=mock_runner,
            ) as mock_run,
        ):
            configure_agent("test-host", claw_type, config_data)
        if not mock_run.call_args:
            return None
        return mock_run.call_args.kwargs.get("timeout")

    def test_zeroclaw_uses_180s_timeout(self, tmp_path: Path):
        host, key_path = self._setup_paths(tmp_path)
        playbook = tmp_path / "configure.yaml"
        timeout = self._run_and_capture(host, key_path, playbook, "zeroclaw")
        assert timeout == 180, (
            f"Zeroclaw configure_timeout regression: expected 180s, got {timeout}. "
            f"Did the elif branch collapse back to the legacy 60s budget?"
        )

    def test_hermes_branch_pins_240s_in_source(self):
        # Hermes also gets an extended budget (240s), but its configure
        # path short-circuits before ansible-runner when
        # HERMES_API_SERVER_KEY is missing from secrets.json — wiring
        # that for a runtime test would essentially re-test the hermes
        # install flow. Pin the hermes branch of the elif chain by
        # reading the source with a word-boundary regex so a substring
        # value like `2400` cannot satisfy the assertion (ATX iter 6
        # S-new-1).
        import inspect
        import re

        from clawrium.core import lifecycle

        src = inspect.getsource(lifecycle.configure_agent)
        assert 'resolved_type == "hermes"' in src
        assert re.search(r"configure_timeout\s*=\s*240\b", src), (
            "Hermes 240s timeout literal must appear with word boundary "
            "in configure_agent (not as a substring of 2400, 24000, etc.)"
        )

    def test_openclaw_uses_legacy_60s_timeout(self, tmp_path: Path):
        host, key_path = self._setup_paths(tmp_path)
        host["agents"]["agent-x"]["type"] = "openclaw"
        playbook = tmp_path / "configure.yaml"
        timeout = self._run_and_capture(host, key_path, playbook, "openclaw")
        assert timeout == 60, (
            f"Openclaw must keep the legacy 60s configure budget, got {timeout}"
        )


# ---------------------------------------------------------------------------
# #422 — zeroclaw Discord hydration via lifecycle.configure_agent
# ---------------------------------------------------------------------------


class TestZeroclawDiscordHydration:
    """`configure_agent` must hydrate `DISCORD_BOT_TOKEN` from secrets.json
    onto `config_data['channels']['discord']['bot_token']` for zeroclaw
    just like it does for hermes (#422). The hydration block lives outside
    the hermes-only api_server branch so both agent types share it.
    """

    def _make_host(self, discord_persisted: dict | None) -> dict:
        agent_config: dict = {
            "provider": {
                "name": "p",
                "type": "anthropic",
                "default_model": "claude-sonnet-4-5",
            },
            "gateway": {"host": "0.0.0.0", "port": 40000},
        }
        if discord_persisted is not None:
            agent_config["channels"] = {"discord": discord_persisted}
        return {
            "hostname": "test-host",
            "key_id": "test",
            "agents": {
                "zc-test": {
                    "type": "zeroclaw",
                    "agent_name": "zc-test",
                    "config": agent_config,
                }
            },
        }

    def _setup_fact_cache(self, tmp_path: Path) -> Path:
        """ZeroClaw configure reads pairing facts after Ansible runs. Provide
        a token so the playbook's fact-extraction path succeeds and we can
        focus on the hydration block under test."""
        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        (fact_cache_dir / "test-host").write_text(
            json.dumps(
                {
                    "__payload__": json.dumps(
                        {
                            "zeroclaw_gateway_token": "paired-bearer-token",
                            "zeroclaw_gateway_url": "ws://test-host:40000/ws/chat",
                        }
                    ),
                }
            )
        )
        return artifacts_dir

    def _run_zeroclaw_configure(
        self,
        host: dict,
        tmp_path: Path,
        secrets: dict,
    ) -> tuple[bool, str | None, dict]:
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        artifacts_dir = self._setup_fact_cache(tmp_path)

        captured: dict = {}

        def fake_run(**kwargs):
            captured["inventory"] = kwargs["inventory"]
            m = MagicMock()
            m.status = "successful"
            m.events = []
            m.config.artifact_dir = str(artifacts_dir)
            return m

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", return_value=True),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "zeroclaw",
                {
                    "provider": {
                        "name": "p",
                        "type": "anthropic",
                        "default_model": "claude-sonnet-4-5",
                    },
                    "gateway": {"host": "0.0.0.0", "port": 40000},
                },
                agent_name="zc-test",
            )

        return success, error, captured

    def _discord_secrets_entry(self, token: str) -> dict:
        return {
            "DISCORD_BOT_TOKEN": {
                "key": "DISCORD_BOT_TOKEN",
                "value": token,
                "created_at": "2026-05-18T00:00:00+00:00",
                "updated_at": "2026-05-18T00:00:00+00:00",
                "description": "Discord bot token",
            }
        }

    def test_discord_token_hydrated_for_zeroclaw(self, tmp_path: Path):
        """The bot_token from secrets.json lands on
        config_data['channels']['discord']['bot_token'] before the playbook
        runs — same path as hermes, just a different downstream consumer
        (config.toml.j2 instead of .env.j2)."""
        token = "B" * 64
        host = self._make_host(
            discord_persisted={
                "enabled": True,
                "allowed_users": ["740723459344302120"],
                "allowed_guilds": ["123"],
                "require_mention": True,
            }
        )
        secrets = self._discord_secrets_entry(token)

        success, error, captured = self._run_zeroclaw_configure(host, tmp_path, secrets)
        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert sent["channels"]["discord"]["bot_token"] == token
        # Persisted shape merged onto config_data even though the caller
        # only passed provider/gateway.
        assert sent["channels"]["discord"]["allowed_users"] == ["740723459344302120"]
        assert sent["channels"]["discord"]["allowed_guilds"] == ["123"]

    def test_discord_disabled_does_not_hydrate_zeroclaw(self, tmp_path: Path):
        """No channels.discord block in hosts.json → no hydration, no error
        even if DISCORD_BOT_TOKEN happens to exist in secrets.json."""
        host = self._make_host(discord_persisted=None)
        secrets = self._discord_secrets_entry("B" * 64)

        success, error, captured = self._run_zeroclaw_configure(host, tmp_path, secrets)
        assert success is True, error
        sent = captured["inventory"]["all"]["vars"]["config"]
        assert (
            "channels" not in sent
            or "discord" not in sent.get("channels", {})
            or "bot_token" not in sent["channels"].get("discord", {})
        )

    def test_discord_enabled_without_token_rejected_zeroclaw(self, tmp_path: Path):
        """`enabled = true` with no DISCORD_BOT_TOKEN in secrets.json must
        return (False, error) — same failure mode as hermes."""
        host = self._make_host(discord_persisted={"enabled": True})
        secrets = {}  # No DISCORD_BOT_TOKEN at all.

        success, error, _ = self._run_zeroclaw_configure(host, tmp_path, secrets)
        assert success is False
        assert "DISCORD_BOT_TOKEN" in (error or "")

    def test_discord_short_token_rejected_zeroclaw(self, tmp_path: Path):
        """Bot tokens shorter than 50 chars are rejected; mirrors hermes
        validation."""
        host = self._make_host(discord_persisted={"enabled": True})
        secrets = self._discord_secrets_entry("short-token")

        success, error, _ = self._run_zeroclaw_configure(host, tmp_path, secrets)
        assert success is False
        assert "DISCORD_BOT_TOKEN" in (error or "")

    def test_discord_bot_token_stripped_from_hosts_json_zeroclaw(self, tmp_path: Path):
        """ATX Round 1 B1: zeroclaw must mirror hermes's strip-before-persist
        behavior so bot_token never lands in hosts.json. Without this, the
        token roundtrips: hydrated → persisted → read into existing_config →
        re-hydrated, defeating the B3 invariant that bot_token lives in
        secrets.json only."""
        token = "B" * 64
        host = self._make_host(
            discord_persisted={
                "enabled": True,
                "allowed_users": ["740723459344302120"],
                "require_mention": True,
            }
        )
        secrets = self._discord_secrets_entry(token)

        captured_update: dict = {}

        def fake_update_host(_hostname, updater_fn):
            # Run the updater on a deepcopy of the host so the captured
            # post-strip shape reflects what would be written to disk.
            from copy import deepcopy

            mutated = updater_fn(deepcopy(host))
            captured_update["host"] = mutated
            return True

        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook = tmp_path / "configure.yaml"
        playbook.write_text("---\n")
        artifacts_dir = self._setup_fact_cache(tmp_path)

        def fake_run(**_kwargs):
            m = MagicMock()
            m.status = "successful"
            m.events = []
            m.config.artifact_dir = str(artifacts_dir)
            return m

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ),
            patch("clawrium.core.lifecycle.ansible_runner.run", side_effect=fake_run),
            patch("clawrium.core.lifecycle.update_host", side_effect=fake_update_host),
            patch("clawrium.core.lifecycle.get_instance_secrets", return_value=secrets),
        ):
            success, error = configure_agent(
                "test-host",
                "zeroclaw",
                {
                    "provider": {
                        "name": "p",
                        "type": "anthropic",
                        "default_model": "claude-sonnet-4-5",
                    },
                    "gateway": {"host": "0.0.0.0", "port": 40000},
                },
                agent_name="zc-test",
            )

        assert success is True, error
        persisted = captured_update["host"]["agents"]["zc-test"]["config"]
        # The Discord block must be persisted (so re-configure can find it)
        # but bot_token MUST be stripped — only secrets.json holds it.
        assert "channels" in persisted
        assert "discord" in persisted["channels"]
        assert persisted["channels"]["discord"]["enabled"] is True
        assert "bot_token" not in persisted["channels"]["discord"], (
            f"bot_token leaked into hosts.json for zeroclaw — "
            f"persisted shape: {persisted['channels']['discord']}"
        )
        # Other persisted fields survive the strip (idempotency check).
        assert persisted["channels"]["discord"]["allowed_users"] == [
            "740723459344302120"
        ]

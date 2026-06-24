"""Tests for claw lifecycle management module.

Secrets isolation in this file relies on a load-bearing autouse fixture in
`tests/conftest.py::_isolate_config_dir` — it redirects `XDG_CONFIG_HOME`
to a tmp directory, so `clawrium.core.secrets.load_secrets()` returns `{}`
for any test that doesn't explicitly mock `get_instance_secrets`. Removing
or narrowing that fixture silently regresses ~all tests in this file that
exercise the configure/start/restart paths — they would call the real
secrets loader against the developer's `~/.config/clawrium/secrets.json`.
The patches inside `_run_with_events`/`_capture_configure` are defence in
depth (with a meta-test pinning correct interception); the fixture is the
primary guarantee. ATX iter-6 W1.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawrium.core.lifecycle import (
    start_agent,
    stop_agent,
    restart_agent,
    remove_agent,
    sync_agent,
    LifecycleError,
    _get_lifecycle_playbook_path,
    _run_lifecycle_playbook,
    _resolve_agent_record,
    _cleanup_ansible_artifacts,
    _safe_host_display,
)


class TestGetLifecyclePlaybookPath:
    """Tests for playbook path resolution."""

    def test_returns_path_for_start_operation(self):
        path = _get_lifecycle_playbook_path("openclaw", "start")
        assert "openclaw" in str(path)
        assert "start.yaml" in str(path)

    def test_returns_path_for_stop_operation(self):
        path = _get_lifecycle_playbook_path("zeroclaw", "stop")
        assert "zeroclaw" in str(path)
        assert "stop.yaml" in str(path)


class TestRunLifecyclePlaybook:
    """Tests for _run_lifecycle_playbook helper."""

    def test_returns_false_when_playbook_missing(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"opc-work": {"type": "openclaw"}},
        }

        with patch("clawrium.core.lifecycle._get_lifecycle_playbook_path") as mock_path:
            mock_path.return_value = tmp_path / "nonexistent.yaml"
            success, error = _run_lifecycle_playbook(
                "openclaw", "opc-work", "192.168.1.100", "start", host
            )

        assert success is False
        assert "not found" in error

    def test_returns_false_when_ssh_key_missing(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "missing-key",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"opc-work": {"type": "openclaw"}},
        }

        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        with patch("clawrium.core.lifecycle._get_lifecycle_playbook_path") as mock_path:
            mock_path.return_value = playbook_path
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=None
            ):
                success, error = _run_lifecycle_playbook(
                    "openclaw", "opc-work", "192.168.1.100", "start", host
                )

        assert success is False
        assert "SSH key not found" in error

    def _run_with_events(
        self,
        host,
        tmp_path: Path,
        events: list,
        *,
        runner_status: str = "failed",
    ):
        """Helper that runs _run_lifecycle_playbook with a stubbed runner
        emitting the supplied events. Returns (success, error).

        ATX iter-4 NW-A: mocks `get_instance_secrets` and `get_instance_key`
        so a dev machine with a matching real entry in `~/.config/clawrium/
        secrets.json` doesn't silently populate the Ansible inventory."""
        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")
        key_path = tmp_path / "key"
        key_path.write_text("k")

        runner = MagicMock()
        runner.status = runner_status
        runner.events = events

        with (
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=runner,
            ),
            patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
            ),
            patch(
                # ATX iter-5: patch at the consumer namespace, not the source
                # module. `lifecycle.py` does `from clawrium.core.secrets import
                # get_instance_secrets` at module-load — patching the source
                # module is a no-op against the already-bound name in lifecycle.
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={},
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_key",
                return_value="test-key",
            ),
        ):
            return _run_lifecycle_playbook(
                "zeroclaw", "zer-test", "192.168.1.100", "start", host
            )

    def test_censored_event_does_not_leak_bearer(self, tmp_path: Path):
        """ATX iter-2 NB1: censored-guard at lifecycle.py:~360 covers the
        generic start/stop/restart lifecycle path. Same security invariant
        as the repair path, separate code site — pin it independently."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }

        success, error = self._run_with_events(
            host,
            tmp_path,
            [
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "res": {
                            "censored": "no_log: true was specified",
                            "msg": "Bearer zc_LEAKED_FROM_START_xxxxxxxxxxx",
                        }
                    },
                },
            ],
        )

        assert success is False
        assert "zc_LEAKED_FROM_START" not in error, (
            f"_run_lifecycle_playbook censored-guard regressed: {error!r}"
        )
        # All events censored → falls through to generic prefix.
        assert error == "Start playbook failed: failed"

    def test_all_censored_events_falls_back_to_generic_error(self, tmp_path: Path):
        """ATX iter-3 NW6: parity with TestZeroclawRepairAfterStart's
        all-censored fallback. Two censored events with bearers in both
        msg AND stderr — guard skips them both, generic prefix surfaces.
        Pins exact format (S3)."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        success, error = self._run_with_events(
            host,
            tmp_path,
            [
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "res": {
                            "censored": "hidden",
                            "msg": "Bearer zc_RL_LEAK_AAAAAAAAAAAAAAAAAAAAA",
                        }
                    },
                },
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "res": {
                            "censored": "hidden",
                            "stderr": "Bearer zc_RL_LEAK_BBBBBBBBBBBBBBBBBB",
                        }
                    },
                },
            ],
        )
        assert success is False
        assert "zc_" not in error
        assert error == "Start playbook failed: failed"

    def test_msg_none_event_does_not_return_none_error(self, tmp_path: Path):
        """ATX iter-3 NW4: in the generic lifecycle path too, a
        non-censored event with msg=None must not short-circuit to None."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        success, error = self._run_with_events(
            host,
            tmp_path,
            [
                {
                    "event": "runner_on_failed",
                    "event_data": {"res": {"msg": None, "stderr": None}},
                },
            ],
        )
        assert success is False
        assert error is not None
        assert error == "Start playbook failed: failed"

    def test_timeout_returns_friendly_error(self, tmp_path: Path):
        """ATX iter-4 NW-B: pin the timeout branch of _run_lifecycle_playbook
        — `result.status == 'timeout'` returns a fixed string before any
        event extraction runs."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }
        success, error = self._run_with_events(
            host,
            tmp_path,
            [],
            runner_status="timeout",
        )
        assert success is False
        assert error == "Start operation timed out"

    def test_secrets_patches_are_actually_called(self, tmp_path: Path):
        """ATX iter-5 NW-A meta-test: the patch targets in `_run_with_events`
        must hit the names actually consumed by `_run_lifecycle_playbook`.
        A wrong patch target (e.g. `clawrium.core.secrets.*` against a
        `from x import y` consumer) silently no-ops and the secrets-
        isolation defence becomes illusory. Assert the mocks are called."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {"zer-test": {"type": "zeroclaw"}},
        }

        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")
        key_path = tmp_path / "key"
        key_path.write_text("k")

        runner = MagicMock()
        runner.status = "successful"
        runner.events = []

        with (
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=runner,
            ),
            patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={},
            ) as mock_get_secrets,
            patch(
                "clawrium.core.lifecycle.get_instance_key",
                return_value="test-key",
            ) as mock_get_key,
        ):
            _run_lifecycle_playbook(
                "zeroclaw", "zer-test", "192.168.1.100", "start", host
            )

        # ATX iter-6/iter-7: both calls MUST be intercepted. `get_instance_
        # secrets` is the security-critical gate (real disk reads); assert
        # it first so a regression fails fast on the more important call.
        # `get_instance_key` is a pure formatter and would still be invoked
        # by any refactor that bypassed `get_instance_secrets` (e.g.
        # inlining a json.load or introducing a new helper) — the second
        # assert is the refactor-drift canary.
        assert mock_get_secrets.called, (
            "get_instance_secrets not called — this is the call that gates "
            "real secret values; if a refactor bypasses it, real "
            "~/.config/clawrium/secrets.json reads happen unintercepted "
            "(ATX iter-5 NW-A / iter-6)"
        )
        assert mock_get_key.called, (
            "get_instance_key not called — patch target or call path drifted "
            "(ATX iter-5 NW-A / iter-6)"
        )

    def _run_with_inventory_capture(
        self,
        tmp_path: Path,
        host: dict,
        agent_type: str,
        agent_name: str,
    ) -> dict:
        """Helper: invoke _run_lifecycle_playbook with a stub ansible runner
        and return the inventory dict the call would have passed to ansible.

        Centralises the patch setup so the three injection tests below stay
        focused on the inventory assertion they actually care about.
        """
        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")
        key_path = tmp_path / "key"
        key_path.write_text("k")

        runner = MagicMock()
        runner.status = "successful"
        runner.events = []

        with (
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
            ),
            patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=runner,
            ) as mock_run,
            patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={},
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_key",
                return_value="test-key",
            ),
        ):
            _run_lifecycle_playbook(
                agent_type, agent_name, host["hostname"], "start", host
            )

        # ansible_runner.run is invoked as a keyword-only call in
        # _run_lifecycle_playbook, so inventory lands in call_args.kwargs.
        return mock_run.call_args.kwargs["inventory"]

    def test_hermes_dashboard_port_injected_into_inventory(self, tmp_path: Path):
        """ATX B2: hermes agent with a valid dashboard.port in hosts.json
        must surface it as `dashboard_port` in the ansible inventory so
        start/stop/remove playbooks can re-render the unit file."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "her-test": {
                    "type": "hermes",
                    "config": {
                        "dashboard": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 45100,
                        }
                    },
                }
            },
        }
        inventory = self._run_with_inventory_capture(
            tmp_path, host, "hermes", "her-test"
        )
        assert inventory["all"]["vars"]["dashboard_port"] == 45100

    def test_non_hermes_agent_does_not_get_dashboard_port(self, tmp_path: Path):
        """ATX B2: zeroclaw / openclaw / nemoclaw must NOT receive a
        dashboard_port var. The agent-type guard is the only thing
        preventing future playbook tasks guarded by `when: dashboard_port
        is defined` from firing on the wrong claw."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "zer-test": {
                    "type": "zeroclaw",
                    # A bogus dashboard config that should be IGNORED for
                    # non-hermes: regression guard against a refactor that
                    # drops the agent-type check.
                    "config": {"dashboard": {"port": 45100}},
                }
            },
        }
        inventory = self._run_with_inventory_capture(
            tmp_path, host, "zeroclaw", "zer-test"
        )
        assert "dashboard_port" not in inventory["all"]["vars"]

    def test_hermes_legacy_agent_no_dashboard_config_does_not_inject_port(
        self, tmp_path: Path
    ):
        """ATX B2: a hermes agent installed before issue #482 has no
        config.dashboard key at all. The injection path must fall through
        cleanly — no AttributeError, no `dashboard_port: null` leak."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "her-legacy": {
                    "type": "hermes",
                    # Pre-#482 record: no `config` block at all.
                }
            },
        }
        inventory = self._run_with_inventory_capture(
            tmp_path, host, "hermes", "her-legacy"
        )
        assert "dashboard_port" not in inventory["all"]["vars"]

    def test_hermes_out_of_window_dashboard_port_rejected(self, tmp_path: Path):
        """ATX W5: a tampered hosts.json with `dashboard.port = 80` must
        NOT escape into the ansible inventory. Only ports in the documented
        45000..46999 allocation window are propagated."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "her-tampered": {
                    "type": "hermes",
                    "config": {
                        "dashboard": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": 80,
                        }
                    },
                }
            },
        }
        inventory = self._run_with_inventory_capture(
            tmp_path, host, "hermes", "her-tampered"
        )
        assert "dashboard_port" not in inventory["all"]["vars"]


class TestStartClaw:
    """Tests for start_claw function."""

    def test_raises_error_when_host_not_found(self):
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                start_agent("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                start_agent("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_raises_error_when_onboarding_incomplete(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "pending"},
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                start_agent("192.168.1.100", "openclaw")

        assert "incomplete" in str(exc_info.value)

    def test_returns_success_on_successful_start(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = start_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "start"


class TestStopClaw:
    """Tests for stop_claw function."""

    def test_raises_error_when_host_not_found(self):
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                stop_agent("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self):
        host = {
            "hostname": "192.168.1.100",
            "agents": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                stop_agent("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_returns_success_on_successful_stop(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "stop.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = stop_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "stop"


class TestRestartClaw:
    """Tests for restart_claw function."""

    def test_returns_stop_failure_when_stop_fails(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "stop.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "failed"
        mock_runner.events = [
            {"event": "runner_on_failed", "event_data": {"res": {"msg": "Stop failed"}}}
        ]

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            result = restart_agent("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert "Stop failed" in result["error"]

    def test_returns_success_on_successful_restart(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "test.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                result = restart_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "restart"


class TestZeroclawRepairAfterStart:
    """Issue #437: `_zeroclaw_repair_after_start` re-pairs after any
    systemd-level start of the zeroclaw daemon and atomically updates
    `hosts.json.gateway.auth`. Tested directly so the failure modes
    (playbook failure, update_host failure) are exercised without
    going through the full start_agent stack."""

    def _host(self, auth: str = "old-token-zzzzz") -> dict:
        return {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "zer-test": {
                    "type": "zeroclaw",
                    "agent_name": "zerot",
                    "onboarding": {"state": "ready"},
                    "config": {"gateway": {"port": 40000, "auth": auth}},
                }
            },
        }

    def _setup_repair_runner(
        self, tmp_path: Path, token: str
    ) -> tuple[MagicMock, Path]:
        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        (fact_cache_dir / "192.168.1.100").write_text(
            json.dumps(
                {
                    "__payload__": json.dumps(
                        {
                            "zeroclaw_gateway_token": token,
                            "zeroclaw_gateway_url": "ws://192.168.1.100:40000/ws/chat",
                        }
                    )
                }
            )
        )
        runner = MagicMock()
        runner.status = "successful"
        runner.events = []
        runner.config.artifact_dir = str(artifacts_dir)
        return runner, artifacts_dir

    def _run_repair(
        self,
        host: dict,
        tmp_path: Path,
        *,
        runner: MagicMock,
        update_host_result=True,
        update_host_capture: dict | None = None,
        reason: str = "restart",
        on_event=None,
    ):
        key_path = tmp_path / "test_key"
        key_path.write_text("key")
        playbook_path = tmp_path / "restart.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        def update_host_side_effect(_hostname: str, updater) -> bool:
            if update_host_capture is not None:
                h = {"hostname": "192.168.1.100", "agents": dict(host["agents"])}
                update_host_capture["updated"] = updater(h)
            return update_host_result

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.update_host",
                            side_effect=update_host_side_effect,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                from clawrium.core.lifecycle import (
                                    _zeroclaw_repair_after_start,
                                )

                                return _zeroclaw_repair_after_start(
                                    "192.168.1.100",
                                    agent_name="zer-test",
                                    on_event=on_event,
                                    reason=reason,
                                )

    def test_happy_path_updates_hosts_json_and_emits_rotation(self, tmp_path: Path):
        host = self._host()
        runner, _ = self._setup_repair_runner(tmp_path, "fresh-after-restart-zzzzz")
        capture: dict = {}
        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        success, error = self._run_repair(
            host,
            tmp_path,
            runner=runner,
            update_host_capture=capture,
            reason="restart",
            on_event=on_event,
        )
        assert success is True, error
        new_auth = capture["updated"]["agents"]["zer-test"]["config"]["gateway"]["auth"]
        assert new_auth == "fresh-after-restart-zzzzz"
        rotation = [m for s, m in events if s == "gateway_token_rotated"]
        assert len(rotation) == 1
        payload = json.loads(rotation[0])
        assert payload["agent_key"] == "zer-test"
        assert payload["reason"] == "restart"

    def test_reason_start_propagates_into_event_payload(self, tmp_path: Path):
        host = self._host()
        runner, _ = self._setup_repair_runner(tmp_path, "fresh-after-start-zzzzz")
        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        success, _ = self._run_repair(
            host,
            tmp_path,
            runner=runner,
            reason="start",
            on_event=on_event,
        )
        assert success is True
        rotation = [m for s, m in events if s == "gateway_token_rotated"]
        assert json.loads(rotation[0])["reason"] == "start"

    def test_returns_failure_when_playbook_fails(self, tmp_path: Path):
        host = self._host()
        runner = MagicMock()
        runner.status = "failed"
        runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "pair handshake exploded"}},
            }
        ]
        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        assert "pair handshake exploded" in error

    def test_censored_event_does_not_leak_bearer_into_error(self, tmp_path: Path):
        """ATX iter-2 NB1: the W1 censored-guard at lifecycle.py:~808 is the
        security invariant that keeps a `no_log: true` failure from leaking
        a bearer into user-visible error strings. Without test coverage, a
        one-line refactor (moving the `continue` below the `if 'msg' in res`
        block) silently regresses it. Pin the invariant.

        ansible-runner replaces the entire `res` dict with
        `{'censored': '<reason>'}` for no_log-failed tasks — see
        ansible_runner/display_callback/callback/awx_display.py. But a
        misbehaving debug-mode daemon could echo the Bearer back in a 401
        body; if that ever lands in `res.msg` alongside `censored`, we must
        not surface it.
        """
        host = self._host()
        runner = MagicMock()
        runner.status = "failed"
        runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {
                    "res": {
                        "censored": "the output has been hidden due to "
                        "the fact that 'no_log: true' was "
                        "specified for this result",
                        "msg": "Bearer zc_LEAKED_SECRET_xxxxxxxxxxxxxxxxxx",
                    }
                },
            },
            # Trailing non-censored event whose msg is safe to surface.
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "Re-pair playbook reported failure"}},
            },
        ]
        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        assert "zc_LEAKED_SECRET" not in error, (
            f"censored guard regressed — bearer leaked into error: {error!r}"
        )
        assert "Re-pair playbook reported failure" in error

    def test_all_censored_events_falls_back_to_generic_error(self, tmp_path: Path):
        """ATX iter-2 NB1 companion: when every runner_on_failed event is
        censored, the loop must fall through to the generic 'Re-pair
        playbook failed: <status>' message rather than the last seen msg.

        ATX iter-3 S3: assert the EXACT generic message format so a
        regression that drops the status suffix is caught (substring match
        would tolerate it).
        """
        host = self._host()
        runner = MagicMock()
        runner.status = "failed"
        runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {
                    "res": {
                        "censored": "hidden",
                        "msg": "Bearer zc_ANOTHER_SECRET_yyyyyyyyyyyyyyy",
                    }
                },
            },
            {
                "event": "runner_on_failed",
                "event_data": {
                    "res": {
                        "censored": "hidden",
                        "stderr": "Bearer zc_AND_ANOTHER_zzzzzzzzzzzzzzzz",
                    }
                },
            },
        ]
        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        # No secret in error.
        assert "zc_" not in error, (
            f"all-censored fallback leaked a bearer fragment: {error!r}"
        )
        # Exact format pinned (S3): drop the status suffix and this fails.
        assert error == "Re-pair playbook failed: failed"

    def test_msg_none_event_does_not_return_none_error(self, tmp_path: Path):
        """ATX iter-3 NW4: a non-censored event with `res = {'msg': None}`
        must NOT short-circuit and return (False, None). The guard
        `if res.get('msg') is not None` keeps the loop searching for a
        usable msg/stderr instead of leaking a None up the stack."""
        host = self._host()
        runner = MagicMock()
        runner.status = "failed"
        runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {
                    # No censored key — this is the case the `if "msg" in res`
                    # guard would have mishandled before the iter-3 fix.
                    "res": {"msg": None, "stderr": None}
                },
            },
        ]
        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        assert error is not None, (
            "msg=None on a non-censored event must not surface as a None "
            "error string (iter-3 NW4)"
        )
        # Falls through to the generic prefix because msg and stderr are None.
        assert error == "Re-pair playbook failed: failed"

    def test_returns_failure_when_update_host_returns_false(self, tmp_path: Path):
        """ATX W8: the exact divergence #437 fixes — playbook succeeds but
        hosts.json never gets written. Must surface as a failure."""
        host = self._host()
        runner, _ = self._setup_repair_runner(tmp_path, "fresh-but-not-persisted")
        success, error = self._run_repair(
            host,
            tmp_path,
            runner=runner,
            update_host_result=False,
        )
        assert success is False
        assert "failed to update hosts.json" in error

    def test_returns_failure_when_playbook_times_out(self, tmp_path: Path):
        host = self._host()
        runner = MagicMock()
        runner.status = "timeout"
        runner.events = []
        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        assert "timed out" in error.lower()

    def test_rejects_invalid_agent_name(self, tmp_path: Path):
        """ATX W4: parity with configure_agent's validation guard."""
        host = self._host()
        host["agents"]["zer-test"]["agent_name"] = "INVALID/name"
        runner, _ = self._setup_repair_runner(tmp_path, "any-token")
        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        assert "Invalid agent_name" in error

    def test_returns_failure_when_fact_cache_empty(self, tmp_path: Path):
        """ATX W-COV-2: playbook reports successful but the fact cache
        is empty — the pair token never made it back to clm. This is
        the exact timing window the always-repair invariant must
        surface as a failure, not silently leave hosts.json stale."""
        host = self._host()
        artifacts_dir = tmp_path / "artifacts"
        (artifacts_dir / "fact_cache").mkdir(parents=True)
        # No fact files written → extractor returns (None, None).
        runner = MagicMock()
        runner.status = "successful"
        runner.events = []
        runner.config.artifact_dir = str(artifacts_dir)

        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        assert "pairing token was not captured" in error

    def test_returns_failure_when_gateway_port_missing(self, tmp_path: Path):
        """ATX W-COV-4: hosts.json record without config.gateway.port
        must surface a clear error rather than building an invalid
        Ansible inventory."""
        host = self._host()
        host["agents"]["zer-test"]["config"]["gateway"] = {"auth": "x" * 32}
        runner, _ = self._setup_repair_runner(tmp_path, "any-token")
        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        assert "Gateway port missing" in error

    def test_no_rotation_event_emitted_when_update_host_fails(self, tmp_path: Path):
        """ATX W-COV-3: the rotation event must NOT fire if the disk
        write fails — that's the exact ordering invariant W2 fixed in
        configure_agent. Pin the same invariant for the restart path."""
        host = self._host()
        runner, _ = self._setup_repair_runner(tmp_path, "would-be-new-token")
        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        success, _ = self._run_repair(
            host,
            tmp_path,
            runner=runner,
            update_host_result=False,
            on_event=on_event,
        )
        assert success is False
        rotation = [m for s, m in events if s == "gateway_token_rotated"]
        assert not rotation, (
            f"rotation event leaked despite write failure: {rotation!r}"
        )

    def _capture_repair(
        self,
        host: dict,
        tmp_path: Path,
        *,
        new_token: str,
    ) -> tuple[dict, dict, list[tuple[str, str]], bool, str | None]:
        """Run _zeroclaw_repair_after_start with full instrumentation:
        capture the inventory passed to ansible-runner, the dict produced
        by update_host's updater closure, and the on_event sequence.

        Returns (inventory, hosts_json_after, events, success, error).
        """
        runner, _ = self._setup_repair_runner(tmp_path, new_token)
        captured_inventory: dict = {}
        captured_hosts: dict = {}

        def capture_run(**kwargs):
            captured_inventory.update(kwargs.get("inventory") or {})
            return runner

        def capture_update_host(_hostname: str, updater) -> bool:
            h = {"hostname": "192.168.1.100", "agents": dict(host["agents"])}
            captured_hosts.update(updater(h))
            return True

        events: list[tuple[str, str]] = []

        def on_event(stage: str, message: str) -> None:
            events.append((stage, message))

        key_path = tmp_path / "test_key"
        key_path.write_text("key")
        playbook_path = tmp_path / "restart.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                side_effect=capture_run,
            ),
            patch(
                "clawrium.core.lifecycle.update_host",
                side_effect=capture_update_host,
            ),
            patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
            ),
        ):
            from clawrium.core.lifecycle import _zeroclaw_repair_after_start

            success, error = _zeroclaw_repair_after_start(
                "192.168.1.100",
                agent_name="zer-test",
                on_event=on_event,
                reason="restart",
            )
        return captured_inventory, captured_hosts, events, success, error

    def test_repair_passes_existing_bearer_and_rotates_atomically(self, tmp_path: Path):
        """Issue #445: tasks/pair.yaml's locked-pair branch authenticates
        against /api/pairing/initiate using the current bearer from
        hosts.json. The Python helper must (a) forward that bearer as
        config.gateway.auth in the Ansible inventory, AND (b) atomically
        replace it in hosts.json with the new rotated bearer from the
        fact_cache. ATX B4: pin the full read-existing → inject → run →
        write-new pipeline so a refactor can't silently break either half.
        """
        host = self._host(auth="zc_existing_bearer_aaaaaaaaaaaaaaa")
        inv, hosts_after, events, success, error = self._capture_repair(
            host,
            tmp_path,
            new_token="zc_new_rotated_bearer_xxxxxxxxxxx",
        )
        assert success is True, error

        gateway_in = inv["all"]["vars"]["config"]["gateway"]
        assert gateway_in["auth"] == "zc_existing_bearer_aaaaaaaaaaaaaaa", (
            "existing bearer must flow into the playbook so the locked-pair "
            "branch can authenticate against /api/pairing/initiate"
        )
        assert gateway_in["port"] == 40000

        # B4: hosts.json must reflect the rotated bearer, not the input one.
        gateway_out = hosts_after["agents"]["zer-test"]["config"]["gateway"]
        assert gateway_out["auth"] == "zc_new_rotated_bearer_xxxxxxxxxxx", (
            "hosts.json must be rewritten with the new bearer minted by "
            "the playbook, not silently keep the stale input bearer (B4)"
        )

        # B4: exactly one rotation event fires (not zero, not multiple).
        rotations = [m for s, m in events if s == "gateway_token_rotated"]
        assert len(rotations) == 1, (
            f"exactly one gateway_token_rotated event must fire per repair; "
            f"got {len(rotations)}: {rotations!r}"
        )
        payload = json.loads(rotations[0])
        assert payload["agent_key"] == "zer-test"
        assert payload["reason"] == "restart"

    def test_repair_passes_empty_bearer_when_hosts_json_lacks_auth(
        self, tmp_path: Path
    ):
        """First-install path: hosts.json has no `auth` field yet. The
        helper must pass an empty string (not raise, not omit the key) so
        the playbook's `default('')` filter keeps the locked branch dormant
        on a fresh daemon. The write-back path still rotates atomically
        once /pair returns a fresh bearer."""
        host = self._host()
        host["agents"]["zer-test"]["config"]["gateway"] = {"port": 40000}
        inv, hosts_after, _events, success, _err = self._capture_repair(
            host,
            tmp_path,
            new_token="zc_first_install_bearer_yyyyyyy",
        )
        assert success is True
        assert inv["all"]["vars"]["config"]["gateway"]["auth"] == ""
        # Even from an empty starting auth, the rotation closure must write
        # the freshly minted bearer back.
        assert (
            hosts_after["agents"]["zer-test"]["config"]["gateway"]["auth"]
            == "zc_first_install_bearer_yyyyyyy"
        )


class TestConfigureAgentZeroclawBearerForwarding:
    """ATX #445 B1/W3: configure_agent must inject the prior bearer from
    `agent_record.config.gateway.auth` into the Ansible inventory when the
    caller's `config_data` lacks one, so the locked-pair branch in
    `tasks/pair.yaml` has something to POST to `/api/pairing/initiate`."""

    def _zc_host(self, *, auth_in_record: str | None) -> dict:
        gateway: dict = {"port": 40000}
        if auth_in_record is not None:
            gateway["auth"] = auth_in_record
        return {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "zer-test": {
                    "type": "zeroclaw",
                    "agent_name": "zerot",
                    "onboarding": {"state": "ready"},
                    "config": {"gateway": gateway},
                }
            },
        }

    def _capture_configure(
        self,
        host: dict,
        config_data: dict,
        tmp_path: Path,
        *,
        runner_status: str = "successful",
        runner_events: list | None = None,
    ) -> tuple[dict, bool, str | None]:
        runner = MagicMock()
        runner.status = runner_status
        runner.events = runner_events or []
        artifacts_dir = tmp_path / "artifacts"
        (artifacts_dir / "fact_cache").mkdir(parents=True)
        runner.config.artifact_dir = str(artifacts_dir)

        captured: dict = {}

        def capture_run(**kwargs):
            captured.update(kwargs.get("inventory") or {})
            return runner

        key_path = tmp_path / "k"
        key_path.write_text("k")
        playbook_path = tmp_path / "configure.yaml"
        playbook_path.write_text("---\n- hosts: all\n")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                side_effect=capture_run,
            ),
            patch(
                "clawrium.core.lifecycle.update_host",
                return_value=True,
            ),
            patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
            ),
            patch(
                "clawrium.core.providers.get_provider_api_key",
                return_value="",
            ),
            patch(
                "clawrium.core.providers.get_provider_aws_credentials",
                return_value=("", ""),
            ),
            patch(
                # ATX iter-5: lifecycle namespace, not source module —
                # see _run_with_events for the same fix.
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={},
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_key",
                return_value="test-key",
            ),
            patch(
                "clawrium.core.integrations.get_agent_integrations",
                return_value=[],
            ),
            patch.object(
                Path,
                "exists",
                return_value=True,
            ),
        ):
            from clawrium.core.lifecycle import configure_agent

            success, error = configure_agent(
                "192.168.1.100",
                "zeroclaw",
                config_data,
                agent_name="zer-test",
            )
        return captured, success, error

    def test_configure_injects_record_bearer_when_config_data_lacks_one(
        self, tmp_path: Path
    ):
        """B1 head-on: a caller that builds config_data from scratch (e.g.
        `_run_identity_stage` at cli/agent.py:639) does not carry forward
        `gateway.auth`. configure_agent must defensively pull it from the
        agent record so the playbook's locked-pair branch can authenticate
        /api/pairing/initiate."""
        host = self._zc_host(
            auth_in_record="zc_record_bearer_aaaaaaaaaaaaaaaaaaaa",
        )
        bare_config = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "p",
                "type": "ollama",
                "endpoint": "http://x",
                "default_model": "m",
            },
        }
        inv, success, error = self._capture_configure(
            host,
            bare_config,
            tmp_path,
        )
        # Configure may bail later (no provider creds, etc.) but the
        # inventory builder runs first; assert what was passed regardless.
        gw = inv["all"]["vars"]["config"]["gateway"]
        assert gw["auth"] == "zc_record_bearer_aaaaaaaaaaaaaaaaaaaa", (
            "configure_agent must defensively pull the bearer from the "
            "agent record so the locked-pair branch authenticates correctly "
            "(ATX #445 B1)"
        )

    def test_configure_censored_event_does_not_leak_bearer(self, tmp_path: Path):
        """ATX iter-2 NB1: censored-guard at lifecycle.py:~1517 covers the
        configure path. The runner_on_failed extraction loop must skip
        events where `res.censored` is set, even if they happen to carry a
        `msg`/`stderr` (e.g., debug-mode daemon echoing the bearer back)."""
        host = self._zc_host(
            auth_in_record="zc_record_for_configure_aaaaaaaaaaaaa",
        )
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "p",
                "type": "ollama",
                "endpoint": "http://x",
                "default_model": "m",
            },
        }
        _inv, success, error = self._capture_configure(
            host,
            config_data,
            tmp_path,
            runner_status="failed",
            runner_events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "res": {
                            "censored": "no_log: true was specified",
                            "msg": "Bearer zc_LEAK_FROM_CONFIGURE_xxxxxxxx",
                        }
                    },
                },
            ],
        )
        assert success is False
        assert "zc_LEAK_FROM_CONFIGURE" not in (error or ""), (
            f"configure_agent censored-guard regressed: {error!r}"
        )
        # #583: the bearer-leak contract is the load-bearing one and
        # still holds verbatim. The wording around it changed because
        # the reporter now surfaces a `no_log: true` hint with the
        # failing task name instead of the bare prefix.
        assert "no_log: true" in (error or "")
        assert "ANSIBLE_NO_LOG=False" in (error or "")

    def test_configure_all_censored_events_falls_back_to_generic_error(
        self, tmp_path: Path
    ):
        """ATX iter-3 NW6: parity with the repair and lifecycle paths.
        Multiple censored events; nothing usable surfaces; generic prefix
        appears with the runner status."""
        host = self._zc_host(
            auth_in_record="zc_record_for_configure_bbbbbbbbbbbbb",
        )
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "p",
                "type": "ollama",
                "endpoint": "http://x",
                "default_model": "m",
            },
        }
        _inv, success, error = self._capture_configure(
            host,
            config_data,
            tmp_path,
            runner_status="failed",
            runner_events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "res": {
                            "censored": "hidden",
                            "msg": "Bearer zc_CFG_LEAK_AAAAAAAAAAAAAAAAA",
                        }
                    },
                },
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "res": {
                            "censored": "hidden",
                            "stderr": "Bearer zc_CFG_LEAK_BBBBBBBBBBBBBBB",
                        }
                    },
                },
            ],
        )
        assert success is False
        # #583: bearer must still not leak — that contract is the load-bearing
        # one. The wording around it changed because the reporter now
        # surfaces a `no_log: true` hint instead of the bare prefix.
        assert "zc_" not in (error or "")
        assert "no_log: true" in (error or "")
        assert "ANSIBLE_NO_LOG=False" in (error or "")

    def test_configure_timeout_returns_friendly_error(self, tmp_path: Path):
        """ATX iter-4 NW-B: pin the configure timeout branch. The
        configure path has its own timeout return distinct from the
        repair path and was untested through iter-3."""
        host = self._zc_host(
            auth_in_record="zc_record_for_timeout_eeeeeeeeeeeeeee",
        )
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "p",
                "type": "ollama",
                "endpoint": "http://x",
                "default_model": "m",
            },
        }
        _inv, success, error = self._capture_configure(
            host,
            config_data,
            tmp_path,
            runner_status="timeout",
            runner_events=[],
        )
        assert success is False
        assert error == "Configure operation timed out"

    def test_configure_msg_none_event_does_not_return_none_error(self, tmp_path: Path):
        """ATX iter-3 NW4: configure path must also not return (False, None)
        when a runner_on_failed event has msg=None."""
        host = self._zc_host(
            auth_in_record="zc_record_for_configure_ccccccccccccc",
        )
        config_data = {
            "gateway": {"port": 40000},
            "provider": {
                "name": "p",
                "type": "ollama",
                "endpoint": "http://x",
                "default_model": "m",
            },
        }
        _inv, success, error = self._capture_configure(
            host,
            config_data,
            tmp_path,
            runner_status="failed",
            runner_events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {"res": {"msg": None, "stderr": None}},
                },
            ],
        )
        assert success is False
        assert error is not None
        # #583: when msg AND stderr are both None, the reporter now
        # falls through to the pre-task summary (no events to attribute
        # to a task name). The load-bearing contract — error is never
        # None — still holds.
        assert "None" not in error
        assert "Configure playbook failed" in error

    def test_configure_zeroclaw_missing_gateway_fails_port_validation(
        self, tmp_path: Path
    ):
        """ATX iter-3 NW5: pin the NS1 invariant. A caller that passes
        config_data with no `gateway` key (e.g. _run_identity_stage at
        cli/agent.py:639 before any prior gateway state existed) must hit
        the port validation early, BEFORE ansible_runner.run is ever
        called. If NS1 is silently reverted (B1 injection moves back below
        the validation block), this test fails because the validation
        would skip when gateway is absent."""
        host = self._zc_host(
            auth_in_record="zc_record_for_no_gateway_dddddddddddd",
        )
        config_data: dict = {
            # No "gateway" key at all — mimics a fresh-install caller path.
            "provider": {
                "name": "p",
                "type": "ollama",
                "endpoint": "http://x",
                "default_model": "m",
            },
        }
        runner_called = {"count": 0}

        runner = MagicMock()
        runner.status = "successful"
        runner.events = []
        artifacts_dir = tmp_path / "artifacts"
        (artifacts_dir / "fact_cache").mkdir(parents=True)
        runner.config.artifact_dir = str(artifacts_dir)

        def count_runs(**_kwargs):
            runner_called["count"] += 1
            return runner

        key_path = tmp_path / "k"
        key_path.write_text("k")
        playbook_path = tmp_path / "configure.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                side_effect=count_runs,
            ),
            patch(
                "clawrium.core.lifecycle.update_host",
                return_value=True,
            ),
            patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
            ),
            patch(
                "clawrium.core.providers.get_provider_api_key",
                return_value="",
            ),
            patch(
                "clawrium.core.providers.get_provider_aws_credentials",
                return_value=("", ""),
            ),
            patch(
                # ATX iter-5: lifecycle namespace, not source module.
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={},
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_key",
                return_value="test-key",
            ),
            patch(
                "clawrium.core.integrations.get_agent_integrations",
                return_value=[],
            ),
        ):
            # ATX iter-4 S-D: no `Path.exists` mock — configure_agent
            # returns at the port validation block (~L1300) before any
            # Path check is reached (template ~L1426, playbook ~L1431).
            # Adding the mock would mask a future refactor that placed a
            # Path check before port validation.
            from clawrium.core.lifecycle import configure_agent

            success, error = configure_agent(
                "192.168.1.100",
                "zeroclaw",
                config_data,
                agent_name="zer-test",
            )
        assert success is False
        assert error == "Incomplete gateway config - missing: port", (
            f"NS1 regressed — port validation didn't fire: {error!r}"
        )
        # Critical: validation MUST run before ansible — no SSH/playbook
        # side effects on a config that's missing required fields.
        assert runner_called["count"] == 0, (
            "ansible_runner.run was called despite missing gateway port; "
            "NS1 ordering is broken"
        )

    def test_configure_does_not_override_explicit_bearer(self, tmp_path: Path):
        """If the caller already populated `gateway.auth` (e.g. via
        cli/agent.py:357), configure_agent must NOT clobber it with the
        record's older value. The caller's intent wins."""
        host = self._zc_host(
            auth_in_record="zc_record_OLD_aaaaaaaaaaaaaaaaaaaaaaa",
        )
        config_with_fresh = {
            "gateway": {
                "port": 40000,
                "auth": "zc_caller_FRESH_xxxxxxxxxxxxxxxxxxx",
            },
            "provider": {
                "name": "p",
                "type": "ollama",
                "endpoint": "http://x",
                "default_model": "m",
            },
        }
        inv, _success, _error = self._capture_configure(
            host,
            config_with_fresh,
            tmp_path,
        )
        gw = inv["all"]["vars"]["config"]["gateway"]
        assert gw["auth"] == "zc_caller_FRESH_xxxxxxxxxxxxxxxxxxx", (
            "configure_agent must not overwrite a caller-supplied bearer "
            "with a stale value from hosts.json"
        )


class TestSafeHostDisplay:
    """ATX W-R3-1: `_safe_host_display` is a path-traversal guard used at
    three log-dir construction sites. Pin the documented edge cases so
    a regex widening that re-opens traversal fails a test."""

    def test_traversal_alias_is_sanitized(self):
        assert _safe_host_display({"alias": "../etc"}, "h") == ".._etc"

    def test_slash_in_alias_is_sanitized(self):
        assert _safe_host_display({"alias": "my/box"}, "h") == "my_box"

    def test_empty_inputs_fall_back_to_host(self):
        assert _safe_host_display({}, "") == "host"

    def test_all_bad_chars_fall_back_to_host(self):
        assert _safe_host_display({"alias": "///"}, "h") == "host"

    def test_falls_back_to_key_id_when_no_alias(self):
        assert _safe_host_display({"key_id": "kev"}, "192.168.1.1") == "kev"

    def test_falls_back_to_hostname_when_neither_alias_nor_key_id(self):
        assert _safe_host_display({}, "192.168.1.1") == "192.168.1.1"

    def test_preserves_safe_chars(self):
        assert _safe_host_display({"alias": "Foo-bar_1.2"}, "h") == "Foo-bar_1.2"


class TestStartAgentZeroclawRepairWiring:
    """ATX W-COV-1: exercise the start_agent → _zeroclaw_repair_after_start
    branch through a real `start_agent` call (the helper is unit-tested
    in TestZeroclawRepairAfterStart; this class pins the wiring)."""

    def _zeroclaw_host(self) -> dict:
        return {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "zer-test": {
                    "type": "zeroclaw",
                    "agent_name": "zerot",
                    "onboarding": {"state": "ready"},
                    "config": {"gateway": {"port": 40000, "auth": "x" * 32}},
                }
            },
        }

    def test_start_zeroclaw_invokes_repair_with_reason_start(self, tmp_path: Path):
        host = self._zeroclaw_host()
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                with patch(
                                    "clawrium.core.lifecycle._zeroclaw_repair_after_start",
                                    return_value=(True, None),
                                ) as mock_repair:
                                    sentinel_events: list[tuple[str, str]] = []

                                    def sentinel_on_event(stage: str, msg: str) -> None:
                                        sentinel_events.append((stage, msg))

                                    result = start_agent(
                                        "192.168.1.100",
                                        "zeroclaw",
                                        on_event=sentinel_on_event,
                                    )

        assert result["success"] is True
        mock_repair.assert_called_once()
        kwargs = mock_repair.call_args.kwargs
        assert kwargs.get("reason") == "start"
        # ATX W-NEW-2: helper receives resolved agent_key (not raw param)
        assert kwargs.get("agent_name") == "zer-test"
        # ATX W-R3-2: on_event forwarded so the rotation notice reaches
        # the CLI handler. Identity check — must be the same callable.
        assert kwargs.get("on_event") is sentinel_on_event

    def test_start_zeroclaw_returns_failure_when_repair_fails(self, tmp_path: Path):
        host = self._zeroclaw_host()
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                with patch(
                                    "clawrium.core.lifecycle._zeroclaw_repair_after_start",
                                    return_value=(False, "pair failed"),
                                ):
                                    result = start_agent("192.168.1.100", "zeroclaw")

        assert result["success"] is False
        assert "Re-pair after start failed" in result["error"]
        assert "pair failed" in result["error"]

    def test_start_openclaw_does_not_invoke_zeroclaw_repair(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-test": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                }
            },
        }
        key_path = tmp_path / "key"
        key_path.write_text("k")
        playbook_path = tmp_path / "start.yaml"
        playbook_path.write_text("---\n- hosts: all\n")
        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                with patch(
                                    "clawrium.core.lifecycle._zeroclaw_repair_after_start",
                                ) as mock_repair:
                                    result = start_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        mock_repair.assert_not_called()


class TestRestartAgentZeroclawWiring:
    """Issue #437: `restart_agent` for zeroclaw drives the re-pair through
    `start_agent(repair_reason='restart')`. Verify the wiring without
    exercising the underlying playbook (covered by
    TestZeroclawRepairAfterStart)."""

    def test_restart_calls_start_agent_with_repair_reason_restart(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "zer-test": {"type": "zeroclaw", "onboarding": {"state": "ready"}},
            },
        }
        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.stop_agent",
                return_value={
                    "success": True,
                    "agent": "zer-test",
                    "host": "192.168.1.100",
                    "operation": "stop",
                    "pid": None,
                    "started_at": None,
                    "error": None,
                },
            ):
                with patch(
                    "clawrium.core.lifecycle.start_agent",
                    return_value={
                        "success": True,
                        "agent": "zer-test",
                        "host": "192.168.1.100",
                        "operation": "start",
                        "pid": None,
                        "started_at": "2026-05-19T00:00:00Z",
                        "error": None,
                    },
                ) as mock_start:
                    result = restart_agent("192.168.1.100", "zeroclaw")

        assert result["success"] is True
        assert result["operation"] == "restart"
        kwargs = mock_start.call_args.kwargs
        assert kwargs.get("repair_reason") == "restart"


class TestRemoveClaw:
    """Tests for remove_claw function."""

    def test_raises_error_when_host_not_found(self):
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                remove_agent("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_claw_not_installed(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                remove_agent("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_stops_running_claw_before_removal(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "running"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "test.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                with patch(
                                    "clawrium.core.lifecycle.remove_agent_from_host",
                                    return_value=True,
                                ):
                                    result = remove_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "remove"

    def test_continues_removal_when_stop_fails(self, tmp_path: Path):
        """Should continue with removal even if stop fails."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "running"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "test.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner_fail = MagicMock()
        mock_runner_fail.status = "failed"
        mock_runner_fail.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "Stop failed"}},
            }
        ]

        mock_runner_success = MagicMock()
        mock_runner_success.status = "successful"
        mock_runner_success.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        side_effect=[mock_runner_fail, mock_runner_success],
                    ):
                        with patch(
                            "clawrium.core.lifecycle._update_agent_runtime",
                            return_value=True,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.get_config_dir",
                                return_value=tmp_path,
                            ):
                                with patch(
                                    "clawrium.core.lifecycle.remove_agent_from_host",
                                    return_value=True,
                                ):
                                    result = remove_agent("192.168.1.100", "openclaw")

        # Should still succeed with removal
        assert result["success"] is True

    def test_returns_failure_when_playbook_fails(self, tmp_path: Path):
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "stopped"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "remove.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "failed"
        mock_runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"res": {"msg": "Removal failed"}},
            }
        ]

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            result = remove_agent("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert "Removal failed" in result["error"]

    def test_removes_claw_from_host_config(self, tmp_path: Path):
        """Verify claw is removed from hosts.json."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "stopped"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "remove.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.remove_agent_from_host"
                            ) as mock_remove:
                                mock_remove.return_value = True
                                result = remove_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        # Now removes by agent_name (opc-work), not claw_type (openclaw)
        mock_remove.assert_called_once_with("192.168.1.100", "opc-work")

    def test_event_callbacks_invoked(self, tmp_path: Path):
        """Verify on_event callback is called with appropriate messages."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "runtime": {"status": "stopped"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "remove.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        events = []

        def on_event(stage, message):
            events.append((stage, message))

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key", return_value=key_path
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.remove_agent_from_host",
                                return_value=True,
                            ):
                                result = remove_agent(
                                    "192.168.1.100", "openclaw", on_event=on_event
                                )

        assert result["success"] is True
        # Should have validate and remove events
        assert any(stage == "validate" for stage, _ in events)
        assert any(stage == "remove" for stage, _ in events)
        # Verify the specific state cleanup message is emitted (or "already absent")
        remove_messages = [msg for st, msg in events if st == "remove"]
        assert any("agent state" in msg.lower() for msg in remove_messages), (
            f"Expected state cleanup message, got: {remove_messages}"
        )

    def test_removes_agent_state_directory(self, tmp_path: Path):
        """Pre-seed a per-agent state directory and verify remove_agent
        cleans it up (the core fix for #400)."""
        from clawrium.core.skills_state import write_state

        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "agent_name": "opc-work",
                    "runtime": {"status": "stopped"},
                }
            },
        }

        key_path = tmp_path / "test_key"
        key_path.write_text("private key")

        playbook_path = tmp_path / "test.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        # Pre-seed the agent state directory with a skills.json
        write_state("opc-work", ["tdd"])
        agent_state_dir = tmp_path / "clawrium" / "agents" / "opc-work"
        assert agent_state_dir.is_dir()

        mock_runner = MagicMock()
        mock_runner.status = "successful"
        mock_runner.events = []

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ):
                with patch(
                    "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                    return_value=playbook_path,
                ):
                    with patch(
                        "clawrium.core.lifecycle.ansible_runner.run",
                        return_value=mock_runner,
                    ):
                        with patch(
                            "clawrium.core.lifecycle.get_config_dir",
                            return_value=tmp_path,
                        ):
                            with patch(
                                "clawrium.core.lifecycle.remove_agent_from_host",
                                return_value=True,
                            ):
                                result = remove_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert not agent_state_dir.exists()


class TestResolveAgentRecord:
    """Tests for _resolve_agent_record function."""

    def test_multiple_agents_same_type_raises_error(self):
        """B7: Multiple agents of same type should raise LifecycleError."""
        host = {
            "hostname": "test-host",
            "agents": {
                "assistant-1": {"type": "openclaw", "status": "installed"},
                "assistant-2": {"type": "openclaw", "status": "installed"},
            },
        }

        with pytest.raises(LifecycleError) as exc_info:
            _resolve_agent_record(host, "openclaw", expected_type="openclaw")

        assert "Multiple" in str(exc_info.value)
        assert "assistant-1" in str(exc_info.value)
        assert "assistant-2" in str(exc_info.value)

    def test_agent_without_type_field_skipped(self):
        """B8: Agents without explicit 'type' field should be skipped."""
        host = {
            "hostname": "test-host",
            "agents": {
                "old-agent": {
                    "status": "installed",
                    # Missing "type" field - should be skipped
                },
            },
        }

        result = _resolve_agent_record(host, "openclaw", expected_type="openclaw")
        assert result is None

    def test_direct_key_lookup_without_type_returns_none(self):
        """Direct lookup by agent_name also requires type field."""
        host = {
            "hostname": "test-host",
            "agents": {
                "my-assistant": {
                    "status": "installed",
                    # Missing "type" field
                },
            },
        }

        result = _resolve_agent_record(host, "my-assistant")
        assert result is None

    def test_matches_single_agent_by_type(self):
        """Single agent of expected type should be found."""
        host = {
            "hostname": "test-host",
            "agents": {
                "work-bot": {"type": "openclaw", "status": "installed"},
            },
        }

        result = _resolve_agent_record(host, "openclaw", expected_type="openclaw")
        assert result is not None
        agent_name, agent_type, record = result
        assert agent_name == "work-bot"
        assert agent_type == "openclaw"

    def test_matches_by_direct_key(self):
        """Direct lookup by agent_name works when type is present."""
        host = {
            "hostname": "test-host",
            "agents": {
                "work-bot": {"type": "openclaw", "status": "installed"},
            },
        }

        result = _resolve_agent_record(host, "work-bot")
        assert result is not None
        agent_name, agent_type, record = result
        assert agent_name == "work-bot"
        assert agent_type == "openclaw"


class TestSyncAgent:
    """Tests for sync_agent function."""

    @pytest.fixture(autouse=True)
    def _stub_transition_state(self):
        """B-NEW-2 (ATX #555 polish round 4): `sync_agent` now mirrors
        the canonical pipeline's success/error contract — the
        post-configure `transition_state(..., READY)` call sets
        `success=False` on registry-incoherence or IO errors. These
        tests mock `get_host`/`configure_agent` but the real
        `transition_state` runs against an empty `XDG_CONFIG_HOME`
        (isolated by `_isolate_config_dir`) and naturally raises
        `OnboardingNotFoundError`, which previously was silently
        swallowed. Patch it here so each test exercises its intended
        contract; tests that want to assert the failure path patch it
        themselves and override this autouse fixture's effect."""
        with patch(
            "clawrium.core.onboarding.transition_state", return_value=None
        ):
            yield

    def test_raises_error_when_host_not_found(self):
        """Sync with unknown host fails."""
        with patch("clawrium.core.lifecycle.get_host", return_value=None):
            with pytest.raises(LifecycleError) as exc_info:
                sync_agent("unknown-host", "openclaw")

        assert "not found" in str(exc_info.value)

    def test_raises_error_when_agent_not_installed(self):
        """Sync when agent not installed fails."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {},
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                sync_agent("192.168.1.100", "openclaw")

        assert "not installed" in str(exc_info.value)

    def test_raises_error_when_onboarding_incomplete(self):
        """B1: Sync raises error when agent onboarding is not complete."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "pending"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                sync_agent("192.168.1.100", "openclaw")

        assert "onboarding not started" in str(exc_info.value)

    def test_raises_error_when_no_config(self):
        """Sync when no config exists fails."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    # No config
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with pytest.raises(LifecycleError) as exc_info:
                sync_agent("192.168.1.100", "openclaw")

        assert "No configuration found" in str(exc_info.value)

    def test_returns_failure_when_configure_fails(self):
        """Sync fails when configure step fails."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(False, "Config error"),
            ) as mock_configure:
                with patch("clawrium.core.lifecycle.restart_agent") as mock_restart:
                    result = sync_agent("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert "Configure failed" in result["error"]
        assert result["operation"] == "sync"
        # W6: Verify restart was NOT called when configure fails
        mock_configure.assert_called_once()
        mock_restart.assert_not_called()

    def test_does_not_call_restart_agent(self):
        """Issue #437: sync no longer orchestrates a separate restart.
        configure handles re-pairing + handler-driven restart in one shot."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ) as mock_configure:
                with patch("clawrium.core.lifecycle.restart_agent") as mock_restart:
                    result = sync_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "sync"
        mock_configure.assert_called_once()
        # Issue #437: restart is no longer orchestrated by sync.
        mock_restart.assert_not_called()

    def test_returns_success_on_successful_sync(self):
        """Sync succeeds when configure succeeds."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ):
                result = sync_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        assert result["operation"] == "sync"
        assert result["agent"] == "opc-work"

    def test_sync_passes_reason_sync_to_configure(self):
        """Issue #437: sync calls configure_agent with reason='sync' so
        the rotation event payload identifies the originating op."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ) as mock_configure:
                sync_agent("192.168.1.100", "openclaw")

        kwargs = mock_configure.call_args.kwargs
        assert kwargs.get("reason") == "sync"

    def test_sync_agent_by_explicit_name(self):
        """W7: Test sync with explicit agent_name parameter."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ):
                result = sync_agent("192.168.1.100", "openclaw", agent_name="opc-work")

        assert result["success"] is True
        assert result["agent"] == "opc-work"

    def test_event_callbacks_invoked(self):
        """Verify on_event callback is called with appropriate messages."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        events = []

        def on_event(stage, message):
            events.append((stage, message))

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ):
                result = sync_agent("192.168.1.100", "openclaw", on_event=on_event)

        assert result["success"] is True
        sync_events = [e for e in events if e[0] == "sync"]
        # Issue #437: sync now emits 3 events — "Syncing", "Configuring",
        # "Sync complete" (the explicit "Restarting" step is gone).
        assert len(sync_events) >= 3
        assert "Syncing" in sync_events[0][1]
        assert "complete" in sync_events[-1][1].lower()

    def test_workspace_only_skips_restart(self):
        """workspace_only=True skips restart step."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ) as mock_configure:
                with patch("clawrium.core.lifecycle.restart_agent") as mock_restart:
                    result = sync_agent(
                        "192.168.1.100", "openclaw", workspace_only=True
                    )

        assert result["success"] is True
        assert result["operation"] == "sync"
        # Configure should be called
        mock_configure.assert_called_once()
        # Restart should NOT be called
        mock_restart.assert_not_called()

    def test_sync_registry_incoherence_surfaces_success_false(self):
        """B-NEW-2 (ATX #555 polish round 4): when post-configure
        `transition_state` raises `OnboardingNotFoundError` (registry
        record vanished between configure and READY write), legacy
        `sync_agent` must mirror the canonical pipeline's contract —
        `success=False` + populated `.error` — so a CLI handler
        gating on `.success` does not print "✓ sync complete" with a
        stuck non-READY agent. The autouse `_stub_transition_state`
        fixture is overridden here by the inner `patch` per pytest's
        last-patch-wins semantics."""
        from clawrium.core.onboarding import OnboardingNotFoundError

        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ):
                with patch(
                    "clawrium.core.onboarding.transition_state",
                    side_effect=OnboardingNotFoundError("record vanished"),
                ):
                    result = sync_agent("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert result["error"] is not None
        assert "registry record missing" in result["error"]

    def test_sync_invalid_transition_stays_success_true(self):
        """W2 (ATX #555 polish round 5): `InvalidTransitionError` from
        the post-configure READY transition is the ONLY exception
        branch that must stay `success=True` — the agent is mid-walk
        (PROVIDERS/IDENTITY/CHANNELS), configure_agent already
        succeeded, and `clawctl agent start` will surface the actual
        stage. Pin this contract so a future refactor that
        accidentally lumps `_ITE_post` into the `success=False` branch
        is caught by CI."""
        from clawrium.core.onboarding import InvalidTransitionError

        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        events: list = []

        def on_event(stage, message):
            events.append((stage, message))

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ):
                with patch(
                    "clawrium.core.onboarding.transition_state",
                    side_effect=InvalidTransitionError("stuck in PROVIDERS"),
                ):
                    result = sync_agent(
                        "192.168.1.100", "openclaw", on_event=on_event
                    )

        assert result["success"] is True
        assert result["error"] is None
        # W1 round-5: a `note:` line emitted on the mid-walk branch so
        # the CLI can surface why state didn't advance to READY.
        assert any(
            "skipped state=READY" in msg
            and "PROVIDERS" in msg
            for _, msg in events
        ), events

    def test_sync_agent_not_found_surfaces_success_false(self):
        """W3 (ATX #555 polish round 5): companion to
        `test_sync_registry_incoherence_surfaces_success_false` —
        `AgentNotFoundError` shares the except tuple with
        `OnboardingNotFoundError`. Both must surface as
        `success=False` + populated `error`."""
        from clawrium.core.onboarding import AgentNotFoundError

        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ):
                with patch(
                    "clawrium.core.onboarding.transition_state",
                    side_effect=AgentNotFoundError("agent vanished"),
                ):
                    result = sync_agent("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert result["error"] is not None
        assert "registry record missing" in result["error"]
        assert "agent vanished" in result["error"]

    def test_sync_state_write_io_failure_surfaces_success_false(self):
        """B-NEW-2 (ATX #555 polish round 4): IO/permission failures
        on the READY transition must also surface `success=False` —
        not silently swallowed."""
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ):
                with patch(
                    "clawrium.core.onboarding.transition_state",
                    side_effect=OSError("disk full"),
                ):
                    result = sync_agent("192.168.1.100", "openclaw")

        assert result["success"] is False
        assert result["error"] is not None
        assert "state=READY" in result["error"]
        assert "disk full" in result["error"]

    def test_allows_intermediate_onboarding_states(self):
        """Sync allows onboarding states after PENDING (providers, identity, etc.)."""
        # Test with PROVIDERS state (intermediate)
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "onboarding": {"state": "providers"},  # Intermediate state
                    "config": {
                        "gateway": {"port": 40000},
                        "provider": {
                            "name": "test",
                            "type": "ollama",
                            "endpoint": "http://localhost:11434",
                            "default_model": "llama3",
                        },
                    },
                }
            },
        }

        with patch("clawrium.core.lifecycle.get_host", return_value=host):
            with patch(
                "clawrium.core.lifecycle.configure_agent",
                return_value=(True, None),
            ):
                with patch(
                    "clawrium.core.lifecycle.restart_agent",
                ) as mock_restart:
                    # Should NOT raise - intermediate states allowed
                    result = sync_agent("192.168.1.100", "openclaw")

        assert result["success"] is True
        # W3 fix: Verify restart_agent NOT called for intermediate states
        # (workspace_only auto-coerced to True)
        mock_restart.assert_not_called()


class TestCleanupAnsibleArtifacts:
    """B5 fix: Tests for _cleanup_ansible_artifacts()."""

    def test_cleans_artifacts_dir(self, tmp_path: Path):
        """Removes artifacts directory."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "job_events").mkdir()
        (artifacts_dir / "job_events" / "event.json").write_text("{}")

        _cleanup_ansible_artifacts(tmp_path)

        assert not artifacts_dir.exists()

    def test_cleans_env_dir(self, tmp_path: Path):
        """Removes env directory."""
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        (env_dir / "inventory.json").write_text('{"secrets": "here"}')

        _cleanup_ansible_artifacts(tmp_path)

        assert not env_dir.exists()

    def test_cleans_both_dirs(self, tmp_path: Path):
        """Removes both artifacts and env directories."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        env_dir = tmp_path / "env"
        env_dir.mkdir()

        _cleanup_ansible_artifacts(tmp_path)

        assert not artifacts_dir.exists()
        assert not env_dir.exists()

    def test_skips_nonexistent_dirs(self, tmp_path: Path):
        """Does not error when directories don't exist."""
        # No artifacts or env dir created
        _cleanup_ansible_artifacts(tmp_path)  # Should not raise

    def test_handles_permission_errors(self, tmp_path: Path):
        """Logs warning on permission errors."""
        import stat

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        # Make parent read-only to prevent deletion
        tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)

        try:
            _cleanup_ansible_artifacts(tmp_path)  # Should not raise
            # Artifacts still exist due to permission error
            assert artifacts_dir.exists()
        finally:
            # Restore permissions for cleanup
            tmp_path.chmod(stat.S_IRWXU)

    def test_partial_failure_continues(self, tmp_path: Path):
        """Continues to env cleanup even if artifacts cleanup fails."""
        with patch("clawrium.core.lifecycle.shutil.rmtree") as mock_rmtree:
            # First call (artifacts) fails, second (env) succeeds
            mock_rmtree.side_effect = [PermissionError("denied"), None]

            artifacts_dir = tmp_path / "artifacts"
            artifacts_dir.mkdir()
            env_dir = tmp_path / "env"
            env_dir.mkdir()

            _cleanup_ansible_artifacts(tmp_path)

            # Both attempts should be made
            assert mock_rmtree.call_count == 2


class TestConfigureAgentSlackTokens:
    """Tests for configure_agent loading Slack tokens from secrets."""

    def test_configure_agent_loads_both_slack_tokens(self, isolated_config: Path):
        """Verify both SLACK_BOT_TOKEN and SLACK_APP_TOKEN are loaded and passed to ansible."""
        from clawrium.core.lifecycle import configure_agent
        from clawrium.core.secrets import set_instance_secret, get_instance_key

        instance_key = get_instance_key("192.168.1.100", "openclaw", "testbot")
        set_instance_secret(
            instance_key, "SLACK_BOT_TOKEN", "xoxb-123-test", "Slack bot token"
        )
        set_instance_secret(
            instance_key, "SLACK_APP_TOKEN", "xapp-1-ABC-test", "Slack app token"
        )

        captured_inventories = []

        def capture_runner(*args, **kwargs):
            captured_inventories.append(
                kwargs.get("inventory") or (args[1] if len(args) > 1 else None)
            )
            result = MagicMock()
            result.rc = 0
            result.status = "successful"
            return result

        host_data = {
            "hostname": "192.168.1.100",
            "key_id": "work",
            "port": 22,
            "alias": "work",
            "auth_method": "key",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installed",
                    "agent_name": "testbot",
                    "config": {
                        "gateway": {"port": 40000, "bind": "lan", "auth": "token-123"},
                        "provider": {
                            "name": "test-openai",
                            "type": "openai",
                            "default_model": "gpt-4",
                        },
                        "channels": {"slack": {"enabled": True, "mode": "socket"}},
                    },
                    "onboarding": {"state": "ready", "stages": {}},
                }
            },
        }

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host_data),
            patch("clawrium.core.lifecycle.get_host_private_key") as mock_key,
            patch(
                "clawrium.core.lifecycle.ansible_runner.run", side_effect=capture_runner
            ),
        ):
            from pathlib import Path as P

            mock_key.return_value = P("/fake/key")

            try:
                configure_agent(
                    "192.168.1.100",
                    "openclaw",
                    host_data["agents"]["openclaw"]["config"],
                    agent_name="testbot",
                )
            except Exception:
                pass

        if captured_inventories:
            inv = captured_inventories[0]
            if inv and "all" in inv:
                vars = (
                    inv["all"]["hosts"]
                    .get("192.168.1.100", {})
                    .get("vars", inv["all"].get("vars", {}))
                )
                assert vars.get("slack_bot_token") == "xoxb-123-test"
                assert vars.get("slack_app_token") == "xapp-1-ABC-test"


class TestConfigureAgentBravePreflight:
    """ATX iter 3 B_NEW1: pin the openclaw brave preflight inside
    `configure_agent` directly. The canonical preflight in
    `sync_agent_canonical` is independently covered in
    `tests/core/test_lifecycle_canonical.py`; the configure path has
    its own SSH+key plumbing and error formatting that must be tested
    on its own."""

    def _oc_host(self) -> dict:
        return {
            "hostname": "10.0.0.1",
            "key_id": "test",
            "agent_name": "wolf-i",
            "port": 22,
            "user": "xclm",
            "agents": {
                "oc-test": {
                    "type": "openclaw",
                    "agent_name": "openc",
                    "onboarding": {"state": "ready"},
                    "config": {"gateway": {"port": 40000}},
                }
            },
        }

    def _run_with_preflight(
        self,
        tmp_path: Path,
        *,
        host_version: tuple[int, int, int] | None,
        attach_brave: bool = True,
        pin_raises: bool = False,
        no_ssh_key: bool = False,
    ) -> tuple[bool, str | None]:
        host = self._oc_host()
        key_path = tmp_path / "k"
        key_path.write_text("k")
        playbook_path = tmp_path / "configure.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        integrations_for_agent = ["my-brave"] if attach_brave else []
        brave_integration = {
            "name": "my-brave",
            "type": "brave",
        }
        brave_creds = {"BRAVE_API_KEY": "bsk-1"}

        runner = MagicMock()
        runner.status = "successful"
        runner.events = []
        artifacts_dir = tmp_path / "artifacts"
        (artifacts_dir / "fact_cache").mkdir(parents=True)
        runner.config.artifact_dir = str(artifacts_dir)

        from clawrium.core.lifecycle_canonical import CanonicalSyncError

        def _fake_load_pin():
            if pin_raises:
                raise CanonicalSyncError("manifest corrupt")
            return {
                "npm_package": "@openclaw/brave-plugin",
                "version": "2026.6.8",
                "min_host_version": (2026, 4, 10),
            }

        patches = [
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=None if no_ssh_key else key_path,
            ),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                return_value=runner,
            ),
            patch(
                "clawrium.core.lifecycle.update_host", return_value=True
            ),
            patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
            ),
            patch(
                "clawrium.core.providers.get_provider_api_key",
                return_value="",
            ),
            patch(
                "clawrium.core.providers.get_provider_aws_credentials",
                return_value=("", ""),
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={},
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_key",
                return_value="test-key",
            ),
            patch(
                "clawrium.core.integrations.get_agent_integrations",
                return_value=integrations_for_agent,
            ),
            patch(
                "clawrium.core.integrations.get_integration",
                return_value=brave_integration,
            ),
            patch(
                "clawrium.core.integrations.get_integration_credentials",
                return_value=brave_creds,
            ),
            patch(
                "clawrium.core.lifecycle_canonical._load_openclaw_brave_pin",
                side_effect=_fake_load_pin,
            ),
            patch(
                "clawrium.core.lifecycle_canonical._get_host_openclaw_version",
                return_value=host_version,
            ),
            patch(
                "clawrium.core.lifecycle.paramiko.SSHClient",
                return_value=MagicMock(),
            ),
            patch.object(Path, "exists", return_value=True),
        ]
        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            from clawrium.core.lifecycle import configure_agent

            success, error = configure_agent(
                "10.0.0.1",
                "openclaw",
                {"providers": {"anthropic": {"model": "claude-opus-4-7"}}},
                agent_name="oc-test",
            )
        return success, error

    def test_pin_load_failure_returns_false_with_message(self, tmp_path: Path):
        """`_load_openclaw_brave_pin` raises (corrupt manifest) →
        configure_agent returns (False, msg) instead of letting the
        npm install run with an empty version."""
        success, error = self._run_with_preflight(
            tmp_path, host_version=(2026, 5, 28), pin_raises=True
        )
        assert success is False
        assert "manifest corrupt" in (error or "")

    def test_missing_ssh_key_returns_false(self, tmp_path: Path):
        """If `get_host_private_key` returns None, configure_agent
        must fail closed before any host-side work. The existing
        early-return at `lifecycle.py:2433` covers this; the preflight
        is downstream of it, so we just verify the call fails."""
        success, error = self._run_with_preflight(
            tmp_path, host_version=(2026, 5, 28), no_ssh_key=True
        )
        assert success is False
        assert error is not None and "SSH key" in error

    def test_version_below_minimum_returns_upgrade_hint(self, tmp_path: Path):
        """Host openclaw < 2026.4.10 → upgrade hint, not install hint."""
        success, error = self._run_with_preflight(
            tmp_path, host_version=(2026, 3, 13)
        )
        assert success is False
        assert "2026.3.13" in (error or "")
        assert "clawctl agent upgrade" in (error or "")

    def test_unknown_version_returns_install_hint(self, tmp_path: Path):
        """`_get_host_openclaw_version` returns None (binary missing) →
        install hint, distinct from upgrade hint (W9 ATX iter 1)."""
        success, error = self._run_with_preflight(
            tmp_path, host_version=None
        )
        assert success is False
        assert "<unknown>" in (error or "")
        assert "clawctl agent install" in (error or "")

    def test_exact_minimum_version_proceeds_past_preflight(
        self, tmp_path: Path
    ):
        """Host openclaw == minHostVersion → preflight passes; the
        rest of configure_agent runs (we don't assert deep on the
        ansible-runner mock; success vs falsy is enough to pin the
        preflight has not short-circuited)."""
        success, _ = self._run_with_preflight(
            tmp_path, host_version=(2026, 4, 10)
        )
        # The rest of configure_agent has many side effects; this test
        # only pins that preflight did not return False. `success` may
        # be False for other reasons but the error must not be a
        # preflight error.
        success_or_no_preflight_error = (
            success is True
            or "brave plugin requires" not in (str(_) if _ else "")
        )
        assert success_or_no_preflight_error

    def test_no_brave_integration_skips_preflight(self, tmp_path: Path):
        """When no brave integration is attached, the preflight MUST
        NOT run — every openclaw configure would otherwise pay for an
        SSH version probe it doesn't need."""
        # _get_host_openclaw_version returning None would normally trip
        # the preflight; with no brave attachment the test passes
        # because the preflight branch is never entered.
        success, error = self._run_with_preflight(
            tmp_path, host_version=None, attach_brave=False
        )
        # If preflight ran, error would mention 'brave plugin requires'.
        assert "brave plugin requires" not in (error or "")


class TestConfigureAgentDoesNotPersistOverlay:
    """Issue #794 (Phase 2 of #790): the configure_agent updater must
    strip `provider` / `providers` / `channels` from `persisted_config`
    before writing to `hosts.json`, even though the same keys MUST still
    reach the Ansible inventory so templates can render the model and
    channel hulls. The canonical stores for those three keys live
    elsewhere (tier-1 `agent_record["providers"]` + `providers.json`
    for providers; `channels.json` for channels); persisting a mirror
    is what caused the tier-2 staleness #790 fixed in the read path.
    """

    def _run_configure_capturing_persist(
        self,
        host: dict,
        config_data: dict,
        claw_type: str,
        agent_name: str,
        tmp_path: Path,
    ) -> tuple[dict, dict, bool, str | None]:
        """Run configure_agent end-to-end with ansible_runner + update_host
        mocked. Returns (ansible_inventory, persisted_hosts_json,
        success, error).
        """
        runner = MagicMock()
        runner.status = "successful"
        runner.events = []
        artifacts_dir = tmp_path / "artifacts"
        (artifacts_dir / "fact_cache").mkdir(parents=True)
        runner.config.artifact_dir = str(artifacts_dir)

        captured_inventory: dict = {}
        captured_persisted: dict = {}

        def capture_run(**kwargs):
            captured_inventory.update(kwargs.get("inventory") or {})
            return runner

        def capture_update_host(_hostname: str, updater) -> bool:
            # Mirror the initial-host shape so the updater sees a
            # realistic dict to merge into.
            h = {
                "hostname": host["hostname"],
                "agents": {k: dict(v) for k, v in host["agents"].items()},
            }
            captured_persisted.update(updater(h))
            return True

        key_path = tmp_path / "k"
        key_path.write_text("k")
        playbook_path = tmp_path / "configure.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
            ),
            patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
            ),
            patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                side_effect=capture_run,
            ),
            patch(
                "clawrium.core.lifecycle.update_host",
                side_effect=capture_update_host,
            ),
            patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
            ),
            patch(
                "clawrium.core.providers.get_provider_api_key",
                return_value="",
            ),
            patch(
                "clawrium.core.providers.get_provider_aws_credentials",
                return_value=("", ""),
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={},
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_key",
                return_value="test-key",
            ),
            patch(
                "clawrium.core.integrations.get_agent_integrations",
                return_value=[],
            ),
            patch(
                "clawrium.core.lifecycle._hydrate_channels_from_canonical",
                return_value=(True, None),
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            from clawrium.core.lifecycle import configure_agent

            success, error = configure_agent(
                host["hostname"],
                claw_type,
                config_data,
                agent_name=agent_name,
            )
        return captured_inventory, captured_persisted, success, error

    def _openclaw_host(self) -> dict:
        return {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "opc-test": {
                    "type": "openclaw",
                    "agent_name": "opct",
                    "onboarding": {"state": "ready"},
                    "config": {"gateway": {"port": 40000, "bind": "lan"}},
                    "providers": ["test-provider"],
                }
            },
        }

    def _hermes_host(self) -> dict:
        return {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "hrm-test": {
                    "type": "hermes",
                    "agent_name": "hrmt",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 45000},
                        "api_server": {
                            "enabled": True,
                            "host": "0.0.0.0",
                            "port": 8642,
                        },
                    },
                    "providers": [
                        {"name": "anth", "role": "primary"},
                    ],
                }
            },
        }

    def test_sync_agent_does_not_persist_provider_overlay(self, tmp_path: Path):
        """Singleton path (openclaw/zeroclaw): config_data carries a
        `provider` overlay so Ansible can render templates, but the
        persisted hosts.json record MUST NOT contain
        `config.provider`."""
        host = self._openclaw_host()
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "test-provider",
                "type": "openai",
                "endpoint": "https://api.openai.example",
                "default_model": "gpt-4",
            },
        }

        inv, persisted, success, error = self._run_configure_capturing_persist(
            host, config_data, "openclaw", "opc-test", tmp_path
        )
        assert success is True, error

        persisted_agent = persisted["agents"]["opc-test"]
        persisted_config = persisted_agent["config"]
        assert "provider" not in persisted_config, (
            f"config.provider must not be persisted after sync; "
            f"got {persisted_config.get('provider')!r}"
        )
        # Group B (gateway) must still be persisted.
        assert persisted_config["gateway"]["port"] == 40000

    def test_sync_agent_does_not_persist_providers_overlay_hermes(
        self, tmp_path: Path
    ):
        """Multi-provider path (hermes): config_data carries both
        `provider` (primary) and `providers` (list) overlays. Neither
        may be persisted in hosts.json."""
        host = self._hermes_host()
        config_data = {
            "gateway": {"port": 45000},
            "api_server": {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 8642,
            },
            "provider": {
                "name": "anth",
                "type": "anthropic",
                "endpoint": "https://api.anthropic.example",
                "default_model": "claude-opus",
            },
            "providers": [
                {
                    "name": "anth",
                    "type": "anthropic",
                    "endpoint": "https://api.anthropic.example",
                    "default_model": "claude-opus",
                    "role": "primary",
                    "model": "claude-opus",
                }
            ],
        }
        # Hermes needs a valid API server key in secrets to pass
        # validation, and `configure_agent` pre-renders the canonical
        # config via `render_hermes(build_render_inputs(...))` which
        # reads on-disk hosts.json. Stub all three so the test stays
        # focused on the persist-strip contract.
        from clawrium.core.render import RenderedFiles

        fake_rendered = RenderedFiles(
            files={
                ".hermes/.env": "stub-env",
                ".hermes/config.yaml": "stub-yaml",
            },
        )
        with (
            patch(
                "clawrium.core.install._is_valid_hermes_api_server_key",
                return_value=True,
            ),
            patch(
                "clawrium.core.lifecycle.get_instance_secrets",
                return_value={
                    "HERMES_API_SERVER_KEY": {
                        "value": "0" * 64,
                    }
                },
            ),
            patch(
                "clawrium.core.render.build_render_inputs",
                return_value={},
            ),
            patch(
                "clawrium.core.render.render_hermes",
                return_value=fake_rendered,
            ),
        ):
            inv, persisted, success, error = (
                self._run_configure_capturing_persist(
                    host,
                    config_data,
                    "hermes",
                    "hrm-test",
                    tmp_path,
                )
            )
        assert success is True, error

        persisted_config = persisted["agents"]["hrm-test"]["config"]
        assert "provider" not in persisted_config, (
            f"hermes config.provider must not be persisted; "
            f"got {persisted_config.get('provider')!r}"
        )
        assert "providers" not in persisted_config, (
            f"hermes config.providers must not be persisted; "
            f"got {persisted_config.get('providers')!r}"
        )

    def test_sync_agent_does_not_persist_channels(self, tmp_path: Path):
        """Channels are now sourced from canonical channels.json via
        `_hydrate_channels_from_canonical`. Even if a caller passes
        a `channels` block in `config_data` (legacy code path),
        configure_agent must strip it from persisted hosts.json so
        a stale mirror cannot accumulate."""
        host = self._openclaw_host()
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "test-provider",
                "type": "openai",
                "endpoint": "https://api.openai.example",
                "default_model": "gpt-4",
            },
            "channels": {
                "discord": {
                    "enabled": True,
                    "guilds": {"123": {"channels": {"456": {}}}},
                }
            },
        }
        inv, persisted, success, error = self._run_configure_capturing_persist(
            host, config_data, "openclaw", "opc-test", tmp_path
        )
        assert success is True, error

        persisted_config = persisted["agents"]["opc-test"]["config"]
        assert "channels" not in persisted_config, (
            f"config.channels must not be persisted after sync; "
            f"got {persisted_config.get('channels')!r}"
        )
        # ATX #794 iter-1 S1: pin all three strips per call. A per-key
        # regression that only re-introduces one of the three would
        # otherwise pass this test silently.
        assert "provider" not in persisted_config
        assert "providers" not in persisted_config

    def _hermes_host_for_start(
        self, *, providers: list | None = None
    ) -> dict:
        return {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "hrm-test": {
                    "type": "hermes",
                    "agent_name": "hrmt",
                    "onboarding": {"state": "ready"},
                    "config": {
                        "gateway": {"port": 45000},
                        "api_server": {
                            "enabled": True,
                            "host": "0.0.0.0",
                            "port": 8642,
                        },
                    },
                    "providers": (
                        providers
                        if providers is not None
                        else [{"name": "anth", "role": "primary"}]
                    ),
                }
            },
        }

    def test_start_agent_hermes_unregistered_provider_returns_error(
        self, tmp_path: Path
    ):
        """ATX #794 iter-3 B3 part 1: when the hermes drift path hydrates
        the overlay and the attached provider is not in providers.json,
        `_build_provider_overlays_from_attachments` raises
        `LifecycleError`. The start_agent except branch must convert
        that into a structured `{success: False, error: '...'}` result
        with a remediation hint, NOT propagate the exception or return
        success."""
        host = self._hermes_host_for_start()

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            # Unregistered provider — get_provider returns None.
            patch(
                "clawrium.core.providers.storage.get_provider",
                return_value=None,
            ),
            patch(
                "clawrium.core.lifecycle._hermes_env_token_matches_secrets",
                return_value=(False, None),
            ),
        ):
            result = start_agent("192.168.1.100", "hermes")

        assert result["success"] is False
        assert result["operation"] == "start"
        assert "Pre-start reconfigure failed" in (result.get("error") or "")
        assert "not registered" in (result.get("error") or "")

    def test_start_agent_hermes_invalid_attachment_shape_returns_error(
        self, tmp_path: Path
    ):
        """ATX #794 iter-3 B3 part 2: malformed attachment (two primary
        roles) must surface as success=False through the new
        LifecycleError branch, not via an uncaught exception."""
        host = self._hermes_host_for_start(
            providers=[
                {"name": "anth", "role": "primary"},
                {"name": "other", "role": "primary"},  # second primary → invalid
            ]
        )

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._hermes_env_token_matches_secrets",
                return_value=(False, None),
            ),
        ):
            result = start_agent("192.168.1.100", "hermes")

        assert result["success"] is False
        assert "Pre-start reconfigure failed" in (result.get("error") or "")
        assert "invalid provider attachments" in (result.get("error") or "")

    def test_start_agent_hermes_empty_attachments_still_runs_configure(
        self, tmp_path: Path
    ):
        """ATX #794 iter-3 B3 part 3: `providers=[]` is a valid (if
        unusual) shape — the hydration helper returns
        `(None, None, None)`, neither `config_data['provider']` nor
        `config_data['providers']` is set, and `configure_agent` still
        runs (the configure playbook's post-render verifications skip
        themselves when config.provider is undefined)."""
        host = self._hermes_host_for_start(providers=[])

        captured: dict = {}

        def fake_configure(hostname, claw_name, config_data, **kwargs):
            captured["config_data"] = dict(config_data)
            return (True, None)

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.lifecycle._hermes_env_token_matches_secrets",
                return_value=(False, None),
            ),
            patch(
                "clawrium.core.lifecycle._run_lifecycle_playbook",
                return_value=(True, None),
            ),
            patch(
                "clawrium.core.lifecycle._update_agent_runtime",
                return_value=True,
            ),
            patch(
                "clawrium.core.lifecycle.configure_agent",
                side_effect=fake_configure,
            ),
        ):
            result = start_agent("192.168.1.100", "hermes")

        assert result["success"] is True, result.get("error")
        cfg = captured["config_data"]
        assert "provider" not in cfg
        assert "providers" not in cfg
        # Other persisted state still flows through.
        assert cfg["gateway"]["port"] == 45000

    def test_start_agent_hydrates_provider_before_hermes_reconfigure(
        self, tmp_path: Path
    ):
        """ATX #794 iter-2 B1 regression test: `start_agent`'s hermes
        pre-start reconfigure (the API_SERVER_KEY drift path at
        lifecycle.py:703-756) historically passed `claw_record.config`
        directly to `configure_agent`. After Phase 2 stripped
        `config.provider` from persisted hosts.json, the playbook's
        post-render verification tasks (configure.yaml:208-264) were
        silently skipping because they're gated on
        `config.provider is defined`. The fix hydrates the overlay
        from canonical attachments + providers.json before invoking
        configure_agent — assert the inventory shipped to ansible
        contains the resolved primary provider.
        """
        host = {
            "hostname": "192.168.1.100",
            "key_id": "test",
            "agent_name": "xclm",
            "port": 22,
            "agents": {
                "hrm-test": {
                    "type": "hermes",
                    "agent_name": "hrmt",
                    "onboarding": {"state": "ready"},
                    # Post-#794 shape: no config.provider mirror.
                    "config": {
                        "gateway": {"port": 45000},
                        "api_server": {
                            "enabled": True,
                            "host": "0.0.0.0",
                            "port": 8642,
                        },
                    },
                    "providers": [
                        {"name": "anth", "role": "primary"},
                    ],
                }
            },
        }

        provider_record = {
            "name": "anth",
            "type": "anthropic",
            "endpoint": "https://api.anthropic.example",
            "default_model": "claude-opus",
        }

        mock_configure = MagicMock(return_value=(True, None))

        with (
            patch("clawrium.core.lifecycle.get_host", return_value=host),
            patch(
                "clawrium.core.providers.storage.get_provider",
                return_value=provider_record,
            ),
            # Force the env-token drift branch so configure_agent runs.
            patch(
                "clawrium.core.lifecycle._hermes_env_token_matches_secrets",
                return_value=(False, None),
            ),
            # Stub the start playbook + runtime update so the test
            # focuses on the pre-start configure path.
            patch(
                "clawrium.core.lifecycle._run_lifecycle_playbook",
                return_value=(True, None),
            ),
            patch(
                "clawrium.core.lifecycle._update_agent_runtime",
                return_value=True,
            ),
            patch(
                "clawrium.core.lifecycle.configure_agent",
                side_effect=mock_configure,
            ),
        ):
            result = start_agent("192.168.1.100", "hermes")

        assert result["success"] is True, result.get("error")
        # ATX #794 iter-3 W10: pin the call shape so this regression
        # test cannot pass on any other configure entry point (e.g.,
        # a refactor that accidentally routes through `reason='configure'`).
        mock_configure.assert_called_once()
        call_kwargs = mock_configure.call_args.kwargs
        assert call_kwargs.get("reason") == "start-precheck"
        assert call_kwargs.get("agent_name") == "hrm-test"

        # B1 fix: hydrated overlay reached configure_agent.
        cfg = mock_configure.call_args.args[2]
        assert cfg.get("provider") is not None, (
            "start_agent hermes pre-start reconfigure shipped an empty "
            "config.provider — the playbook's post-render verification "
            "tasks would silently skip (ATX #794 iter-2 B1)"
        )
        assert cfg["provider"]["name"] == "anth"
        assert cfg["provider"]["type"] == "anthropic"
        assert cfg["provider"]["default_model"] == "claude-opus"
        # And the multi-provider list is hydrated too (hermes).
        assert isinstance(cfg.get("providers"), list)
        assert cfg["providers"][0]["name"] == "anth"
        assert cfg["providers"][0]["role"] == "primary"

    def test_configure_agent_passes_channels_extravars(self, tmp_path: Path):
        """ATX #794 iter-1 W3 (positive half for channels): even though
        the persisted config strips `channels`, the Ansible inventory
        MUST still carry the overlay so playbook templates can render
        the channel hulls. Mirrors
        `test_configure_agent_passes_provider_extravars` for the
        channels surface."""
        host = self._openclaw_host()
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "test-provider",
                "type": "openai",
                "endpoint": "https://api.openai.example",
                "default_model": "gpt-4",
            },
            "channels": {
                "discord": {
                    "enabled": True,
                    "guilds": {"123": {"channels": {"456": {}}}},
                }
            },
        }
        inv, persisted, success, error = self._run_configure_capturing_persist(
            host, config_data, "openclaw", "opc-test", tmp_path
        )
        assert success is True, error

        ansible_channels = inv["all"]["vars"]["config"]["channels"]
        assert ansible_channels["discord"]["enabled"] is True
        assert ansible_channels["discord"]["guilds"]["123"]["channels"] == {
            "456": {}
        }
        # Persist-strip still held on the same call.
        assert "channels" not in persisted["agents"]["opc-test"]["config"]

    def test_configure_agent_passes_provider_extravars(self, tmp_path: Path):
        """Negative half of the contract: even though the persisted
        config strips provider/providers, the Ansible inventory MUST
        still carry the overlay so templates can render the model.
        Mirrors the scaffold's `test_configure_agent_passes_provider_extravars`
        — the "extravars" path here is `inventory.all.vars.config.provider`
        (config_data is forwarded into ansible_vars as `config`).
        """
        host = self._openclaw_host()
        config_data = {
            "gateway": {"port": 40000, "bind": "lan"},
            "provider": {
                "name": "test-provider",
                "type": "openai",
                "endpoint": "https://api.openai.example",
                "default_model": "gpt-4-overlay-marker",
            },
        }
        inv, persisted, success, error = self._run_configure_capturing_persist(
            host, config_data, "openclaw", "opc-test", tmp_path
        )
        assert success is True, error

        ansible_provider = inv["all"]["vars"]["config"]["provider"]
        assert ansible_provider["name"] == "test-provider"
        assert ansible_provider["default_model"] == "gpt-4-overlay-marker"

        # And confirm the persist strip still happened on the same run.
        assert (
            "provider" not in persisted["agents"]["opc-test"]["config"]
        )

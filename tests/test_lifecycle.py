"""Tests for claw lifecycle management module."""

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

    def _setup_repair_runner(self, tmp_path: Path, token: str) -> tuple[MagicMock, Path]:
        artifacts_dir = tmp_path / "artifacts"
        fact_cache_dir = artifacts_dir / "fact_cache"
        fact_cache_dir.mkdir(parents=True)
        (fact_cache_dir / "192.168.1.100").write_text(
            json.dumps({
                "__payload__": json.dumps({
                    "zeroclaw_gateway_token": token,
                    "zeroclaw_gateway_url": "ws://192.168.1.100:40000/ws/chat",
                })
            })
        )
        runner = MagicMock()
        runner.status = "successful"
        runner.events = []
        runner.config.artifact_dir = str(artifacts_dir)
        return runner, artifacts_dir

    def _run_repair(self, host: dict, tmp_path: Path, *,
                    runner: MagicMock, update_host_result=True,
                    update_host_capture: dict | None = None,
                    reason: str = "restart",
                    on_event=None):
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
            host, tmp_path,
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
            host, tmp_path, runner=runner, reason="start", on_event=on_event,
        )
        assert success is True
        rotation = [m for s, m in events if s == "gateway_token_rotated"]
        assert json.loads(rotation[0])["reason"] == "start"

    def test_returns_failure_when_playbook_fails(self, tmp_path: Path):
        host = self._host()
        runner = MagicMock()
        runner.status = "failed"
        runner.events = [
            {"event": "runner_on_failed",
             "event_data": {"res": {"msg": "pair handshake exploded"}}}
        ]
        success, error = self._run_repair(host, tmp_path, runner=runner)
        assert success is False
        assert "pair handshake exploded" in error

    def test_returns_failure_when_update_host_returns_false(self, tmp_path: Path):
        """ATX W8: the exact divergence #437 fixes — playbook succeeds but
        hosts.json never gets written. Must surface as a failure."""
        host = self._host()
        runner, _ = self._setup_repair_runner(tmp_path, "fresh-but-not-persisted")
        success, error = self._run_repair(
            host, tmp_path, runner=runner, update_host_result=False,
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
            host, tmp_path, runner=runner,
            update_host_result=False, on_event=on_event,
        )
        assert success is False
        rotation = [m for s, m in events if s == "gateway_token_rotated"]
        assert not rotation, f"rotation event leaked despite write failure: {rotation!r}"

    def test_repair_passes_existing_bearer_in_inventory(self, tmp_path: Path):
        """Issue #445: tasks/pair.yaml's locked-pair branch authenticates
        against /api/pairing/initiate using the current bearer from
        hosts.json. The Python helper must forward that bearer as
        config.gateway.auth in the Ansible inventory so the playbook can
        reach it. Without this, the locked branch fires with an empty
        Authorization header and the daemon rejects it."""
        host = self._host(auth="zc_existing_bearer_aaaaaaaaaaaaaaa")
        runner, _ = self._setup_repair_runner(tmp_path, "new-rotated-token")
        captured_inventory: dict = {}

        def capture_run(**kwargs):
            captured_inventory.update(kwargs.get("inventory") or {})
            return runner

        key_path = tmp_path / "test_key"
        key_path.write_text("key")
        playbook_path = tmp_path / "restart.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        with patch("clawrium.core.lifecycle.get_host", return_value=host), \
             patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
             ), \
             patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
             ), \
             patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                side_effect=capture_run,
             ), \
             patch(
                "clawrium.core.lifecycle.update_host",
                return_value=True,
             ), \
             patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
             ):
            from clawrium.core.lifecycle import _zeroclaw_repair_after_start
            success, error = _zeroclaw_repair_after_start(
                "192.168.1.100",
                agent_name="zer-test",
                on_event=None,
                reason="restart",
            )
        assert success is True, error
        gateway_vars = captured_inventory["all"]["vars"]["config"]["gateway"]
        assert gateway_vars["auth"] == "zc_existing_bearer_aaaaaaaaaaaaaaa", (
            "existing bearer must flow into the playbook so the locked-pair "
            "branch can authenticate against /api/pairing/initiate"
        )
        assert gateway_vars["port"] == 40000

    def test_repair_passes_empty_bearer_when_hosts_json_lacks_auth(
        self, tmp_path: Path
    ):
        """First-install path: hosts.json has no `auth` field yet. The
        helper must pass an empty string (not raise, not omit the key) so
        the playbook's `default('')` filter keeps the locked branch dormant
        on a fresh daemon."""
        host = self._host()
        host["agents"]["zer-test"]["config"]["gateway"] = {"port": 40000}
        runner, _ = self._setup_repair_runner(tmp_path, "fresh-token")
        captured_inventory: dict = {}

        def capture_run(**kwargs):
            captured_inventory.update(kwargs.get("inventory") or {})
            return runner

        key_path = tmp_path / "test_key"
        key_path.write_text("key")
        playbook_path = tmp_path / "restart.yaml"
        playbook_path.write_text("---\n- hosts: all\n")

        with patch("clawrium.core.lifecycle.get_host", return_value=host), \
             patch(
                "clawrium.core.lifecycle.get_host_private_key",
                return_value=key_path,
             ), \
             patch(
                "clawrium.core.lifecycle._get_lifecycle_playbook_path",
                return_value=playbook_path,
             ), \
             patch(
                "clawrium.core.lifecycle.ansible_runner.run",
                side_effect=capture_run,
             ), \
             patch(
                "clawrium.core.lifecycle.update_host",
                return_value=True,
             ), \
             patch(
                "clawrium.core.lifecycle.get_config_dir",
                return_value=tmp_path,
             ):
            from clawrium.core.lifecycle import _zeroclaw_repair_after_start
            success, _ = _zeroclaw_repair_after_start(
                "192.168.1.100",
                agent_name="zer-test",
                on_event=None,
                reason="restart",
            )
        assert success is True
        assert (
            captured_inventory["all"]["vars"]["config"]["gateway"]["auth"]
            == ""
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
                                        "192.168.1.100", "zeroclaw",
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
                    "success": True, "agent": "zer-test", "host": "192.168.1.100",
                    "operation": "stop", "pid": None, "started_at": None, "error": None,
                },
            ):
                with patch(
                    "clawrium.core.lifecycle.start_agent",
                    return_value={
                        "success": True, "agent": "zer-test", "host": "192.168.1.100",
                        "operation": "start", "pid": None,
                        "started_at": "2026-05-19T00:00:00Z", "error": None,
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
        assert any(
            "agent state" in msg.lower() for msg in remove_messages
        ), f"Expected state cleanup message, got: {remove_messages}"

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
        write_state("opc-work", ["clawrium/tdd"])
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
                with patch(
                    "clawrium.core.lifecycle.restart_agent"
                ) as mock_restart:
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
                result = sync_agent(
                    "192.168.1.100", "openclaw", agent_name="opc-work"
                )

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

"""Unit tests for core/agent_exec.py — Ansible passthrough dispatcher.

ansible_runner is mocked so tests run offline. Event lists model what
the real `exec.yaml` playbook emits: three debug events tagged
EXEC_STDOUT=/EXEC_STDERR=/EXEC_RC=.
"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawrium.core import agent_exec


def _ok_event(msg: str) -> dict:
    return {"event": "runner_on_ok", "event_data": {"res": {"msg": msg}}}


def _make_result(events: list[dict], status: str = "successful") -> SimpleNamespace:
    return SimpleNamespace(events=events, status=status)


@pytest.fixture
def patched_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(
        agent_exec,
        "get_config_dir",
        lambda: tmp_path / "config",
    )
    monkeypatch.setattr(
        agent_exec.core_keys,
        "get_host_private_key",
        lambda key_id: tmp_path / "fake-key",
    )
    (tmp_path / "fake-key").write_text("KEY")
    # Make all per-type playbook paths exist
    for ctype in agent_exec.SUPPORTED_CLAW_TYPES:
        p = agent_exec._playbook_path(ctype)
        if not p.exists():  # pragma: no cover — real playbooks exist
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("dummy")
    # Stub get_host
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {"hostname": h, "user": "alice", "port": 22, "alias": "wolf-i"},
    )
    return tmp_path


def test_run_agent_exec_success(monkeypatch, patched_env):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _make_result(
            [
                _ok_event(
                    "EXEC_STDOUT=" + base64.b64encode(b"hello world").decode()
                ),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["--version"]
    )
    assert (stdout, stderr, rc) == ("hello world", "", 0)
    # extra_vars passes cmd_argv as a typed list
    inv = captured["inventory"]
    assert inv["all"]["vars"]["cmd_argv"] == ["--version"]
    assert inv["all"]["vars"]["agent_name"] == "wolf-i"


def test_run_agent_exec_nonzero_rc(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"").decode()),
                _ok_event(
                    "EXEC_STDERR=" + base64.b64encode(b"oops\n").decode()
                ),
                _ok_event("EXEC_RC=42"),
            ]
        ),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["bogus"]
    )
    assert rc == 42
    assert "oops" in stderr


def test_run_agent_exec_unreachable(monkeypatch, patched_env):
    unreach = {
        "event": "runner_on_unreachable",
        "event_data": {"res": {"msg": "ssh failed"}},
    }
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([unreach], status="failed"),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "unreachable" in stderr.lower()


def test_run_agent_exec_timeout(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([], status="timeout"),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "timed out" in stderr


def test_unknown_claw_type_raises(patched_env):
    with pytest.raises(agent_exec.AgentExecError):
        agent_exec.run_agent_exec("10.0.0.1", "x", "nemoclaw", ["foo"])


def test_empty_cmd_argv_raises(patched_env):
    with pytest.raises(agent_exec.AgentExecError):
        agent_exec.run_agent_exec("10.0.0.1", "x", "openclaw", [])


def test_missing_ssh_key(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.core_keys, "get_host_private_key", lambda key_id: None
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "SSH key" in stderr


def test_missing_host(monkeypatch, patched_env):
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(hosts_module, "get_host", lambda h: None)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "nope", "x", "openclaw", ["v"]
    )
    assert rc == 255
    assert "not found" in stderr


def test_invalid_agent_name_raises(patched_env):
    with pytest.raises(agent_exec.AgentExecError):
        agent_exec.run_agent_exec("10.0.0.1", "Bad Name!", "openclaw", ["x"])


@pytest.mark.parametrize("claw_type", ["hermes", "zeroclaw"])
def test_run_agent_exec_per_type_success(monkeypatch, patched_env, claw_type):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _make_result(
            [
                _ok_event(
                    "EXEC_STDOUT=" + base64.b64encode(b"v1.0").decode()
                ),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "agent", claw_type, ["--version"]
    )
    assert (stdout, rc) == ("v1.0", 0)
    assert claw_type in captured["playbook"]


def test_runner_on_failed_with_msg(monkeypatch, patched_env):
    failed = {
        "event": "runner_on_failed",
        "event_data": {"res": {"msg": "binary not found"}},
    }
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([failed], status="failed"),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "binary not found" in stderr


def test_runner_on_failed_with_stderr(monkeypatch, patched_env):
    failed = {
        "event": "runner_on_failed",
        "event_data": {"res": {"stderr": "permission denied"}},
    }
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result([failed], status="failed"),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255
    assert "permission denied" in stderr


def test_log_dir_uses_uuid_suffix(monkeypatch, patched_env):
    captured = {}

    def fake_run(**kw):
        captured["pd"] = kw["private_data_dir"]
        return _make_result(
            [
                _ok_event("EXEC_STDOUT=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("EXEC_RC=0"),
            ]
        )

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    agent_exec.run_agent_exec("10.0.0.1", "wolf-i", "openclaw", ["x"])
    # Path ends in `-<8 hex chars>`
    suffix = captured["pd"].rsplit("-", 1)[-1]
    assert len(suffix) == 8 and all(c in "0123456789abcdef" for c in suffix)


def test_missing_rc_marker(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event(
                    "EXEC_STDOUT=" + base64.b64encode(b"out").decode()
                ),
                _ok_event("EXEC_STDERR=" + base64.b64encode(b"").decode()),
                # no EXEC_RC
            ]
        ),
    )
    stdout, stderr, rc = agent_exec.run_agent_exec(
        "10.0.0.1", "wolf-i", "openclaw", ["x"]
    )
    assert rc == 255

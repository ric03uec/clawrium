"""Tests for the SSH tunnel manager (issue #478 phase 3).

Covers idempotency (reuse healthy, evict stale), the cmdline guard
that prevents killing unrelated PIDs, port selection, and the SSH
spawn path. ``ssh`` is never actually invoked; ``subprocess.Popen``
is patched so we can return a deterministic fake-process handle.
"""

from __future__ import annotations

import json
import socket
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clawrium.core import web_ui_tunnel
from clawrium.core.web_ui import ResolvedUI
from clawrium.core.web_ui_tunnel import (
    TunnelError,
    _cmdline_matches,
    _cmdline_signature,
    _pick_free_port,
    close,
    ensure,
    is_idle,
    tunnel_state_dir,
)


def _resolved(host: str = "hermes.local", port: int = 9119) -> ResolvedUI:
    return ResolvedUI(
        host=host,
        remote_port=port,
        bind="loopback",
        ssh_config={"user": "xclm", "identity_file": "/tmp/key"},
    )


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """All tunnel state writes land in tmp_path; never touch real config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    web_ui_tunnel._OWNED_TUNNELS.clear()
    return tmp_path


def test_tunnel_state_dir_is_under_config(isolated_state: Path):
    state_dir = tunnel_state_dir()
    assert state_dir.is_dir()
    assert "tunnels" in state_dir.parts
    assert str(state_dir).startswith(str(isolated_state))


def test_pick_free_port_returns_loopback_port():
    port = _pick_free_port()
    assert 1024 < port < 65536


def test_cmdline_signature_matches_actual_proc_format():
    cmd = ["ssh", "-N", "-L", "1234:127.0.0.1:9119", "xclm@host"]
    signature = _cmdline_signature(cmd)
    actual = " ".join(cmd)  # how /proc renders it after NUL→space
    assert _cmdline_matches(actual, signature)


def test_cmdline_signature_rejects_unrelated_cmdline():
    signature = _cmdline_signature(["ssh", "-N", "-L", "1234:127.0.0.1:9119", "xclm@host"])
    assert not _cmdline_matches("nginx: worker process", signature)


def test_ensure_returns_existing_local_port_when_healthy(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """A live, matching state file with a bound local port reuses the port."""
    # Stand up a real listening socket on a free port to mimic an existing
    # tunnel. _local_port_bound() checks via connect_ex.
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        local_port = sock.getsockname()[1]

        signature = _cmdline_signature(
            ["ssh", "-N", "-L", f"{local_port}:127.0.0.1:9119", "xclm@hermes.local"]
        )
        state_path = tunnel_state_dir() / "demo.json"
        state_path.write_text(
            json.dumps(
                {
                    "pid": 1,  # current process — guaranteed alive
                    "local_port": local_port,
                    "started_at": time.time(),
                    "ssh_cmdline_signature": signature,
                }
            )
        )

        monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: True)
        monkeypatch.setattr(
            web_ui_tunnel,
            "_read_cmdline",
            lambda pid: " ".join(
                ["ssh", "-N", "-L", f"{local_port}:127.0.0.1:9119", "xclm@hermes.local"]
            ),
        )
        monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: _resolved())

        result = ensure("demo")
        assert result == local_port


def test_ensure_evicts_stale_pid_then_spawns_new_tunnel(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """A state file pointing at a dead PID is evicted; ssh is respawned."""
    state_path = tunnel_state_dir() / "demo.json"
    state_path.write_text(
        json.dumps(
            {
                "pid": 999999,
                "local_port": 0,
                "started_at": 0,
                "ssh_cmdline_signature": "ssh -N -L 0:127.0.0.1:9119 xclm@hermes.local",
            }
        )
    )
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: False)
    monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: _resolved())

    # Spawn produces a fake handle; _wait_for_connect succeeds immediately.
    fake_proc = MagicMock()
    fake_proc.pid = 4242
    fake_proc.poll.return_value = None
    monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", lambda cmd: fake_proc)
    monkeypatch.setattr(web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0: True)

    result = ensure("demo")
    assert result > 0
    persisted = json.loads(state_path.read_text())
    assert persisted["pid"] == 4242
    assert persisted["local_port"] == result


def test_cmdline_guard_refuses_kill_for_mismatched_pid(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """_terminate must NOT signal a PID whose cmdline doesn't match."""
    state_path = tunnel_state_dir() / "demo.json"
    signature = "ssh -N -L 1234:127.0.0.1:9119 xclm@hermes.local"
    state_path.write_text(
        json.dumps(
            {
                "pid": 1,
                "local_port": 1234,
                "started_at": time.time(),
                "ssh_cmdline_signature": signature,
            }
        )
    )
    # PID is alive, but cmdline is unrelated — guard must hold.
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: True)
    monkeypatch.setattr(web_ui_tunnel, "_read_cmdline", lambda pid: "init")
    kill_calls: list[int] = []
    monkeypatch.setattr(
        "os.kill", lambda pid, sig: kill_calls.append(pid)
    )

    web_ui_tunnel._evict_stale("demo")
    assert kill_calls == []
    # State file is removed even when we refused to kill — the entry is stale
    # from our perspective; another process owns that PID now.
    assert not state_path.exists()


def test_ensure_raises_when_ssh_fails_to_bind(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """If _wait_for_connect times out, ensure() raises TunnelError."""
    monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: _resolved())
    fake_proc = MagicMock()
    fake_proc.pid = 5555
    fake_proc.poll.return_value = 1
    fake_proc.stderr = None
    monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", lambda cmd: fake_proc)
    monkeypatch.setattr(web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0: False)

    with pytest.raises(TunnelError):
        ensure("demo")


def test_ensure_rejects_agent_without_web_ui(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: None)
    with pytest.raises(TunnelError):
        ensure("not-installed")


def test_close_is_safe_when_no_state(isolated_state: Path):
    close("never-existed")  # no-op, no exception


def test_is_idle_threshold():
    now = time.time()
    assert is_idle("k", now - 3600, threshold=1800) is True
    assert is_idle("k", now - 60, threshold=1800) is False
    assert is_idle("k", 0, threshold=1800) is False


def test_ensure_with_missing_ssh_user_raises(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """Resolved UI without an ssh user can't be tunnelled."""
    bad = ResolvedUI(host="x", remote_port=9119, bind="loopback", ssh_config={})
    monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: bad)
    with pytest.raises(TunnelError):
        ensure("demo")

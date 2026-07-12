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
    _build_ssh_for,
    _cmdline_matches,
    _cmdline_signature,
    _http_endpoint_healthy,
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


def test_http_endpoint_healthy_accepts_any_http_response_byte():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    try:
        def serve_once():
            conn, _ = server.accept()
            with closing(conn):
                conn.recv(1024)
                conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")

        import threading

        thread = threading.Thread(target=serve_once)
        thread.start()
        assert _http_endpoint_healthy(port) is True
        thread.join(timeout=1)
        assert not thread.is_alive()
    finally:
        server.close()


def test_http_endpoint_healthy_returns_false_on_connection_reset():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    try:
        def serve_once():
            conn, _ = server.accept()
            conn.close()

        import threading

        thread = threading.Thread(target=serve_once)
        thread.start()
        assert _http_endpoint_healthy(port) is False
        thread.join(timeout=1)
        assert not thread.is_alive()
    finally:
        server.close()


def test_http_endpoint_healthy_treats_recv_timeout_as_alive(monkeypatch: pytest.MonkeyPatch):
    timeouts: list[float] = []

    class FakeSocket:
        def settimeout(self, value):
            timeouts.append(value)

        def connect(self, address):
            return None

        def sendall(self, data):
            return None

        def recv(self, size):
            raise TimeoutError

        def close(self):
            return None

    monkeypatch.setattr(web_ui_tunnel.socket, "socket", lambda *args, **kwargs: FakeSocket())

    assert _http_endpoint_healthy(41091) is True
    assert timeouts == [0.5, 2.0]


def test_cmdline_signature_matches_actual_proc_format():
    cmd = ["ssh", "-N", "-L", "1234:127.0.0.1:9119", "xclm@host"]
    signature = _cmdline_signature(cmd)
    actual = " ".join(cmd)  # how /proc renders it after NUL→space
    assert _cmdline_matches(actual, signature)


def test_cmdline_signature_rejects_unrelated_cmdline():
    signature = _cmdline_signature(
        ["ssh", "-N", "-L", "1234:127.0.0.1:9119", "xclm@host"]
    )
    assert not _cmdline_matches("nginx: worker process", signature)


def test_build_ssh_for_loopback_targets_remote_loopback():
    """A `loopback`-bound agent yields a `-L L:127.0.0.1:R` forward."""
    resolved = ResolvedUI(
        host="hermes.local",
        remote_port=45123,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    cmd = _build_ssh_for(resolved, local_port=39211)
    forward = next(arg for arg in cmd if arg.startswith("39211:"))
    assert forward == "39211:127.0.0.1:45123"


def test_build_ssh_for_wildcard_resolves_to_remote_loopback():
    """Value lock-in: `bind='wildcard'` produces a `-L L:127.0.0.1:R` flag.

    This is a value assertion only — both code paths (a real lookup of
    `BIND_ADDRESS_MAP['wildcard']` and a hardcoded `'127.0.0.1'`) would
    pass it today. `test_build_ssh_for_consults_bind_address_map_*`
    below are the load-bearing tests for the map-lookup contract.
    """
    resolved = ResolvedUI(
        host="zero.local",
        remote_port=40123,
        bind="wildcard",
        ssh_config={"user": "xclm"},
    )
    cmd = _build_ssh_for(resolved, local_port=39211)
    forward = next(arg for arg in cmd if arg.startswith("39211:"))
    assert forward == "39211:127.0.0.1:40123"


def test_build_ssh_for_enforces_strict_host_key_checking():
    """ATX B5: SSH command MUST set `StrictHostKeyChecking=yes` — never `accept-new`.

    `accept-new` allows TOFU on first connect, which silently undermines
    the SSH-as-auth-boundary contract documented in AGENTS.md (a LAN MITM
    on the first tunnel session would harvest the zeroclaw pairing bearer).
    Regression-guards a code-only revert to `accept-new`.
    """
    resolved = ResolvedUI(
        host="hermes.local",
        remote_port=45123,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    cmd = _build_ssh_for(resolved, local_port=39211)
    assert "StrictHostKeyChecking=yes" in cmd
    assert not any("accept-new" in arg for arg in cmd)


def test_build_ssh_for_consults_bind_address_map_wildcard(monkeypatch):
    """The builder MUST go through `BIND_ADDRESS_MAP['wildcard']`.

    Swap a sentinel into the map and assert the `-L` flag reflects the
    swap. If a future refactor re-introduces a hardcoded `127.0.0.1`
    for the wildcard path this test fails. ATX iter 2 B-new1.
    """
    monkeypatch.setitem(web_ui_tunnel.BIND_ADDRESS_MAP, "wildcard", "10.99.99.99")
    resolved = ResolvedUI(
        host="zero.local",
        remote_port=40123,
        bind="wildcard",
        ssh_config={"user": "xclm"},
    )
    cmd = _build_ssh_for(resolved, local_port=39211)
    forward = next(arg for arg in cmd if arg.startswith("39211:"))
    assert forward == "39211:10.99.99.99:40123"


def test_build_ssh_for_consults_bind_address_map_loopback(monkeypatch):
    """Symmetric to the wildcard sentinel test, for `bind='loopback'`.

    Closes a regression vector where a refactor could keep the map
    lookup for `wildcard` while hardcoding `127.0.0.1` specifically
    for `loopback` — the wildcard-only sentinel test would still pass.
    ATX iter 3 W3.
    """
    monkeypatch.setitem(web_ui_tunnel.BIND_ADDRESS_MAP, "loopback", "10.88.88.88")
    resolved = ResolvedUI(
        host="hermes.local",
        remote_port=45123,
        bind="loopback",
        ssh_config={"user": "xclm"},
    )
    cmd = _build_ssh_for(resolved, local_port=39211)
    forward = next(arg for arg in cmd if arg.startswith("39211:"))
    assert forward == "39211:10.88.88.88:45123"


def test_build_ssh_for_unknown_bind_raises_tunnel_error():
    """An unknown `bind` value surfaces as `TunnelError`, not `KeyError`.

    The manifest validator restricts `bind` to a closed enum at load
    time so this path is unreachable through the bundled manifests.
    But `Literal[...]` is unenforced at runtime — a tampered
    `hosts.json` or a third-party manifest mocked through `load_manifest`
    can produce a `ResolvedUI(bind='future_mode', ...)`. The builder
    must fail loudly with a `TunnelError` referencing the bind name so
    operators see "extend BIND_ADDRESS_MAP" rather than an opaque
    `KeyError` traceback. ATX iter 3 W2.
    """
    resolved = ResolvedUI(
        host="x.local",
        remote_port=9000,
        bind="future_mode",  # type: ignore[arg-type]  # intentional invalid value
        ssh_config={"user": "u"},
    )
    with pytest.raises(TunnelError, match="unknown bind mode"):
        _build_ssh_for(resolved, local_port=12345)


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
        monkeypatch.setattr(web_ui_tunnel, "_http_endpoint_healthy", lambda port: True)

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
    monkeypatch.setattr(
        web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: True
    )

    result = ensure("demo")
    assert result > 0
    persisted = json.loads(state_path.read_text())
    assert persisted["pid"] == 4242
    assert persisted["local_port"] == result


def test_ensure_evicts_existing_tunnel_when_http_probe_fails(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """A bound-but-dead forwarded endpoint must not be reused."""
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
                    "pid": 1234,
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
        monkeypatch.setattr(web_ui_tunnel, "_http_endpoint_healthy", lambda port: False)
        monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: _resolved())

        fake_proc = MagicMock()
        fake_proc.pid = 4242
        fake_proc.poll.return_value = None
        monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", lambda cmd: fake_proc)
        monkeypatch.setattr(
            web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: True
        )

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
    monkeypatch.setattr("os.kill", lambda pid, sig: kill_calls.append(pid))

    web_ui_tunnel._evict_stale("demo")
    assert kill_calls == []
    # State file is removed even when we refused to kill — the entry is stale
    # from our perspective; another process owns that PID now.
    assert not state_path.exists()


def test_terminate_sends_sigterm_when_cmdline_matches(monkeypatch: pytest.MonkeyPatch):
    """ATX iter-3 B1: _terminate MUST send SIGTERM (signal 15) to a PID whose
    cmdline still matches the recorded signature. Locks in the happy path
    that test_cmdline_guard_refuses_kill_for_mismatched_pid omits.
    """
    signature = "ssh -N -L 1234:127.0.0.1:9119 xclm@hermes.local"
    monkeypatch.setattr(web_ui_tunnel, "_read_cmdline", lambda pid: signature)
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: False)
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr("os.kill", lambda pid, sig: sent.append((pid, sig)))

    web_ui_tunnel._terminate(4242, signature)

    assert sent == [(4242, 15)]


def test_terminate_escalates_to_sigkill_when_process_survives(
    monkeypatch: pytest.MonkeyPatch,
):
    """ATX iter-3 B1: if the process is still alive after SIGTERM AND the
    cmdline still matches, _terminate MUST escalate to SIGKILL (signal 9).
    """
    signature = "ssh -N -L 1234:127.0.0.1:9119 xclm@hermes.local"
    monkeypatch.setattr(web_ui_tunnel, "_read_cmdline", lambda pid: signature)
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: True)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr("os.kill", lambda pid, sig: sent.append((pid, sig)))

    web_ui_tunnel._terminate(4242, signature)

    # SIGTERM first, then SIGKILL after the alive-poll loop expires.
    assert sent == [(4242, 15), (4242, 9)]


def test_terminate_skips_sigkill_when_cmdline_changes_after_sigterm(
    monkeypatch: pytest.MonkeyPatch,
):
    """ATX iter-3 B1: the post-SIGTERM cmdline re-check closes the PID-recycle
    window. If the cmdline no longer matches (process exited and PID was
    reused), _terminate MUST NOT send SIGKILL.
    """
    signature = "ssh -N -L 1234:127.0.0.1:9119 xclm@hermes.local"
    # First read (pre-SIGTERM): matches. Second read (pre-SIGKILL): different.
    reads = iter([signature, "init"])
    monkeypatch.setattr(web_ui_tunnel, "_read_cmdline", lambda pid: next(reads))
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: True)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr("os.kill", lambda pid, sig: sent.append((pid, sig)))

    web_ui_tunnel._terminate(4242, signature)

    # Only SIGTERM was sent; SIGKILL suppressed by the cmdline-change recheck.
    assert sent == [(4242, 15)]


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
    monkeypatch.setattr(
        web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: False
    )

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


# ── Port persistence tests (issue #866) ──────────────────────────────────────


def test_preferred_port_reused_after_stale_eviction(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """When a dead tunnel state file holds a local_port that is available,
    ensure() must reuse that exact port for the new SSH command (#866).
    """
    preferred = 54321
    state_path = tunnel_state_dir() / "demo.json"
    state_path.write_text(
        json.dumps(
            {
                "pid": 9999,
                "local_port": preferred,
                "started_at": time.time(),
                "ssh_cmdline_signature": "ssh -N old-signature",
            }
        )
    )

    monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: _resolved())
    # Tunnel is dead: PID not alive, state is stale.
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: False)
    # Preferred port is available — mock is port-specific so a wrong port fails.
    monkeypatch.setattr(web_ui_tunnel, "_is_port_available", lambda port: port == preferred)

    captured_cmds: list[list[str]] = []

    fake_proc = MagicMock()
    fake_proc.pid = 7777
    fake_proc.poll.return_value = None

    def fake_spawn(cmd: list[str]) -> MagicMock:
        captured_cmds.append(cmd)
        return fake_proc

    monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", fake_spawn)
    monkeypatch.setattr(
        web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: True
    )

    result = ensure("demo")

    assert result == preferred
    l_idx = captured_cmds[0].index("-L")
    assert captured_cmds[0][l_idx + 1].startswith(f"{preferred}:")


def test_preferred_port_fallback_when_occupied(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """When the preferred port is occupied, ensure() falls back to _pick_free_port
    and uses whatever OS-assigned port it returns (#866).
    """
    preferred = 54321
    fallback = 11111
    state_path = tunnel_state_dir() / "demo.json"
    state_path.write_text(
        json.dumps(
            {
                "pid": 9999,
                "local_port": preferred,
                "started_at": time.time(),
                "ssh_cmdline_signature": "ssh -N old-signature",
            }
        )
    )

    monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: _resolved())
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: False)
    # Preferred port is occupied; fallback should be used.
    monkeypatch.setattr(web_ui_tunnel, "_is_port_available", lambda port: False)
    monkeypatch.setattr(web_ui_tunnel, "_pick_free_port", lambda: fallback)

    captured_cmds: list[list[str]] = []

    fake_proc = MagicMock()
    fake_proc.pid = 7778
    fake_proc.poll.return_value = None

    def fake_spawn(cmd: list[str]) -> MagicMock:
        captured_cmds.append(cmd)
        return fake_proc

    monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", fake_spawn)
    monkeypatch.setattr(
        web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: True
    )

    result = ensure("demo")

    assert result == fallback
    assert result != preferred
    l_idx = captured_cmds[0].index("-L")
    assert captured_cmds[0][l_idx + 1].startswith(f"{fallback}:")


def test_ssh_command_includes_keepalive_params():
    """_ssh_command must emit ServerAliveInterval=60 and ServerAliveCountMax=10 (#866)."""
    from clawrium.core.web_ui_tunnel import _ssh_command

    cmd = _ssh_command(
        local_port=12345,
        remote_port=9119,
        remote_bind_addr="127.0.0.1",
        ssh_user="xclm",
        ssh_host="hermes.local",
        ssh_port=None,
        identity_file=None,
    )

    assert "ServerAliveInterval=60" in cmd
    assert "ServerAliveCountMax=10" in cmd
    assert "ServerAliveInterval=30" not in cmd


def test_is_port_available_occupied_vs_free():
    """_is_port_available returns False while a socket holds the port (#866)."""
    from clawrium.core.web_ui_tunnel import _is_port_available

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as holder:
        holder.bind(("127.0.0.1", 0))
        held_port = holder.getsockname()[1]
        # Port is held — should not be available.
        assert _is_port_available(held_port) is False
        # Bind a second socket to the same port under a still-open holder;
        # assert False again to keep both sockets alive and avoid the
        # post-release race (another process could grab the port between
        # the close and the next assert).
        assert _is_port_available(held_port) is False


def test_preferred_port_reused_ensure_at_port(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """ensure_at_port reuses the preferred port from a dead namespaced state (#866)."""
    preferred = 54322
    remote_port = 9119
    namespaced_key = f"demo:{remote_port}"
    state_path = tunnel_state_dir() / f"{namespaced_key}.json"
    state_path.write_text(
        json.dumps(
            {
                "pid": 9999,
                "local_port": preferred,
                "started_at": time.time(),
                "ssh_cmdline_signature": "ssh -N old-signature",
            }
        )
    )

    import clawrium.core.web_ui as _web_ui

    # ensure_at_port does `from clawrium.core.web_ui import resolve` locally, so
    # we must patch the source module rather than the web_ui_tunnel import site.
    monkeypatch.setattr(_web_ui, "resolve", lambda key: _resolved())
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: False)
    monkeypatch.setattr(web_ui_tunnel, "_is_port_available", lambda port: port == preferred)

    captured_cmds: list[list[str]] = []

    fake_proc = MagicMock()
    fake_proc.pid = 8888
    fake_proc.poll.return_value = None

    def fake_spawn(cmd: list[str]) -> MagicMock:
        captured_cmds.append(cmd)
        return fake_proc

    monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", fake_spawn)
    monkeypatch.setattr(
        web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: True
    )

    from clawrium.core.web_ui_tunnel import ensure_at_port

    result = ensure_at_port("demo", remote_port)

    assert result == preferred
    l_idx = captured_cmds[0].index("-L")
    assert captured_cmds[0][l_idx + 1].startswith(f"{preferred}:")


def test_preferred_port_fallback_ensure_at_port(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
):
    """ensure_at_port falls back to _pick_free_port when preferred port is occupied (#866)."""
    preferred = 54322
    fallback = 11112
    remote_port = 9119
    namespaced_key = f"demo:{remote_port}"
    state_path = tunnel_state_dir() / f"{namespaced_key}.json"
    state_path.write_text(
        json.dumps(
            {
                "pid": 9999,
                "local_port": preferred,
                "started_at": time.time(),
                "ssh_cmdline_signature": "ssh -N old-signature",
            }
        )
    )

    import clawrium.core.web_ui as _web_ui

    # ensure_at_port does `from clawrium.core.web_ui import resolve` locally, so
    # we must patch the source module rather than the web_ui_tunnel import site.
    monkeypatch.setattr(_web_ui, "resolve", lambda key: _resolved())
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: False)
    monkeypatch.setattr(web_ui_tunnel, "_is_port_available", lambda port: False)
    monkeypatch.setattr(web_ui_tunnel, "_pick_free_port", lambda: fallback)

    captured_cmds: list[list[str]] = []

    fake_proc = MagicMock()
    fake_proc.pid = 8889
    fake_proc.poll.return_value = None

    def fake_spawn(cmd: list[str]) -> MagicMock:
        captured_cmds.append(cmd)
        return fake_proc

    monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", fake_spawn)
    monkeypatch.setattr(
        web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: True
    )

    from clawrium.core.web_ui_tunnel import ensure_at_port

    result = ensure_at_port("demo", remote_port)

    assert result == fallback
    assert result != preferred
    l_idx = captured_cmds[0].index("-L")
    assert captured_cmds[0][l_idx + 1].startswith(f"{fallback}:")


@pytest.mark.parametrize("out_of_range_port", [0, 80, 1023, 65536, 99999])
def test_out_of_range_preferred_port_falls_back(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    out_of_range_port: int,
):
    """Ports outside [1024, 65535] in the state file must be ignored (#866)."""
    fallback = 40123
    state_path = tunnel_state_dir() / "demo.json"
    state_path.write_text(
        json.dumps(
            {
                "pid": 9999,
                "local_port": out_of_range_port,
                "started_at": time.time(),
                "ssh_cmdline_signature": "ssh -N old-signature",
            }
        )
    )

    monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: _resolved())
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: False)
    monkeypatch.setattr(web_ui_tunnel, "_pick_free_port", lambda: fallback)

    fake_proc = MagicMock()
    fake_proc.pid = 5555
    fake_proc.poll.return_value = None
    monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", lambda cmd: fake_proc)
    monkeypatch.setattr(
        web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: True
    )

    result = ensure("demo")

    assert result == fallback


@pytest.mark.parametrize(
    "bad_state",
    [
        {"pid": 9999, "local_port": None, "started_at": 0.0, "ssh_cmdline_signature": "x"},
        {"pid": 9999, "started_at": 0.0, "ssh_cmdline_signature": "x"},
        {"pid": 9999, "local_port": "not-a-number", "started_at": 0.0, "ssh_cmdline_signature": "x"},
    ],
    ids=["null_port", "missing_port", "non_integer_port"],
)
def test_malformed_state_falls_back_gracefully(
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_state: dict,
):
    """Corrupted local_port in state must be silently ignored (#866)."""
    fallback = 40124
    state_path = tunnel_state_dir() / "demo.json"
    state_path.write_text(json.dumps(bad_state))

    monkeypatch.setattr(web_ui_tunnel, "resolve", lambda key: _resolved())
    monkeypatch.setattr(web_ui_tunnel, "_process_alive", lambda pid: False)
    monkeypatch.setattr(web_ui_tunnel, "_pick_free_port", lambda: fallback)

    fake_proc = MagicMock()
    fake_proc.pid = 5556
    fake_proc.poll.return_value = None
    monkeypatch.setattr(web_ui_tunnel, "_spawn_ssh", lambda cmd: fake_proc)
    monkeypatch.setattr(
        web_ui_tunnel, "_wait_for_connect", lambda port, timeout=5.0, **kwargs: True
    )

    result = ensure("demo")

    assert result == fallback

"""SSH tunnel manager for native agent web UIs (hermes dashboard).

Issue #478 Phase 3. Maintains idempotent local-port-forward SSH tunnels
from the user's machine to an agent host's loopback dashboard port. State
is persisted at ``~/.config/clawrium/tunnels/<agent_key>.json`` so a second
``clm agent open`` (or GUI ``/web-ui`` request) reuses the same local
port instead of spawning a duplicate ``ssh -L`` process.

Each state file records the PID, local port, start time, and the exact
SSH command-line signature used to spawn the process. Before reusing a
tunnel we re-verify (a) the PID is still alive, (b) ``/proc/<pid>/cmdline``
matches the recorded signature (so we never kill an unrelated process
that has inherited the PID), and (c) the local port is still bound.

A process-wide ``atexit`` hook closes all tunnels that were created by
the current Python process.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import shlex
import socket
import subprocess
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clawrium.core.config import get_config_dir, init_config_dir
from clawrium.core.web_ui import BIND_ADDRESS_MAP, ResolvedUI, resolve

__all__ = [
    "TunnelError",
    "TunnelInfo",
    "ensure",
    "close",
    "is_idle",
    "tunnel_state_dir",
]

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_S = 5.0
_CONNECT_POLL_INTERVAL_S = 0.1

_OWNED_TUNNELS: set[str] = set()
_ATEXIT_REGISTERED = False

# Per-agent locks serialise the check→spawn→write_state sequence inside
# ensure(). Two concurrent GUI requests for the same agent_key would
# otherwise both miss the existing-tunnel check and race to spawn
# duplicate ssh processes (ATX B2). The per-key lock is fetched under
# _ENSURE_LOCKS_MUTEX to keep dict access itself thread-safe.
_ENSURE_LOCKS_MUTEX = threading.Lock()
_ENSURE_LOCKS: dict[str, threading.Lock] = {}


class TunnelError(RuntimeError):
    """Raised when establishing an SSH tunnel fails."""


@dataclass(frozen=True)
class TunnelInfo:
    """Persisted state for a live SSH tunnel."""

    pid: int
    local_port: int
    started_at: float
    ssh_cmdline_signature: str


def tunnel_state_dir() -> Path:
    """Return (and create) the directory that holds per-agent tunnel state."""
    base = get_config_dir() / "tunnels"
    old_umask = os.umask(0o077)
    try:
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
    finally:
        os.umask(old_umask)
    return base


def _state_path(agent_key: str) -> Path:
    safe = agent_key.replace("/", "_")
    return tunnel_state_dir() / f"{safe}.json"


def _read_state(agent_key: str) -> dict[str, Any] | None:
    path = _state_path(agent_key)
    if not path.is_file():
        return None
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_state(agent_key: str, info: TunnelInfo) -> None:
    init_config_dir()
    path = _state_path(agent_key)
    payload = {
        "pid": info.pid,
        "local_port": info.local_port,
        "started_at": info.started_at,
        "ssh_cmdline_signature": info.ssh_cmdline_signature,
    }
    # ATX B3: caller-unique tmp filename so two threads (or processes) racing
    # to write the same agent's state never trample each other. ATX W1: open
    # with mode 0o600 atomically via O_CREAT|O_EXCL — no chmod gap during
    # which the file is world-readable.
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    fdopen_succeeded = False
    try:
        fh = os.fdopen(fd, "w")
        fdopen_succeeded = True
        try:
            json.dump(payload, fh)
        finally:
            fh.close()
        os.replace(tmp, path)
    except Exception:
        if not fdopen_succeeded:
            # os.fdopen() did not take ownership of the raw fd; close it
            # manually to avoid leaking a descriptor under EMFILE etc.
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _delete_state(agent_key: str) -> None:
    path = _state_path(agent_key)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _read_cmdline(pid: int) -> str | None:
    """Read /proc/<pid>/cmdline, NUL-separated, decoded best-effort."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    if not raw:
        return None
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _local_port_bound(port: int) -> bool:
    """Return True iff something is listening on 127.0.0.1:<port>."""
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _pick_free_port() -> int:
    """Bind to an ephemeral port on loopback and return the chosen number.

    The kernel guarantees the port is free at the moment of the bind. There
    is an unavoidable race between releasing this port and SSH grabbing it
    in the spawned subprocess; if SSH fails to bind we surface the error
    and bail out rather than silently retry to avoid masking real issues.
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.getsockname()[1]


def _ssh_command(
    local_port: int,
    remote_port: int,
    remote_bind_addr: str,
    ssh_user: str,
    ssh_host: str,
    ssh_port: int | None,
    identity_file: str | None,
) -> list[str]:
    cmd: list[str] = [
        "ssh",
        "-N",
        "-L",
        f"{local_port}:{remote_bind_addr}:{remote_port}",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        # Strict mode (not accept-new): TOFU would let the first tunnel to a
        # given host silently trust whichever server answers. AGENTS.md states
        # the SSH key is the auth boundary — that only holds with mutual
        # authentication enforced. `clawctl host create --bootstrap` populates
        # known_hosts; if the host isn't there yet, ssh fails loudly and the
        # user is told to run host-create first.
        "StrictHostKeyChecking=yes",
    ]
    if ssh_port:
        cmd += ["-p", str(ssh_port)]
    if identity_file:
        cmd += ["-i", identity_file]
    cmd.append(f"{ssh_user}@{ssh_host}")
    return cmd


def _cmdline_signature(cmd: list[str]) -> str:
    """Stable signature used to verify a recorded PID still belongs to us."""
    return " ".join(shlex.quote(p) for p in cmd)


def _terminate(pid: int, signature: str) -> None:
    """Kill ``pid`` only if its cmdline still matches our signature.

    The cmdline guard avoids the classic PID-recycle hazard: by the time we
    decide a tunnel is stale, the kernel may have handed the same PID to a
    completely unrelated process. We never send a signal unless the cmdline
    still looks like the SSH invocation we recorded — and we re-verify the
    cmdline immediately before SIGKILL to close the SIGTERM→SIGKILL window
    where the PID may have been recycled (ATX B1).
    """
    if pid <= 0:
        return
    actual = _read_cmdline(pid)
    if actual is None:
        return
    if not _cmdline_matches(actual, signature):
        logger.debug("Refusing to kill pid %d: cmdline mismatch", pid)
        return
    try:
        os.kill(pid, 15)
    except (ProcessLookupError, PermissionError, OSError):
        return
    for _ in range(20):
        if not _process_alive(pid):
            return
        time.sleep(0.1)
    recheck = _read_cmdline(pid)
    if recheck is None or not _cmdline_matches(recheck, signature):
        logger.debug("Refusing SIGKILL to pid %d: cmdline changed", pid)
        return
    try:
        os.kill(pid, 9)
    except (ProcessLookupError, PermissionError, OSError):
        return


def _cmdline_matches(actual: str, signature: str) -> bool:
    """Compare the running process' cmdline against our recorded signature.

    /proc/<pid>/cmdline yields tokens joined by NUL bytes (which we turn
    into spaces) without the shell-quoting that the signature uses. The
    sequence of tokens, in order, is what we actually want to compare.
    """
    actual_tokens = [t for t in actual.split() if t]
    try:
        expected_tokens = shlex.split(signature)
    except ValueError:
        return False
    return actual_tokens == expected_tokens


def _existing_healthy_tunnel(agent_key: str) -> TunnelInfo | None:
    state = _read_state(agent_key)
    if not state:
        return None
    try:
        pid = int(state["pid"])
        local_port = int(state["local_port"])
        started_at = float(state["started_at"])
        signature = str(state["ssh_cmdline_signature"])
    except (KeyError, TypeError, ValueError):
        _delete_state(agent_key)
        return None

    if not _process_alive(pid):
        _delete_state(agent_key)
        return None
    actual_cmdline = _read_cmdline(pid)
    if actual_cmdline is None or not _cmdline_matches(actual_cmdline, signature):
        _delete_state(agent_key)
        return None
    if not _local_port_bound(local_port):
        _terminate(pid, signature)
        _delete_state(agent_key)
        return None
    return TunnelInfo(
        pid=pid,
        local_port=local_port,
        started_at=started_at,
        ssh_cmdline_signature=signature,
    )


def _evict_stale(agent_key: str) -> None:
    state = _read_state(agent_key)
    if not state:
        return
    try:
        pid = int(state["pid"])
        signature = str(state["ssh_cmdline_signature"])
    except (KeyError, TypeError, ValueError):
        _delete_state(agent_key)
        return
    _terminate(pid, signature)
    _delete_state(agent_key)


def _register_atexit() -> None:
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    atexit.register(_close_owned_tunnels)
    _ATEXIT_REGISTERED = True


def _close_owned_tunnels() -> None:
    for agent_key in list(_OWNED_TUNNELS):
        try:
            close(agent_key)
        except Exception:  # noqa: BLE001 — atexit must not raise
            logger.debug("atexit close failed for %s", agent_key, exc_info=True)


def _wait_for_connect(port: int, timeout: float = _CONNECT_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _local_port_bound(port):
            return True
        time.sleep(_CONNECT_POLL_INTERVAL_S)
    return False


def _spawn_ssh(cmd: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def _build_ssh_for(resolved: ResolvedUI, local_port: int) -> list[str]:
    ssh = resolved.ssh_config or {}
    user = ssh.get("user")
    if not isinstance(user, str) or not user:
        raise TunnelError("SSH user not configured for host; cannot establish tunnel.")
    try:
        remote_bind_addr = BIND_ADDRESS_MAP[resolved.bind]
    except KeyError as e:
        # The manifest validator restricts `bind` to a closed enum, so this
        # is unreachable in practice. Surfacing it as TunnelError keeps the
        # BIND_ADDRESS_MAP contract enforced rather than aspirational: a
        # future bind mode added to the manifest schema MUST also extend
        # the map, or the tunnel builder fails loudly here.
        raise TunnelError(
            f"unknown bind mode {resolved.bind!r} — extend BIND_ADDRESS_MAP"
        ) from e
    return _ssh_command(
        local_port=local_port,
        remote_port=resolved.remote_port,
        remote_bind_addr=remote_bind_addr,
        ssh_user=user,
        ssh_host=resolved.host,
        ssh_port=ssh.get("port") if isinstance(ssh.get("port"), int) else None,
        identity_file=ssh.get("identity_file")
        if isinstance(ssh.get("identity_file"), str)
        else None,
    )


def _get_ensure_lock(agent_key: str) -> threading.Lock:
    with _ENSURE_LOCKS_MUTEX:
        lock = _ENSURE_LOCKS.get(agent_key)
        if lock is None:
            lock = threading.Lock()
            _ENSURE_LOCKS[agent_key] = lock
        return lock


def ensure(agent_key: str, *, owned: bool = True) -> int:
    """Idempotently establish (or reuse) an SSH tunnel for ``agent_key``.

    Returns the local port on 127.0.0.1 that forwards to the agent's
    dashboard. Raises :class:`TunnelError` if the agent has no web UI,
    SSH config is incomplete, or the SSH process fails to bind the
    forward in time. Concurrent callers for the same key are serialised
    by a per-key lock so they never spawn duplicate ssh processes.

    When *owned* is True (default, used by the GUI), the tunnel is
    registered with the process-wide atexit handler and will be killed
    when this Python process exits. When False (used by the CLI), the
    tunnel subprocess outlives the caller — it stays alive until the
    SSH connection drops, or another caller explicitly closes it.
    """
    resolved = resolve(agent_key)
    if resolved is None:
        raise TunnelError(
            f"Agent '{agent_key}' has no native web UI (or is not installed)."
        )

    with _get_ensure_lock(agent_key):
        existing = _existing_healthy_tunnel(agent_key)
        if existing is not None:
            if owned:
                _OWNED_TUNNELS.add(agent_key)
                _register_atexit()
            return existing.local_port

        _evict_stale(agent_key)

        local_port = _pick_free_port()
        cmd = _build_ssh_for(resolved, local_port)
        signature = _cmdline_signature(cmd)

        proc = _spawn_ssh(cmd)
        if not _wait_for_connect(local_port):
            if proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                except (ProcessLookupError, OSError):
                    pass
            stderr_tail = ""
            if proc.stderr is not None:
                try:
                    stderr_tail = proc.stderr.read().decode("utf-8", errors="replace")
                except (OSError, ValueError):
                    stderr_tail = ""
            raise TunnelError(
                f"SSH tunnel for '{agent_key}' did not become ready within "
                f"{_CONNECT_TIMEOUT_S:.0f}s. {stderr_tail.strip()[:200]}"
            )

        info = TunnelInfo(
            pid=proc.pid,
            local_port=local_port,
            started_at=time.time(),
            ssh_cmdline_signature=signature,
        )
        _write_state(agent_key, info)
        if owned:
            _OWNED_TUNNELS.add(agent_key)
            _register_atexit()
        return local_port


def ensure_at_port(agent_key: str, remote_port: int, *, owned: bool = True) -> int:
    """Like ``ensure`` but tunnels to an explicit ``remote_port`` instead of
    the agent's web-UI port.  Use a namespaced key (e.g. ``"kevin:chat"``) to
    avoid colliding with the web-UI tunnel for the same agent.
    """
    from clawrium.core.web_ui import ResolvedUI, resolve

    resolved = resolve(agent_key)
    if resolved is None:
        raise TunnelError(
            f"Agent '{agent_key}' could not be resolved for SSH tunnel."
        )

    ssh_config = resolved.ssh_config
    namespaced_key = f"{agent_key}:{remote_port}"
    with _get_ensure_lock(namespaced_key):
        existing = _existing_healthy_tunnel(namespaced_key)
        if existing is not None:
            if owned:
                _OWNED_TUNNELS.add(namespaced_key)
                _register_atexit()
            return existing.local_port

        _evict_stale(namespaced_key)

        local_port = _pick_free_port()
        tmp_resolved = ResolvedUI(
            host=resolved.host,
            bind="loopback",
            remote_port=remote_port,
            ssh_config=ssh_config,
        )
        cmd = _build_ssh_for(tmp_resolved, local_port)
        signature = _cmdline_signature(cmd)
        proc = _spawn_ssh(cmd)
        if not _wait_for_connect(local_port):
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
            raise TunnelError(
                f"SSH tunnel to port {remote_port} did not become ready in time."
            )

        import time
        info = TunnelInfo(pid=proc.pid, local_port=local_port, started_at=time.time(), ssh_cmdline_signature=signature)
        _write_state(namespaced_key, info)
        if owned:
            _OWNED_TUNNELS.add(namespaced_key)
            _register_atexit()
        return local_port


def close(agent_key: str) -> None:
    """Close (kill) the tunnel for ``agent_key`` if we own it.

    Safe to call when no tunnel exists. The cmdline guard ensures we
    never send signals to a PID that no longer corresponds to our SSH
    process.
    """
    _evict_stale(agent_key)
    _OWNED_TUNNELS.discard(agent_key)


def is_idle(agent_key: str, last_access_ts: float, threshold: float = 1800.0) -> bool:
    """Return True iff the tunnel for ``agent_key`` has been idle for too long.

    ``last_access_ts`` is the timestamp (``time.time()``) of the most
    recent request that touched this tunnel. The caller (GUI reaper)
    is responsible for tracking activity; we only decide if the gap is
    over threshold.
    """
    if last_access_ts <= 0:
        return False
    return (time.time() - last_access_ts) > threshold

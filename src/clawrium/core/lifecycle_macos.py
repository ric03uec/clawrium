"""launchctl-based lifecycle backend for macOS hermes agents.

Counterpart to `core/lifecycle.py:_run_lifecycle_playbook` for Darwin
targets. Where the systemd path runs a per-op playbook
(start.yaml/stop.yaml/restart.yaml) that wraps `systemctl`, the macOS
path just opens a paramiko SSH session and shells out to `launchctl`
in the `system` domain.

Why launchctl and not a playbook: launchctl's bootstrap/bootout/
kickstart trio is the entire surface area we need, and wrapping three
one-line `sudo launchctl ...` calls in three more YAML files would
just add indirection. The plist file itself (rendered in step 6) is
the only artifact that lives on disk.

Functions defined here intentionally mirror the signatures of the
equivalents in `core/lifecycle.py`: when `lifecycle.start_agent()`
sees `os_family == "darwin"` it delegates here. The CLI layer is
unchanged.
"""

from __future__ import annotations

import logging
import shlex
from datetime import datetime, timezone
from typing import Callable, TypedDict

import paramiko

from clawrium.core.launchd import (
    label_for,
    plist_path_for,
    remove_plist,
    render_plist,
    write_plist,
)

logger = logging.getLogger(__name__)


class LifecycleResult(TypedDict, total=False):
    success: bool
    agent: str
    host: str
    operation: str
    pid: int | None
    started_at: str | None
    error: str | None


class LifecycleError(Exception):
    """Raised on terminal failures (missing host record, ssh refused, ...)."""


def _ssh(host: dict) -> paramiko.SSHClient:
    """Open a paramiko SSH session to the host using the per-host key."""
    from clawrium.core.keys import get_host_private_key

    key_id = host.get("key_id") or host["hostname"]
    key_path = get_host_private_key(key_id)
    if not key_path:
        raise LifecycleError(f"No SSH key found for host {host['hostname']!r}")

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host["hostname"],
        port=int(host.get("port", 22)),
        username=host.get("user", "xclm"),
        key_filename=str(key_path),
        timeout=15,
    )
    return client


def _run(client: paramiko.SSHClient, cmd: str) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def install_service(client: paramiko.SSHClient, agent_name: str) -> str:
    """Render and write the gateway plist for `agent_name`. Returns the path.

    Idempotent: writing the same content over an existing plist is a
    no-op semantically. Does NOT bootstrap the unit — that's start_agent.
    Always ensures /Users/<agent>/.hermes/logs exists so StandardOutPath
    / StandardErrorPath in the plist resolve.
    """
    contents = render_plist(agent_name)
    path = write_plist(client, agent_name, contents)
    # Ensure log dir exists with correct ownership; launchd writes there
    # as the agent user.
    _run(
        client,
        "sudo mkdir -p /Users/" + shlex.quote(agent_name) + "/.hermes/logs "
        "&& sudo chown " + shlex.quote(agent_name) + ":staff "
        "/Users/" + shlex.quote(agent_name) + "/.hermes/logs",
    )
    return path


def _bootstrap(client: paramiko.SSHClient, agent_name: str) -> tuple[int, str, str]:
    """`launchctl bootstrap system <plist>`. Idempotent-ish.

    Bootstrap fails (rc=37 or rc=5) if the unit is already loaded; the
    caller treats that case as success. Other non-zero results bubble up.
    """
    path = plist_path_for(agent_name)
    return _run(client, f"sudo launchctl bootstrap system {shlex.quote(path)}")


def _bootout(client: paramiko.SSHClient, agent_name: str) -> tuple[int, str, str]:
    """`launchctl bootout system/<label>`. Tolerates "not loaded"."""
    label = label_for(agent_name)
    return _run(client, f"sudo launchctl bootout system/{shlex.quote(label)}")


def _kickstart(
    client: paramiko.SSHClient, agent_name: str, *, kill: bool = False
) -> tuple[int, str, str]:
    """`launchctl kickstart [-k] system/<label>` — restart in place."""
    label = label_for(agent_name)
    flag = "-k " if kill else ""
    return _run(client, f"sudo launchctl kickstart {flag}system/{shlex.quote(label)}")


def start_agent_macos(
    host: dict,
    agent_name: str,
    on_event: Callable[[str, str], None] | None = None,
) -> tuple[bool, str | None]:
    """Bootstrap the gateway plist into launchd's system domain.

    Returns (success, error). On a fresh install the plist needs to be
    rendered + written before bootstrap. On a re-run, bootstrap will
    return "already loaded" — we treat that as success and call
    kickstart to ensure the daemon is actually running.
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    client = _ssh(host)
    try:
        emit("start", f"installing plist for {agent_name}")
        install_service(client, agent_name)

        emit("start", f"launchctl bootstrap {agent_name}")
        rc, out, err = _bootstrap(client, agent_name)
        # rc 37 (Service already loaded) / rc 5 (Input/output) / rc 17
        # (File exists) — treat all "already loaded" variants as OK and
        # kickstart instead.
        already_loaded = rc in (5, 17, 37) and (
            "already" in (out + err).lower() or "service" in (out + err).lower()
        )
        if rc != 0 and not already_loaded:
            return False, f"launchctl bootstrap failed (rc={rc}): {err.strip() or out.strip()}"

        emit("start", f"launchctl kickstart {agent_name}")
        rc, out, err = _kickstart(client, agent_name)
        if rc != 0:
            return False, f"launchctl kickstart failed (rc={rc}): {err.strip() or out.strip()}"

        return True, None
    finally:
        client.close()


def stop_agent_macos(
    host: dict,
    agent_name: str,
    on_event: Callable[[str, str], None] | None = None,
) -> tuple[bool, str | None]:
    """`launchctl bootout system/<label>`. Tolerates not-loaded."""

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    client = _ssh(host)
    try:
        emit("stop", f"launchctl bootout {agent_name}")
        rc, out, err = _bootout(client, agent_name)
        not_loaded = rc != 0 and "could not find service" in (out + err).lower()
        if rc != 0 and not not_loaded:
            return False, f"launchctl bootout failed (rc={rc}): {err.strip() or out.strip()}"
        return True, None
    finally:
        client.close()


def restart_agent_macos(
    host: dict,
    agent_name: str,
    on_event: Callable[[str, str], None] | None = None,
) -> tuple[bool, str | None]:
    """`launchctl kickstart -k system/<label>` if loaded, else bootstrap."""

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    client = _ssh(host)
    try:
        emit("restart", f"launchctl kickstart -k {agent_name}")
        rc, out, err = _kickstart(client, agent_name, kill=True)
        if rc == 0:
            return True, None
        # kickstart fails if not loaded — fall back to fresh bootstrap.
        if "could not find service" in (out + err).lower():
            install_service(client, agent_name)
            rc2, out2, err2 = _bootstrap(client, agent_name)
            if rc2 != 0:
                return False, f"launchctl bootstrap fallback failed: {err2.strip() or out2.strip()}"
            return True, None
        return False, f"launchctl kickstart -k failed (rc={rc}): {err.strip() or out.strip()}"
    finally:
        client.close()


def remove_service_macos(
    host: dict, agent_name: str, on_event: Callable[[str, str], None] | None = None
) -> tuple[bool, str | None]:
    """bootout + delete plist file. Idempotent."""

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    client = _ssh(host)
    try:
        emit("remove", f"bootout {agent_name}")
        _bootout(client, agent_name)  # tolerate not-loaded
        remove_plist(client, agent_name)
        return True, None
    finally:
        client.close()


__all__ = [
    "LifecycleError",
    "LifecycleResult",
    "install_service",
    "remove_service_macos",
    "restart_agent_macos",
    "start_agent_macos",
    "stop_agent_macos",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

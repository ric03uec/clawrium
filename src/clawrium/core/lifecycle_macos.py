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

Public surface mirrors `core/lifecycle.py` (`start_agent`, `stop_agent`,
`restart_agent`, `configure_agent`) so the CLI can pick the right
backend via `playbook_resolver.resolve_lifecycle_backend(os_family)`
and call into it uniformly. `core/lifecycle.py` itself stays
OS-agnostic — no `if Darwin` branches there.
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


def install_service(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    dashboard_port: int | None = None,
    agent_type: str = "hermes",
) -> str:
    """Render and write the gateway plist (and dashboard plist if `dashboard_port`)
    for `agent_name`. Returns the gateway plist path.

    Idempotent: re-writing the same content is a no-op. Does NOT bootstrap
    the units — that's start_agent. Always ensures the agent's logs dir
    exists so StandardOutPath / StandardErrorPath in the plists resolve.
    """
    if agent_type == "openclaw":
        template_name = "openclaw.plist.j2"
        logs_dir = f"/Users/{agent_name}/.openclaw/logs"
    else:
        template_name = "gateway.plist.j2"
        logs_dir = f"/Users/{agent_name}/.hermes/logs"

    contents = render_plist(
        agent_name, template_name=template_name, agent_type=agent_type
    )
    path = write_plist(client, agent_name, contents, agent_type=agent_type)
    if agent_type == "hermes" and dashboard_port is not None:
        dash_contents = render_plist(
            agent_name,
            template_name="dashboard.plist.j2",
            dashboard_port=dashboard_port,
            agent_type=agent_type,
        )
        write_plist(
            client, agent_name, dash_contents, kind="dashboard", agent_type=agent_type
        )
    # Ensure log dir exists with correct ownership; launchd writes there
    # as the agent user. Surface failures — a missing logs dir crashes
    # the daemon at start with ENOENT on StandardOutPath.
    rc, out, err = _run(
        client,
        f"sudo mkdir -p {shlex.quote(logs_dir)} "
        f"&& sudo chown {shlex.quote(agent_name)}:staff {shlex.quote(logs_dir)}",
    )
    if rc != 0:
        raise RuntimeError(
            f"install_service: failed to prepare logs dir {logs_dir!r} "
            f"(rc={rc}): {(err or out).strip()}"
        )
    return path


def _bootstrap(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    kind: str = "gateway",
    agent_type: str = "hermes",
) -> tuple[int, str, str]:
    """`launchctl bootstrap system <plist>`. Idempotent-ish.

    Bootstrap fails (rc=37 or rc=5) if the unit is already loaded; the
    caller treats that case as success. Other non-zero results bubble up.
    """
    path = plist_path_for(agent_name, kind=kind, agent_type=agent_type)
    return _run(client, f"sudo launchctl bootstrap system {shlex.quote(path)}")


def _bootout(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    kind: str = "gateway",
    agent_type: str = "hermes",
) -> tuple[int, str, str]:
    """`launchctl bootout system/<label>`. Tolerates "not loaded"."""
    label = label_for(agent_name, kind=kind, agent_type=agent_type)
    return _run(client, f"sudo launchctl bootout system/{shlex.quote(label)}")


def _kickstart(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    kill: bool = False,
    kind: str = "gateway",
    agent_type: str = "hermes",
) -> tuple[int, str, str]:
    """`launchctl kickstart [-k] system/<label>` — restart in place."""
    label = label_for(agent_name, kind=kind, agent_type=agent_type)
    flag = "-k " if kill else ""
    return _run(client, f"sudo launchctl kickstart {flag}system/{shlex.quote(label)}")


def _dashboard_port_from_host(host: dict, agent_name: str) -> int | None:
    """Look up the persisted dashboard port for `agent_name` in `host`.

    install.py persists it under `agents.<name>.config.dashboard.port`.
    Returns None if the agent has no dashboard configured.
    """
    agents = host.get("agents") or {}
    rec = agents.get(agent_name) or {}
    cfg = rec.get("config") or {}
    dash = cfg.get("dashboard") or {}
    port = dash.get("port")
    try:
        return int(port) if port is not None else None
    except (TypeError, ValueError):
        return None


def _bootstrap_with_tolerance(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    kind: str,
    agent_type: str = "hermes",
) -> tuple[bool, str | None]:
    """`launchctl bootstrap`, treating any "already loaded" signal as success.

    macOS launchctl is annoyingly inconsistent about what it reports when
    a unit is already bootstrapped — observed cases include:
      - rc=5 + "Input/output error" (Sonoma onward)
      - rc=17 + "File exists"
      - rc=37 + "Service already loaded"
      - rc=149 + "Bootstrap failed: 149: Operation already in progress"
    The pragmatic check: any non-zero rc whose output mentions "already",
    "input/output", "file exists", or "service" is treated as success.
    The follow-up kickstart confirms whether the daemon is actually
    running.
    """
    rc, out, err = _bootstrap(client, agent_name, kind=kind, agent_type=agent_type)
    if rc == 0:
        return True, None
    combined = (out + err).lower()
    already_loaded = any(
        marker in combined
        for marker in ("already", "input/output", "file exists", "service")
    )
    if already_loaded:
        return True, None
    return False, f"launchctl bootstrap ({kind}) failed (rc={rc}): {err.strip() or out.strip()}"


def start_agent_macos(
    host: dict,
    agent_name: str,
    on_event: Callable[[str, str], None] | None = None,
    agent_type: str = "hermes",
) -> tuple[bool, str | None]:
    """Bootstrap the gateway (and dashboard, if configured) plists into
    launchd's system domain.

    Returns (success, error). On a fresh install the plists need to be
    rendered + written before bootstrap. On a re-run, bootstrap will
    return "already loaded" — we treat that as success and call
    kickstart to ensure the daemons are actually running.
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    dashboard_port = (
        _dashboard_port_from_host(host, agent_name) if agent_type == "hermes" else None
    )

    client = _ssh(host)
    try:
        emit("start", f"installing plists for {agent_name}")
        install_service(
            client, agent_name, dashboard_port=dashboard_port, agent_type=agent_type
        )

        emit("start", f"launchctl bootstrap {agent_name} (gateway)")
        ok, err = _bootstrap_with_tolerance(
            client, agent_name, kind="gateway", agent_type=agent_type
        )
        if not ok:
            return False, err

        emit("start", f"launchctl kickstart {agent_name} (gateway)")
        rc, out, err = _kickstart(
            client, agent_name, kind="gateway", agent_type=agent_type
        )
        if rc != 0:
            return False, f"launchctl kickstart (gateway) failed (rc={rc}): {err.strip() or out.strip()}"

        if dashboard_port is not None:
            emit("start", f"launchctl bootstrap {agent_name} (dashboard:{dashboard_port})")
            ok, err = _bootstrap_with_tolerance(
                client, agent_name, kind="dashboard", agent_type=agent_type
            )
            if not ok:
                return False, err
            emit("start", f"launchctl kickstart {agent_name} (dashboard)")
            rc, out, err = _kickstart(
                client, agent_name, kind="dashboard", agent_type=agent_type
            )
            if rc != 0:
                return False, f"launchctl kickstart (dashboard) failed (rc={rc}): {err.strip() or out.strip()}"

        return True, None
    finally:
        client.close()


def stop_agent_macos(
    host: dict,
    agent_name: str,
    on_event: Callable[[str, str], None] | None = None,
    agent_type: str = "hermes",
) -> tuple[bool, str | None]:
    """`launchctl bootout` for both dashboard (if present) and gateway.

    Tolerates "could not find service" for both — launchd lacks a systemd
    PartOf= equivalent, so we enumerate the labels explicitly. Dashboard
    is reaped first so the gateway's lifecycle is the last thing the
    operator sees in logs.
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    kinds_to_stop = (
        ("dashboard", "gateway") if agent_type == "hermes" else ("gateway",)
    )
    client = _ssh(host)
    try:
        for kind in kinds_to_stop:
            emit("stop", f"launchctl bootout {agent_name} ({kind})")
            rc, out, err = _bootout(
                client, agent_name, kind=kind, agent_type=agent_type
            )
            combined = (out + err).lower()
            # rc=3 "no such process" + rc=113/varied "could not find service"
            # both signal "wasn't loaded" — idempotent stop tolerates them.
            not_loaded = rc != 0 and (
                "could not find service" in combined
                or "no such process" in combined
                or "no such file" in combined
            )
            if rc != 0 and not not_loaded:
                return False, f"launchctl bootout ({kind}) failed (rc={rc}): {err.strip() or out.strip()}"
        return True, None
    finally:
        client.close()


def restart_agent_macos(
    host: dict,
    agent_name: str,
    on_event: Callable[[str, str], None] | None = None,
    agent_type: str = "hermes",
) -> tuple[bool, str | None]:
    """`launchctl kickstart -k system/<label>` for both labels if loaded.

    Mirrors stop_agent_macos's explicit ('dashboard', 'gateway') enumeration
    so dashboard restarts in lock-step with the gateway. If either label
    is not loaded, falls back to a fresh bootstrap of BOTH plists using
    the persisted dashboard port (if any) from the host record. This
    ensures `clawctl agent restart h1` on a cold host produces the same
    end state as a clean `start`.
    """

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    dashboard_port = (
        _dashboard_port_from_host(host, agent_name) if agent_type == "hermes" else None
    )
    kinds: tuple[str, ...] = (
        ("dashboard", "gateway") if dashboard_port is not None else ("gateway",)
    )

    client = _ssh(host)
    try:
        any_not_loaded = False
        for kind in kinds:
            emit("restart", f"launchctl kickstart -k {agent_name} ({kind})")
            rc, out, err = _kickstart(
                client, agent_name, kill=True, kind=kind, agent_type=agent_type
            )
            if rc == 0:
                continue
            combined = (out + err).lower()
            if "could not find service" in combined or "no such process" in combined:
                any_not_loaded = True
                break
            return False, (
                f"launchctl kickstart -k ({kind}) failed (rc={rc}): "
                f"{err.strip() or out.strip()}"
            )

        if not any_not_loaded:
            return True, None

        # Fallback: at least one label was missing — full re-bootstrap of
        # both plists. install_service handles dashboard when port is given.
        emit("restart", f"installing plists for {agent_name} (fallback)")
        install_service(
            client, agent_name, dashboard_port=dashboard_port, agent_type=agent_type
        )
        for kind in kinds:
            emit("restart", f"launchctl bootstrap {agent_name} (fallback {kind})")
            ok, err = _bootstrap_with_tolerance(
                client, agent_name, kind=kind, agent_type=agent_type
            )
            if not ok:
                return False, err
            emit("restart", f"launchctl kickstart {agent_name} (fallback {kind})")
            rc, out, err = _kickstart(
                client, agent_name, kind=kind, agent_type=agent_type
            )
            if rc != 0:
                return False, (
                    f"launchctl kickstart fallback ({kind}) failed (rc={rc}): "
                    f"{err.strip() or out.strip()}"
                )
        return True, None
    finally:
        client.close()


def remove_service_macos(
    host: dict,
    agent_name: str,
    on_event: Callable[[str, str], None] | None = None,
    agent_type: str = "hermes",
) -> tuple[bool, str | None]:
    """bootout + delete plist file. Idempotent."""

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    kinds_to_remove = (
        ("dashboard", "gateway") if agent_type == "hermes" else ("gateway",)
    )
    client = _ssh(host)
    try:
        for kind in kinds_to_remove:
            emit("remove", f"bootout {agent_name} ({kind})")
            rc, out, err = _bootout(
                client, agent_name, kind=kind, agent_type=agent_type
            )
            combined = (out + err).lower()
            not_loaded = rc != 0 and (
                "could not find service" in combined
                or "no such process" in combined
                or "no such file" in combined
            )
            # rc != 0 and not "not loaded" → real bootout failure (e.g.
            # rc=5 operation not permitted). Bail BEFORE deleting the
            # plist to avoid orphaning the still-running daemon.
            if rc != 0 and not not_loaded:
                return False, (
                    f"launchctl bootout ({kind}) failed (rc={rc}): "
                    f"{err.strip() or out.strip()}"
                )
            remove_plist(client, agent_name, kind=kind, agent_type=agent_type)
        return True, None
    finally:
        client.close()


# ===== Public API (matches core/lifecycle.py shape) =====
#
# The CLI layer (`cli/clawctl/agent/{start,stop,restart,configure}.py`)
# selects this backend via
# `playbook_resolver.resolve_lifecycle_backend(os_family)` and calls
# these entry points uniformly. core/lifecycle.py never has to know
# about darwin.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_agent_record(host: dict, target: str, expected_type: str):
    """Re-export the resolver from lifecycle.py for parity (avoids a
    circular import by importing inside the function body)."""
    from clawrium.core.lifecycle import _resolve_agent_record as _r

    return _r(host, target, expected_type=expected_type)


def _update_agent_runtime(hostname: str, agent_key: str, runtime_data: dict):
    from clawrium.core.lifecycle import _update_agent_runtime as _u

    return _u(hostname, agent_key, runtime_data)


def start_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    force: bool = False,
    on_event: Callable[[str, str], None] | None = None,
    repair_reason: str = "start",
) -> LifecycleResult:
    """Match `lifecycle.start_agent` signature; execute via launchctl."""
    from clawrium.core.hosts import get_host
    from clawrium.core.onboarding import OnboardingState

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("validate", f"Checking {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, _agent_type, claw_record = resolved

    onboarding = claw_record.get("onboarding", {})
    state_value = onboarding.get("state", "pending")
    try:
        state = OnboardingState(state_value)
    except ValueError:
        state = OnboardingState.PENDING

    if state != OnboardingState.READY and not force:
        raise LifecycleError(
            f"Cannot start {agent_key}: onboarding incomplete (state={state_value}). "
            f"Run 'clawctl agent configure {agent_key}' first."
        )

    emit("start", f"Starting {agent_key} on {hostname}...")
    success, error = start_agent_macos(
        host, agent_key, on_event=on_event, agent_type=claw_name
    )

    now = _now_iso() if success else None
    if success:
        _update_agent_runtime(
            host["hostname"],
            agent_key,
            {"status": "running", "started_at": now, "last_check": now},
        )
        emit("start", f"Started {agent_key} successfully")

    return {
        "success": success,
        "agent": agent_key,
        "host": hostname,
        "operation": "start",
        "pid": None,
        "started_at": now,
        "error": error,
    }


def stop_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    timeout: int = 30,  # noqa: ARG001 — accepted for parity, unused on launchctl
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Match `lifecycle.stop_agent` signature; execute via launchctl."""
    from clawrium.core.hosts import get_host

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("validate", f"Checking {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, _agent_type, _ = resolved

    emit("stop", f"Stopping {agent_key} on {hostname}...")
    success, error = stop_agent_macos(
        host, agent_key, on_event=on_event, agent_type=claw_name
    )

    now = _now_iso() if success else None
    if success:
        _update_agent_runtime(
            host["hostname"],
            agent_key,
            {
                "status": "stopped",
                "started_at": None,
                "stopped_at": now,
                "last_check": now,
            },
        )
        emit("stop", f"Stopped {agent_key} successfully")

    return {
        "success": success,
        "agent": agent_key,
        "host": hostname,
        "operation": "stop",
        "pid": None,
        "started_at": None,
        "error": error,
    }


def restart_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Match `lifecycle.restart_agent` signature; execute via launchctl
    kickstart -k for both labels (with bootstrap fallback)."""
    from clawrium.core.hosts import get_host

    def emit(stage: str, message: str) -> None:
        if on_event:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    target = agent_name or claw_name
    emit("restart", f"Restarting {target} on {hostname}...")

    host = get_host(hostname)
    if not host:
        raise LifecycleError(f"Host '{hostname}' not found")

    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        raise LifecycleError(f"Agent '{target}' not installed on '{hostname}'")
    agent_key, _agent_type, _ = resolved

    success, error = restart_agent_macos(
        host, agent_key, on_event=on_event, agent_type=claw_name
    )

    now = _now_iso() if success else None
    if success:
        _update_agent_runtime(
            host["hostname"],
            agent_key,
            {"status": "running", "started_at": now, "last_check": now},
        )
        emit("restart", f"Restarted {agent_key} successfully")

    return {
        "success": success,
        "agent": agent_key,
        "host": hostname,
        "operation": "restart",
        "pid": None,
        "started_at": now,
        "error": error,
    }


def configure_agent(
    hostname: str,
    claw_name: str,
    config_data: dict,
    agent_name: str | None = None,
    extra_vars: dict | None = None,
    on_event: Callable[[str, str], None] | None = None,
    reason: str = "configure",
) -> tuple[bool, str | None]:
    """Match `lifecycle.configure_agent` signature.

    Delegates to `lifecycle.configure_agent` with the macOS playbook
    forced via the `playbook_path_override` hook. After a successful
    configure, triggers a launchctl restart so the daemon picks up the
    new .env / config.yaml — the configure_macos.yaml playbook itself
    does not poke launchctl (would duplicate the dispatcher logic in
    YAML, and ATX iteration 1 B2 flagged the previous "orchestrator
    will dispatch" comment as unimplemented; this is the dispatch).
    """
    from clawrium.core.hosts import get_host
    from clawrium.core.lifecycle import configure_agent as _core_configure
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    macos_playbook = resolve_agent_playbook(claw_name, "configure", "darwin")
    ok, err = _core_configure(
        hostname=hostname,
        claw_name=claw_name,
        config_data=config_data,
        agent_name=agent_name,
        extra_vars=extra_vars,
        on_event=on_event,
        reason=reason,
        playbook_path_override=macos_playbook,
    )
    if not ok:
        return False, err

    host = get_host(hostname)
    if host is None:
        return False, f"Host '{hostname}' not found after configure"

    target = agent_name or claw_name
    resolved = _resolve_agent_record(host, target, expected_type=claw_name)
    if not resolved:
        return False, f"Agent '{target}' missing after configure"
    agent_key, _agent_type, _ = resolved

    restart_ok, restart_err = restart_agent_macos(
        host, agent_key, on_event=on_event, agent_type=claw_name
    )
    if not restart_ok:
        return False, f"Post-configure restart failed: {restart_err}"
    return True, None


def sync_agent(
    hostname: str,
    claw_name: str,
    agent_name: str | None = None,
    workspace_only: bool = False,
    on_event: Callable[[str, str], None] | None = None,
) -> LifecycleResult:
    """Match `lifecycle.sync_agent` signature.

    Delegates to `lifecycle.sync_agent` with the macOS configure
    playbook forced via `playbook_path_override`, then triggers a
    launchctl restart so the gateway/dashboard pick up the freshly
    written .env / config.yaml. configure_macos.yaml has no Ansible
    handlers (the Linux configure.yaml's "Restart hermes service"
    handler is systemd-only); the restart here is the equivalent.
    """
    from clawrium.core.hosts import get_host
    from clawrium.core.lifecycle import sync_agent as _core_sync
    from clawrium.core.playbook_resolver import resolve_agent_playbook

    macos_playbook = resolve_agent_playbook(claw_name, "configure", "darwin")
    result = _core_sync(
        hostname=hostname,
        claw_name=claw_name,
        agent_name=agent_name,
        workspace_only=workspace_only,
        on_event=on_event,
        playbook_path_override=macos_playbook,
    )
    if not result.get("success"):
        return result

    host = get_host(hostname)
    if host is None:
        result["success"] = False
        result["error"] = f"Host '{hostname}' not found after sync"
        return result

    agent_key = result.get("agent") or agent_name or claw_name
    restart_ok, restart_err = restart_agent_macos(
        host, agent_key, on_event=on_event, agent_type=claw_name
    )
    if not restart_ok:
        result["success"] = False
        result["error"] = f"Post-sync restart failed: {restart_err}"
    return result


__all__ = [
    "LifecycleError",
    "LifecycleResult",
    "configure_agent",
    "install_service",
    "remove_service_macos",
    "restart_agent",
    "restart_agent_macos",
    "start_agent",
    "start_agent_macos",
    "stop_agent",
    "stop_agent_macos",
    "sync_agent",
]

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


def _run(
    client: paramiko.SSHClient,
    cmd: str,
    *,
    timeout: int | None = None,
) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
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
    timeout: int | None = None,
) -> str:
    """Render and write the gateway plist (and dashboard plist if `dashboard_port`)
    for `agent_name`. Returns the gateway plist path.

    Idempotent: re-writing the same content is a no-op. Does NOT bootstrap
    the units — that's start_agent. Always ensures the agent's logs dir
    exists so StandardOutPath / StandardErrorPath in the plists resolve.

    `timeout` (default None = no bound) is honored on the `sudo mkdir
    -p / chown` command so callers from the canonical sync path can
    bound every sudo call in the fallback leg (B2).
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
        timeout=timeout,
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
    timeout: int | None = None,
) -> tuple[int, str, str]:
    """`launchctl bootstrap system <plist>`. Idempotent-ish.

    Bootstrap fails (rc=37 or rc=5) if the unit is already loaded; the
    caller treats that case as success. Other non-zero results bubble up.
    """
    path = plist_path_for(agent_name, kind=kind, agent_type=agent_type)
    return _run(
        client,
        f"sudo launchctl bootstrap system {shlex.quote(path)}",
        timeout=timeout,
    )


def _bootout(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    kind: str = "gateway",
    agent_type: str = "hermes",
    timeout: int | None = None,
) -> tuple[int, str, str]:
    """`launchctl bootout system/<label>`. Tolerates "not loaded"."""
    label = label_for(agent_name, kind=kind, agent_type=agent_type)
    return _run(
        client,
        f"sudo launchctl bootout system/{shlex.quote(label)}",
        timeout=timeout,
    )


def _kickstart(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    kill: bool = False,
    kind: str = "gateway",
    agent_type: str = "hermes",
    timeout: int | None = None,
) -> tuple[int, str, str]:
    """`launchctl kickstart [-k] system/<label>` — restart in place."""
    label = label_for(agent_name, kind=kind, agent_type=agent_type)
    flag = "-k " if kill else ""
    return _run(
        client,
        f"sudo launchctl kickstart {flag}system/{shlex.quote(label)}",
        timeout=timeout,
    )


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
    timeout: int | None = None,
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
    rc, out, err = _bootstrap(
        client, agent_name, kind=kind, agent_type=agent_type, timeout=timeout
    )
    if rc == 0:
        return True, None
    combined = (out + err).lower()
    # Explicit (rc, marker) pairs — bare 'service' substring used
    # previously over-matched malformed-plist errors (e.g. rc=5
    # 'Service configuration invalid: ...') and silently reported
    # success. Anything outside this matrix bubbles up as a real failure.
    already_loaded = (
        rc == 37
        or (rc == 17 and "file exists" in combined)
        or (rc == 5 and "input/output" in combined)
        or (rc == 149 and "already" in combined)
        or "service already loaded" in combined
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
    # ATX iter4 B1: do NOT let _core_sync write state=READY before we
    # know the post-sync launchctl restart succeeded. Otherwise a
    # failed restart leaves hosts.json claiming the agent is ready
    # while the daemon is down — a subsequent `clawctl agent start`
    # passes the READY guard and meets a stopped service.
    result = _core_sync(
        hostname=hostname,
        claw_name=claw_name,
        agent_name=agent_name,
        workspace_only=workspace_only,
        on_event=on_event,
        playbook_path_override=macos_playbook,
        defer_state_transition=True,
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

    # Restart succeeded → commit the deferred READY transition. Mirrors
    # the matrix in _core_sync (InvalidTransitionError is a no-op, the
    # two registry-missing branches surface as warnings).
    from clawrium.core.onboarding import (
        AgentNotFoundError,
        InvalidTransitionError,
        OnboardingNotFoundError,
        OnboardingState,
        transition_state,
    )

    try:
        transition_state(hostname, agent_key, OnboardingState.READY)
    except InvalidTransitionError as exc:
        if on_event:
            on_event(
                "sync",
                f"note: skipped state=READY for {agent_key} (mid-walk: {exc!s})",
            )
    except (AgentNotFoundError, OnboardingNotFoundError) as exc:
        result["success"] = False
        result["error"] = (
            f"registry record missing for {agent_key} after sync: {exc!s}"
        )
    except Exception as exc:
        result["success"] = False
        result["error"] = (
            f"could not write state=READY to hosts.json: {exc!s}. "
            f"Agent is configured + running; re-run sync to commit state."
        )
    return result


# --- Canonical-sync dispatch helpers (called from lifecycle_canonical.py) ----
#
# These wrap launchctl in the same shape the Linux path uses in
# lifecycle_canonical.py (atomic_write / restart_unit / verify_health) so
# the canonical sync pipeline can route to macOS via a thin dispatcher
# rather than `if host_os == 'macos':` branches inside the canonical file.
# Dispatcher-only OS fork — see AGENTS.md feedback memory.


def atomic_write_macos(
    client: paramiko.SSHClient,
    *,
    agent_name: str,
    remote_path: str,
    body: str,
    timeout: int = 30,
) -> None:
    """Atomic file replace on macOS via `install -g staff`.

    macOS agent users are created with PrimaryGroupID 20 (`staff`); there
    is no per-user group matching the agent name like on Linux. Raises
    `clawrium.core.lifecycle_canonical.CanonicalSyncError` on failure so
    the canonical sync surface stays uniform.

    `agent_name` is validated up-front (defense-in-depth W1) — every
    public entry point in `launchd.py` does the same; the `shlex.quote`
    on the f-string interpolation alone is current-safe but an explicit
    regex guard survives future refactors to argv form.
    """
    from clawrium.core.launchd import _validate_agent_name
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    _validate_agent_name(agent_name)

    quoted_path = shlex.quote(remote_path)
    tmp_path: str | None = None
    try:
        # `/tmp` is mode 1777 (sticky bit) on every supported macOS /
        # Linux host, so only root or the owner can unlink files in
        # it — the mktemp→sftp→install window is safe against a
        # same-host attacker racing to swap the tmpfile contents (S3).
        # The mktemp template ends in XXXXXX → mode 0600 on creation
        # per POSIX. mktemp is inside the try (W3) so the empty-stdout
        # / unsafe-path branches below still hit the cleanup leg if
        # mktemp managed to land a file before reporting back.
        _, mktemp_out, mktemp_err = client.exec_command(
            "mktemp /tmp/clawrium-sync.XXXXXX", timeout=timeout
        )
        # S1: drain stderr first (W2 deadlock guard), then exit
        # status — surfaces sudo/disk-full/permissions errors instead
        # of a bare "mktemp failed".
        mktemp_stdout_text = mktemp_out.read().decode("utf-8", errors="replace")
        mktemp_stderr_text = mktemp_err.read().decode("utf-8", errors="replace")
        mktemp_rc = mktemp_out.channel.recv_exit_status()
        if mktemp_rc != 0:
            detail = mktemp_stderr_text.strip() or mktemp_stdout_text.strip()
            raise CanonicalSyncError(
                f"mktemp failed on host (exit {mktemp_rc}): {detail}"
            )
        candidate = mktemp_stdout_text.strip()
        if not candidate:
            raise CanonicalSyncError(
                "mktemp returned empty path (transient SSH glitch?); "
                "refusing to write body to an empty target"
            )
        # B1: validate the path actually lives under our /tmp prefix.
        # A hostile/malfunctioning host returning
        # `/Users/<agent>/.openclaw/openclaw.json` from mktemp would
        # otherwise let the sudo install below overwrite that path
        # with `body`. Same defense-in-depth register as
        # _validate_agent_name.
        if not candidate.startswith("/tmp/clawrium-sync."):
            raise CanonicalSyncError(
                f"mktemp returned unsafe path {candidate!r}; expected "
                f"prefix '/tmp/clawrium-sync.'"
            )
        tmp_path = candidate

        sftp = client.open_sftp()
        try:
            with sftp.file(tmp_path, "wb") as fh:
                fh.write(body.encode("utf-8"))
        finally:
            sftp.close()
        owner = shlex.quote(agent_name)
        cmd = (
            f"sudo -n install -m 0600 -o {owner} -g staff "
            f"{shlex.quote(tmp_path)} {quoted_path}"
        )
        _, install_out, install_err = client.exec_command(cmd, timeout=timeout)
        # W2: drain stderr (and stdout) BEFORE `recv_exit_status`. If
        # the remote process is buffered on a full stderr (≥64KB) it
        # blocks on write and recv_exit_status waits forever. read()
        # drains the buffer as bytes arrive, unblocking the write.
        stdout_text = install_out.read().decode("utf-8", errors="replace")
        stderr_text = install_err.read().decode("utf-8", errors="replace")
        rc = install_out.channel.recv_exit_status()
        if rc != 0:
            detail = stderr_text.strip() or stdout_text.strip()
            raise CanonicalSyncError(
                f"install {remote_path!r} failed (exit {rc}): {detail}"
            )
    finally:
        # S2: drain the cleanup channel deterministically — without
        # `recv_exit_status` the SSH channel lingers until GC and can
        # tie up server-side resources on long-lived sync sessions.
        # Skip when `tmp_path` is None (mktemp itself failed before
        # returning a path); skip when path is unsafe (we never
        # accepted it). The `rm -f` is bounded by the same timeout.
        if tmp_path is not None:
            _, cleanup_out, _ = client.exec_command(
                f"rm -f {shlex.quote(tmp_path)}", timeout=timeout
            )
            cleanup_out.channel.recv_exit_status()


def restart_unit_macos(
    client: paramiko.SSHClient,
    *,
    host: dict,
    agent_name: str,
    agent_type: str,
    on_event: Callable[[str, str], None] | None = None,
    timeout: int = 30,
) -> None:
    """Restart agent via launchctl using existing macOS helpers.

    Mirrors `restart_agent_macos` but takes a pre-opened client (so the
    canonical sync can reuse its connection): enumerates dashboard +
    gateway labels for hermes; falls back to a fresh
    install_service + bootstrap when kickstart reports "not loaded".

    `agent_name` is validated up-front so a shell metacharacter cannot
    reach `sudo launchctl` through the label f-string in `_kickstart`.
    `label_for` raises `ValueError` for unsupported (agent_type, kind)
    combinations (e.g. zeroclaw on macOS) — wrapped here as
    `CanonicalSyncError` so the canonical sync's error surface stays
    uniform (W4).

    `timeout` (default 30s) is propagated into every `launchctl …` call
    so a wedged sudo cannot hang the canonical sync indefinitely (W3).
    """
    from clawrium.core.launchd import _validate_agent_name
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    _validate_agent_name(agent_name)

    def _emit(stage: str, msg: str) -> None:
        if on_event is not None:
            on_event(stage, msg)

    dashboard_port = (
        _dashboard_port_from_host(host, agent_name) if agent_type == "hermes" else None
    )
    kinds: tuple[str, ...] = (
        ("dashboard", "gateway") if dashboard_port is not None else ("gateway",)
    )

    # W4: resolve labels up-front so a `label_for` ValueError
    # (unsupported agent_type/kind combo, e.g. zeroclaw on macOS)
    # surfaces as CanonicalSyncError before any wire call, not as an
    # unhandled traceback past sync_agent_canonical.
    #
    # S1 iter-3: the resolved values feed only the `_emit` log lines
    # below — `_kickstart` recomputes its own label internally via
    # `label_for`. The eager resolve is for FAIL-FAST + LOG-DISPLAY,
    # not to share state with the launchctl helpers.
    try:
        labels = {
            kind: label_for(agent_name, kind=kind, agent_type=agent_type)
            for kind in kinds
        }
    except ValueError as exc:
        raise CanonicalSyncError(
            f"restart_unit_macos: unsupported launchd label for "
            f"agent_type={agent_type!r}: {exc}"
        ) from exc

    any_not_loaded = False
    for kind in kinds:
        _emit("restart", f"launchctl kickstart -k system/{labels[kind]}")
        rc, out, err = _kickstart(
            client,
            agent_name,
            kill=True,
            kind=kind,
            agent_type=agent_type,
            timeout=timeout,
        )
        if rc == 0:
            continue
        combined = (out + err).lower()
        if "could not find service" in combined or "no such process" in combined:
            any_not_loaded = True
            break
        raise CanonicalSyncError(
            f"launchctl kickstart -k ({kind}) failed (rc={rc}): "
            f"{(err or out).strip()}"
        )

    if not any_not_loaded:
        return

    _emit("restart", f"installing plists for {agent_name} (fallback)")
    install_service(
        client,
        agent_name,
        dashboard_port=dashboard_port,
        agent_type=agent_type,
        timeout=timeout,
    )
    for kind in kinds:
        _emit("restart", f"launchctl bootstrap {agent_name} (fallback {kind})")
        ok, err = _bootstrap_with_tolerance(
            client,
            agent_name,
            kind=kind,
            agent_type=agent_type,
            timeout=timeout,
        )
        if not ok:
            raise CanonicalSyncError(err)
        _emit("restart", f"launchctl kickstart {agent_name} (fallback {kind})")
        rc, out, err = _kickstart(
            client,
            agent_name,
            kind=kind,
            agent_type=agent_type,
            timeout=timeout,
        )
        if rc != 0:
            raise CanonicalSyncError(
                f"launchctl kickstart fallback ({kind}) failed (rc={rc}): "
                f"{(err or out).strip()}"
            )


def verify_health_macos(
    client: paramiko.SSHClient,
    *,
    agent_name: str,
    gateway_port: int | None,
    on_event: Callable[[str, str], None] | None = None,
    timeout: int = 30,
) -> None:
    """Poll the gateway port with `nc -z` until accept, or raise on timeout.

    macOS launchd has no `systemctl is-active` equivalent. We probe the
    loopback gateway port with `nc -z -w 1 127.0.0.1 <port>` — a TCP
    connect that succeeds when the daemon is `accept()`-ing. `nc` ships
    in macOS by default and (unlike `lsof -i :<port>`) does not require
    `sudo` to see a listener owned by a different user (the canonical
    sync runs as `xclm` while the daemon runs as `<agent_name>`; macOS
    `lsof` only shows your own ports).

    A missing port is treated as `CanonicalSyncError` rather than a
    skip (W2 iter-3): all agent types reaching this dispatcher on
    macOS (openclaw, hermes) declare gateways in their manifests, so
    `gateway_port is None` means install.py never allocated one — the
    agent was never properly installed, and a skip would let
    canonical sync write `state=READY` for a never-verified daemon.
    """
    from clawrium.core.launchd import _validate_agent_name
    from clawrium.core.lifecycle_canonical import CanonicalSyncError
    import re as _re
    import time as _time

    # W4: parity with atomic_write_macos / restart_unit_macos. The
    # name currently only appears in error strings, but a future
    # refactor adding e.g. `lsof -u <name>` for richer diagnostics
    # would silently lose the guard without this call.
    _validate_agent_name(agent_name)

    if gateway_port is None:
        raise CanonicalSyncError(
            f"verify_health_macos: no gateway port persisted for "
            f"{agent_name!r}. install.py never allocated one — the "
            f"agent install is incomplete. Re-run "
            f"`clawctl agent create` or inspect "
            f"hosts.json.agents.{agent_name}.config.gateway.port."
        )
    # `type(...) is int` (not `isinstance`) so `True`/`False` are
    # rejected — bool is a subclass of int and a JSON parser that
    # round-trips `true` through `int` would otherwise sail through.
    if (
        type(gateway_port) is not int
        or not 0 < gateway_port < 65536
    ):
        raise CanonicalSyncError(
            f"verify_health_macos: invalid gateway_port {gateway_port!r}"
        )

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        cmd = f"nc -z -w 1 127.0.0.1 {gateway_port}"
        _, out, err = client.exec_command(cmd, timeout=5)
        # W2 ordering: drain both streams before exit status.
        _ = out.read()
        stderr_text = err.read().decode("utf-8", errors="replace")
        rc = out.channel.recv_exit_status()
        if rc == 0:
            return
        # W5: if `nc` itself is missing (PATH-broken, stripped image,
        # etc.) every poll fails with a "command not found"-shaped
        # stderr. Break early with a diagnostic that points at the
        # tool, not at the daemon — otherwise the operator chases a
        # 30s "port not accepting" red herring.
        #
        # W1 iter-3: regex-match the precise "nc … not found" shape.
        # The previous boolean had an unparenthesized `or … and …`
        # that risked matching a stray "nc:" prefix on BSD
        # `connection refused` stderr from a not-yet-listening daemon
        # and prematurely aborting the wait window.
        _NC_MISSING_RE = _re.compile(r"\bnc\b[^\n]*not found", _re.IGNORECASE)
        if (
            "command not found" in stderr_text.lower()
            or _NC_MISSING_RE.search(stderr_text)
        ):
            raise CanonicalSyncError(
                f"verify_health_macos: `nc` is not available on the agent "
                f"host (stderr: {stderr_text.strip()}). nc ships with "
                f"macOS by default — investigate PATH / image stripping."
            )
        _time.sleep(1)
    raise CanonicalSyncError(
        f"gateway port {gateway_port} not accepting connections after "
        f"{timeout}s (agent={agent_name})"
    )


__all__ = [
    "LifecycleError",
    "LifecycleResult",
    "atomic_write_macos",
    "configure_agent",
    "install_service",
    "remove_service_macos",
    "restart_agent",
    "restart_agent_macos",
    "restart_unit_macos",
    "start_agent",
    "start_agent_macos",
    "stop_agent",
    "stop_agent_macos",
    "sync_agent",
    "verify_health_macos",
]

"""Canonical sync pipeline for parent #555 F3.

The legacy `core/lifecycle.py:sync_agent` re-renders on-host config via
ansible extravars and templates that conditionally emit each block
based on whether `hosts.json.agents.<name>.config.<field>` happens to
be populated. That's the bug parent #555 documents: every clawctl op
silently wipes whichever blocks lack a populated hosts.json field.

This module replaces that path with the canonical pipeline:

    inputs   = build_render_inputs(name)        # raises on missing
    rendered = render_<atype>(inputs)           # pure function
    remote   = read_remote_file(...) per file   # what's on host now
    diff     = compute per-file unified diff
    refuse   = if diff removes a secret line AND not force: raise
    write    = atomic per-file sudo-mv into place, mode 0600
    restart  = systemctl restart <atype>-<name>.service
    verify   = light health check (unit active)

Since #560, this is the only sync path — the `--canonical` opt-in flag
was dropped and the legacy ansible extravar fork was removed from
`clawctl agent sync`. The test matrix in
`tests/integration/test_render_matrix.py` continues to prove parity
against the legacy renderer outputs.

Post-write tail (#560):

    repair  = for zeroclaw, re-pair gateway bearer (#437) and atomically
              persist to hosts.json.gateway.auth
    advance = transition onboarding state to READY (swallows
              InvalidTransitionError for mid-walk agents)

The re-pair step reuses `lifecycle._zeroclaw_repair_after_start` so the
ansible pair playbook (the single source of truth for the
`POST /pair/code → POST /pair` handshake) is not duplicated. The READY
write mirrors `sync_agent`'s post-configure transition at
`lifecycle.py:1386-1438` and tolerates the same exception shapes.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from typing import Callable

import paramiko

from clawrium.core.hosts import get_agent_by_name
from clawrium.core.keys import get_host_private_key
from clawrium.core.render import (
    build_render_inputs,
    render_hermes,
    render_openclaw,
    render_zeroclaw,
)
from clawrium.core.render_diff import (
    FileDiff,
    diff_files,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CanonicalSyncError",
    "SecretRemovalRefused",
    "CanonicalSyncResult",
    "sync_agent_canonical",
]


_RENDERERS = {
    "hermes": render_hermes,
    "zeroclaw": render_zeroclaw,
    "openclaw": render_openclaw,
}

# Lines whose key matches one of these patterns are considered to carry
# a secret. When a host file contains such a line and the rendered body
# does NOT, the canonical pipeline refuses to write — that's exactly
# the silent-wipe class the parent #555 audit documented. `--force`
# overrides. The list is the union of every secret env var emitted by
# the three renderers; extending the renderers requires extending this
# list (enforced by the matrix test).
_SECRET_KEY_PATTERN = re.compile(
    r"^(?P<key>[A-Z_][A-Z0-9_]*)\s*=",
    re.MULTILINE,
)
_SECRET_KEY_SUFFIXES = (
    "_TOKEN",
    "_API_KEY",
    "_SECRET",
    "_SECRET_KEY",
    "_PASSWORD",
    "_CREDENTIALS",
    "_KEY",  # broad; AWS_ACCESS_KEY_ID, etc.
)


class CanonicalSyncError(Exception):
    """Any failure in the canonical sync pipeline."""


class SecretRemovalRefused(CanonicalSyncError):
    """Raised when the rendered body would remove a host-side secret.

    The message names every secret key that would disappear. The
    operator's recovery is either to fix the underlying attachment
    (most often: re-attach the channel/integration that owns the
    secret, or `clawctl secret set ...` for the missing record) or
    re-run with `--force` if the removal is intentional (e.g. they
    actually did `clawctl agent channel detach`).
    """


@dataclass(frozen=True)
class CanonicalSyncResult:
    success: bool
    agent: str
    host: str
    files_written: tuple[str, ...]
    files_unchanged: tuple[str, ...]
    diffs: tuple[FileDiff, ...]
    error: str | None = None


def _extract_secret_keys(body: str) -> set[str]:
    """Return the set of secret-looking env var keys present in `body`.

    Operates on a `.env`-style body; the YAML config side carries no
    bare secrets in the rendered output (provider credentials are
    always in `.env`), so a YAML-only diff cannot trip the guard. The
    `_SECRET_KEY_SUFFIXES` heuristic is intentionally broad — false
    positives manifest as the operator needing to pass `--force` on a
    legitimate non-secret removal, which is annoying but safe; false
    negatives manifest as the original #555 silent-wipe regression,
    which is unsafe. The matrix test pins the suffix list.
    """
    keys: set[str] = set()
    for m in _SECRET_KEY_PATTERN.finditer(body):
        key = m.group("key")
        if any(key.endswith(suf) for suf in _SECRET_KEY_SUFFIXES):
            keys.add(key)
    return keys


def _diff_removes_secrets(diff: FileDiff) -> set[str]:
    """Return the set of secret keys present on host but absent in render.

    A non-empty set means the canonical pipeline must refuse without
    `force=True`. Returns the empty set when the file is .yaml /
    .toml — those formats don't carry bare KEY=VALUE secrets in our
    renderers (every secret is in the `.env`), and the unified-diff
    body would otherwise produce false positives from matching key
    fragments inside YAML quoted strings.
    """
    # Only `.env` bodies carry bare key=value secret pairs in any of
    # our renderers. Skip the guard for other formats to avoid false
    # positives. The matrix test asserts this — if a future renderer
    # starts emitting bare secrets to e.g. `config.toml`, this branch
    # must extend.
    if not diff.path.endswith(".env"):
        return set()
    host_keys = _extract_secret_keys(diff.remote_body)
    rendered_keys = _extract_secret_keys(diff.rendered_body)
    return host_keys - rendered_keys


def _open_ssh(host: dict, *, timeout: int = 15) -> paramiko.SSHClient:
    """Open an SSH client to `host` using the registered private key.

    Host-key policy: `WarningPolicy` — matches `lifecycle.py:471` and
    `render_diff.py:119` so every clawctl SSH client in the codebase
    behaves the same way. The rationale (from `lifecycle.py:462-471`):
    `clawctl host create` provisions a host without a `known_hosts`
    entry; default `RejectPolicy` would refuse every legitimate first
    connection. `AutoAddPolicy` silently persists keys with no
    visibility. `WarningPolicy` connects but logs, so a key swap
    surfaces via paramiko's logger.

    `BadHostKeyException` (raised by paramiko when a *known* key
    changes) is NOT suppressed — it propagates as a connect failure,
    which is the desired behavior for MITM detection. The TOFU-style
    `StrictHostKeyPolicy` in `ssh_connection.py` is for the
    user-prompt path; the sync pipeline is non-interactive, so the
    project-wide `WarningPolicy` is the right cell here.
    """
    key_id = host.get("key_id") or host.get("hostname") or ""
    private_key = get_host_private_key(key_id)
    if not private_key:
        raise CanonicalSyncError(
            f"no SSH key registered for host {key_id!r}; "
            "re-run `clawctl host create` to provision one"
        )
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    try:
        client.connect(
            hostname=host.get("hostname", ""),
            port=int(host.get("port", 22) or 22),
            username=host.get("user", "xclm"),
            key_filename=str(private_key),
            timeout=timeout,
        )
    except paramiko.BadHostKeyException as exc:
        raise CanonicalSyncError(
            f"host key for {host.get('hostname', '')!r} has changed since "
            f"`clawctl host create` recorded it: {exc}. Refusing to "
            f"write — this could be a MITM. Verify the host and re-run "
            f"`clawctl host create` if intentional."
        ) from exc
    except (paramiko.AuthenticationException, paramiko.SSHException) as exc:
        raise CanonicalSyncError(
            f"SSH connection to {host.get('hostname', '')!r} failed: {exc}"
        ) from exc
    except OSError as exc:
        raise CanonicalSyncError(
            f"network error reaching {host.get('hostname', '')!r}: {exc}"
        ) from exc
    return client


def _atomic_write(
    client: paramiko.SSHClient,
    *,
    agent_name: str,
    remote_path: str,
    body: str,
    timeout: int = 30,
) -> None:
    """Atomically replace `remote_path` with `body`, mode 0600, owned by agent.

    Uses `sudo -n` to write a tmpfile under `/tmp` (xclm-writable) and
    then `sudo -n install` to atomically move it into place with the
    correct mode / owner. `install` is preferred over `mv` because it
    sets mode + owner in one syscall and is universally available on
    Linux hosts.
    """
    quoted_path = shlex.quote(remote_path)
    # mktemp -p /tmp: deterministic, world-writable location for the
    # xclm user before sudo takes over for the final placement.
    _, stdout, _ = client.exec_command("mktemp /tmp/clawrium-sync.XXXXXX")
    if stdout.channel.recv_exit_status() != 0:
        raise CanonicalSyncError("mktemp failed on host")
    tmp_path = stdout.read().decode("utf-8").strip()
    if not tmp_path:
        raise CanonicalSyncError("mktemp returned empty path")
    try:
        sftp = client.open_sftp()
        try:
            with sftp.file(tmp_path, "wb") as fh:
                fh.write(body.encode("utf-8"))
        finally:
            sftp.close()
        # `install -m 0600 -o <name> -g <name>` requires sudo (target
        # dirs are root- or agent-owned). `install` is atomic w.r.t.
        # the destination so a partial write is never visible.
        owner = shlex.quote(agent_name)
        cmd = (
            f"sudo -n install -m 0600 -o {owner} -g {owner} "
            f"{shlex.quote(tmp_path)} {quoted_path}"
        )
        _, install_out, install_err = client.exec_command(cmd, timeout=timeout)
        rc = install_out.channel.recv_exit_status()
        if rc != 0:
            stderr_text = install_err.read().decode("utf-8", errors="replace")
            raise CanonicalSyncError(
                f"install {remote_path!r} failed (exit {rc}): {stderr_text.strip()}"
            )
    finally:
        client.exec_command(f"rm -f {shlex.quote(tmp_path)}")


def _restart_unit(
    client: paramiko.SSHClient,
    *,
    agent_type: str,
    agent_name: str,
    timeout: int = 30,
) -> None:
    unit = f"{agent_type}-{agent_name}.service"
    cmd = f"sudo -n systemctl restart {shlex.quote(unit)}"
    _, out, err = client.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    if rc != 0:
        stderr_text = err.read().decode("utf-8", errors="replace")
        raise CanonicalSyncError(
            f"systemctl restart {unit} failed (exit {rc}): {stderr_text.strip()}"
        )


def _verify_health(
    client: paramiko.SSHClient,
    *,
    agent_type: str,
    agent_name: str,
    timeout: int = 15,
) -> None:
    unit = f"{agent_type}-{agent_name}.service"
    cmd = f"systemctl is-active {shlex.quote(unit)}"
    _, out, _ = client.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    state = out.read().decode("utf-8", errors="replace").strip()
    if rc != 0 or state != "active":
        raise CanonicalSyncError(
            f"unit {unit} is not active after restart (state={state!r})"
        )


def sync_agent_canonical(
    agent_name: str,
    *,
    force: bool = False,
    restart: bool = True,
    verify: bool = True,
    on_event: Callable[[str, str], None] | None = None,
) -> CanonicalSyncResult:
    """Sync `agent_name` via the canonical pipeline.

    Args:
        agent_name: The agent instance name (as recorded in hosts.json).
        force: Allow writes that remove a host-side secret line. Without
            this, `SecretRemovalRefused` is raised before any host write.
        restart: When True (default), restart the agent's systemd unit
            after writes. When False, files are written but the running
            process keeps its old config until the next restart — useful
            for an operator who wants to stage changes without flapping
            the agent.
        verify: When True (default), assert the unit is `active` after
            restart. Implies `restart=True` — verify without restart is
            a noop. Pass False to skip post-restart polling.
        on_event: Callback `(stage, message)` for progress streaming.

    Raises:
        AgentConfigError: from build_render_inputs (missing attachment)
        CanonicalSyncError / SecretRemovalRefused: pipeline failure
        RemoteReadError: SSH probe failed in a way the operator must see
    """

    def emit(stage: str, message: str) -> None:
        if on_event is not None:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    emit("validate", f"assembling render inputs for {agent_name}")
    inputs = build_render_inputs(agent_name)

    renderer = _RENDERERS.get(inputs.agent_type)
    if renderer is None:
        raise CanonicalSyncError(
            f"no canonical renderer for agent type {inputs.agent_type!r}"
        )

    emit("render", f"rendering canonical config for {inputs.agent_type}")
    rendered = renderer(inputs)

    resolved = get_agent_by_name(agent_name)
    if resolved is None:
        raise CanonicalSyncError(
            f"agent {agent_name!r} not found in hosts.json"
        )
    host, agent_key, _claw_record = resolved
    hostname = host.get("hostname", "")

    emit("diff", f"reading on-host files from {hostname}")
    diffs = diff_files(
        host=host, agent_name=agent_name, rendered_files=rendered.files
    )

    # Secret-removal guard. See module docstring; this is the single
    # behavior #555 added that the legacy path lacks.
    refused: dict[str, set[str]] = {}
    for d in diffs:
        if not d.unified_diff:
            continue
        missing = _diff_removes_secrets(d)
        if missing:
            refused[d.path] = missing
    if refused and not force:
        details = "; ".join(
            f"{path}: would remove {sorted(keys)}"
            for path, keys in sorted(refused.items())
        )
        raise SecretRemovalRefused(
            f"refusing to sync {agent_name!r}: rendered body removes "
            f"host-side secrets ({details}). Inspect with `clawctl "
            f"agent sync {agent_name} --dry-run --diff`. Recovery: "
            f"re-attach the channel/integration that owns the missing "
            f"secret, or restore it via `clawctl secret set ...`."
        )

    files_written: list[str] = []
    files_unchanged: list[str] = []

    client = _open_ssh(host)
    try:
        for d in diffs:
            if not d.unified_diff:
                files_unchanged.append(d.path)
                continue
            emit("write", f"writing {d.remote_path}")
            _atomic_write(
                client,
                agent_name=agent_name,
                remote_path=d.remote_path,
                body=d.rendered_body,
            )
            files_written.append(d.path)

        # Restart policy:
        #
        # - zeroclaw MUST restart on every sync regardless of
        #   `files_written`, so the gateway bearer rotation downstream
        #   (issue #437, see B1 comment below) runs every time. The
        #   AGENTS.md "Gateway Token Lifecycle (zeroclaw)" section is
        #   explicit: "There is no idempotent-skip path." A no-drift
        #   sync that skipped restart would leave `hosts.json.gateway.auth`
        #   permanently stale after any external daemon restart (host
        #   reboot, `systemctl restart`, etc.).
        # - Other agent types (hermes, openclaw) keep the file-drift-gated
        #   restart so a true no-op sync stays cheap.
        zeroclaw_force_restart = (
            restart and inputs.agent_type == "zeroclaw" and not files_written
        )
        if restart and (files_written or zeroclaw_force_restart):
            if zeroclaw_force_restart:
                emit(
                    "restart",
                    f"restarting {inputs.agent_type}-{agent_name}.service "
                    f"(no drift; zeroclaw bearer rotation requires restart)",
                )
            else:
                emit(
                    "restart",
                    f"restarting {inputs.agent_type}-{agent_name}.service",
                )
            _restart_unit(
                client,
                agent_type=inputs.agent_type,
                agent_name=agent_name,
            )
            if verify:
                emit("verify", "checking unit is active")
                _verify_health(
                    client,
                    agent_type=inputs.agent_type,
                    agent_name=agent_name,
                )
        elif restart and not files_written:
            emit("restart", "skipped (no files changed)")
    finally:
        client.close()

    # B1 (#437): zeroclaw daemon does not persist bearer state across
    # systemd restarts. After a restart, the cached bearer in
    # hosts.json.gateway.auth is stale; the daemon will enforce a
    # freshly-minted token on its next request. Re-pair unconditionally
    # whenever sync is operating on a zeroclaw with `restart=True` —
    # AGENTS.md's "Gateway Token Lifecycle (zeroclaw)" explicitly
    # forbids an idempotent-skip path here. The restart block above
    # already force-restarts zeroclaw on no-drift sync for exactly this
    # invariant. The pair playbook is the single source of truth for
    # the handshake — reuse `_zeroclaw_repair_after_start` rather than
    # reimplementing.
    if restart and inputs.agent_type == "zeroclaw":
        from clawrium.core.lifecycle import _zeroclaw_repair_after_start

        emit("repair", f"re-pairing zeroclaw gateway for {agent_name}")
        repair_ok, repair_err = _zeroclaw_repair_after_start(
            hostname,
            agent_name=agent_name,
            on_event=on_event,
            reason="sync",
        )
        if not repair_ok:
            raise CanonicalSyncError(
                f"sync wrote and restarted {agent_name!r} but the gateway "
                f"re-pair failed: {repair_err}. `clawctl agent chat` will "
                f"return 401 until you re-run `clawctl agent sync` or "
                f"`clawctl agent restart`."
            )

    # B2: advance the onboarding state machine to READY so
    # `start_agent` (which gates on state == READY) accepts the agent
    # after a sync. Mirrors lifecycle.py:1386-1438's post-configure
    # transition contract. The three exception shapes have distinct
    # remediations:
    #   - InvalidTransitionError: mid-walk (PROVIDERS/IDENTITY/...);
    #     sync cannot bypass the stage walk. Silent — start_agent
    #     surfaces the non-READY state.
    #   - AgentNotFoundError / OnboardingNotFoundError: registry
    #     incoherence; surfacing via emit() rather than raise because
    #     the host-side write already succeeded.
    #   - Anything else (IO, permission): same — surface as warning,
    #     don't fail the sync.
    from clawrium.core.onboarding import (
        AgentNotFoundError as _ANF,
        InvalidTransitionError as _ITE,
        OnboardingNotFoundError as _ONF,
        OnboardingState as _OS,
        transition_state as _transition,
    )

    try:
        _transition(hostname, agent_key, _OS.READY)
    except _ITE:
        pass
    except (_ANF, _ONF) as exc:
        emit(
            "sync",
            f"warning: registry record missing for {agent_key} after "
            f"sync: {exc!s}. Inspect hosts.json before running "
            f"clawctl agent start.",
        )
    except Exception as exc:
        emit(
            "sync",
            f"warning: could not write state=READY to hosts.json: "
            f"{exc!s}. Re-run sync to commit state.",
        )

    emit(
        "sync",
        f"synced {agent_name}: {len(files_written)} written, "
        f"{len(files_unchanged)} unchanged",
    )
    return CanonicalSyncResult(
        success=True,
        agent=agent_name,
        host=hostname,
        files_written=tuple(files_written),
        files_unchanged=tuple(files_unchanged),
        diffs=tuple(diffs),
    )

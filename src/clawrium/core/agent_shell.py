"""Run an arbitrary command on the agent's host in a login bash shell.

Self-contained: does NOT import from `agent_exec`. Keeps the shell flow
free to evolve without contaminating exec's hardened code path.

`run_agent_shell(hostname, agent_name, cmd_argv, timeout)` invokes the
shell playbook against the host that owns the agent. The playbook is
selected per-OS by `core.playbook_resolver.resolve_shell_playbook` —
Linux runs `shell.yaml` (`/usr/bin/timeout` enforces the kill window);
macOS runs `shell_macos.yaml` (Homebrew `gtimeout` when present, plain
`bash -lc` otherwise). Both shapes run as the agent's unix user,
capture stdout/stderr/rc, and emit them as three base64-tagged debug
events (`SHELL_STDOUT=`, `SHELL_STDERR=`, `SHELL_RC=`). This module
parses those events and returns `(stdout, stderr, rc)`.

Timeout handling — all clamping lives here, not at the CLI seam:

- ``None`` / ``0`` / negative → ``1800`` (no client cap; the hard
  30-min ceiling still applies).
- positive → ``min(int(timeout), 1800)``.

The runner-level timeout is ``effective + 30`` so the inner kill
binary (`timeout(1)` on Linux, `gtimeout` on macOS when present) is
the canonical kill path under normal operation; the +30s buffer gives
the playbook time to clean up. On macOS hosts without `gtimeout`, the
runner-level timeout itself becomes the kill backstop — runner status
`timeout` already maps to rc=124 below, so the user-facing contract
is unchanged.

Failure modes:
    - Unknown host → ``("", err, 255)``.
    - SSH key not found → ``("", err, 255)``.
    - Playbook missing → ``("", err, 255)``.
    - Runner exception → ``("", "ansible-runner error: ...", 255)``.
    - Runner timeout → ``("", "remote command timed out after Ns", 124)``.
    - Remote rc missing → propagate stdout + stderr, rc=255.
    - Remote command nonzero rc → propagated verbatim.

Non-UTF-8 stdout/stderr from the remote command is lossy: Ansible's
``command`` module decodes child output as UTF-8 with
``errors='replace'`` before we ever see it, so non-UTF-8 byte
sequences arrive as U+FFFD by the time the playbook b64-encodes them.
``tests/core/test_agent_shell.py::test_non_utf8_stdout_documented_lossy``
asserts this contract.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import ansible_runner

from clawrium.core import keys as core_keys
from clawrium.core import playbook_resolver
from clawrium.core.config import get_config_dir
from clawrium.core.names import RESERVED_UNIX_NAMES

logger = logging.getLogger(__name__)

__all__ = ["AgentShellError", "run_agent_shell"]

# Hard 30-min ceiling. Hardcoded per plan §1 — overrides user input
# unconditionally so a runaway remote process cannot pin the local CLI.
_HARD_TIMEOUT_CAP = 1800

# Runner-level grace buffer. Inner `timeout(1)` is the canonical kill
# path; the runner timeout is `effective + _RUNNER_GRACE_S` so the
# playbook always has time to emit the SHELL_RC=124 event before the
# runner itself gives up.
_RUNNER_GRACE_S = 30

_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# `log_dir` directory-name component must contain only filename-safe
# characters. A tampered hosts.json alias of `../tmp/evil` would
# otherwise escape the logs root.
_LOG_DIR_SAFE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class AgentShellError(Exception):
    """Raised for caller-recoverable errors before invoking ansible_runner."""


def _logs_dir() -> Path:
    d = get_config_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_artifacts(log_dir: Path) -> None:
    """Recursively remove the per-call private_data_dir.

    `ansible-runner` writes `artifacts/`, `env/`, `inventory/`,
    `project/`, `command*.json`, `daemon.log`, and `pid` directly into
    the runner workdir. The previous implementation removed only the
    first three; the rest survived and `log_dir.rmdir()` silently
    failed because the dir wasn't empty. `rmtree(..., ignore_errors=True)`
    is the only safe sweep (#761 iter-2 B3).
    """
    shutil.rmtree(log_dir, ignore_errors=True)


def _build_inventory(host: dict, ssh_key: Path, extra_vars: dict) -> dict:
    return {
        "all": {
            "hosts": {
                host["hostname"]: {
                    "ansible_user": host.get("user", "xclm"),
                    "ansible_port": host.get("port", 22),
                    "ansible_ssh_private_key_file": str(ssh_key),
                }
            },
            "vars": extra_vars,
        }
    }


def _parse_events(result) -> tuple[str, str, int | None]:
    """Walk runner events and extract SHELL_STDOUT/SHELL_STDERR/SHELL_RC.

    Distinct prefix from EXEC_* — a mis-shared parser cannot cross
    paths silently.
    """
    stdout = ""
    stderr = ""
    rc: int | None = None
    for event in result.events:
        if event.get("event") != "runner_on_ok":
            continue
        msg = event.get("event_data", {}).get("res", {}).get("msg")
        if not isinstance(msg, str):
            continue
        if msg.startswith("SHELL_STDOUT="):
            try:
                stdout = base64.b64decode(msg[len("SHELL_STDOUT=") :]).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, TypeError):
                stdout = ""
        elif msg.startswith("SHELL_STDERR="):
            try:
                stderr = base64.b64decode(msg[len("SHELL_STDERR=") :]).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, TypeError):
                stderr = ""
        elif msg.startswith("SHELL_RC="):
            try:
                rc = int(msg[len("SHELL_RC=") :])
            except ValueError:
                rc = None
    return stdout, stderr, rc


def _extract_failure_message(result, default: str) -> str:
    for event in result.events:
        if event.get("event") == "runner_on_unreachable":
            res = event.get("event_data", {}).get("res", {})
            msg = res.get("msg") or "host unreachable"
            return f"Host unreachable: {msg}"
    for event in result.events:
        if event.get("event") == "runner_on_failed":
            res = event.get("event_data", {}).get("res", {})
            if "msg" in res:
                return res["msg"]
            if "stderr" in res:
                return res["stderr"]
    return default


def _effective_timeout(timeout: int | None) -> int:
    """Resolve the user-supplied timeout to the on-wire `shell_timeout`.

    Clamping lives here (core), not at the CLI seam — non-CLI callers
    cannot bypass the ceiling. Matrix asserted by test K16:

        (None, 0, -1, 1, 60, 1800, 1801, 9999) → (1800, 1800, 1800,
         1, 60, 1800, 1800, 1800)
    """
    if timeout is None:
        return _HARD_TIMEOUT_CAP
    try:
        t = int(timeout)
    except (TypeError, ValueError):
        return _HARD_TIMEOUT_CAP
    if t <= 0:
        return _HARD_TIMEOUT_CAP
    return min(t, _HARD_TIMEOUT_CAP)


def run_agent_shell(
    hostname: str,
    agent_name: str,
    cmd_argv: list[str],
    timeout: int = 120,
) -> tuple[str, str, int]:
    """Run `cmd_argv` in a login bash shell on `hostname` as `agent_name`.

    Returns ``(stdout, stderr, rc)``. Setup failures return rc=255
    with the error message on stderr. A remote ``timeout(1)`` kill
    returns rc=124 with the friendly message
    ``"remote command timed out after Ns"``.
    """
    if not isinstance(cmd_argv, list) or not cmd_argv:
        raise AgentShellError("cmd_argv must be a non-empty list")
    if not _AGENT_NAME_RE.match(agent_name):
        raise AgentShellError(f"invalid agent_name: {agent_name!r}")
    # Defense-in-depth against a tampered hosts.json: even if a record's
    # `agent_name` regex-matches, it must never name a privileged or
    # system unix account. `become_user: {{ agent_name }}` in the
    # playbook would otherwise grant the shell whatever rights that
    # account holds (root, daemon, etc.) over the SSH+sudo channel.
    if agent_name in RESERVED_UNIX_NAMES:
        raise AgentShellError(
            f"refusing to run shell as reserved system user: {agent_name!r}"
        )

    from clawrium.core.hosts import get_host

    host = get_host(hostname)
    if not host:
        return "", f"host {hostname!r} not found", 255

    # A tampered hosts.json could carry a non-string os_family (int,
    # dict, list). Guard the .lower() so the caller gets the controlled
    # ("", err, 255) shape rather than an uncaught AttributeError.
    raw_os = host.get("os_family")
    os_family = raw_os.lower() if isinstance(raw_os, str) and raw_os else "linux"
    try:
        playbook = playbook_resolver.resolve_shell_playbook(os_family)
    except (FileNotFoundError, ValueError) as e:
        return "", str(e), 255

    key_id = host.get("key_id") or host["hostname"]
    ssh_key = core_keys.get_host_private_key(key_id)
    if not ssh_key:
        return (
            "",
            f"SSH key for host {key_id!r} not found. "
            f"Run 'clawctl host create {host['hostname']} --user xclm --alias <name>' "
            f"to register it (see docs/host-preparation.md for host setup).",
            255,
        )

    effective = _effective_timeout(timeout)
    # ssh-like passthrough: cmd_argv is joined with a single space so the
    # user's locally-quoted command string reaches `bash -lc` verbatim.
    # `shlex.join` would re-quote single-element argv like `['ls -la ~/']`
    # into `"'ls -la ~/'"` and bash would treat it as one literal word.
    # Multi-token argv (`['echo', 'a b']`) is passed through without
    # extra quoting — documented in --help.
    user_cmd = " ".join(cmd_argv)
    # Explicitly source rc files from a login (non-interactive) shell so
    # PATH shims set up there (pyenv, nvm, asdf, virtualenv activations)
    # are loaded before the command runs. Plain `bash -lc` skips
    # `~/.bashrc`; `bash -lic` sources it but also enables job-control
    # noise on stderr and appends history (#761 iter-3 W1). The per-OS
    # prelude is owned by `playbook_resolver.shell_rc_prepend` so this
    # module stays free of OS literals (dispatcher-only OS-fork
    # invariant — `playbook_resolver.py` docstring).
    rc_prepend = playbook_resolver.shell_rc_prepend(os_family)
    cmd_str = f"{rc_prepend} {user_cmd}"
    # The command runs through ansible's templating layer, so a user
    # command of `echo {{ lookup('env','SECRET') }}` would otherwise
    # expand the lookup on the controller and ship the secret to the
    # remote host (iter-1 W1). Defense: base64-encode in Python and let
    # the playbook decode with `| b64decode` exactly once — the
    # decoded value is treated as plain text and never re-templated.
    cmd_b64 = base64.b64encode(cmd_str.encode("utf-8")).decode("ascii")
    extra_vars = {
        "agent_name": agent_name,
        "cmd_b64": cmd_b64,
        "shell_timeout": effective,
    }

    try:
        inventory = _build_inventory(host, ssh_key, extra_vars)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        raw_display = host.get("alias") or host.get("key_id") or host["hostname"]
        host_display = (
            raw_display if _LOG_DIR_SAFE_RE.match(raw_display or "") else "host"
        )
        suffix = uuid.uuid4().hex[:8]
        log_dir = _logs_dir() / f"shell-{host_display}-{timestamp}-{suffix}"
        try:
            log_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return "", f"Failed to set up runner workdir: {log_dir} already exists", 255
        try:
            os.chmod(log_dir, 0o700)
        except OSError:
            try:
                log_dir.rmdir()
            except OSError:
                pass
            raise
    except OSError as e:
        return "", f"Failed to set up runner workdir: {e}", 255

    try:
        result = ansible_runner.run(
            private_data_dir=str(log_dir),
            inventory=inventory,
            playbook=str(playbook),
            quiet=True,
            timeout=effective + _RUNNER_GRACE_S,
        )
    except Exception as e:
        _cleanup_artifacts(log_dir)
        return "", f"ansible-runner error: {e}", 255

    try:
        if result.status == "timeout":
            # Message reports the user-configured kill window. On Linux
            # and macOS-with-gtimeout this matches the actual wall-clock
            # spend (inner timeout fires at `effective`s). On macOS
            # without gtimeout the runner-level timeout fires up to
            # +_RUNNER_GRACE_S later, so the wall-clock spend can
            # exceed `effective`s by ~30s — documented at module level.
            return "", f"remote command timed out after {effective}s", 124
        if result.status != "successful":
            err = _extract_failure_message(result, f"playbook {result.status}")
            return "", err, 255

        stdout, stderr, rc = _parse_events(result)
        if rc is None:
            return (
                stdout,
                stderr or "remote command did not report an exit code",
                255,
            )
        # Note: rc=124 is propagated verbatim. It's the natural exit
        # code from inner `/usr/bin/timeout`, but it's also a legitimate
        # exit code for unrelated CLI tools — overwriting stderr with a
        # synthetic "timed out" message would mask real diagnostics (#761
        # iter-2 B2). The ansible-runner-level `status == "timeout"`
        # branch above is the only synthetic-timeout-message path.
        return stdout, stderr, rc
    finally:
        _cleanup_artifacts(log_dir)

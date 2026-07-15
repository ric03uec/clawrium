"""Host-vs-rendered diff for parent #555 F8.

`build_render_inputs` + `render_<atype>` produce the canonical
on-host content. To answer "what would `clawctl agent sync` change?",
we need to read the current file from the host and unified-diff it
against the rendered bytes. This module is the only place that
crosses the SSH boundary for that diff.

Kept narrowly scoped: read one file per call via `sudo -n cat`, no
state, no parallelism. The CLI layer iterates over the files map.
"""

from __future__ import annotations

import difflib
import shlex
import tomllib
from dataclasses import dataclass, field

import paramiko

from clawrium.core.keys import get_host_private_key


__all__ = [
    "FileDiff",
    "RemoteReadError",
    "read_remote_file",
    "read_remote_toml",
    "remote_path_for",
    "diff_files",
]


class RemoteReadError(Exception):
    """Raised when a remote probe fails for an operator-actionable reason.

    Distinct from "file is genuinely absent" — that is reported by
    `read_remote_file` as `(False, "")` so the caller can render a
    "would create" diff. `RemoteReadError` covers the cases where the
    diff cannot be trusted (sudo unavailable, SSH transport dead,
    permission denied on the file itself) and the caller must
    surface a warning rather than silently emit a misleading patch.
    Fixes ATX iter-1 B4 (sudo-fail indistinguishable from absent file).
    """


@dataclass(frozen=True)
class FileDiff:
    """One file's host-vs-rendered comparison.

    `remote_present` distinguishes "first sync" (no file yet) from
    "would change" (file exists but differs). Operators care: the
    former is expected on a freshly-installed agent; the latter on a
    healthy agent likely means someone hand-edited the host.

    ATX iter-1 W5: `remote_body` and `rendered_body` carry plaintext
    secrets. `repr=False` on both fields prevents accidental
    plaintext leakage through `repr()` in pytest tracebacks, debug
    logs, or `print(diff)`. Diff structure (path / present / unified)
    is still visible.
    """

    path: str  # relative path under agent home, e.g. ".hermes/.env"
    remote_path: str  # absolute path on the host
    remote_present: bool
    remote_body: str = field(repr=False)
    rendered_body: str = field(repr=False)
    # The unified diff is *also* secret-carrying (it contains the
    # secret lines that differ) — but operators need to see it in
    # text mode. Keep it repr=False; the CLI layer prints it directly.
    unified_diff: str = field(repr=False)


def remote_path_for(os_family: str, agent_name: str, relative: str) -> str:
    """Resolve a relative-to-home file key into an absolute host path.

    `relative` comes from `RenderedFiles.files` (e.g. `.hermes/.env`).
    The home root mirrors the convention used by
    `core/lifecycle.py:_get_hermes_env_path` — `/Users/<name>` on
    darwin, `/home/<name>` everywhere else.
    """
    home_root = "/Users" if (os_family or "linux") == "darwin" else "/home"
    return f"{home_root}/{agent_name}/{relative.lstrip('/')}"


def read_remote_file(
    *,
    hostname: str,
    port: int,
    user: str,
    key_filename: str,
    remote_path: str,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Cat one file from the host. Returns (present, body).

    Uses `sudo -n cat` because agent home directories are typically
    `0700` and xclm (the management user) cannot read them directly
    but does have passwordless sudo per `clawctl host create`. `-n`
    avoids any password prompt.

    File-existence is probed with a dedicated `sudo -n test -e` call
    whose exit status is read via `recv_exit_status()`:

    - exit 0 → file exists; second call `sudo -n cat` retrieves body
    - exit 1 → file does not exist; return `(False, "")`
    - any other exit → sudo unavailable or transport issue; raise
      `RemoteReadError` so the operator sees a real warning rather
      than a misleading "would create" diff (ATX iter-1 B4).

    A non-existent file is reported as `(False, "")` so the caller
    can render a "would create" diff against an empty body without
    special-casing.
    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # WarningPolicy mirrors core/lifecycle.py — see the rationale block
    # there. Probes-only path, no command-injection surface beyond the
    # caller-supplied `remote_path` which we shlex.quote below.
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    try:
        client.connect(
            hostname=hostname,
            port=int(port),
            username=user,
            key_filename=key_filename,
            timeout=timeout,
        )
        quoted = shlex.quote(remote_path)
        # Probe existence first via a separate command whose exit
        # status disambiguates "missing" (exit 1 from `test -e`) from
        # "sudo unavailable" (exit 1 from sudo itself — `-n` returns
        # exit 1 on auth failure, but the stderr message reveals
        # which it is). We use exec_command twice rather than one
        # compound script so the structured exit code is preserved.
        _, probe_stdout, probe_stderr = client.exec_command(
            f"sudo -n test -e {quoted}", timeout=timeout
        )
        probe_exit = probe_stdout.channel.recv_exit_status()
        if probe_exit == 0:
            _, stdout, _ = client.exec_command(
                f"sudo -n cat {quoted}", timeout=timeout
            )
            # ATX iter-2 W13: read body BEFORE polling exit status.
            # paramiko's `recv_exit_status()` can block until EOF on
            # large outputs but only after the channel's stdout
            # buffer is drained — reading first ensures the channel
            # closes cleanly. Calling exit-status first then read()
            # has caused deadlocks under load in other paramiko
            # users (see paramiko #1617).
            raw = stdout.read().decode("utf-8", errors="replace")
            cat_exit = stdout.channel.recv_exit_status()
            if cat_exit != 0:
                raise RemoteReadError(
                    f"sudo cat {remote_path!r} failed with exit {cat_exit}"
                )
            return True, raw
        if probe_exit == 1:
            # Distinguish "file truly absent" (sudo ran fine) from
            # "sudo refused to run" by inspecting stderr. A clean
            # `test -e` miss emits no stderr at all; ANY stderr text
            # on the probe channel means sudo itself spoke up — most
            # likely a sudoers misconfiguration. ATX iter-2 W14:
            # don't anchor on the word "password" — sudo's NOPASSWD
            # failure modes also produce "Sorry, user X is not
            # allowed to execute ...", "sudo: no tty present", and
            # locale-translated variants. Any non-empty stderr on
            # exit-1 is operator-actionable.
            stderr_text = probe_stderr.read().decode("utf-8", errors="replace")
            if stderr_text.strip():
                raise RemoteReadError(
                    f"sudo -n unavailable on {hostname}: "
                    f"{stderr_text.strip()} "
                    "(re-run `clawctl host create` to fix sudoers)"
                )
            return False, ""
        # Any other exit code is a transport / auth surprise. Surface
        # it loudly rather than silently presenting a "would create".
        raise RemoteReadError(
            f"sudo -n test -e {remote_path!r} exited {probe_exit} on {hostname}"
        )
    finally:
        client.close()


def read_remote_toml(
    *,
    hostname: str,
    port: int,
    user: str,
    key_filename: str,
    remote_path: str,
    timeout: int = 10,
) -> dict | None:
    """Read `remote_path` from the host and parse as TOML.

    Thin wrapper over `read_remote_file` + stdlib `tomllib.loads`.
    Returns `None` when the file is absent (so callers can distinguish
    "first sync" from "present but empty"). Propagates `RemoteReadError`
    verbatim on ssh / sudo failures — the caller must not silently
    substitute a `None` here, or a transient ssh failure would masquerade
    as a missing file and the caller would render an incorrect default.

    Malformed TOML (`tomllib.TOMLDecodeError`) is also wrapped as
    `RemoteReadError` — a garbled host-side config is operator-actionable
    and must not be swallowed. #910: added to support preserving
    zeroclaw `[onboard_state].completed_sections` across sync/re-render.
    """
    present, body = read_remote_file(
        hostname=hostname,
        port=port,
        user=user,
        key_filename=key_filename,
        remote_path=remote_path,
        timeout=timeout,
    )
    if not present:
        return None
    try:
        return tomllib.loads(body)
    except tomllib.TOMLDecodeError as exc:
        raise RemoteReadError(
            f"TOML parse failure on {remote_path!r} at {hostname}: {exc}"
        ) from exc


def diff_files(
    *,
    host: dict,
    agent_name: str,
    rendered_files: dict[str, str],
    reader=None,
) -> list[FileDiff]:
    """Diff every rendered file against the host.

    `reader` defaults to the module-level `read_remote_file` *resolved
    at call time* (not at def time) so tests that
    `monkeypatch.setattr(render_diff, "read_remote_file", fake)` reach
    the production path. Tests that prefer to pass a fake directly can
    still do so via this kwarg.
    """
    if reader is None:
        # Re-import from module globals so monkeypatching takes effect.
        from clawrium.core import render_diff as _self

        reader = _self.read_remote_file
    key_id = host.get("key_id") or host.get("hostname") or ""
    private_key = get_host_private_key(key_id)
    if not private_key:
        raise RuntimeError(
            f"no SSH key registered for host {key_id!r}; "
            "re-run `clawctl host create` to provision one"
        )

    os_family = host.get("os_family", "linux")
    hostname = host.get("hostname", "")
    port = int(host.get("port", 22) or 22)
    user = host.get("user", "xclm")

    diffs: list[FileDiff] = []
    for rel_path, rendered_body in rendered_files.items():
        remote_path = remote_path_for(os_family, agent_name, rel_path)
        try:
            present, remote_body = reader(
                hostname=hostname,
                port=port,
                user=user,
                key_filename=str(private_key),
                remote_path=remote_path,
            )
        except RemoteReadError:
            # Propagate verbatim — the CLI layer renders this as a
            # `diff error:` line so the operator is not handed a
            # misleading "would create" diff (ATX iter-1 B4).
            raise
        unified = (
            ""
            if remote_body == rendered_body
            else "".join(
                difflib.unified_diff(
                    remote_body.splitlines(keepends=True),
                    rendered_body.splitlines(keepends=True),
                    fromfile=f"host:{remote_path}",
                    tofile=f"rendered:{rel_path}",
                    n=3,
                )
            )
        )
        diffs.append(
            FileDiff(
                path=rel_path,
                remote_path=remote_path,
                remote_present=present,
                remote_body=remote_body,
                rendered_body=rendered_body,
                unified_diff=unified,
            )
        )
    return diffs

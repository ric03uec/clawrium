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
from dataclasses import dataclass

import paramiko

from clawrium.core.keys import get_host_private_key


__all__ = [
    "FileDiff",
    "read_remote_file",
    "remote_path_for",
    "diff_files",
]


@dataclass(frozen=True)
class FileDiff:
    """One file's host-vs-rendered comparison.

    `remote_present` distinguishes "first sync" (no file yet) from
    "would change" (file exists but differs). Operators care: the
    former is expected on a freshly-installed agent; the latter on a
    healthy agent likely means someone hand-edited the host.
    """

    path: str  # relative path under agent home, e.g. ".hermes/.env"
    remote_path: str  # absolute path on the host
    remote_present: bool
    remote_body: str
    rendered_body: str
    unified_diff: str  # empty string when bodies are byte-identical


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
    avoids any password prompt — if sudo is not available we surface
    a non-zero exit code as "not present" rather than blocking.

    A non-existent file is reported as `(False, "")` not an exception
    so the caller can render a "would create" diff against an empty
    body without special-casing.
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
        # `test -r`: returns 0 only if file exists and is readable
        # by *root* (we run via sudo). The cat is guarded so a missing
        # file produces `(False, "")` rather than stderr noise.
        cmd = (
            f"if sudo -n test -e {quoted}; then "
            f"sudo -n cat {quoted}; else echo __CLAWRIUM_MISSING__; fi"
        )
        _, stdout, _ = client.exec_command(cmd, timeout=timeout)
        raw = stdout.read().decode("utf-8", errors="replace")
    finally:
        client.close()

    if raw.strip() == "__CLAWRIUM_MISSING__":
        return False, ""
    return True, raw


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
        present, remote_body = reader(
            hostname=hostname,
            port=port,
            user=user,
            key_filename=str(private_key),
            remote_path=remote_path,
        )
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

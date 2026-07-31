"""Shared live-version resolver for openclaw.

Extracted from ``core/lifecycle_canonical`` so that multiple callers
(upgrade preflight, ``clawctl agent upgrade``, and the ``brave`` plugin
preflight) share one SSH-probe implementation. Issue #754.

The dispatcher ``get_host_openclaw_version`` is the public entry-point.
Per-OS implementations are private; callers never branch on
``os_family`` themselves (dispatcher-only-OS-fork invariant from
AGENTS.md).
"""

from __future__ import annotations

import re
import shlex
from typing import TYPE_CHECKING

import paramiko

from clawrium.core.playbook_resolver import home_root_for

if TYPE_CHECKING:
    pass

__all__ = ["get_host_openclaw_version", "parse_semver_tuple"]


# ─── Constants ────────────────────────────────────────────────────────────────

_LINUX_OPENCLAW_PATH_SAFELIST: tuple[str, ...] = (
    "/usr/local/bin/",
    "/usr/bin/",
    "/home/",
)
_MACOS_OPENCLAW_PATH_SAFELIST: tuple[str, ...] = (
    "/opt/homebrew/bin/",
    "/usr/local/bin/",
    "/usr/bin/",
    "/Users/",
)


# ─── Parsing ──────────────────────────────────────────────────────────────────

def parse_semver_tuple(raw: str) -> tuple[int, int, int] | None:
    """Parse a leading ``X.Y.Z`` out of *raw*.

    Returns ``None`` when no triple is present (treated as unknown,
    NOT zero — see preflight). Anchors at line start to avoid picking
    up a runtime/Node version; falls back to first-anywhere as a
    safety net.
    """
    if not raw:
        return None
    first_line = raw.splitlines()[0]
    m = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", first_line)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


# ─── Script builders ─────────────────────────────────────────────────────────

def _build_openclaw_version_inner_script(
    agent_name: str, *, home_root: str, path_safelist: tuple[str, ...]
) -> str:
    """Return the bash body that resolves the openclaw binary (no
    sudo wrap, no ``bash -lc`` shell quoting).

    Per-agent binary at ``<home_root>/<agent>/.openclaw/bin/openclaw``
    wins; PATH fallback is accepted only when ``command -v openclaw``
    resolves under one of *path_safelist*.
    """
    per_agent = f"{home_root}/{agent_name}/.openclaw/bin/openclaw"
    quoted_per_agent = shlex.quote(per_agent)
    patterns = "|".join(f"{shlex.quote(prefix)}*" for prefix in path_safelist)
    return (
        f"if [ -x {quoted_per_agent} ] && [ -s {quoted_per_agent} ]; then "
        f"  {quoted_per_agent} --version; "
        f"elif resolved=$(command -v openclaw 2>/dev/null); then "
        f"  ok=0; "
        f'  case "$resolved" in {patterns}) ok=1 ;; esac; '
        f'  if [ "$ok" = 1 ]; then "$resolved" --version; '
        f'  else echo "openclaw on PATH is at unsafe path: $resolved" 1>&2; exit 2; fi; '
        f"else exit 1; fi"
    )


def _build_openclaw_version_probe(
    agent_name: str, *, home_root: str, path_safelist: tuple[str, ...]
) -> str:
    """Build the ``sudo -n -u <agent> bash -lc '...'`` command."""
    inner = _build_openclaw_version_inner_script(
        agent_name, home_root=home_root, path_safelist=path_safelist
    )
    quoted_agent = shlex.quote(agent_name)
    return f"sudo -n -u {quoted_agent} bash -lc {shlex.quote(inner)}"


# ─── SSH execution ────────────────────────────────────────────────────────────

def _run_openclaw_version_probe(
    client: paramiko.SSHClient, cmd: str, *, timeout: int
) -> tuple[tuple[int, int, int] | None, str]:
    """Run *cmd* via SSH and return ``(version_tuple, stderr_tail)``."""
    _, out, err = client.exec_command(cmd, timeout=timeout)
    body = out.read().decode("utf-8", errors="replace").strip()
    err_bytes = err.read()
    stderr_tail = err_bytes.decode("utf-8", errors="replace")[-512:].strip()
    if out.channel.recv_exit_status() != 0:
        return None, stderr_tail
    return parse_semver_tuple(body), stderr_tail


# ─── Per-OS resolvers ────────────────────────────────────────────────────────

def _get_host_openclaw_version_linux(
    client: paramiko.SSHClient, agent_name: str, *, timeout: int = 10
) -> tuple[tuple[int, int, int] | None, str]:
    """Linux variant: per-agent binary under ``/home/<agent>/``, PATH
    fallback safelist matches Linux install.yaml lines ~50-57.

    Returns ``(version, stderr_tail)``. ``version`` is ``None`` when
    the binary is missing, the output is unparseable, or the resolved
    PATH binary is rejected by the safelist.
    """
    cmd = _build_openclaw_version_probe(
        agent_name,
        home_root=home_root_for("linux"),
        path_safelist=_LINUX_OPENCLAW_PATH_SAFELIST,
    )
    return _run_openclaw_version_probe(client, cmd, timeout=timeout)


def _get_host_openclaw_version_macos(
    client: paramiko.SSHClient, agent_name: str, *, timeout: int = 10
) -> tuple[tuple[int, int, int] | None, str]:
    """macOS (arm64) variant: per-agent binary under ``/Users/<agent>/``.

    Forked completely from the Linux variant — when a future macOS
    x86_64 platform is added, dispatch should fork further rather
    than retrofitting an arch branch into either function.
    """
    cmd = _build_openclaw_version_probe(
        agent_name,
        home_root=home_root_for("darwin"),
        path_safelist=_MACOS_OPENCLAW_PATH_SAFELIST,
    )
    return _run_openclaw_version_probe(client, cmd, timeout=timeout)


# ─── Public dispatcher ────────────────────────────────────────────────────────

def get_host_openclaw_version(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    os_family: str,
    timeout: int = 10,
) -> tuple[tuple[int, int, int] | None, str]:
    """Dispatcher: routes to the Linux or macOS variant based on
    *os_family* (the host record's ``os_family`` field).

    The Linux and macOS resolvers are intentionally separate functions —
    the dispatcher is the only place that knows about both, matching the
    dispatcher-only-OS-fork convention in AGENTS.md.
    """
    if (os_family or "linux").lower() == "darwin":
        return _get_host_openclaw_version_macos(client, agent_name, timeout=timeout)
    return _get_host_openclaw_version_linux(client, agent_name, timeout=timeout)

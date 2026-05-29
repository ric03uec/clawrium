"""launchd plist rendering and installation helpers (issue #469 step 6).

Pure-Python helpers that:
  1. Render a hermes launchd plist from `gateway.plist.j2` for a given
     agent name (and optional dashboard port).
  2. Write the rendered plist to /Library/LaunchDaemons/<label>.plist
     on a remote host via paramiko.
  3. Remove a plist by label.

These functions stay decoupled from the systemd-only lifecycle module
so that core/lifecycle_macos.py (step 7) can compose them without
dragging in linux-specific imports.

The "system" launchd domain is used throughout — units must survive
user logout. See gateway.plist.j2 for the rationale.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

if TYPE_CHECKING:
    import paramiko

logger = logging.getLogger(__name__)

# Reverse-DNS label prefix shared by hermes plists. Keep in sync with
# gateway.plist.j2's <key>Label</key> string. Dashboards (issue #469
# step 10) append `.dashboard` to this prefix.
LABEL_PREFIX = "ai.clawrium.hermes"

# launchd daemons live in /Library/LaunchDaemons (system domain). The
# `/Library/LaunchAgents` path is for per-user GUI session daemons,
# which is precisely what we DON'T want — those die on logout.
LAUNCHD_DAEMONS_DIR = "/Library/LaunchDaemons"

_TEMPLATE_ROOT = (
    Path(__file__).parent.parent / "platform" / "registry" / "hermes" / "templates"
)


def _env() -> jinja2.Environment:
    """Build a Jinja2 env scoped to the hermes templates directory.

    Cached at module load via the lru_cache decorator below.
    """
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_ROOT)),
        autoescape=False,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


def label_for(agent_name: str, *, kind: str = "gateway") -> str:
    """Return the launchd Label for the gateway/dashboard plist.

    `kind="gateway"` → `ai.clawrium.hermes.<agent_name>`.
    `kind="dashboard"` → `ai.clawrium.hermes.<agent_name>.dashboard`.
    """
    if kind == "gateway":
        return f"{LABEL_PREFIX}.{agent_name}"
    if kind == "dashboard":
        return f"{LABEL_PREFIX}.{agent_name}.dashboard"
    raise ValueError(f"unsupported plist kind: {kind!r}")


def plist_path_for(agent_name: str, *, kind: str = "gateway") -> str:
    """Return the absolute path where the plist must live on disk.

    launchd's `bootstrap`/`bootout` ARGV expects this exact path.
    """
    return f"{LAUNCHD_DAEMONS_DIR}/{label_for(agent_name, kind=kind)}.plist"


def render_plist(
    agent_name: str,
    template_name: str = "gateway.plist.j2",
    *,
    dashboard_port: int | None = None,
) -> str:
    """Render `template_name` for `agent_name` into a plist XML string.

    Raises jinja2.UndefinedError on missing template vars (StrictUndefined).

    The dashboard template requires a `dashboard_port` — pass it explicitly.
    """
    template = _env().get_template(template_name)
    ctx: dict = {"agent_name": agent_name}
    if dashboard_port is not None:
        ctx["dashboard_port"] = dashboard_port
    return template.render(**ctx)


def write_plist(
    client: "paramiko.SSHClient",
    agent_name: str,
    contents: str,
    *,
    kind: str = "gateway",
) -> str:
    """Write `contents` to the gateway/dashboard plist path on the remote host.

    Uses paramiko SFTP under the hood. Requires the SSH session to be able
    to write /Library/LaunchDaemons — i.e. either root or a passwordless
    sudo helper. Returns the remote path written.

    Permissions: launchd ignores plists that aren't 0644 root:wheel. We
    set both explicitly via sudo after the SFTP write.
    """
    remote_path = plist_path_for(agent_name, kind=kind)
    # SFTP first, into /tmp, then sudo-move into place. SFTP itself can't
    # elevate privileges; the move is the privileged step.
    tmp_path = f"/tmp/{label_for(agent_name, kind=kind)}.plist"
    sftp = client.open_sftp()
    try:
        with sftp.file(tmp_path, "w") as remote:
            remote.write(contents)
    finally:
        sftp.close()

    _exec_checked(
        client,
        f"sudo install -m 0644 -o root -g wheel {tmp_path} {remote_path} "
        f"&& sudo rm -f {tmp_path}",
        "write_plist",
    )
    return remote_path


def remove_plist(
    client: "paramiko.SSHClient", agent_name: str, *, kind: str = "gateway"
) -> None:
    """Remove the gateway/dashboard plist file from /Library/LaunchDaemons.

    Idempotent: missing file is not an error.
    """
    remote_path = plist_path_for(agent_name, kind=kind)
    _exec_checked(client, f"sudo rm -f {remote_path}", "remove_plist")


def _exec_checked(client: "paramiko.SSHClient", cmd: str, what: str) -> None:
    _, stdout, stderr = client.exec_command(cmd)
    stdout.read()
    err = stderr.read().decode().strip()
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        raise RuntimeError(
            f"{what}: remote command failed (exit {exit_status}): {cmd}\n{err}"
        )


__all__ = [
    "LABEL_PREFIX",
    "LAUNCHD_DAEMONS_DIR",
    "label_for",
    "plist_path_for",
    "render_plist",
    "write_plist",
    "remove_plist",
]

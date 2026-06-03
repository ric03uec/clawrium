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
import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

if TYPE_CHECKING:
    import paramiko

logger = logging.getLogger(__name__)

# Reverse-DNS label prefix used by hermes plists. Openclaw uses
# `ai.clawrium.openclaw` — resolved via `_label_prefix_for(agent_type)`.
# Keep `LABEL_PREFIX` exported for backwards compatibility (tests, callers).
LABEL_PREFIX = "ai.clawrium.hermes"

# launchd daemons live in /Library/LaunchDaemons (system domain). The
# `/Library/LaunchAgents` path is for per-user GUI session daemons,
# which is precisely what we DON'T want — those die on logout.
LAUNCHD_DAEMONS_DIR = "/Library/LaunchDaemons"

_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _validate_agent_name(agent_name: str) -> None:
    """Defense-in-depth: reject names that would let shell metacharacters
    reach `sudo install` / `sudo rm` via the exported helpers below.
    Callers in lifecycle.py already validate at the boundary; this guard
    closes the gap if a future caller bypasses that path."""
    if not isinstance(agent_name, str) or not _AGENT_NAME_RE.match(agent_name):
        raise ValueError(f"invalid agent_name for launchd helpers: {agent_name!r}")


_LABEL_PREFIX_BY_TYPE = {
    "hermes": "ai.clawrium.hermes",
    "openclaw": "ai.clawrium.openclaw",
}

_PLATFORM_REGISTRY = Path(__file__).parent.parent / "platform" / "registry"

# Default template root preserved as `hermes` so existing callers
# (and `LABEL_PREFIX` consumers) keep working unchanged.
_TEMPLATE_ROOT = _PLATFORM_REGISTRY / "hermes" / "templates"


def _label_prefix_for(agent_type: str) -> str:
    try:
        return _LABEL_PREFIX_BY_TYPE[agent_type]
    except KeyError as exc:
        raise ValueError(f"unsupported agent_type for launchd: {agent_type!r}") from exc


def _env(agent_type: str = "hermes") -> jinja2.Environment:
    """Build a Jinja2 env scoped to `<agent_type>`'s templates directory."""
    root = _PLATFORM_REGISTRY / agent_type / "templates"
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(root)),
        autoescape=False,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


def label_for(
    agent_name: str, *, kind: str = "gateway", agent_type: str = "hermes"
) -> str:
    """Return the launchd Label for the plist.

    Hermes (gateway): `ai.clawrium.hermes.<agent_name>`.
    Hermes (dashboard): `ai.clawrium.hermes.<agent_name>.dashboard`.
    Openclaw (gateway): `ai.clawrium.openclaw.<agent_name>` (only kind).
    """
    prefix = _label_prefix_for(agent_type)
    if agent_type == "openclaw":
        if kind != "gateway":
            raise ValueError(f"openclaw does not support plist kind: {kind!r}")
        return f"{prefix}.{agent_name}"
    if kind == "gateway":
        return f"{prefix}.{agent_name}"
    if kind == "dashboard":
        return f"{prefix}.{agent_name}.dashboard"
    raise ValueError(f"unsupported plist kind: {kind!r}")


def plist_path_for(
    agent_name: str, *, kind: str = "gateway", agent_type: str = "hermes"
) -> str:
    """Return the absolute path where the plist must live on disk."""
    return (
        f"{LAUNCHD_DAEMONS_DIR}/"
        f"{label_for(agent_name, kind=kind, agent_type=agent_type)}.plist"
    )


def render_plist(
    agent_name: str,
    template_name: str = "gateway.plist.j2",
    *,
    dashboard_port: int | None = None,
    agent_type: str = "hermes",
    extra_context: dict | None = None,
) -> str:
    """Render `template_name` for `agent_name` into a plist XML string.

    Raises jinja2.UndefinedError on missing template vars (StrictUndefined).
    The dashboard template requires a `dashboard_port`. Openclaw's
    template requires `openclaw_binary` (via `extra_context`).
    """
    template = _env(agent_type).get_template(template_name)
    ctx: dict = {"agent_name": agent_name}
    if dashboard_port is not None:
        ctx["dashboard_port"] = dashboard_port
    if extra_context:
        ctx.update(extra_context)
    return template.render(**ctx)


def write_plist(
    client: "paramiko.SSHClient",
    agent_name: str,
    contents: str,
    *,
    kind: str = "gateway",
    agent_type: str = "hermes",
) -> str:
    """Write `contents` to the gateway/dashboard plist path on the remote host.

    Uses paramiko SFTP under the hood. Requires the SSH session to be able
    to write /Library/LaunchDaemons — i.e. either root or a passwordless
    sudo helper. Returns the remote path written.

    Permissions: launchd ignores plists that aren't 0644 root:wheel. We
    set both explicitly via sudo after the SFTP write.
    """
    _validate_agent_name(agent_name)
    remote_path = plist_path_for(agent_name, kind=kind, agent_type=agent_type)
    # SFTP first, into /tmp, then sudo-move into place. SFTP itself can't
    # elevate privileges; the move is the privileged step.
    tmp_path = f"/tmp/{label_for(agent_name, kind=kind, agent_type=agent_type)}.plist"
    sftp = client.open_sftp()
    try:
        with sftp.file(tmp_path, "w") as remote:
            remote.write(contents)
    finally:
        sftp.close()

    _exec_checked(
        client,
        f"sudo install -m 0644 -o root -g wheel {shlex.quote(tmp_path)} "
        f"{shlex.quote(remote_path)} && sudo rm -f {shlex.quote(tmp_path)}",
        "write_plist",
    )
    return remote_path


def remove_plist(
    client: "paramiko.SSHClient",
    agent_name: str,
    *,
    kind: str = "gateway",
    agent_type: str = "hermes",
) -> None:
    """Remove the gateway/dashboard plist file from /Library/LaunchDaemons.

    Idempotent: missing file is not an error.
    """
    _validate_agent_name(agent_name)
    remote_path = plist_path_for(agent_name, kind=kind, agent_type=agent_type)
    _exec_checked(client, f"sudo rm -f {shlex.quote(remote_path)}", "remove_plist")


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

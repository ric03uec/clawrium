"""Playbook + lifecycle backend resolver.

Single source of truth for the OS-family fork. Every other module reads
`host.os_family` ("linux" or "darwin") and asks this module which file or
backend to use. No other code is allowed to branch on OS family.

Naming convention: macOS analogs of existing files use the `_macos` suffix
(e.g. `install_macos.yaml`, `lifecycle_macos.py`). Linux files keep their
original name; they are byte-for-byte unchanged by the Mac-support PR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

SUPPORTED_OS: frozenset[str] = frozenset({"linux", "darwin"})

OSFamily = Literal["linux", "darwin"]

_PLATFORM_ROOT = Path(__file__).parent.parent / "platform"


def _suffix_for(os_family: str) -> str:
    if os_family not in SUPPORTED_OS:
        raise ValueError(
            f"unsupported os_family: {os_family!r} (expected one of {sorted(SUPPORTED_OS)})"
        )
    return "" if os_family == "linux" else "_macos"


_HOME_ROOT_BY_OS: dict[str, str] = {
    "linux": "/home",
    "darwin": "/Users",
}


def normalize_os_family(host: dict | None) -> str:
    """Return a normalized `os_family` string for a hosts.json record.

    Reads `host.get("os_family")`, strips whitespace + lowercases, and
    coerces the common `mac` / `macos` / `osx` aliases to `darwin`.
    Legacy or missing host records fall back to `linux` (mirrors the
    `load_hosts` migration default at `core/hosts.py:330`).

    Callers pass the normalized value into per-OS APIs
    (`render_hermes(..., os_family=of)`, `render_openclaw(..., os_family=of)`)
    — each raises on any final value outside `{'linux', 'darwin'}` so
    an exotic input surfaces loudly at the per-API boundary rather
    than getting silently coerced to `linux` here. Extracted (ATX
    #835 iter-1 W2) so `lifecycle.configure_agent`'s previously-
    duplicated coercion blocks stay in lockstep.
    """
    raw = (host.get("os_family") if host else None) or "linux"
    of = str(raw).strip().lower()
    if of in ("mac", "macos", "osx"):
        of = "darwin"
    return of


def home_root_for(os_family: str) -> str:
    """Return the per-OS user home-directory root.

    Linux uses `/home`, macOS uses `/Users`. Callers that need to
    materialize an agent's home path do so as
    `f"{home_root_for(os_family)}/{agent_name}"`. This is the single
    seam for the home-root branch so the rest of the codebase keeps
    the no-OS-literal invariant (issue #770; U13 / S4 iter-3).
    """
    if os_family not in SUPPORTED_OS:
        raise ValueError(
            f"unsupported os_family: {os_family!r} (expected one of {sorted(SUPPORTED_OS)})"
        )
    return _HOME_ROOT_BY_OS[os_family]


_SUPPORTED_AGENT_TYPES: frozenset[str] = frozenset(
    {"ethos", "hermes", "zeroclaw", "openclaw"}
)


def unit_path_for(os_family: str, agent_type: str, agent_name: str) -> str:
    """Return the absolute path of the agent's service-manager artifact.

    - Linux: `/etc/systemd/system/<agent_type>-<agent_name>.service`
    - macOS: `/Library/LaunchDaemons/<label_for(...)>.plist`

    Used by the sync validate-phase host probe (#811) so the
    "is this agent actually installed" check has a single source of
    truth for both OS families. Imports the launchd helper lazily to
    avoid pulling jinja into the linux-only call path.

    Validates `agent_type` against the platform-supported set
    (ATX #811 iter-2 W2) on BOTH OS branches — darwin would
    already raise `ValueError` from `_label_prefix_for`, the
    Linux branch was previously unvalidated and would
    cheerfully build a path for any string. Symmetric strictness
    keeps the contract uniform.
    """
    if os_family not in SUPPORTED_OS:
        raise ValueError(
            f"unsupported os_family: {os_family!r} (expected one of {sorted(SUPPORTED_OS)})"
        )
    if agent_type not in _SUPPORTED_AGENT_TYPES:
        raise ValueError(
            f"unsupported agent_type: {agent_type!r} (expected one of "
            f"{sorted(_SUPPORTED_AGENT_TYPES)})"
        )
    if os_family == "darwin":
        from clawrium.core.launchd import plist_path_for

        return plist_path_for(agent_name, kind="gateway", agent_type=agent_type)
    return f"/etc/systemd/system/{agent_type}-{agent_name}.service"


def resolve_base_playbook(os_family: str) -> Path:
    """Return the path to the system-prerequisites playbook for this OS family.

    Raises FileNotFoundError with an actionable message if the playbook does
    not exist yet. This is the path users hit when a Mac install is attempted
    before the corresponding `_macos.yaml` has been added.
    """
    suffix = _suffix_for(os_family)
    path = _PLATFORM_ROOT / "playbooks" / f"base{suffix}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"base playbook for os_family={os_family!r} not found at {path}. "
            f"This OS family is not yet supported by this clawrium build."
        )
    return path


def resolve_agent_playbook(agent_type: str, op: str, os_family: str) -> Path:
    """Return the path to an agent-specific playbook (install/configure/...)
    for this OS family.

    `op` is the playbook stem (e.g. "install", "configure", "remove").
    """
    suffix = _suffix_for(os_family)
    path = (
        _PLATFORM_ROOT
        / "registry"
        / agent_type
        / "playbooks"
        / f"{op}{suffix}.yaml"
    )
    if not path.exists():
        raise FileNotFoundError(
            f"agent {agent_type!r} does not support os_family={os_family!r}: "
            f"expected playbook at {path}"
        )
    return path


def resolve_shell_playbook(os_family: str) -> Path:
    """Return the path to the `clawctl agent shell` playbook for this OS family."""
    suffix = _suffix_for(os_family)
    path = _PLATFORM_ROOT / "shell" / f"shell{suffix}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"shell playbook for os_family={os_family!r} not found at {path}. "
            f"This OS family is not yet supported by this clawrium build."
        )
    return path


# Per-OS bash rc-file prepend strings for the shell playbook. Keeping
# this here instead of inside agent_shell.py preserves the
# dispatcher-only OS-fork invariant: `core.playbook_resolver` owns the
# OS literal, everywhere else just calls the resolver. Both strings
# end with a trailing semicolon so the caller can concatenate with a
# single space before the user's command.
#
# macOS bash login-shell precedence is `.bash_profile` → `.bash_login`
# → `.profile` (first found wins). We mirror that with elif chains so
# operators with a `.profile`-only POSIX-compat dotfile setup still
# get their PATH shims. `.bashrc` is always sourced last because
# operators commonly chain it from `.bash_profile` — we want it to
# load even when the chain isn't set up.
_SHELL_RC_PREPEND_BY_OS: dict[str, str] = {
    "linux": '[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc";',
    "darwin": (
        'if [ -f "$HOME/.bash_profile" ]; then . "$HOME/.bash_profile";'
        ' elif [ -f "$HOME/.bash_login" ]; then . "$HOME/.bash_login";'
        ' elif [ -f "$HOME/.profile" ]; then . "$HOME/.profile"; fi;'
        ' [ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc";'
    ),
}




def shell_rc_prepend(os_family: str) -> str:
    """Return the bash rc-file source prelude for `clawctl agent shell`.

    The string is concatenated by `core.agent_shell` ahead of the
    user's command, then base64-encoded together with it for the
    `bash -lc` decode-hop in the shell playbook. Keeping the OS branch
    here keeps `agent_shell` OS-agnostic and preserves the
    dispatcher-only OS-fork invariant declared at the top of this
    module.
    """
    if os_family not in SUPPORTED_OS:
        raise ValueError(
            f"unsupported os_family: {os_family!r} (expected one of {sorted(SUPPORTED_OS)})"
        )
    return _SHELL_RC_PREPEND_BY_OS[os_family]


def resolve_lifecycle_backend(os_family: str):
    """Return the lifecycle module appropriate for this OS family.

    Linux returns `core.lifecycle` (systemd-based). Darwin returns
    `core.lifecycle_macos` (launchctl-based). All lifecycle entry
    points in core.lifecycle delegate to the macOS module when the
    host record's os_family is "darwin", so callers usually don't need
    this helper directly — but it's exposed for tests and for any
    future caller that wants to dispatch explicitly.
    """
    if os_family not in SUPPORTED_OS:
        raise ValueError(
            f"unsupported os_family: {os_family!r} (expected one of {sorted(SUPPORTED_OS)})"
        )
    if os_family == "darwin":
        from clawrium.core import lifecycle_macos

        return lifecycle_macos
    from clawrium.core import lifecycle

    return lifecycle

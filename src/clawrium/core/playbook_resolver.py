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

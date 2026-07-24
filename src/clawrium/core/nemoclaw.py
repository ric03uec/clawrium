"""NemoClaw runtime substrate — Phase 1 skeleton (issue #11 / #943).

This module holds the pinned NemoClaw upstream version and the per-arch
tarball URL / SHA256 table that downstream phases will consume:

- Phase 2 wires the CLI wrapper (onboard / start / stop / status / logs /
  destroy) and adds `install_nemoclaw.yaml` runbooks that read
  `NEMOCLAW_VERSION` + `TARBALL_URLS` + `TARBALL_SHA256` via the version-
  lockstep test.
- Phase 3 delegates the openclaw lifecycle verbs to this wrapper.

Phase 1 intentionally ships **no behavior** — only the pinned constants
and the `clawctl doctor nemoclaw` probe (see
`clawrium.cli.clawctl.doctor.nemoclaw`) that verifies these values
against `https://api.github.com/repos/NVIDIA/NemoClaw` before any host
work lands. Bumping the pin here is the single write-side of the phase-2
3-way lockstep contract (constant ↔ manifest ↔ runbook var).
"""

from __future__ import annotations

UPSTREAM_REPO = "NVIDIA/NemoClaw"
UPSTREAM_DOCS = "https://docs.nvidia.com/nemoclaw/latest/"

NEMOCLAW_VERSION = "v0.0.94"

_TARBALL_URL_TEMPLATE = (
    "https://github.com/NVIDIA/NemoClaw/releases/download/"
    "{version}/nemoclaw-{version}-{arch}.tar.zst"
)

SUPPORTED_ARCHES = ("x86_64", "aarch64")


def tarball_url(arch: str, version: str = NEMOCLAW_VERSION) -> str:
    """Return the upstream tarball URL for the given arch + version.

    Raises ValueError on unsupported arches so callers fail loudly at
    the boundary rather than requesting a nonexistent asset.
    """
    if arch not in SUPPORTED_ARCHES:
        raise ValueError(
            f"nemoclaw: unsupported arch {arch!r}; "
            f"supported: {', '.join(SUPPORTED_ARCHES)}"
        )
    return _TARBALL_URL_TEMPLATE.format(version=version, arch=arch)


# Per-arch SHA256 for the pinned NEMOCLAW_VERSION tarball. Populated by
# the phase-2 lockstep test / release automation once the tarball is
# frozen upstream. Phase 1 ships the map with `None` sentinels so the
# doctor probe can report `sha=pending-upstream-freeze` clearly instead
# of hard-crashing during the validity gate.
TARBALL_SHA256: dict[str, str | None] = {
    "x86_64": None,
    "aarch64": None,
}

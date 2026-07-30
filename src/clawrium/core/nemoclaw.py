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

from dataclasses import dataclass

UPSTREAM_REPO = "NVIDIA/NemoClaw"
UPSTREAM_DOCS = "https://docs.nvidia.com/nemoclaw/latest/"

NEMOCLAW_VERSION = "v0.0.97"

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


# ---------------------------------------------------------------------------
# Phase 2: thin CLI wrapper (issue #944).
#
# Every verb below wraps a single `nemoclaw <verb> <sandbox_name>`
# invocation. The actual host-side execution is driven by
# `core.lifecycle_canonical` via ansible-runner playbooks (see
# `openclaw/playbooks/nemoclaw_onboard.yaml`); this wrapper's job is
# to (a) normalize the argv shape so callers do not embed CLI-syntax
# in their own code paths, and (b) sit as the single seam Phase 3
# swaps to full openclaw-lifecycle delegation. Phase 2 uses only
# `onboard`; the other verbs ship here so the surface is complete
# and Phase 3's `sync`/`start`/`stop`/`remove` do not have to grow
# the module.
# ---------------------------------------------------------------------------


NEMOCLAW_BINARY = "/usr/local/bin/nemoclaw"

_VALID_VERBS = frozenset(
    {"onboard", "start", "stop", "status", "logs", "destroy"}
)


@dataclass(frozen=True)
class NemoclawCommand:
    """A structured NemoClaw CLI invocation.

    `argv` is the exact argument list an executor (subprocess.run,
    ansible-runner, or an SSH exec_command) will pass to the host
    `nemoclaw` binary. Callers must not mutate `argv` — the frozen
    dataclass exists so a spy in tests can compare invocations by
    value.
    """

    verb: str
    sandbox_name: str
    argv: tuple[str, ...]


def _validate_sandbox_name(sandbox_name: str) -> None:
    """Fail closed on any sandbox name that could smuggle a shell
    fragment. Matches the agent-name shape enforced by
    `lifecycle_canonical._validate_agent_name` so a sandbox_name
    can round-trip through hosts.json without further sanitization.
    """
    import re

    if not isinstance(sandbox_name, str) or not sandbox_name:
        raise ValueError(f"nemoclaw: invalid sandbox_name {sandbox_name!r}")
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", sandbox_name):
        raise ValueError(
            f"nemoclaw: sandbox_name {sandbox_name!r} must match "
            "^[a-z][a-z0-9_-]{0,31}$"
        )


def _build(verb: str, sandbox_name: str) -> NemoclawCommand:
    if verb not in _VALID_VERBS:
        raise ValueError(
            f"nemoclaw: unknown verb {verb!r}; "
            f"supported: {', '.join(sorted(_VALID_VERBS))}"
        )
    _validate_sandbox_name(sandbox_name)
    return NemoclawCommand(
        verb=verb,
        sandbox_name=sandbox_name,
        argv=(NEMOCLAW_BINARY, verb, sandbox_name),
    )


def onboard(sandbox_name: str) -> NemoclawCommand:
    """Create + register a new sandbox. First-run of Phase 2 sync."""
    return _build("onboard", sandbox_name)


def start(sandbox_name: str) -> NemoclawCommand:
    """Start an already-onboarded sandbox."""
    return _build("start", sandbox_name)


def stop(sandbox_name: str) -> NemoclawCommand:
    """Stop a running sandbox without destroying it."""
    return _build("stop", sandbox_name)


def status(sandbox_name: str) -> NemoclawCommand:
    """Report sandbox health. Consumed by Phase 3 `clawctl host validate`."""
    return _build("status", sandbox_name)


def logs(sandbox_name: str) -> NemoclawCommand:
    """Tail sandbox logs."""
    return _build("logs", sandbox_name)


def destroy(sandbox_name: str) -> NemoclawCommand:
    """Tear down and forget a sandbox. Phase 3 wires this into remove."""
    return _build("destroy", sandbox_name)


def default_sandbox_name(agent_name: str) -> str:
    """Deterministic sandbox name derived from the openclaw agent name.

    Kept trivial in Phase 2 (identity) so operators reading hosts.json
    can trace the sandbox back to the agent at a glance. A future
    phase can hash / prefix / namespace this without callers noticing —
    every write site must route through this helper.
    """
    _validate_sandbox_name(agent_name)
    return agent_name

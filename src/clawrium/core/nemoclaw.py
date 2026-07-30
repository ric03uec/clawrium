"""NemoClaw runtime substrate — pinned upstream version + install.sh URL.

NVIDIA/NemoClaw does NOT publish binary release artifacts on GitHub
Releases. The canonical install path documented upstream is:

    curl -fsSL https://raw.githubusercontent.com/NVIDIA/NemoClaw/<ref>/install.sh | bash

which clones the ref at runtime and executes `scripts/install.sh` from
the checkout (see the bootstrap at
https://github.com/NVIDIA/NemoClaw/blob/main/install.sh).

We therefore pin the install.sh bootstrap's SHA256 (not a nonexistent
tarball SHA). A version bump MUST re-hash install.sh at the new tag and
update `INSTALL_SH_SHA256` here AND the matching
`nemoclaw_install_sh_sha256` var in
`platform/registry/openclaw/playbooks/install_nemoclaw.yaml` in lockstep.
The doctor probe (`clawctl doctor nemoclaw`) can verify the pin against
live upstream via `install_sh_url()` before any host work lands.
"""

from __future__ import annotations

from dataclasses import dataclass

UPSTREAM_REPO = "NVIDIA/NemoClaw"
UPSTREAM_DOCS = "https://docs.nvidia.com/nemoclaw/latest/"

NEMOCLAW_VERSION = "v0.0.97"

_INSTALL_SH_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/NVIDIA/NemoClaw/"
    "{version}/install.sh"
)

# SHA256 of the install.sh bootstrap at NEMOCLAW_VERSION. Fresh-hashed
# on 2026-07-29 from
# https://raw.githubusercontent.com/NVIDIA/NemoClaw/v0.0.97/install.sh.
# Bumping NEMOCLAW_VERSION MUST re-hash and update this constant.
INSTALL_SH_SHA256 = "7de1c1e630672e8afa3333e3e17c8b162ab93cdaefae9450be9ac270bc74626f"

SUPPORTED_ARCHES = ("x86_64", "aarch64")


def install_sh_url(version: str = NEMOCLAW_VERSION) -> str:
    """Return the raw.githubusercontent.com URL for install.sh at `version`."""
    return _INSTALL_SH_URL_TEMPLATE.format(version=version)


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

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


# ---------------------------------------------------------------------------
# Phase 4: gateway provider registration (issue #946).
#
# Provider credentials (api_key + base_url) are handed to NemoClaw's
# gateway registry so the sandboxed openclaw process never sees the raw
# bearer. The gateway substitutes the key transparently on every egress
# call. This wrapper is a **best-guess** shape for the upstream CLI (see
# `.itx/946/00_BLOCKED.md` — parent-issue #11 §7.5 is still unresolved);
# the argv layout mirrors the directive the orchestrator delivered:
#   nemoclaw <sandbox> gateway provider add <name>
#       --api-key <k> --base-url <u>
# If upstream diverges, this is the single seam to update — every caller
# routes through `gateway_register_provider` and the Ansible playbook
# consumes `NemoclawCommand.argv` verbatim.
# ---------------------------------------------------------------------------


_PROVIDER_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"


def _validate_provider_name(provider_name: str) -> None:
    import re

    if not isinstance(provider_name, str) or not provider_name:
        raise ValueError(
            f"nemoclaw: invalid provider name {provider_name!r}"
        )
    if not re.match(_PROVIDER_NAME_PATTERN, provider_name):
        raise ValueError(
            f"nemoclaw: provider name {provider_name!r} must match "
            f"{_PROVIDER_NAME_PATTERN}"
        )


def _validate_base_url(base_url: str) -> None:
    if not isinstance(base_url, str) or not base_url:
        raise ValueError(f"nemoclaw: invalid base_url {base_url!r}")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ValueError(
            f"nemoclaw: base_url {base_url!r} must start with http:// or https://"
        )
    # Reject shell/argv smuggling; upstream CLI receives base_url via argv.
    for ch in ("\n", "\r", "\0", " "):
        if ch in base_url:
            raise ValueError(
                f"nemoclaw: base_url {base_url!r} contains illegal whitespace/control char"
            )


def _validate_api_key(api_key: str) -> None:
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("nemoclaw: api_key must be a non-empty string")
    for ch in ("\n", "\r", "\0"):
        if ch in api_key:
            raise ValueError(
                "nemoclaw: api_key contains illegal newline/null byte"
            )


def gateway_register_provider(
    sandbox_name: str,
    provider_name: str,
    api_key: str,
    base_url: str,
) -> NemoclawCommand:
    """Register a provider (api_key + base_url) on the sandbox's NemoClaw
    gateway. Returns a `NemoclawCommand` whose `argv` a caller passes to
    `subprocess.run` or ansible-runner. The api_key travels in argv here —
    upstream may prefer stdin/env; the seam is single-sourced in this
    helper so a future upstream-verified change is one edit.
    """
    _validate_sandbox_name(sandbox_name)
    _validate_provider_name(provider_name)
    _validate_api_key(api_key)
    _validate_base_url(base_url)
    return NemoclawCommand(
        verb="gateway-provider-add",
        sandbox_name=sandbox_name,
        argv=(
            NEMOCLAW_BINARY,
            sandbox_name,
            "gateway",
            "provider",
            "add",
            provider_name,
            "--api-key",
            api_key,
            "--base-url",
            base_url,
        ),
    )


def default_sandbox_name(agent_name: str) -> str:
    """Deterministic sandbox name derived from the openclaw agent name.

    Kept trivial in Phase 2 (identity) so operators reading hosts.json
    can trace the sandbox back to the agent at a glance. A future
    phase can hash / prefix / namespace this without callers noticing —
    every write site must route through this helper.
    """
    _validate_sandbox_name(agent_name)
    return agent_name

"""OpenClaw sandbox integration — NemoClaw runtime substrate.

#1071 phase 4: this module is the new home for the NemoClaw
integration code that previously lived at `core/nemoclaw.py`.
NemoClaw is openclaw's upstream runtime substrate — openclaw agents
run inside a NemoClaw sandbox, and the control-plane needs a Python
seam for:

- Translating Clawrium provider types into NemoClaw's install.sh enum.
- Validating sandbox names before they hit a shell / argv edge.
- Building the exact CLI invocations that `lifecycle_canonical`'s
  openclaw onboard / start / stop / destroy paths consume.
- Routing provider credentials to NemoClaw's gateway registry so the
  sandboxed openclaw process never sees the raw bearer.

Scope compared to the pre-#1071 `core/nemoclaw.py`:

- **Removed with the operator doctor probe** (`clawctl doctor
  nemoclaw` was deleted in #1071 phase 1):
    - `UPSTREAM_REPO`, `UPSTREAM_DOCS` — doc constants.
    - `INSTALL_SH_SHA256`, `_INSTALL_SH_URL_TEMPLATE`,
      `install_sh_url()` — the pin-against-upstream helper the doctor
      probe compared the on-disk playbook pin against. The pin itself
      lives in `install_nemoclaw.yaml` (Linux) +
      `install_nemoclaw_macos.yaml` (darwin) + this module's
      `NEMOCLAW_VERSION` constant; lockstep is enforced by
      `tests/platform/test_nemoclaw_pin_lockstep.py`.
- **Kept** (load-bearing openclaw infrastructure):
    - `NEMOCLAW_VERSION` — stamped into `hosts.json.agents.<name>
      .config.nemoclaw_version` by `core/install.py` on every fresh
      install or resume.
    - `SUPPORTED_ARCHES` — the arch set the install playbook claims
      to support; lockstep-asserted against `install_nemoclaw.yaml`.
    - Provider mapping + `UnmappedProviderError` +
      `clawrium_provider_type_to_nemoclaw`.
    - CLI wrapper surface (`NemoclawCommand`, `onboard` / `start` /
      `stop` / `status` / `logs` / `destroy`,
      `_validate_sandbox_name`, `default_sandbox_name`).
    - `gateway_register_provider` + the fail-closed guard (issue
      #946, still pending upstream confirmation).
"""

from __future__ import annotations

from dataclasses import dataclass


# Pin stamped into `hosts.json.agents.<name>.config.nemoclaw_version`
# by `core/install.py`. Bumping it requires re-hashing install.sh at
# the new tag and updating `nemoclaw_install_sh_sha256` in
# `install_nemoclaw.yaml` + `install_nemoclaw_macos.yaml` in lockstep
# (asserted by `tests/platform/test_nemoclaw_pin_lockstep.py`).
NEMOCLAW_VERSION = "v0.0.97"

SUPPORTED_ARCHES = ("x86_64", "aarch64")


# ---------------------------------------------------------------------------
# Provider mapping — Clawrium provider `type` → NemoClaw's NEMOCLAW_PROVIDER
# vocabulary. NemoClaw's install.sh accepts a fixed enum (see the `--help`
# section of https://raw.githubusercontent.com/NVIDIA/NemoClaw/main/install.sh);
# unmapped types must fail loudly at install time rather than silently
# substitute a default (which is `build` — NVIDIA Endpoints — and would
# demand a key the operator didn't set).
# ---------------------------------------------------------------------------


CLAWRIUM_TO_NEMOCLAW_PROVIDER: dict[str, str] = {
    "openrouter": "openrouter",
    "openai": "openai",
    "anthropic": "anthropic",
    "anthropic-compatible": "anthropicCompatible",
    "litellm-anthropic": "anthropicCompatible",
    "gemini": "gemini",
    "ollama": "ollama",
    "nim-local": "nim-local",
    "vllm": "vllm",
    "vllm-inx": "vllm",
    "custom": "custom",
}


class UnmappedProviderError(ValueError):
    """Clawrium provider type has no NemoClaw counterpart."""


def clawrium_provider_type_to_nemoclaw(clawrium_type: str) -> str:
    """Translate a Clawrium provider `type` into NemoClaw's install.sh vocabulary.

    Raises `UnmappedProviderError` on any type not in
    `CLAWRIUM_TO_NEMOCLAW_PROVIDER` so a `NEMOCLAW_PROVIDER=<unknown>`
    can never reach install.sh's `--provider` arg where it would either
    fall through to the `build` default or crash with a less actionable
    error mid-onboarding.
    """
    try:
        return CLAWRIUM_TO_NEMOCLAW_PROVIDER[clawrium_type]
    except KeyError as exc:
        raise UnmappedProviderError(
            f"Clawrium provider type {clawrium_type!r} has no NemoClaw "
            f"mapping. Supported types: "
            f"{sorted(CLAWRIUM_TO_NEMOCLAW_PROVIDER)}."
        ) from exc


# ---------------------------------------------------------------------------
# Thin CLI wrapper (issue #944).
#
# Every verb below wraps a single `nemoclaw <verb> <sandbox_name>`
# invocation. The actual host-side execution is driven by
# `core.lifecycle_canonical` via ansible-runner playbooks (see
# `openclaw/playbooks/nemoclaw_onboard.yaml`); this wrapper's job is
# to (a) normalize the argv shape so callers do not embed CLI-syntax
# in their own code paths, and (b) sit as the single seam Phase 3
# swaps to full openclaw-lifecycle delegation.
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

    def __repr__(self) -> str:
        # ATX iter-4 B1: default @dataclass __repr__ prints argv verbatim,
        # leaking any api_key that gateway_register_provider embedded after
        # `--api-key`. Redact any argv element immediately following a
        # `--api-key` / `--secret` / `--token` sentinel so debug logs and
        # test failures (see S2) never surface raw credentials.
        redacted: list[str] = []
        skip_next = False
        for arg in self.argv:
            if skip_next:
                redacted.append("***REDACTED***")
                skip_next = False
                continue
            if any(
                arg.startswith(f"{flag}=")
                for flag in ("--api-key", "--secret", "--token", "--password")
            ):
                flag, _value = arg.split("=", 1)
                redacted.append(f"{flag}=***REDACTED***")
                continue
            redacted.append(arg)
            if arg in ("--api-key", "--secret", "--token", "--password"):
                skip_next = True
        return (
            f"NemoclawCommand(verb={self.verb!r}, "
            f"sandbox_name={self.sandbox_name!r}, "
            f"argv={tuple(redacted)!r})"
        )


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
# consumes `NemoclawCommand.argv` verbatim. Until parent-plan §7.5 is
# answered, the helper is intentionally fail-closed unless the caller
# passes an explicit upstream-confirmation flag; this prevents the guessed
# argv from becoming production behavior by accident.
# ---------------------------------------------------------------------------


_PROVIDER_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"
_GATEWAY_PROVIDER_CLI_UNCONFIRMED_ERROR = (
    "nemoclaw gateway provider registration CLI shape is unconfirmed "
    "(parent-plan §7.5). Devashish must choose the production contract: "
    "A) confirm `nemoclaw <sandbox> gateway provider add <name> --api-key "
    "<key> --base-url <url>`, B) require stdin/env/file secret handoff, or "
    "C) defer Clawrium-managed registration and expose an explicit operator "
    "NemoClaw step. Recommended default: B (stdin/env/file) to avoid "
    "putting provider bearers in argv/process listings."
)


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
    for ch in ("\n", "\r", "\0", " ", "\t"):
        if ch in base_url:
            raise ValueError(
                f"nemoclaw: base_url {base_url!r} contains illegal whitespace/control char"
            )


def _validate_api_key(api_key: str) -> None:
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("nemoclaw: api_key must be a non-empty string")
    # ATX iter-4 W1 + W2: reject whitespace + control bytes. The docstring
    # advertises SSH exec_command as a supported executor path (which passes
    # a joined string to /bin/sh -c) so any character that shell would
    # tokenize on or interpret as a control byte must fail-closed here,
    # regardless of the current argv-only subprocess call path.
    for ch in ("\n", "\r", "\0", " ", "\t"):
        if ch in api_key:
            raise ValueError(
                "nemoclaw: api_key contains illegal whitespace/control char"
            )


def gateway_register_provider(
    sandbox_name: str,
    provider_name: str,
    api_key: str,
    base_url: str,
    *,
    upstream_cli_shape_confirmed: bool = False,
) -> NemoclawCommand:
    """Register a provider (api_key + base_url) on the sandbox's NemoClaw
    gateway.

    The argv shape below is the ITX-STUCK best guess. It is deliberately
    fail-closed unless the caller passes `upstream_cli_shape_confirmed=True`,
    so a future lifecycle/playbook integration cannot accidentally ship the
    guessed CLI as production behavior before parent-plan §7.5 is answered.
    Once Devashish confirms the real upstream contract, remove the guard or
    replace this function with the confirmed stdin/env/file/argv handoff.
    """
    _validate_sandbox_name(sandbox_name)
    _validate_provider_name(provider_name)
    _validate_api_key(api_key)
    _validate_base_url(base_url)
    if not upstream_cli_shape_confirmed:
        raise NotImplementedError(_GATEWAY_PROVIDER_CLI_UNCONFIRMED_ERROR)
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

    Kept trivial (identity) so operators reading hosts.json can trace
    the sandbox back to the agent at a glance. A future phase can
    hash / prefix / namespace this without callers noticing — every
    write site must route through this helper.
    """
    _validate_sandbox_name(agent_name)
    return agent_name

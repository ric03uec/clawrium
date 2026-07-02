"""Canonical sync pipeline for parent #555 F3.

The legacy `core/lifecycle.py:sync_agent` re-renders on-host config via
ansible extravars and templates that conditionally emit each block
based on whether `hosts.json.agents.<name>.config.<field>` happens to
be populated. That's the bug parent #555 documents: every clawctl op
silently wipes whichever blocks lack a populated hosts.json field.

This module replaces that path with the canonical pipeline:

    inputs   = build_render_inputs(name)        # raises on missing
    rendered = render_<atype>(inputs)           # pure function
    remote   = read_remote_file(...) per file   # what's on host now
    diff     = compute per-file unified diff
    refuse   = if diff removes a secret line AND not force: raise
    write    = atomic per-file sudo-mv into place, mode 0600
    restart  = systemctl restart <atype>-<name>.service
    verify   = light health check (unit active)

Since #560, this is the only sync path — the `--canonical` opt-in flag
was dropped and the legacy ansible extravar fork was removed from
`clawctl agent sync`. The test matrix in
`tests/integration/test_render_matrix.py` continues to prove parity
against the legacy renderer outputs.

Post-write tail (#560):

    repair  = for zeroclaw, re-pair gateway bearer (#437) and atomically
              persist to hosts.json.gateway.auth
    advance = transition onboarding state to READY (swallows
              InvalidTransitionError for mid-walk agents)

The re-pair step reuses `lifecycle._zeroclaw_repair_after_start` so the
ansible pair playbook (the single source of truth for the
`POST /pair/code → POST /pair` handshake) is not duplicated. The READY
write mirrors `sync_agent`'s post-configure transition at
`lifecycle.py:1386-1438` and tolerates the same exception shapes.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import paramiko

from clawrium.core.hosts import get_agent_by_name
from clawrium.core.keys import get_host_private_key
from clawrium.core.playbook_resolver import home_root_for, unit_path_for
from clawrium.core.render import (
    build_render_inputs,
    render_hermes,
    render_openclaw,
    render_zeroclaw,
)
from clawrium.core.render_diff import (
    FileDiff,
    diff_files,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AgentInstallMissingError",
    "CanonicalSyncError",
    "SecretRemovalRefused",
    "CanonicalSyncResult",
    "HostInstallProbe",
    "probe_host_install",
    "sync_agent_canonical",
]


_RENDERERS = {
    "hermes": render_hermes,
    "zeroclaw": render_zeroclaw,
    "openclaw": render_openclaw,
}

# Lines whose key matches one of these patterns are considered to carry
# a secret. When a host file contains such a line and the rendered body
# does NOT, the canonical pipeline refuses to write — that's exactly
# the silent-wipe class the parent #555 audit documented. `--force`
# overrides. The list is the union of every secret env var emitted by
# the three renderers; extending the renderers requires extending this
# list (enforced by the matrix test).
_SECRET_KEY_PATTERN = re.compile(
    r"^(?P<key>[A-Z_][A-Z0-9_]*)\s*=",
    re.MULTILINE,
)
_SECRET_KEY_SUFFIXES = (
    "_TOKEN",
    "_API_KEY",
    "_SECRET",
    "_SECRET_KEY",
    "_PASSWORD",
    "_CREDENTIALS",
    "_KEY",  # broad; matches AWS_SECRET_ACCESS_KEY, GATEWAY_AUTH_KEY, etc.
    # B5 (ATX #555 polish): explicit names for secret env vars whose
    # suffix would NOT otherwise match (e.g. `AWS_ACCESS_KEY_ID` ends
    # in `_ID`, not `_KEY`). Listed by exact suffix so they're picked
    # up by the `endswith` check on the captured key.
    "_KEY_ID",
)


# Openclaw brave plugin pin is loaded from `manifest.yaml` so the
# Python preflight and Ansible playbook never drift on the version or
# minHostVersion (W2 ATX iter 1). The loader hard-fails on a missing
# or malformed entry — silently falling back to an empty version would
# let `npm install @openclaw/brave-plugin@` run with an unbounded
# version and surface as an opaque error under `no_log: true`
# (W3 ATX iter 1).


def _load_openclaw_brave_pin() -> dict:
    """Read `plugins.brave` from the openclaw manifest. Returns a dict
    with `npm_package`, `version` (str), and `min_host_version` (tuple).
    Raises `CanonicalSyncError` on any structural problem so the caller
    never proceeds with an undefined pin."""
    import yaml as _yaml

    manifest_path = (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / "openclaw"
        / "manifest.yaml"
    )
    manifest = _yaml.safe_load(manifest_path.read_text())
    brave = (manifest.get("plugins") or {}).get("brave") or {}
    pkg = brave.get("npm_package")
    ver = brave.get("version")
    minv = brave.get("min_host_version")
    if not pkg or not ver or not minv:
        raise CanonicalSyncError(
            "openclaw manifest is missing plugins.brave.{npm_package, "
            "version, min_host_version} — clawrium build is corrupt; "
            "reinstall via `uv tool install clawrium`."
        )
    minv_tuple = _parse_semver_tuple(minv)
    if minv_tuple is None:
        raise CanonicalSyncError(
            f"openclaw manifest plugins.brave.min_host_version={minv!r} "
            "is not a valid X.Y.Z version."
        )
    return {
        "npm_package": pkg,
        "version": ver,
        "min_host_version": minv_tuple,
    }


def _parse_semver_tuple(raw: str) -> tuple[int, int, int] | None:
    """Parse a leading `X.Y.Z` out of `raw`. Returns None when no triple
    is present (treated as unknown, NOT zero — see preflight).

    Anchors at line start to avoid picking up a runtime/Node version
    that some future `openclaw --version` build might print first
    (W8 ATX iter 1). Falls back to first-anywhere as a safety net so
    operator-friendly output like `openclaw 2026.5.28` still parses.
    """
    if not raw:
        return None
    first_line = raw.splitlines()[0]
    m = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", first_line)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _build_openclaw_version_inner_script(
    agent_name: str, *, home_root: str, path_safelist: tuple[str, ...]
) -> str:
    """Return the bash body that resolves the openclaw binary (no
    sudo wrap, no `bash -lc` shell quoting). Split out so tests can
    execute the script directly via `subprocess.run(['bash', '-c',
    ...])` against fixture binaries — mocked SSH cannot catch shell
    semantics regressions like the one ATX iter 2 found.

    Per-agent binary at `<home_root>/<agent>/.openclaw/bin/openclaw`
    wins; PATH fallback is accepted only when `command -v openclaw`
    resolves under one of `path_safelist` (matches install.yaml's
    discovery gate).
    """
    per_agent = f"{home_root}/{agent_name}/.openclaw/bin/openclaw"
    quoted_per_agent = shlex.quote(per_agent)
    # IMPORTANT: a single `case` with `|` alternation is the only
    # shape that actually enforces every prefix. A chain of separate
    # `case ... esac || case ... esac` short-circuits on the first
    # one because `case` always exits 0 regardless of whether a
    # pattern matched (ATX iter 2 B4).
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
    """Build the `sudo -n -u <agent> bash -lc '...'` command that
    runs the inner version-probe script on the host."""
    inner = _build_openclaw_version_inner_script(
        agent_name, home_root=home_root, path_safelist=path_safelist
    )
    quoted_agent = shlex.quote(agent_name)
    return f"sudo -n -u {quoted_agent} bash -lc {shlex.quote(inner)}"


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


def _get_host_openclaw_version_linux(
    client: paramiko.SSHClient, agent_name: str, *, timeout: int = 10
) -> tuple[tuple[int, int, int] | None, str]:
    """Linux variant: per-agent binary under `/home/<agent>/`, PATH
    fallback safelist matches Linux install.yaml lines ~50-57.

    The `/home` literal is sourced via `home_root_for("linux")` so the
    OS→home-root mapping stays in a single seam (issue #752 invariant).

    Returns `(version, stderr_tail)`. `version` is `None` when the
    binary is missing, the output is unparseable, or the resolved
    PATH binary is rejected by the safelist; `stderr_tail` is the
    last ~512 bytes of stderr so the caller can surface a diagnostic
    instead of an opaque `<unknown>`.
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
    """macOS (arm64) variant: per-agent binary under `/Users/<agent>/`,
    PATH fallback safelist matches install_macos.yaml line ~109.

    The `/Users` literal is sourced via `home_root_for("darwin")` so
    the OS→home-root mapping stays in a single seam (issue #752
    invariant).

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


def _run_openclaw_version_probe(
    client: paramiko.SSHClient, cmd: str, *, timeout: int
) -> tuple[tuple[int, int, int] | None, str]:
    _, out, err = client.exec_command(cmd, timeout=timeout)
    body = out.read().decode("utf-8", errors="replace").strip()
    err_bytes = err.read()
    stderr_tail = err_bytes.decode("utf-8", errors="replace")[-512:].strip()
    if out.channel.recv_exit_status() != 0:
        return None, stderr_tail
    return _parse_semver_tuple(body), stderr_tail


def _get_host_openclaw_version(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    os_family: str,
    timeout: int = 10,
) -> tuple[tuple[int, int, int] | None, str]:
    """Dispatcher: routes to the Linux or macOS variant based on
    `os_family` (the host record's `os_family` field). The Linux and
    macOS resolvers are intentionally separate functions — the
    dispatcher is the only place that knows about both, matching the
    dispatcher-only-OS-fork convention in AGENTS.md.
    """
    if (os_family or "linux").lower() == "darwin":
        return _get_host_openclaw_version_macos(
            client, agent_name, timeout=timeout
        )
    return _get_host_openclaw_version_linux(
        client, agent_name, timeout=timeout
    )


class CanonicalSyncError(Exception):
    """Any failure in the canonical sync pipeline."""


class SecretRemovalRefused(CanonicalSyncError):
    """Raised when the rendered body would remove a host-side secret.

    The message names every secret key that would disappear. The
    operator's recovery is either to fix the underlying attachment
    (most often: re-attach the channel/integration that owns the
    secret, or `clawctl secret set ...` for the missing record) or
    re-run with `--force` if the removal is intentional (e.g. they
    actually did `clawctl agent channel detach`).
    """


class AgentInstallMissingError(CanonicalSyncError):
    """Raised when the validate-phase host probe finds the agent's
    on-host install missing (#811).

    Both the service-manager artifact (systemd unit / launchd plist)
    and the agent home directory are checked. The exception names
    every missing artifact so the operator sees the full gap in one
    pass and routes to the `clawctl agent delete` + `clawctl
    agent create` reinstall flow rather than discovering it
    piecemeal after a half-applied sync. (ATX iter-5 B1: there is
    no `clawctl agent install` verb today; the install path is
    `agent create`.)
    """


@dataclass(frozen=True)
class HostInstallProbe:
    """Result of probe_host_install — a single SSH round-trip.

    `unit_present` and `home_present` reflect what `test -e` / `test -d`
    saw on the host. The resolved absolute paths are returned so the
    caller can interpolate them into operator-facing error text without
    re-deriving them from `os_family`/`agent_type`/`agent_name`.
    """

    unit_present: bool
    home_present: bool
    unit_path: str
    home_path: str

    @property
    def ok(self) -> bool:
        return self.unit_present and self.home_present

    def missing_summary(self) -> str:
        """Render a one-line, ordered summary of what's missing."""
        parts: list[str] = []
        if not self.unit_present:
            parts.append(f"service unit {self.unit_path!r}")
        if not self.home_present:
            parts.append(f"agent home {self.home_path!r}")
        return ", ".join(parts)


def probe_host_install(
    client: paramiko.SSHClient,
    *,
    agent_type: str,
    agent_name: str,
    host: dict,
    timeout: int = 10,
) -> HostInstallProbe:
    """Probe the host for the agent's install artifacts (#811).

    Runs a single `bash -c` over SSH that prints `unit:0|1` and
    `home:0|1` based on `test -e` / `test -d` results. One round-trip
    keeps the latency cost ~50–100ms on LAN; the failure mode it
    prevents is an entire render/diff/write/restart pipeline executed
    against a missing daemon (the original #811 wedge on wolf-i).

    OS routing goes through `unit_path_for` + `home_root_for` so this
    function carries no OS literals — the dispatcher-only OS-fork
    invariant stays intact.

    The unit check (`test -e /etc/systemd/system/*.service` /
    `/Library/LaunchDaemons/*.plist`) does not need sudo — both
    directories are world-readable. The home check DOES need
    `sudo -n`: the agent's parent `$HOME` is owned by the agent
    user and (on every wolf-i installation we observed) is
    `drwxr-x---` (0750) — the world-execute bit is unset, which
    blocks the `xclm` management user from `test -d` on any path
    inside it regardless of the inner directory's permissions.
    The exact mode varies by installer version (sometimes 0750,
    sometimes 0755 on legacy installs) but the missing world-x
    bit on the agent's home is what trips us. We learned this on
    wolf-i during #811 UAT — without sudo, the probe falsely
    reported the home dir missing on every healthy agent.

    Failure-mode discipline (ATX review #811 iter-1 B1/B2/W1):

    - Unparseable / partial stdout MUST NOT be silently treated as
      "both missing" (which would raise `AgentInstallMissingError`
      against a healthy host whose probe blipped). The function
      raises `CanonicalSyncError` with the raw body on ANY
      parse failure.
    - Transport exceptions from paramiko (`SSHException`,
      `socket.timeout`, `OSError`) are wrapped in
      `CanonicalSyncError` so callers see the project's typed
      error shape instead of a raw traceback.
    - `unit_path_for` raises `ValueError` for an unsupported
      (agent_type, os_family) pair — e.g. zeroclaw on darwin,
      which has no launchd plist convention. We wrap that in
      `CanonicalSyncError` so a malformed hosts.json row produces
      an actionable typed error.
    - `sudo -n` stderr is captured: if sudo refused (`password
      required`, `not allowed`), the probe raises
      `CanonicalSyncError` rather than silently flagging the home
      as missing.
    """
    os_family = host.get("os_family", "linux")
    try:
        unit_path = unit_path_for(os_family, agent_type, agent_name)
    except ValueError as exc:
        raise CanonicalSyncError(
            f"cannot probe host install for agent_type="
            f"{agent_type!r} on os_family={os_family!r}: {exc}. "
            f"This (agent_type, os_family) pair has no service-"
            f"manager artifact convention in this clawrium build."
        ) from exc
    home_path = _agent_home_path(os_family, agent_type, agent_name)
    cmd = _build_probe_command(unit_path, home_path)
    try:
        _, out, err = client.exec_command(cmd, timeout=timeout)
        body = out.read().decode("utf-8", errors="replace")
        stderr_text = err.read().decode("utf-8", errors="replace")
    except (paramiko.SSHException, OSError) as exc:
        raise CanonicalSyncError(
            f"host install probe transport failure for "
            f"{agent_name!r}: {exc}"
        ) from exc
    parsed, unit_present, home_present = _parse_probe_output(body)
    if not parsed:
        # Empty / garbage stdout — could be a sudo-denied banner on
        # stderr, an SSH MOTD interleaved into stdout, or a
        # transport hiccup. Raise the typed error rather than
        # invent a "both missing" verdict.
        hint = (
            f" stderr: {stderr_text.strip()!r}"
            if stderr_text.strip()
            else ""
        )
        raise CanonicalSyncError(
            f"host install probe for {agent_name!r} returned "
            f"unparseable output: {body!r}.{hint}"
        )
    # sudo -n stderr inspection. If only the home check failed AND
    # stderr looks like a sudo refusal, we cannot trust the
    # home_present verdict — raise instead of mis-flagging the
    # agent as INSTALL_MISSING.
    if (
        not home_present
        and stderr_text
        and _looks_like_sudo_refusal(stderr_text)
    ):
        raise CanonicalSyncError(
            f"host install probe for {agent_name!r} could not "
            f"verify {home_path!r}: sudo refused on host "
            f"({stderr_text.strip()}). Re-run `clawctl host "
            f"create` to restore passwordless sudo, or inspect "
            f"the host's sudoers configuration."
        )
    return HostInstallProbe(
        unit_present=unit_present,
        home_present=home_present,
        unit_path=unit_path,
        home_path=home_path,
    )


def _agent_home_path(
    os_family: str, agent_type: str, agent_name: str
) -> str:
    """Single source of truth for the agent's `.<type>` home dir.

    Mirrored by `health._probe_install_artifacts`. Extracted (ATX
    iter-1 W2/S2) so a future change to the home-dir convention
    only has to land here, not in both probe call sites.
    """
    return f"{home_root_for(os_family)}/{agent_name}/.{agent_type}"


def _build_probe_command(unit_path: str, home_path: str) -> str:
    """Build the `bash -c`-shaped probe command (ATX iter-1 W2/S1).

    Newline-separated `unit:0|1\\nhome:0|1\\n` so the parser does
    not have to know how the writer joined the tokens. Both probes
    in `lifecycle_canonical` and `health` consume this builder so
    the wire format cannot drift between the two transports.

    `LC_ALL=C` is prepended (ATX #811 iter-2 W1) as a
    best-effort hint to keep sudo's refusal banner in English
    on hosts with a non-default `LANG`. It is NOT a strong
    guarantee — `sudoers`' default `env_reset` scrubs the
    inherited env, and sudo's actual message locale is
    governed by the `sudoers_locale` defaults entry. The
    broad `_SUDO_REFUSAL_PATTERNS` list is the load-bearing
    defense; the env hint just narrows the window where
    pattern matching fails open against a hardened sudoers
    config (ATX iter-4 W8).
    """
    return (
        f"LC_ALL=C; export LC_ALL; "
        f"unit=0; home=0; "
        f"test -e {shlex.quote(unit_path)} && unit=1; "
        f"sudo -n test -d {shlex.quote(home_path)} && home=1; "
        f'printf "unit:%s\\nhome:%s\\n" "$unit" "$home"'
    )


def _parse_probe_output(body: str) -> tuple[bool, bool, bool]:
    """Parse `_build_probe_command` stdout. Returns (parsed, unit, home).

    `parsed=False` means neither key was recognized — the caller
    must treat that as an inconclusive probe, never as "both
    missing." (ATX iter-1 B1.)
    """
    unit_present = False
    home_present = False
    parsed = False
    for line in body.splitlines():
        key, _, value = line.partition(":")
        if key == "unit":
            unit_present = value.strip() == "1"
            parsed = True
        elif key == "home":
            home_present = value.strip() == "1"
            parsed = True
    return parsed, unit_present, home_present


# ATX #811 iter-2 W1: the pattern list MUST stay broad. A miss here
# silently turns a sudo-denied host into a fleet-wide spurious
# INSTALL_MISSING flag (the lifecycle probe raises but the health
# probe falls through — both depend on this list). Locale-stability
# is enforced separately by prefixing the probe command with
# `LC_ALL=C` so sudo's message stays English on `LANG=*` hosts.
_SUDO_REFUSAL_PATTERNS = (
    "a password is required",
    "password is required",
    "not allowed to execute",
    "is not allowed to run sudo",
    "not in the sudoers",
    "may not run sudo",
    "incident will be reported",
    "no tty present",
    "sudo: a terminal is required",
    # ATX #811 iter-4 W7: sudo binary absent → shell emits this
    # before any banner. The probe should NOT treat the resulting
    # `home_present=False` as authoritative.
    "sudo: command not found",
)


def _looks_like_sudo_refusal(stderr_text: str) -> bool:
    """Heuristic for "sudo -n said no" (ATX iter-1 W1).

    Matched against lowercased stderr. False positives surface as
    `CanonicalSyncError`("sudo refused") on an actually-missing
    home — annoying but safe; the operator's next step is the
    same (`clawctl host create` to fix sudoers, OR
    `clawctl agent create` to reinstall the missing home).
    False
    negatives leave the original mis-flag-as-missing bug intact
    for that one host, so the pattern list is kept broad.
    """
    lower = stderr_text.lower()
    return any(p in lower for p in _SUDO_REFUSAL_PATTERNS)


@dataclass(frozen=True)
class CanonicalSyncResult:
    success: bool
    agent: str
    host: str
    files_written: tuple[str, ...]
    files_unchanged: tuple[str, ...]
    diffs: tuple[FileDiff, ...]
    error: str | None = None
    # Issue #760: per-sync workspace overlay phase counters. Always
    # populated (empty tuples when the agent type has no
    # `features.workspace_overlay` block, or in failure paths that
    # short-circuit before the phase runs).
    workspace_files_pushed: tuple[str, ...] = ()
    workspace_files_excluded: tuple[str, ...] = ()


def _extract_secret_keys(body: str) -> set[str]:
    """Return the set of secret-looking env var keys present in `body`.

    Operates on a `.env`-style body; the YAML config side carries no
    bare secrets in the rendered output (provider credentials are
    always in `.env`), so a YAML-only diff cannot trip the guard. The
    `_SECRET_KEY_SUFFIXES` heuristic is intentionally broad — false
    positives manifest as the operator needing to pass `--force` on a
    legitimate non-secret removal, which is annoying but safe; false
    negatives manifest as the original #555 silent-wipe regression,
    which is unsafe. The matrix test pins the suffix list.
    """
    keys: set[str] = set()
    for m in _SECRET_KEY_PATTERN.finditer(body):
        key = m.group("key")
        if any(key.endswith(suf) for suf in _SECRET_KEY_SUFFIXES):
            keys.add(key)
    return keys


def _diff_removes_secrets(diff: FileDiff) -> set[str]:
    """Return the set of secret keys present on host but absent in render.

    A non-empty set means the canonical pipeline must refuse without
    `force=True`. Returns the empty set when the file is .yaml /
    .toml — those formats don't carry bare KEY=VALUE secrets in our
    renderers (every secret is in the `.env`), and the unified-diff
    body would otherwise produce false positives from matching key
    fragments inside YAML quoted strings.
    """
    # Only `.env` bodies carry bare key=value secret pairs in any of
    # our renderers. Skip the guard for other formats to avoid false
    # positives. The matrix test asserts this — if a future renderer
    # starts emitting bare secrets to e.g. `config.toml`, this branch
    # must extend.
    #
    # NOTE (#723 ATX W6): openclaw's `models.providers.<name>.apiKey`
    # in `.openclaw/openclaw.json` is the first JSON-body inline
    # secret in the canonical pipeline. It is intentionally NOT
    # covered by this guard — a provider swap (litellm → ollama)
    # legitimately drops the litellm block AND its `apiKey`, and a
    # JSON-aware guard would falsely block the operator on every
    # such swap. The boundary is enforced upstream instead:
    # `build_render_inputs` raises `AgentConfigError` if the secret
    # is missing in `secrets.json`, so a missing-bearer regression
    # cannot reach this guard in the first place. If a future
    # provider type carries a JSON-inline secret that should survive
    # cross-provider transitions, extend the guard rather than
    # papering over with `force=True`.
    if not diff.path.endswith(".env"):
        return set()
    host_keys = _extract_secret_keys(diff.remote_body)
    rendered_keys = _extract_secret_keys(diff.rendered_body)
    return host_keys - rendered_keys


def _open_ssh(host: dict, *, timeout: int = 15) -> paramiko.SSHClient:
    """Open an SSH client to `host` using the registered private key.

    Host-key policy: `WarningPolicy` — matches `lifecycle.py:471` and
    `render_diff.py:119` so every clawctl SSH client in the codebase
    behaves the same way. The rationale (from `lifecycle.py:462-471`):
    `clawctl host create` provisions a host without a `known_hosts`
    entry; default `RejectPolicy` would refuse every legitimate first
    connection. `AutoAddPolicy` silently persists keys with no
    visibility. `WarningPolicy` connects but logs, so a key swap
    surfaces via paramiko's logger.

    `BadHostKeyException` (raised by paramiko when a *known* key
    changes) is NOT suppressed — it propagates as a connect failure,
    which is the desired behavior for MITM detection. The TOFU-style
    `StrictHostKeyPolicy` in `ssh_connection.py` is for the
    user-prompt path; the sync pipeline is non-interactive, so the
    project-wide `WarningPolicy` is the right cell here.
    """
    key_id = host.get("key_id") or host.get("hostname") or ""
    private_key = get_host_private_key(key_id)
    if not private_key:
        raise CanonicalSyncError(
            f"no SSH key registered for host {key_id!r}; "
            "re-run `clawctl host create` to provision one"
        )
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    try:
        client.connect(
            hostname=host.get("hostname", ""),
            port=int(host.get("port", 22) or 22),
            username=host.get("user", "xclm"),
            key_filename=str(private_key),
            timeout=timeout,
        )
    except paramiko.BadHostKeyException as exc:
        raise CanonicalSyncError(
            f"host key for {host.get('hostname', '')!r} has changed since "
            f"`clawctl host create` recorded it: {exc}. Refusing to "
            f"write — this could be a MITM. Verify the host and re-run "
            f"`clawctl host create` if intentional."
        ) from exc
    except (paramiko.AuthenticationException, paramiko.SSHException) as exc:
        raise CanonicalSyncError(
            f"SSH connection to {host.get('hostname', '')!r} failed: {exc}"
        ) from exc
    except OSError as exc:
        raise CanonicalSyncError(
            f"network error reaching {host.get('hostname', '')!r}: {exc}"
        ) from exc
    return client


def _host_is_macos(host: dict) -> bool:
    """Single OS-detection helper for the canonical pipeline dispatchers."""
    return host.get("hardware", {}).get("os") == "macos"


def _atomic_write_linux(
    client: paramiko.SSHClient,
    *,
    agent_name: str,
    remote_path: str,
    body: str,
    timeout: int = 30,
) -> None:
    """Linux implementation: agent_name doubles as the primary group name."""
    quoted_path = shlex.quote(remote_path)
    _, stdout, _ = client.exec_command("mktemp /tmp/clawrium-sync.XXXXXX")
    if stdout.channel.recv_exit_status() != 0:
        raise CanonicalSyncError("mktemp failed on host")
    tmp_path = stdout.read().decode("utf-8").strip()
    if not tmp_path:
        raise CanonicalSyncError("mktemp returned empty path")
    try:
        sftp = client.open_sftp()
        try:
            with sftp.file(tmp_path, "wb") as fh:
                fh.write(body.encode("utf-8"))
        finally:
            sftp.close()
        owner = shlex.quote(agent_name)
        cmd = (
            f"sudo -n install -m 0600 -o {owner} -g {owner} "
            f"{shlex.quote(tmp_path)} {quoted_path}"
        )
        _, install_out, install_err = client.exec_command(cmd, timeout=timeout)
        rc = install_out.channel.recv_exit_status()
        if rc != 0:
            stderr_text = install_err.read().decode("utf-8", errors="replace")
            raise CanonicalSyncError(
                f"install {remote_path!r} failed (exit {rc}): {stderr_text.strip()}"
            )
    finally:
        client.exec_command(f"rm -f {shlex.quote(tmp_path)}")


def _atomic_write(
    client: paramiko.SSHClient,
    *,
    agent_name: str,
    remote_path: str,
    body: str,
    host: dict | None = None,
    timeout: int = 30,
) -> None:
    """Dispatcher — routes to the Linux or macOS atomic-write impl by host OS.

    `install` is atomic w.r.t. the destination on both platforms, so a
    partial write is never visible. The OS split is purely about the
    primary-group name passed to `install -g`: Linux uses a per-user
    group matching `agent_name`; macOS uses the shared `staff` group.
    """
    if host is not None and _host_is_macos(host):
        from clawrium.core.lifecycle_macos import atomic_write_macos

        return atomic_write_macos(
            client,
            agent_name=agent_name,
            remote_path=remote_path,
            body=body,
            timeout=timeout,
        )
    _atomic_write_linux(
        client,
        agent_name=agent_name,
        remote_path=remote_path,
        body=body,
        timeout=timeout,
    )


def _restart_unit_linux(
    client: paramiko.SSHClient,
    *,
    agent_type: str,
    agent_name: str,
    timeout: int = 30,
) -> None:
    unit = f"{agent_type}-{agent_name}.service"
    cmd = f"sudo -n systemctl restart {shlex.quote(unit)}"
    _, out, err = client.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    if rc != 0:
        stderr_text = err.read().decode("utf-8", errors="replace")
        raise CanonicalSyncError(
            f"restart {unit} failed (exit {rc}): {stderr_text.strip()}"
        )


def _restart_unit(
    client: paramiko.SSHClient,
    *,
    agent_type: str,
    agent_name: str,
    host: dict | None = None,
    on_event: Callable[[str, str], None] | None = None,
    timeout: int = 30,
) -> None:
    """Dispatcher — routes to systemctl (Linux) or launchctl helpers (macOS).

    macOS routes through `lifecycle_macos.restart_unit_macos` which
    handles dual-label (gateway + dashboard for hermes), validates the
    agent name via `label_for`, and falls back to a fresh bootstrap if
    the unit was never loaded.
    """
    if host is not None and _host_is_macos(host):
        from clawrium.core.lifecycle_macos import restart_unit_macos

        return restart_unit_macos(
            client,
            host=host,
            agent_name=agent_name,
            agent_type=agent_type,
            on_event=on_event,
            timeout=timeout,
        )
    _restart_unit_linux(
        client,
        agent_type=agent_type,
        agent_name=agent_name,
        timeout=timeout,
    )


# #575: when a unit fails to come active after restart, capture the
# tail of its journal and translate well-known fatal patterns into
# remediation-shaped messages. The default error (`unit not active
# after restart (state='activating')`) sends the operator chasing the
# wrong layer — e.g. the hermes Discord-token crash brings the entire
# FastAPI gateway down via an unisolated `discord.errors.LoginFailure`
# in the upstream package, and the chat-port-never-binds symptom
# points nowhere near the channel registry as the actual cause.
#
# Each entry: (regex, agent_types, summary, remediation). `agent_types`
# is a `frozenset` of agent type names the entry applies to; an empty
# set means "all agent types". The regex matches any substring of the
# journal tail (Python `re.search`). Patterns are checked in order —
# first match wins. The matched journal text is NEVER forwarded to
# callers — only the compile-time `summary` + `remediation` strings
# are returned, so adding a tuple element that captures the matched
# line would be a security regression (avoid).
_KNOWN_UNIT_FATAL_PATTERNS: tuple[
    tuple[str, frozenset[str], str, str], ...
] = (
    (
        r"discord\.errors\.LoginFailure",
        frozenset({"hermes"}),
        "Discord rejected the bot token (LoginFailure / 401 Unauthorized).",
        "Re-issue the channel record with a valid token: `clawctl channel "
        "registry delete <name> --yes` + `clawctl channel registry create "
        "<name> --type discord --token-stdin …` + `clawctl agent sync "
        "<agent>`. The current hermes upstream does not isolate Discord "
        "client failures from the gateway process, so a stale or "
        "fat-fingered token currently takes the chat endpoint down with "
        "it (tracked in #575).",
    ),
    (
        # ATX B3: zeroclaw v0.7.5 emits the exact token
        # `[required_field_empty] gateway.host must not be empty` per the
        # observed journal capture in #576. The broadened alternation
        # also matches a Rust-shaped `field 'gateway.host' is empty` in
        # case a future zeroclaw rewrite changes the wording, so a
        # subsequent version bump does not silently turn this entry
        # into a dead letter.
        # ATX iter-2 B1: dropped `|required` — it over-matched
        # benign startup lines like "gateway.host (required): ..."
        # or "checking gateway.host... required for daemon init"
        # that any 100-line journal tail would contain regardless of
        # crash reason. Two branches survive: branch1 anchors on the
        # canonical zeroclaw token name `required_field_empty`
        # adjacent to `gateway.host` (fires independently of any
        # trailing suffix); branch2 anchors on the actual fault-
        # state phrasings `must not be empty` / `is empty` that
        # any future zeroclaw wording would reuse.
        r"required_field_empty.*gateway\.host"
        r"|gateway\.host.*(?:must not be empty|is empty)",
        frozenset({"zeroclaw"}),
        "zeroclaw daemon refused an empty `gateway.host`.",
        "Re-run `clawctl agent sync <agent>` after `clawctl` is upgraded "
        "to a release containing the #576 fix, or hand-edit "
        "`~/.zeroclaw/config.toml` on the host to set `host = \"0.0.0.0\"` "
        "under `[gateway]` and restart the unit.",
    ),
    (
        # Cross-agent: any agent that loads an OpenRouter provider
        # without a populated key would surface one of these two
        # messages. Parenthesized alternation for clarity (ATX W6).
        # ATX iter-2 B2 + iter-3 W-NEW-1: the separator class covers
        # `KEY: not set`, `KEY=not set`, and tab/space-separated
        # variants; the optional `is` and `\b` tail anchor stay
        # from iter-2 to keep `was not set, now present` rejected.
        # ATX iter-4 W1: the separator class is restricted to
        # horizontal whitespace + `:` + `=`. `[\s:=]+` would have
        # included `\n`, which over `re.search` against the full
        # 100-line journal blob meant a journal where
        # `OPENROUTER_API_KEY` ends one line and `not set ...`
        # begins the next would over-fire.
        # ATX iter-4 W2: the `(?i)` flag applies to the entire
        # pattern, intentionally — `openrouter_api_key not set` (a
        # lowercase env-dump shape that some agents emit) is a
        # legitimate match. `No inference provider configured` also
        # case-folds, which is harmless since both branches share
        # the cross-agent scope and the phrase is specific.
        # ATX iter-4 W3: leading `\b` rejects substring matches
        # inside a longer identifier (e.g. `MY_OPENROUTER_API_KEY` —
        # which is NOT the OpenRouter key clawctl plumbs and should
        # not surface this remediation). `\b` does not match between
        # two word characters, so `MY_OPENROUTER_API_KEY` no longer
        # matches even via `re.search`.
        # ATX iter-5 W1-RESIDUAL (#575): the suffix groups also use
        # `[\t ]+` (not `\s+`) so a journal blob where a newline
        # falls between `is` and `not set` (e.g. `journalctl -o cat`
        # output that drops the per-line timestamp prefix) does not
        # over-fire. ATX iter-6 W1 (#575): the two boundary classes
        # are not symmetric: the KEY↔phrase boundary `[\t :=]+`
        # admits tabs, spaces, colon, and equals (a `KEY=` or
        # `KEY:` style separator); the in-phrase boundaries `[\t ]+`
        # are horizontal-whitespace-only. Both are newline-safe.
        r"(?i)(?:\bOPENROUTER_API_KEY[\t :=]+(?:is[\t ]+)?not[\t ]+set\b"
        r"|No inference provider configured)",
        frozenset(),  # empty == all agent types
        "Provider credentials missing from the rendered config.",
        "Run `clawctl agent doctor <agent>` — it should show "
        "`api_key=present`. If it shows `missing`, re-run "
        "`clawctl agent configure <agent> --stage providers --provider "
        "<id>` and confirm the provider record carries a credential.",
    ),
)


def _diagnose_unit_failure(
    client: paramiko.SSHClient,
    *,
    unit: str,
    agent_type: str,
    timeout: int = 15,
) -> str | None:
    """Tail a failed unit's journal and look for known fatal patterns.

    Returns a one-line remediation-shaped diagnostic, or None if no
    pattern matched. Failures inside this helper (SSH disconnect,
    sudo denied, etc.) deliberately return None — diagnostics must
    never mask the original `unit not active` error. The swallow path
    is debuggable via `logger.debug` so a sudoers regression is not
    completely invisible (ATX W2).

    `agent_type` is required so each catalog entry's `agent_types`
    scope can filter false-positive matches (e.g. a hypothetical
    openclaw journal containing the substring `gateway.host` should
    not surface a zeroclaw-shaped TOML remediation — ATX B1/B2).

    Worst-case wall-clock on this helper is one extra `exec_command`
    bounded by the given `timeout` — the caller's overall budget is
    `2 × timeout` (one is-active probe + one journal fetch). Callers
    that want a tighter cap can pass a smaller `timeout` here.
    """
    cmd = (
        # `-n` matches the rest of this file (`_restart_unit`,
        # `_write_remote_config`) — fail immediately if sudoers was
        # accidentally scoped, rather than blocking on a password
        # prompt that would only hang `exec_command` (ATX W1).
        f"sudo -n journalctl --unit {shlex.quote(unit)} "
        f"--no-pager --lines 100 2>/dev/null || true"
    )
    try:
        _, out, _ = client.exec_command(cmd, timeout=timeout)
        out.channel.recv_exit_status()
        journal = out.read().decode("utf-8", errors="replace")
    except Exception as exc:
        # Keep the swallow contract — but make a sudoers regression
        # debuggable rather than completely invisible (ATX W2).
        logger.debug(
            "_diagnose_unit_failure: exception fetching journal for %s: %s",
            unit,
            exc,
        )
        return None

    if not journal.strip():
        return None

    for pattern, agent_types, summary, remediation in _KNOWN_UNIT_FATAL_PATTERNS:
        if agent_types and agent_type not in agent_types:
            continue
        if re.search(pattern, journal):
            return f"{summary} {remediation}"
    return None


def _verify_health(
    client: paramiko.SSHClient,
    *,
    agent_type: str,
    agent_name: str,
    host: dict | None = None,
    gateway_port: int | None = None,
    on_event: Callable[[str, str], None] | None = None,
    timeout: int = 15,
) -> None:
    """Dispatcher — systemctl is-active + gateway port probe (Linux),
    or `nc -z` port probe (macOS)."""
    if host is not None and _host_is_macos(host):
        from clawrium.core.lifecycle_macos import verify_health_macos

        # macOS launchd needs longer than systemctl to stabilize after
        # kickstart, especially if the daemon crash-looped previously.
        return verify_health_macos(
            client,
            agent_name=agent_name,
            gateway_port=gateway_port,
            on_event=on_event,
            timeout=max(timeout, 30),
        )

    unit = f"{agent_type}-{agent_name}.service"
    cmd = f"systemctl is-active {shlex.quote(unit)}"
    _, out, _ = client.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    state = out.read().decode("utf-8", errors="replace").strip()
    if rc != 0 or state != "active":
        # Diagnostic is best-effort — a raise inside the helper still
        # leaves the verdict-raise below intact (ATX B5).
        diagnostic: str | None
        try:
            diagnostic = _diagnose_unit_failure(
                client,
                unit=unit,
                agent_type=agent_type,
                timeout=timeout,
            )
        except Exception as exc:
            logger.debug(
                "_verify_health: _diagnose_unit_failure raised for %s: %s",
                unit,
                exc,
            )
            diagnostic = None
        base = (
            f"unit {unit} is not active after restart (state={state!r})"
        )
        if diagnostic:
            raise CanonicalSyncError(f"{base}. Diagnosis: {diagnostic}")
        raise CanonicalSyncError(base)

    # #812: `Type=simple` units (our openclaw/zeroclaw/hermes systemd
    # unit shape) report `active` as soon as the process is spawned —
    # before the daemon has had a chance to bind its gateway port. A
    # crashlooping daemon also flashes `active` between `RestartSec`
    # windows. `is-active` alone therefore cannot prove the daemon is
    # serving requests; only an out-of-band probe on the gateway port
    # can. The macOS path (verify_health_macos) already does this; the
    # Linux path now matches.
    #
    # ATX iter-2 W1: parity with `verify_health_macos`'s missing-port
    # raise. A `hosts.json` that lacks a persisted `gateway.port` for an
    # agent that declares one in its manifest means install.py never
    # allocated one — the agent is not properly installed. A silent
    # skip would let canonical sync write `state=READY` for a
    # never-verified daemon and reintroduce exactly the silent-green
    # failure mode #812 exists to close.
    if gateway_port is None:
        raise CanonicalSyncError(
            f"_verify_health: no gateway port persisted for "
            f"{agent_name!r}. install.py never allocated one — the "
            f"agent install is incomplete. Re-run "
            f"`clawctl agent create` or inspect "
            f"hosts.json.agents.{agent_name}.config.gateway.port."
        )
    _verify_gateway_listening_linux(
        client,
        agent_type=agent_type,
        agent_name=agent_name,
        gateway_port=gateway_port,
        timeout=timeout,
    )


# ATX iter-2 W2: precompiled regex modeled on `_NC_MISSING_RE` in
# `lifecycle_macos.verify_health_macos`. Catches "bash not found" via
# the standard shell-prelude shapes ("bash: not found",
# "bash: command not found", "sh: 1: bash: not found", "command not
# found: bash") without false-positiving on a `bashrc` that itself
# emits "command not found" for some unrelated tool while bash is
# fine. Bound with `\b` on each side so a stray substring cannot match.
_BASH_MISSING_RE = re.compile(
    r"(\bbash\b[^\n]*\bnot found\b|\bnot found\b[^\n]*\bbash\b)",
    re.IGNORECASE,
)

# ATX iter-2 W3: bash compiled `--disable-net-redirections` (some
# hardened distro images) emits this exact path-shaped error instead
# of supporting `/dev/tcp`. Without this branch the operator chases a
# `timeout`s "port not accepting" red herring against a perfectly
# healthy daemon.
_BASH_DEV_TCP_DISABLED_RE = re.compile(
    r"/dev/tcp/[^:\s]+[^\n]*\bNo such file or directory\b",
    re.IGNORECASE,
)


def _verify_gateway_listening_linux(
    client: paramiko.SSHClient,
    *,
    agent_type: str,
    agent_name: str,
    gateway_port: int,
    timeout: int = 15,
) -> None:
    """Poll the loopback gateway port via bash `/dev/tcp` until accept,
    or raise `CanonicalSyncError` on timeout.

    Mirrors `verify_health_macos` in shape so that the two paths share
    the same operator-facing failure mode. `bash -c 'exec
    3<>/dev/tcp/127.0.0.1/<port>'` is a TCP connect that succeeds when
    the daemon is `accept()`-ing — it does not require `nc` (sometimes
    absent on minimal Ubuntu cloud images) or `python3` startup
    overhead. `/dev/tcp` is a bash builtin (not a real device file),
    so bash MUST be invoked explicitly — `sh -c` (the default for
    paramiko `exec_command`) on dash-shipping distros would silently
    fail with "No such file or directory" on the path expansion.

    The 15s default timeout matches the existing `_verify_health`
    budget. With `Type=simple` + `Restart=always RestartSec=5s` a
    crashlooping daemon completes ~3 bind-attempt cycles in 15s — more
    polls just compound the wait without disambiguating a slow-bind
    healthy daemon from a never-bind broken one. Field reports of
    false positives should bump this, but 30s (the macOS budget) is
    overkill because Linux already cleared `systemctl is-active`
    above; macOS has no equivalent precheck.
    """
    from clawrium.cli.output._sanitize import sanitize_passthrough

    import time as _time

    # Reject hand-edited hosts.json shapes the same way macOS does.
    # `type(...) is int` (not `isinstance`) so True/False are rejected:
    # bool is an int subclass and a JSON parser that round-trips `true`
    # through `int` would otherwise sail through.
    if (
        type(gateway_port) is not int
        or not 0 < gateway_port < 65536
    ):
        raise CanonicalSyncError(
            f"_verify_gateway_listening_linux: invalid gateway_port "
            f"{gateway_port!r}"
        )

    probe = (
        f"bash -c 'exec 3<>/dev/tcp/127.0.0.1/{gateway_port}' "
        f"</dev/null 2>&1"
    )
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        # ATX iter-2 B1: every other `exec_command` call site in this
        # file is guarded against paramiko / OSError raises. A bare
        # `paramiko.SSHException` (channel reset mid-poll) here would
        # propagate raw through `sync_agent_canonical` instead of
        # surfacing as a `CanonicalSyncError` the CLI knows how to
        # render. ATX iter-3 S1: `EOFError` is paramiko's signal for
        # an abrupt channel teardown and is NOT a subclass of either
        # `SSHException` or `OSError` — must be caught explicitly.
        channel = None
        try:
            try:
                _, out, err = client.exec_command(probe, timeout=5)
                channel = out.channel
                stdout_text = out.read().decode("utf-8", errors="replace")
                stderr_text = err.read().decode("utf-8", errors="replace")
                rc = channel.recv_exit_status()
            except (paramiko.SSHException, OSError, EOFError) as exc:
                raise CanonicalSyncError(
                    f"_verify_gateway_listening_linux: SSH channel "
                    f"error while probing gateway port {gateway_port} "
                    f"on {agent_name}: {exc!r}"
                ) from exc
        finally:
            # ATX iter-3 S2/S8: close in `finally:` so the channel is
            # released even if `out.read()` / `recv_exit_status()`
            # raised mid-iteration. Each `exec_command` opens a fresh
            # SSH channel; ~timeout-seconds-worth of file descriptors
            # would otherwise leak per sync when operators chain syncs.
            if channel is not None:
                try:
                    channel.close()
                except Exception:  # noqa: BLE001 — cleanup, never fatal
                    pass
        if rc == 0:
            return
        combined = stderr_text + stdout_text
        # ATX iter-2 W2: precompiled regex (see `_BASH_MISSING_RE` and
        # `_BASH_DEV_TCP_DISABLED_RE` above) — both diagnose a
        # tool-side problem rather than a daemon-side bind failure, so
        # break early and point the operator at the host image, not
        # the daemon.
        if rc == 127 and _BASH_MISSING_RE.search(combined):
            raise CanonicalSyncError(
                f"_verify_gateway_listening_linux: `bash` is not "
                f"available on the agent host (rc=127, output: "
                f"{sanitize_passthrough(combined.strip())}). bash is "
                f"required for the loopback /dev/tcp probe — install "
                f"bash on the agent host."
            )
        if _BASH_DEV_TCP_DISABLED_RE.search(combined):
            raise CanonicalSyncError(
                f"_verify_gateway_listening_linux: bash on the agent "
                f"host was built without `/dev/tcp` support "
                f"(output: {sanitize_passthrough(combined.strip())}). "
                f"This probe cannot run on a `--disable-net-"
                f"redirections` bash; install a stock bash or run "
                f"the gateway-port check manually."
            )
        _time.sleep(1)
    unit = f"{agent_type}-{agent_name}.service"
    raise CanonicalSyncError(
        f"gateway port {gateway_port} not accepting connections after "
        f"{timeout}s (agent={agent_name}). systemctl is-active reported "
        f"the unit running but the daemon is not bound to its declared "
        f"gateway port. Inspect "
        f"`journalctl -u {unit} --since='2min ago'` on "
        f"the agent host for the bind failure."
    )


# #755: openclaw plugin install on every sync.
#
# Before #755 the `@openclaw/brave-plugin` install lived only in
# `playbooks/openclaw/configure.yaml` (+ the macOS sibling). That made
# `clawctl agent integration attach <brave>` + `clawctl agent sync`
# silently incomplete — the env was rendered with `BRAVE_API_KEY` but
# the plugin manifest the var feeds was never written to host. Lifting
# the install into the canonical sync pipeline makes sync the single
# source of truth for declared state, the operator's mental model.
#
# Generalizes beyond brave: any entry in the openclaw manifest's
# `plugins:` block whose key matches an attached integration's `type`
# is installed at the pinned `npm_package@version`. Future plugin-
# backed integrations need only a manifest row — no playbook change,
# no Python wiring.
def _load_openclaw_plugins() -> dict[str, dict]:
    """Read the entire `plugins:` block from the openclaw manifest.

    Returns a dict keyed by plugin name (matching integration `type`).
    Raises `CanonicalSyncError` on a structural problem so the caller
    cannot proceed with an undefined pin (mirrors
    `_load_openclaw_brave_pin`'s hard-fail discipline)."""
    import yaml as _yaml

    manifest_path = (
        Path(__file__).parent.parent
        / "platform"
        / "registry"
        / "openclaw"
        / "manifest.yaml"
    )
    try:
        manifest = _yaml.safe_load(manifest_path.read_text())
    except Exception as exc:
        raise CanonicalSyncError(
            f"openclaw plugin install: cannot read manifest: {exc}"
        ) from exc
    block = (manifest or {}).get("plugins") or {}
    if not isinstance(block, dict):
        raise CanonicalSyncError(
            "openclaw manifest `plugins:` block is malformed (not a mapping)"
        )
    return block


def _openclaw_plugin_paths(
    agent_name: str, *, os_family: str
) -> tuple[str, str]:
    """Return `(openclaw_home, openclaw_bin)` for `agent_name` on the
    given `os_family`. `/home` vs `/Users` is sourced via
    `home_root_for(os_family)` so the OS→home-root mapping stays in
    one seam (#770 invariant). `openclaw_bin` is the per-agent
    `openclaw` shim installed by `install.yaml` — invoked by absolute
    path so PATH lookup is not load-bearing here."""
    home = f"{home_root_for(os_family)}/{agent_name}/.openclaw"
    openclaw_bin = f"{home}/bin/openclaw"
    return home, openclaw_bin


def _openclaw_install_plugins(
    client: paramiko.SSHClient,
    agent_name: str,
    *,
    os_family: str,
    inputs,
    on_event: Callable[[str, str], None] | None = None,
    install_timeout: int = 180,
    probe_timeout: int = 15,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Install openclaw plugins required by attached integrations.

    For each entry in the openclaw manifest's `plugins:` block whose
    key matches an attached integration `type`, run
    `npm install --prefix ~<agent>/.openclaw <npm_package>@<version>`
    on the host (as the agent user) when the per-version sentinel file
    `<openclaw_home>/.<plugin>-plugin-installed.<version>` is missing.

    Idempotency: a sentinel file whose name encodes the version. A pin
    bump changes the sentinel filename so the install re-fires; a same-
    version repeat is a no-op (the probe short-circuits before npm
    runs). This is the same gating shape the configure playbook
    historically used (`creates:` arg on the `npm install` task at
    `configure.yaml:133`), lifted intact into Python so the canonical
    sync pipeline owns it.

    Returns `(installed, skipped)` — tuples of plugin keys (e.g.
    `("brave",)`) for the caller's event payloads. The `skipped`
    bucket includes both "sentinel already present" and "no attached
    integration for this plugin"; the latter is the common-case empty
    branch.

    Raises `CanonicalSyncError` on any per-host failure (npm missing,
    install non-zero, sentinel stamp failed) so the caller can
    short-circuit before `_restart_unit`. The agent is never restarted
    on a half-installed plugin set."""
    plugins_block = _load_openclaw_plugins()
    if not plugins_block:
        return (), ()

    attached_types = {i.type for i in inputs.integrations}
    home, openclaw_bin = _openclaw_plugin_paths(
        agent_name, os_family=os_family
    )
    quoted_agent = shlex.quote(agent_name)
    quoted_bin = shlex.quote(openclaw_bin)

    installed: list[str] = []
    skipped: list[str] = []

    for plugin_key, spec in plugins_block.items():
        if plugin_key not in attached_types:
            skipped.append(plugin_key)
            continue
        pkg = (spec or {}).get("npm_package")
        ver = (spec or {}).get("version")
        if not pkg or not ver:
            raise CanonicalSyncError(
                f"openclaw manifest plugin {plugin_key!r} is missing "
                f"npm_package or version — clawrium build is corrupt; "
                f"reinstall via `uv tool install clawrium`."
            )
        sentinel = f"{home}/.{plugin_key}-plugin-installed.{ver}"
        quoted_sentinel = shlex.quote(sentinel)

        # Sentinel probe — cheap fast-path that short-circuits the
        # ~Node-startup cost of `openclaw plugins install` on every
        # subsequent sync at the same pin. The sentinel filename
        # encodes the version, so a pin bump auto-fires reinstall
        # via the missing-sentinel branch below. Runs as the agent
        # user because `~<agent>/.openclaw` is mode 0700 and the
        # SSH user (xclm) cannot stat inside it. `sudo -n -H` resets
        # HOME to the agent user's home — required for `openclaw
        # plugins install` downstream which writes plugin state into
        # `~<agent>/.openclaw/state/` (surfaced live during #755 UAT
        # on esper-mac-oc, where the install otherwise inherited
        # `/Users/xclm` as HOME and failed EACCES on the state DB).
        probe = (
            f"sudo -n -H -u {quoted_agent} test -f {quoted_sentinel}"
        )
        _, p_out, _ = client.exec_command(probe, timeout=probe_timeout)
        if p_out.channel.recv_exit_status() == 0:
            if on_event is not None:
                on_event(
                    "plugin_install",
                    f"openclaw plugin {plugin_key}@{ver} already "
                    f"installed on {agent_name} (sentinel present)",
                )
            skipped.append(plugin_key)
            continue

        if on_event is not None:
            on_event(
                "plugin_install",
                f"installing openclaw plugin {pkg}@{ver} on {agent_name}",
            )

        # `openclaw plugins install <npm-spec>` is openclaw's own
        # plugin install path — it writes to the per-agent plugin
        # store that `openclaw plugins list` scans (`~<agent>/.openclaw/
        # node_modules/` alone is NOT scanned, surfaced live during
        # #755 UAT). `--force` overwrites a prior pin so a bumped
        # version takes effect even if the previous install lingers;
        # `--pin` records the resolved `<name>@<version>` exactly so a
        # transitive upgrade cannot smuggle in a new floor.
        install_cmd = (
            f"sudo -n -H -u {quoted_agent} {quoted_bin} plugins install "
            f"--force --pin {shlex.quote(f'{pkg}@{ver}')}"
        )
        _, i_out, i_err = client.exec_command(
            install_cmd, timeout=install_timeout
        )
        # ATX iter-2 W1: drain stdout + stderr BEFORE recv_exit_status.
        # `openclaw plugins install` proxies `npm install` whose output
        # can exceed the ~64KB SSH pipe buffer on fresh-host installs
        # (download progress, peer-dep warnings, audit reports). With
        # the buffer full the remote write blocks before exit-status is
        # sent, so `recv_exit_status()` hangs indefinitely — surfaced as
        # an apparent freeze of `clawctl agent sync` with no diagnostic.
        # Matches the established `_run_openclaw_version_probe` pattern.
        _ = i_out.read()
        err_bytes = i_err.read()
        rc = i_out.channel.recv_exit_status()
        if rc != 0:
            err_text = err_bytes.decode("utf-8", errors="replace")
            raise CanonicalSyncError(
                f"openclaw plugin {pkg}@{ver} install failed on "
                f"{agent_name} (exit {rc}): {err_text.strip()}"
            )

        # Stamp sentinel — touch + chmod in one round-trip. Failure
        # here means a future sync would re-install (sentinel absent),
        # but the plugin itself is already present; surface as an
        # error so the operator can investigate fs / perms now rather
        # than seeing repeated installs on every subsequent sync.
        stamp_inner = (
            f"touch {quoted_sentinel} && chmod 0600 {quoted_sentinel}"
        )
        stamp = (
            f"sudo -n -H -u {quoted_agent} sh -c {shlex.quote(stamp_inner)}"
        )
        _, s_out, s_err = client.exec_command(stamp, timeout=probe_timeout)
        if s_out.channel.recv_exit_status() != 0:
            err_text = s_err.read().decode("utf-8", errors="replace")
            raise CanonicalSyncError(
                f"openclaw plugin {pkg}@{ver} installed on {agent_name} "
                f"but sentinel stamp at {sentinel!r} failed: "
                f"{err_text.strip()}. Run `clawctl agent sync "
                f"{agent_name}` again to retry."
            )
        installed.append(plugin_key)

    return tuple(installed), tuple(skipped)


# #834: hermes MCP subprocess installers.
#
# Follows the architectural pattern documented in AGENTS.md
# §"Integration Binary Install": integration binaries live in
# dedicated single-purpose runbooks and install at sync time when the
# integration is attached — not baked into `configure.yaml`, not
# baked into `install.yaml`. Same design as `_openclaw_install_plugins`
# above (#755). Generalizes as more MCP-backed hermes integrations
# land: one helper + one runbook per integration binary.
#
# Idempotency: the runbook uses `get_url` with `checksum:` so an
# unchanged version pin short-circuits in ~10ms via SHA256 re-verify.
# No sentinel file, no version stamp needed on our side.
_HERMES_SLACK_TYPES = frozenset({"slack-user", "slack-cookie"})


def _hermes_install_slack_mcp(
    agent_name: str,
    hostname: str,
    host: dict,
    inputs,
    *,
    on_event: Callable[[str, str], None] | None = None,
    timeout: int = 180,
) -> None:
    """Install slack-mcp-server on `hostname` via the dedicated runbook.

    Gated on: at least one `slack-user` or `slack-cookie` integration
    in `inputs.integrations`. When no slack integration is attached,
    this is a fast no-op — no SSH, no ansible-runner spawn.

    Dispatches per `host.get("os_family")`: darwin picks the
    `install_slack_mcp_macos.yaml` sibling. All other values (including
    the empty / missing case) fall through to the Linux runbook, which
    is safe because Linux is the fleet default and the runbook itself
    guards with `ansible_os_family == "Darwin"` at task-0.

    Raises `CanonicalSyncError` on any playbook failure so
    `sync_agent_canonical` short-circuits before `_restart_unit`. The
    daemon is never restarted with a rendered config pointing at a
    binary that failed to land.
    """
    if not any(i.type in _HERMES_SLACK_TYPES for i in inputs.integrations):
        return

    # Lazy import to sidestep the lifecycle ↔ lifecycle_canonical cycle
    # that a top-level `from clawrium.core.lifecycle import ...` would
    # trigger during module init on Python 3.13+.
    from clawrium.core.lifecycle import _run_lifecycle_playbook

    os_family = str(host.get("os_family") or "linux").strip().lower()
    if os_family in ("mac", "macos", "osx"):
        os_family = "darwin"
    operation = (
        "install_slack_mcp_macos" if os_family == "darwin" else "install_slack_mcp"
    )

    if on_event is not None:
        on_event(
            "slack_mcp_install",
            f"installing slack-mcp-server for {agent_name} via {operation}.yaml",
        )

    success, err = _run_lifecycle_playbook(
        agent_type="hermes",
        agent_name=agent_name,
        hostname=hostname,
        operation=operation,
        host=host,
        timeout=timeout,
    )
    if not success:
        # The playbook is single-purpose so any failure is a real
        # install error (arch guard, download failure, checksum
        # mismatch, permissions). Preserve the ansible-runner
        # summary — it names the failed task.
        raise CanonicalSyncError(
            f"slack-mcp-server install failed for {agent_name!r}: {err}"
        )


# #835: openclaw slack MCP subprocess installer. Sibling of the hermes
# helper directly above — same binary, same version pin, same runbook
# shape; separate helper because `_run_lifecycle_playbook` resolves the
# runbook path under `platform/registry/<agent_type>/playbooks/`, so a
# hermes-scoped call cannot reach `openclaw/playbooks/install_slack_mcp.yaml`.
# The one-runbook-per-(agent_type, binary) contract is Rule 1 of the
# "Integration Binary Install" architectural pattern in AGENTS.md.
_OPENCLAW_SLACK_TYPES = frozenset({"slack-user", "slack-cookie"})


def _openclaw_install_slack_mcp(
    agent_name: str,
    hostname: str,
    host: dict,
    inputs,
    *,
    on_event: Callable[[str, str], None] | None = None,
    timeout: int = 180,
) -> None:
    """Install slack-mcp-server on `hostname` via the openclaw runbook.

    Structural mirror of `_hermes_install_slack_mcp` above — the only
    difference is the `agent_type="openclaw"` argument threaded into
    `_run_lifecycle_playbook`, which routes the runbook lookup to
    `platform/registry/openclaw/playbooks/install_slack_mcp[_macos].yaml`.

    Gated on: at least one `slack-user` or `slack-cookie` integration
    in `inputs.integrations`. When no slack integration is attached,
    this is a fast no-op — no SSH, no ansible-runner spawn.

    Dispatches per `host.get("os_family")`: darwin picks the
    `install_slack_mcp_macos.yaml` sibling. All other values (including
    the empty / missing case) fall through to the Linux runbook, which
    is safe because Linux is the fleet default and the runbook itself
    guards with `ansible_os_family == "Darwin"` at task-0.

    Raises `CanonicalSyncError` on any playbook failure so
    `sync_agent_canonical` short-circuits before `_restart_unit`. The
    daemon is never restarted with a rendered openclaw.json pointing at
    a `mcp.servers.<slug>.command` path whose binary failed to land.
    """
    if not any(i.type in _OPENCLAW_SLACK_TYPES for i in inputs.integrations):
        return

    # Lazy import to sidestep the lifecycle ↔ lifecycle_canonical cycle
    # (same rationale as the hermes helper above).
    from clawrium.core.lifecycle import _run_lifecycle_playbook

    os_family = str(host.get("os_family") or "linux").strip().lower()
    if os_family in ("mac", "macos", "osx"):
        os_family = "darwin"
    operation = (
        "install_slack_mcp_macos" if os_family == "darwin" else "install_slack_mcp"
    )

    if on_event is not None:
        on_event(
            "slack_mcp_install",
            f"installing slack-mcp-server for {agent_name} via openclaw/{operation}.yaml",
        )

    success, err = _run_lifecycle_playbook(
        agent_type="openclaw",
        agent_name=agent_name,
        hostname=hostname,
        operation=operation,
        host=host,
        timeout=timeout,
    )
    if not success:
        # Single-purpose runbook — any failure is a real install error.
        raise CanonicalSyncError(
            f"slack-mcp-server install failed for {agent_name!r}: {err}"
        )


# #851: zeroclaw slack MCP subprocess installer. Sibling of the hermes
# and openclaw helpers above — same binary, same version pin, same
# runbook shape; separate helper because `_run_lifecycle_playbook`
# resolves the runbook path under `platform/registry/<agent_type>/
# playbooks/`, so a hermes- or openclaw-scoped call cannot reach
# `zeroclaw/playbooks/install_slack_mcp.yaml`. The one-runbook-per-
# (agent_type, binary) contract is Rule 1 of the "Integration Binary
# Install" architectural pattern in AGENTS.md.
#
# Harmonizes zeroclaw with hermes (Phase 1 of #499) and openclaw
# (Phase 2 of #499). Before #851, zeroclaw slack install ran inline
# in `configure.yaml`; the CHANGELOG for Phase 3 already documented
# the runbook pattern as the shipped shape, but the code had drifted
# to an inline install during the stacked-merge recovery of PR #842.
_ZEROCLAW_SLACK_TYPES = frozenset({"slack-user", "slack-cookie"})


def _zeroclaw_install_slack_mcp(
    agent_name: str,
    hostname: str,
    host: dict,
    inputs,
    *,
    on_event: Callable[[str, str], None] | None = None,
    timeout: int = 180,
) -> None:
    """Install slack-mcp-server on `hostname` via the zeroclaw runbook.

    Structural mirror of `_openclaw_install_slack_mcp` above — the two
    differences are the `agent_type="zeroclaw"` argument threaded into
    `_run_lifecycle_playbook` (routes the runbook lookup to
    `platform/registry/zeroclaw/playbooks/install_slack_mcp.yaml`) and
    the darwin refusal — no `install_slack_mcp_macos.yaml` sibling
    exists yet, so macOS zeroclaw slack is a deferred follow-up per
    #836. Refuse loudly on darwin rather than silently routing to the
    Linux runbook (which the runbook's own task-0 guard would reject
    with a less operator-friendly message).

    Gated on: at least one `slack-user` or `slack-cookie` integration
    in `inputs.integrations`. When no slack integration is attached,
    this is a fast no-op — no SSH, no ansible-runner spawn.

    Positioned in `sync_agent_canonical` BEFORE the file-write loop
    AND before `_zeroclaw_repair_after_start` (bearer rotation) so:
    1. A slack install failure short-circuits the sync before the
       gateway re-pair rotates the bearer (#437 stale-bearer
       regression guard — the S9/W2 sync-ordering invariant).
    2. The freshly-installed binary and the freshly-rendered
       config.toml land in a single daemon restart.

    Raises `CanonicalSyncError` on any playbook failure so
    `sync_agent_canonical` short-circuits before `_restart_unit`. The
    daemon is never restarted with a rendered config.toml pointing at
    a `[[mcp.servers]].command` path whose binary failed to land.
    """
    if not any(i.type in _ZEROCLAW_SLACK_TYPES for i in inputs.integrations):
        return

    # macOS zeroclaw slack is not yet supported — the runbook has no
    # darwin sibling. Refuse loudly rather than silently routing to
    # the Linux runbook (which the runbook's own task-0 guard would
    # reject on darwin anyway, but with a less operator-friendly
    # message).
    os_family = str(host.get("os_family") or "linux").strip().lower()
    if os_family in ("mac", "macos", "osx"):
        os_family = "darwin"
    if os_family == "darwin":
        raise CanonicalSyncError(
            f"zeroclaw slack integration is not yet supported on darwin "
            f"hosts (agent {agent_name!r}); the "
            f"`install_slack_mcp_macos.yaml` sibling runbook is a "
            f"follow-up to #836. Detach the slack integration or move "
            f"the agent to a Linux host."
        )

    # Lazy import to sidestep the lifecycle ↔ lifecycle_canonical cycle
    # (same rationale as the hermes / openclaw helpers above).
    from clawrium.core.lifecycle import _run_lifecycle_playbook

    if on_event is not None:
        on_event(
            "slack_mcp_install",
            f"installing slack-mcp-server for {agent_name} via zeroclaw/install_slack_mcp.yaml",
        )

    success, err = _run_lifecycle_playbook(
        agent_type="zeroclaw",
        agent_name=agent_name,
        hostname=hostname,
        operation="install_slack_mcp",
        host=host,
        timeout=timeout,
    )
    if not success:
        # Single-purpose runbook — any failure is a real install error.
        raise CanonicalSyncError(
            f"slack-mcp-server install failed for {agent_name!r}: {err}"
        )


def sync_agent_canonical(
    agent_name: str,
    *,
    force: bool = False,
    restart: bool = True,
    verify: bool = True,
    push_workspace: bool = True,
    workspace_only: bool = False,
    dry_run: bool = False,
    on_event: Callable[[str, str], None] | None = None,
) -> CanonicalSyncResult:
    """Sync `agent_name` via the canonical pipeline.

    Args:
        agent_name: The agent instance name (as recorded in hosts.json).
        force: Allow writes that remove a host-side secret line. Without
            this, `SecretRemovalRefused` is raised before any host write.
        restart: When True (default), restart the agent's systemd unit
            after writes. When False, files are written but the running
            process keeps its old config until the next restart — useful
            for an operator who wants to stage changes without flapping
            the agent.
        verify: When True (default), assert the unit is `active` after
            restart. Implies `restart=True` — verify without restart is
            a noop. Pass False to skip post-restart polling.
        on_event: Callback `(stage, message)` for progress streaming.

    Raises:
        AgentConfigError: from build_render_inputs (missing attachment)
        CanonicalSyncError / SecretRemovalRefused: pipeline failure
        RemoteReadError: SSH probe failed in a way the operator must see
    """

    def emit(stage: str, message: str) -> None:
        if on_event is not None:
            on_event(stage, message)
        logger.info("[%s] %s", stage, message)

    emit("validate", f"assembling render inputs for {agent_name}")
    inputs = build_render_inputs(agent_name)

    renderer = _RENDERERS.get(inputs.agent_type)
    if renderer is None:
        raise CanonicalSyncError(
            f"no canonical renderer for agent type {inputs.agent_type!r}"
        )

    resolved = get_agent_by_name(agent_name)
    if resolved is None:
        raise CanonicalSyncError(
            f"agent {agent_name!r} not found in hosts.json"
        )
    host, agent_key, _claw_record = resolved
    hostname = host.get("hostname", "")

    # Issue #810 — refuse sync on an incomplete installation
    # (local-only check, cheap; runs BEFORE the SSH probe so a
    # half-installed record short-circuits without paying the
    # round-trip cost).
    #
    # A `clawctl agent create` that failed mid-playbook leaves the
    # record at `status="failed", installed_at=None` while preserving
    # any attachments accumulated before the failure. The downstream
    # version-gate (e.g. brave plugin's minHostVersion at line ~1245)
    # then trips against the *broken* on-host binary, suggesting
    # `clawctl agent upgrade` — which itself trips the
    # `clawctl_upgrade_strips_attachments` class. The operator is
    # forced to manually `integration detach` to unblock, even though
    # they never asked to detach.
    #
    # Short-circuit here, before SSH/render, with a clear hint at the
    # actual repair path (`clawctl agent create <name> --type <type>
    # --host <host> --cleanup-failed`, see `cli/clawctl/agent/create.py`
    # and `core/install.py:449` for the status=='failed' retry branch).
    # The hint deliberately avoids `clawctl agent upgrade` so we don't
    # cascade into the `clawctl_upgrade_strips_attachments` class. The
    # empty `_claw_record` shape ({}) used by legacy / pre-status
    # records MUST pass through unchanged, so the second clause
    # requires `status is not None`.
    #
    # Not a #437 anti-pattern: the gateway-bearer-rotation invariant
    # applies to lifecycle ops that touch a *running* daemon. The
    # record we are refusing here has `installed_at=None` — there is
    # no daemon to drift out of sync with, so skipping the rotation
    # cannot strand a remote chat session on a stale bearer.
    install_status = _claw_record.get("status")
    installed_at = _claw_record.get("installed_at")
    install_incomplete = install_status in {"failed", "installing"} or (
        install_status is not None and installed_at is None
    )
    if install_incomplete:
        recovery_hint = (
            f"clawctl agent create {agent_name} "
            f"--type {inputs.agent_type} --host {hostname} "
            f"--cleanup-failed"
        )
        raise CanonicalSyncError(
            f"agent {agent_name!r} on {hostname!r} has an incomplete "
            f"installation (status={install_status!r}, "
            f"installed_at={installed_at!r}); refusing to sync. Run "
            f"`{recovery_hint}` to finish the install first — your "
            f"attachments are preserved."
        )

    # Issue #811: validate-phase host probe.
    #
    # Even when the local record looks complete (status='installed',
    # installed_at populated — passes the #810 guard above), the
    # actual on-host install can still be gone (e.g. operator
    # manually removed the systemd unit, host re-imaged, etc.).
    # Before this probe, sync ran render + diff + write + workspace
    # push and only then discovered the missing unit — at
    # `_restart_unit`, which surfaced as the opaque
    # `Unit ...service not found. (exit 5)` shape on the original
    # wolf-i baseline. The probe runs one SSH round-trip BEFORE render
    # to detect that wedge up-front and route the operator to the
    # `clawctl agent delete` + `clawctl agent create` reinstall flow,
    # so:
    #
    # - no half-rendered files land on a host that can't restart them
    # - zeroclaw bearer rotation never fires against a missing daemon
    # - the workspace-only branch (below) also short-circuits, since
    #   pushing an operator overlay onto an uninstalled agent is the
    #   same wedge in a different costume
    # - dry-run pays the probe cost too: a dry-run that "would change
    #   N files" against a missing unit is misleading, and the probe
    #   is cheap enough that paying it on inspection runs is the right
    #   trade.
    #
    # OS-routing for the probe lives entirely inside `probe_host_install`
    # / `unit_path_for`; this call site stays OS-agnostic per the
    # dispatcher-only OS-fork invariant.
    emit("validate", f"checking host install for {agent_name}")
    probe_client = _open_ssh(host)
    try:
        probe = probe_host_install(
            probe_client,
            agent_type=inputs.agent_type,
            agent_name=agent_name,
            host=host,
        )
    finally:
        probe_client.close()
    if not probe.ok:
        # ATX iter-5 B1: there is no `clawctl agent install` verb —
        # the install path is `agent create`. ATX iter-5 W3: align
        # phrasing on the `refusing to sync` wording the sibling
        # `SecretRemovalRefused` already uses.
        host_alias = host.get("alias") or host.get("hostname") or ""
        raise AgentInstallMissingError(
            f"refusing to sync {agent_name!r}: on-host install is "
            f"incomplete (missing {probe.missing_summary()}). "
            f"Recover with `clawctl agent delete {agent_name}` "
            f"then `clawctl agent create {agent_name} "
            f"--type {inputs.agent_type} --host {host_alias}`, "
            f"or `clawctl agent doctor {agent_name}` for diagnosis."
        )

    # Issue #760 §1.4 `--workspace-only` short-circuit. Skip canonical
    # render / diff / write / restart / verify entirely; push the
    # operator overlay and (for zeroclaw, in later phases) rotate the
    # bearer. State transition is intentionally NOT executed
    # (W5 iter-3): workspace-only preserves the current lifecycle
    # position so an operator may overlay onto a STOPPED agent without
    # silently flipping it to READY.
    if workspace_only:
        from clawrium.core.workspace_sync import push_workspace_phase

        def _ws_event(stage: str, payload: dict) -> None:
            if on_event is None:
                return
            import json as _json

            on_event(stage, _json.dumps(payload))

        ws_result = push_workspace_phase(
            host=host,
            agent_type=inputs.agent_type,
            agent_name=agent_name,
            on_event=_ws_event,
            dry_run=dry_run,
        )
        if not ws_result.success:
            # ATX iter-2 B1-NEW: raise rather than return
            # `CanonicalSyncResult(success=False)`. The CLI only catches
            # raised exceptions — returning a falsy result falls through
            # to `synced (drift=0)` with exit 0, violating the AGENTS.md
            # short-circuit contract. Symmetric with the in-loop path
            # below.
            raise CanonicalSyncError(
                f"workspace overlay push failed for {agent_name!r}: "
                f"{ws_result.error}"
            )

        # Issue #760 Phase 2 (#768) — bearer rotation invariant.
        # AGENTS.md "Gateway Token Lifecycle (zeroclaw)" is explicit:
        # `configure` / `sync` / `restart` MUST mint a fresh bearer and
        # overwrite `hosts.json.gateway.auth` on every call. There is no
        # idempotent-skip path; an out-of-sync `auth` field is the bug
        # we are guarding against (#437). `--workspace-only` is just
        # another sync entry point and is bound by the same contract.
        #
        # Dry-run gate (W6 iter-3): when the CLI passes `dry_run=True`
        # we MUST NOT mint a bearer or emit `gateway_token_rotated` —
        # the operator asked for an inspection, not a rotation. The CLI
        # short-circuits before reaching this branch today (an early
        # return at sync.py:396), but the gate here is defense-in-depth
        # against any future programmatic caller that passes `dry_run`
        # alongside `workspace_only`.
        if inputs.agent_type == "zeroclaw" and not dry_run:
            from clawrium.core.lifecycle import _zeroclaw_repair_after_start

            emit(
                "repair",
                f"re-pairing zeroclaw gateway for {agent_name} "
                f"(workspace-only sync)",
            )
            # iter-1 lifecycle-core S5: pass a distinct `reason` so
            # post-mortem analysis can grep `gateway_token_rotated`
            # events by entry point (workspace-only-sync vs default
            # sync vs restart).
            repair_ok, repair_err = _zeroclaw_repair_after_start(
                hostname,
                agent_name=agent_name,
                on_event=on_event,
                reason="workspace-only-sync",
            )
            if not repair_ok:
                # Workspace push already landed on host; the daemon
                # state is intact and the only fallout is that
                # `hosts.json.gateway.auth` may now lag behind whatever
                # bearer the daemon will enforce on the next request.
                # That's the W11 stale-bearer case — surface it as a
                # structured event before raising so the operator has a
                # diagnostic instead of a silent 401 storm on the next
                # `clawctl agent chat`.
                if on_event is not None:
                    import json as _json

                    on_event(
                        "gateway_auth_stale",
                        _json.dumps(
                            {
                                "agent_key": agent_name,
                                "reason": "workspace-only re-pair failed",
                                "detail": repair_err or "",
                            }
                        ),
                    )
                # iter-1 lifecycle-core W2: tightened remediation — a
                # deterministic pair failure (port-bind issue, dead
                # daemon) will repeat on a plain sync. `restart` first
                # is more likely to recover; `doctor` is the fallback
                # diagnostic.
                raise CanonicalSyncError(
                    f"workspace-only sync wrote overlay for {agent_name!r} "
                    f"but the gateway re-pair failed: {repair_err}. "
                    f"`clawctl agent chat` will return 401 until the "
                    f"bearer rotates. Run `clawctl agent restart "
                    f"{agent_name}` to recover; if that fails, "
                    f"`clawctl agent doctor {agent_name}` for "
                    f"diagnosis."
                )

        emit(
            "sync",
            f"workspace-only sync of {agent_name}: "
            f"{len(ws_result.files_pushed)} pushed, "
            f"{len(ws_result.files_excluded)} excluded",
        )
        return CanonicalSyncResult(
            success=True,
            agent=agent_name,
            host=hostname,
            files_written=(),
            files_unchanged=(),
            diffs=(),
            error=None,
            workspace_files_pushed=ws_result.files_pushed,
            workspace_files_excluded=ws_result.files_excluded,
        )

    emit("render", f"rendering canonical config for {inputs.agent_type}")
    # #835 (ATX iter-1 W1 → iter-2 W1 tightened): thread os_family into
    # hermes/openclaw renderers so `clawctl agent sync` produces the
    # same binary paths `configure` does on darwin. Test stubs across
    # `test_lifecycle_canonical.py`, `test_workspace_*`, and
    # `test_sync.py` accept `**_kw` — no TypeError shim, so any future
    # stub that drops kwarg support fails loudly instead of silently
    # falling back to a linux-only render (the iter-2 reviewer flagged
    # the shim as silencing a programming-error class).
    from clawrium.core.playbook_resolver import normalize_os_family

    _os_family = normalize_os_family(host)
    if inputs.agent_type in ("hermes", "openclaw", "zeroclaw"):
        rendered = renderer(inputs, os_family=_os_family)
    else:
        rendered = renderer(inputs)

    emit("diff", f"reading on-host files from {hostname}")
    diffs = diff_files(
        host=host, agent_name=agent_name, rendered_files=rendered.files
    )

    # Secret-removal guard. See module docstring; this is the single
    # behavior #555 added that the legacy path lacks.
    refused: dict[str, set[str]] = {}
    for d in diffs:
        if not d.unified_diff:
            continue
        missing = _diff_removes_secrets(d)
        if missing:
            refused[d.path] = missing
    if refused and not force:
        details = "; ".join(
            f"{path}: would remove {sorted(keys)}"
            for path, keys in sorted(refused.items())
        )
        raise SecretRemovalRefused(
            f"refusing to sync {agent_name!r}: rendered body removes "
            f"host-side secrets ({details}). Inspect with `clawctl "
            f"agent sync {agent_name} --dry-run --diff`. Recovery: "
            f"re-attach the channel/integration that owns the missing "
            f"secret, or restore it via `clawctl secret set ...`."
        )

    files_written: list[str] = []
    files_unchanged: list[str] = []

    client = _open_ssh(host)
    try:
        # #734 openclaw brave plugin enforces a minHostVersion floor
        # (sourced from `plugins.brave.min_host_version` in the
        # openclaw manifest — do not duplicate the literal here, the
        # manifest is the single source of truth). We check on the
        # live host (not on hosts.json cached state) because
        # an operator may have upgraded out-of-band since the last
        # `clawctl agent get` and we'd otherwise reject a now-valid host.
        # Done after `_open_ssh` so the connect/auth errors surface with
        # their normal messages instead of getting swallowed by the
        # preflight error formatting.
        if inputs.agent_type == "openclaw" and any(
            i.type == "brave" for i in inputs.integrations
        ):
            pin = _load_openclaw_brave_pin()
            min_ver = pin["min_host_version"]
            version, probe_stderr = _get_host_openclaw_version(
                client,
                agent_name,
                os_family=host.get("os_family", "linux"),
            )
            min_str = ".".join(str(p) for p in min_ver)
            if version is None:
                # Binary missing or unparseable — distinct hint from
                # "version too old": install vs upgrade (W9 ATX iter 1).
                # `probe_stderr` surfaces sudo failures, safelist
                # rejections, or PATH-resolution errors so the operator
                # has a starting point beyond <unknown>.
                detail = f" stderr: {probe_stderr}" if probe_stderr else ""
                raise CanonicalSyncError(
                    f"openclaw on {hostname!r} is <unknown> "
                    f"(binary missing or `--version` unparseable); brave "
                    f"plugin requires >= {min_str}. Run "
                    f"`clawctl agent install {agent_name}` first.{detail}"
                )
            if version < min_ver:
                actual = ".".join(str(p) for p in version)
                raise CanonicalSyncError(
                    f"openclaw on {hostname!r} is {actual}; brave plugin "
                    f"requires >= {min_str}. Run "
                    f"`clawctl agent upgrade {agent_name}` first."
                )
            emit(
                "brave_integration_configured",
                f"openclaw {'.'.join(str(p) for p in version)} on {hostname} "
                f"satisfies brave plugin min version",
            )

        # #755: openclaw plugin install — moved out of configure.yaml so
        # `clawctl agent integration attach <brave>` + `clawctl agent
        # sync` actually materializes the plugin on host (operator's
        # mental model: sync flushes EVERYTHING the control plane has
        # declared). Runs BEFORE the file-write loop so the daemon picks
        # up both the new plugin AND a freshly-rendered env carrying its
        # credential in a single restart. A failure here raises
        # CanonicalSyncError and short-circuits before `_restart_unit`,
        # mirroring the workspace-overlay phase: never restart the unit
        # on a half-installed plugin set.
        if inputs.agent_type == "openclaw":
            _openclaw_install_plugins(
                client,
                agent_name,
                os_family=host.get("os_family", "linux"),
                inputs=inputs,
                on_event=on_event,
            )

        # #834: hermes integration-binary install phase. Same slot as
        # openclaw plugins above — runs BEFORE the file-write loop so
        # a freshly-rendered config.yaml AND a freshly-installed binary
        # land in a single daemon restart. Failure raises
        # `CanonicalSyncError` and short-circuits before
        # `_restart_unit`; the daemon is never restarted with a config
        # pointing at a binary that failed to install. Fast no-op when
        # no slack integration is attached.
        if inputs.agent_type == "hermes":
            _hermes_install_slack_mcp(
                agent_name,
                hostname,
                host,
                inputs,
                on_event=on_event,
            )

        # #835: openclaw slack-mcp-server install. Same slot + same
        # short-circuit contract as the hermes helper above; separate
        # entry-point because the runbook lookup is agent-type-scoped
        # (`platform/registry/openclaw/playbooks/install_slack_mcp*.yaml`).
        # Fast no-op when no slack integration is attached.
        if inputs.agent_type == "openclaw":
            _openclaw_install_slack_mcp(
                agent_name,
                hostname,
                host,
                inputs,
                on_event=on_event,
            )

        # #851: zeroclaw slack-mcp-server install. Same slot + same
        # short-circuit contract as the hermes and openclaw helpers
        # above; separate entry-point because the runbook lookup is
        # agent-type-scoped
        # (`platform/registry/zeroclaw/playbooks/install_slack_mcp.yaml`).
        # Fast no-op when no slack integration is attached. Positioned
        # BEFORE the file-write loop AND before the trailing zeroclaw
        # `_zeroclaw_repair_after_start` bearer rotation (line 2175
        # region), so a slack install failure short-circuits the sync
        # before the bearer is re-minted and hosts.json.gateway.auth
        # desyncs from the daemon (#437 stale-bearer regression guard;
        # S9/W2 sync-ordering invariant). Harmonizes zeroclaw with the
        # runbook pattern that Phase 3 CHANGELOG documented but the
        # inline configure.yaml install had drifted from.
        if inputs.agent_type == "zeroclaw":
            _zeroclaw_install_slack_mcp(
                agent_name,
                hostname,
                host,
                inputs,
                on_event=on_event,
            )

        for d in diffs:
            if not d.unified_diff:
                files_unchanged.append(d.path)
                continue
            emit("write", f"writing {d.remote_path}")
            _atomic_write(
                client,
                agent_name=agent_name,
                remote_path=d.remote_path,
                body=d.rendered_body,
                host=host,
            )
            files_written.append(d.path)

        # Issue #760 §1.4 phase 3: push operator workspace overlay.
        # Runs between the canonical write loop and restart so the
        # daemon picks up both canonical config drift AND operator
        # overlay drift in a single restart. Failure here MUST
        # short-circuit before restart (W2 iter-1, I8 frozen-enum
        # payload check) — restarting on a half-applied overlay is the
        # regression class iter-2 protected.
        workspace_files_pushed_t: tuple[str, ...] = ()
        workspace_files_excluded_t: tuple[str, ...] = ()
        if push_workspace:
            from clawrium.core.workspace_sync import push_workspace_phase

            def _ws_event(stage: str, payload: dict) -> None:
                if on_event is None:
                    return
                import json as _json

                on_event(stage, _json.dumps(payload))

            ws_result = push_workspace_phase(
                host=host,
                agent_type=inputs.agent_type,
                agent_name=agent_name,
                on_event=_ws_event,
                dry_run=dry_run,
            )
            workspace_files_pushed_t = ws_result.files_pushed
            workspace_files_excluded_t = ws_result.files_excluded
            if not ws_result.success:
                raise CanonicalSyncError(
                    f"workspace overlay push failed for {agent_name!r}: "
                    f"{ws_result.error}. Skipping restart to avoid "
                    f"flapping the unit on a half-applied overlay."
                )

        # Restart policy:
        #
        # - zeroclaw MUST restart on every sync regardless of
        #   `files_written`, so the gateway bearer rotation downstream
        #   (issue #437, see B1 comment below) runs every time. The
        #   AGENTS.md "Gateway Token Lifecycle (zeroclaw)" section is
        #   explicit: "There is no idempotent-skip path." A no-drift
        #   sync that skipped restart would leave `hosts.json.gateway.auth`
        #   permanently stale after any external daemon restart (host
        #   reboot, `systemctl restart`, etc.).
        # - Other agent types (hermes, openclaw) keep the file-drift-gated
        #   restart so a true no-op sync stays cheap.
        # W-D (ATX #555 polish round 4): renamed from
        # `zeroclaw_force_restart` — the re-pair runs unconditionally
        # (B1 round-3); this flag specifically tracks the "no
        # file-drift but zeroclaw still needs a systemctl restart for
        # bearer rotation to take effect" sub-case.
        zeroclaw_needs_force_restart = (
            restart and inputs.agent_type == "zeroclaw" and not files_written
        )
        if restart and (files_written or zeroclaw_needs_force_restart):
            if zeroclaw_needs_force_restart:
                emit(
                    "restart",
                    f"restarting {inputs.agent_type}-{agent_name}.service "
                    f"(no drift; zeroclaw bearer rotation requires restart)",
                )
            else:
                emit(
                    "restart",
                    f"restarting {inputs.agent_type}-{agent_name}.service",
                )
            _restart_unit(
                client,
                agent_type=inputs.agent_type,
                agent_name=agent_name,
                host=host,
                on_event=on_event,
            )
            if verify:
                emit("verify", "checking unit is active")
                gateway_port = (
                    ((host.get("agents") or {}).get(agent_name) or {})
                    .get("config", {})
                    .get("gateway", {})
                    .get("port")
                )
                _verify_health(
                    client,
                    agent_type=inputs.agent_type,
                    agent_name=agent_name,
                    host=host,
                    gateway_port=gateway_port,
                    on_event=on_event,
                )
        elif restart and not files_written:
            emit("restart", "skipped (no files changed)")
    finally:
        client.close()

    # B1 (#437, ATX #555 polish round 3): zeroclaw daemon does not
    # persist bearer state across systemd restarts. AGENTS.md "Gateway
    # Token Lifecycle (zeroclaw)" is explicit: "clawctl agent
    # configure, clawctl agent sync, and clawctl agent restart all
    # mint a fresh bearer and overwrite hosts.json.gateway.auth
    # atomically. There is no idempotent-skip path. Do not add a
    # --no-rotate flag — branching here is the bug the original ATX
    # Round 1 B3 code introduced." Re-pair unconditionally on every
    # zeroclaw sync regardless of `restart`. The pair playbook is the
    # single source of truth for the handshake.
    #
    # Issue #760 Phase 2 (#768): the same `--no-restart` path lands
    # here too — the bearer rotates even when the operator asked to
    # skip the systemd restart, because (per AGENTS.md) any externally-
    # triggered daemon restart (host reboot, ops-driven `systemctl
    # restart`) will have already invalidated the on-disk bearer.
    # Dry-run gate (W6 iter-3): defense-in-depth against any future
    # programmatic caller that passes `dry_run` into this layer (the
    # CLI short-circuits before reaching here today).
    if inputs.agent_type == "zeroclaw" and not dry_run:
        from clawrium.core.lifecycle import _zeroclaw_repair_after_start

        emit("repair", f"re-pairing zeroclaw gateway for {agent_name}")
        repair_ok, repair_err = _zeroclaw_repair_after_start(
            hostname,
            agent_name=agent_name,
            on_event=on_event,
            reason="sync",
        )
        if not repair_ok:
            # W11 iter-3 stale-bearer banner: restart + verify already
            # completed when applicable; in --no-restart mode any prior
            # external restart already invalidated the on-disk bearer
            # and the re-pair was the recovery path. Either way the
            # disk-side `hosts.json.gateway.auth` may now lag whatever
            # bearer the daemon enforces on the next request — surface
            # the divergence as a structured NDJSON event before
            # raising so operators get a starting point instead of
            # chasing silent 401s on the next `clawctl agent chat`.
            # (iter-1 lifecycle-core W1: corrected from the misleading
            # "restart + verify succeeded above" wording.)
            if on_event is not None:
                import json as _json

                on_event(
                    "gateway_auth_stale",
                    _json.dumps(
                        {
                            "agent_key": agent_name,
                            "reason": "sync re-pair failed",
                            "detail": repair_err or "",
                        }
                    ),
                )
            # iter-1 lifecycle-core W2: tightened remediation — see the
            # workspace-only branch comment for rationale.
            # iter-2 lifecycle-core W3: branch the preamble on `restart`
            # so the message does not claim a restart that did not run
            # in --no-restart mode (operators would otherwise look for
            # systemctl evidence of a restart that never happened).
            if restart:
                preamble = (
                    f"sync wrote and restarted {agent_name!r}"
                )
            else:
                preamble = (
                    f"sync of {agent_name!r} (restart skipped)"
                )
            raise CanonicalSyncError(
                f"{preamble} but the gateway re-pair failed: "
                f"{repair_err}. `clawctl agent chat` will return 401 "
                f"until the bearer rotates. Run `clawctl agent restart "
                f"{agent_name}` to recover; if that fails, "
                f"`clawctl agent doctor {agent_name}` for diagnosis."
            )

    # B2: advance the onboarding state machine to READY so
    # `start_agent` (which gates on state == READY) accepts the agent
    # after a sync. Mirrors lifecycle.py:1386-1438's post-configure
    # transition contract. The three exception shapes have distinct
    # remediations:
    #   - InvalidTransitionError: mid-walk (PROVIDERS/IDENTITY/...);
    #     sync cannot bypass the stage walk. Silent — start_agent
    #     surfaces the non-READY state.
    #   - AgentNotFoundError / OnboardingNotFoundError: registry
    #     incoherence; surfacing via emit() rather than raise because
    #     the host-side write already succeeded.
    #   - Anything else (IO, permission): same — surface as warning,
    #     don't fail the sync.
    from clawrium.core.onboarding import (
        AgentNotFoundError as _ANF,
        InvalidTransitionError as _ITE,
        OnboardingNotFoundError as _ONF,
        OnboardingState as _OS,
        transition_state as _transition,
    )

    # B1 (ATX #555 polish): surface state-write failures on the result.
    # Host-side write + bearer re-pair already succeeded; the sync is
    # not a hard failure, but `start_agent` gates on state == READY so
    # without a populated `error` field the operator sees `success=True`
    # with a stuck non-READY agent and no diagnostic. W1 (ATX #555
    # polish): emit on the `_ITE` branch too — mid-walk agents previously
    # produced a clean success line followed by an unexplained failure
    # from `start_agent`.
    # B2 (ATX #555 polish round 3): only the InvalidTransitionError
    # branch represents "expected, non-fatal" — the agent is mid-walk
    # and start_agent will surface the stage. Both registry-incoherence
    # and generic-exception branches set success=False so a CLI handler
    # gating on `.success` does not print "✓ sync complete" while the
    # agent is stuck in a non-READY state.
    transition_error: str | None = None
    state_write_ok = True
    try:
        _transition(hostname, agent_key, _OS.READY)
    except _ITE as exc:
        emit(
            "sync",
            f"note: skipped state=READY transition for {agent_key} "
            f"(agent is mid-walk: {exc!s}). `clawctl agent start` will "
            f"surface the current onboarding stage.",
        )
    except (_ANF, _ONF) as exc:
        transition_error = (
            f"registry record missing for {agent_key} after sync: "
            f"{exc!s}. Inspect hosts.json before running "
            f"clawctl agent start."
        )
        emit("sync", f"warning: {transition_error}")
        state_write_ok = False
    except Exception as exc:
        transition_error = (
            f"could not write state=READY to hosts.json: {exc!s}. "
            f"Re-run sync to commit state."
        )
        emit("sync", f"warning: {transition_error}")
        state_write_ok = False

    emit(
        "sync",
        f"synced {agent_name}: {len(files_written)} written, "
        f"{len(files_unchanged)} unchanged",
    )
    return CanonicalSyncResult(
        success=state_write_ok,
        agent=agent_name,
        host=hostname,
        files_written=tuple(files_written),
        files_unchanged=tuple(files_unchanged),
        diffs=tuple(diffs),
        error=transition_error,
        workspace_files_pushed=workspace_files_pushed_t,
        workspace_files_excluded=workspace_files_excluded_t,
    )

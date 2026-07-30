"""`clawctl doctor nemoclaw` — read-only substrate probe.

Contract: verify the pinned ``clawrium.core.nemoclaw.NEMOCLAW_VERSION``
against live upstream and print a small table with four checks —
``reachable``, ``tag-exists``, ``correct-sha``, ``arch-match``. Exits
non-zero on any FAIL / UNKNOWN so CI + shell pipelines can gate on it.

The probe hits three endpoints:

- ``GET /repos/NVIDIA/NemoClaw`` — confirms the repo resolves.
- ``GET /repos/NVIDIA/NemoClaw/tags`` — confirms the pinned tag exists.
- ``GET raw.githubusercontent.com/.../install.sh`` — verifies the
  pinned ``INSTALL_SH_SHA256`` matches what upstream serves today.
  A mismatch means NVIDIA pushed a new install.sh under the tag (rare
  but possible for a moving branch ref like ``lkg``); operators must
  re-hash and bump.

NVIDIA does not publish binary release artifacts; the substrate installs
via ``install.sh`` (see ``core/nemoclaw.py`` module docstring and
``playbooks/install_nemoclaw.yaml``).
"""

from __future__ import annotations

import json
import platform
import urllib.error
import urllib.request
from typing import Any, Callable  # noqa: F401 — Callable kept for type hints on helpers

import typer

from clawrium.core import nemoclaw as _nemoclaw

__all__ = ["doctor_nemoclaw"]

_GITHUB_API = "https://api.github.com"
_USER_AGENT = "clawctl-doctor-nemoclaw/1"


def _default_fetch(url: str) -> dict[str, Any] | list[Any]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_fetch_bytes(url: str) -> bytes:
    """Raw-bytes fetch used by `_check_sha` for install.sh SHA verification.

    Distinct from `_default_fetch` (which decodes JSON) so the test-side
    monkeypatch swap for one endpoint does not mask the other.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()


def _current_arch() -> str:
    """Return normalized arch string matching SUPPORTED_ARCHES."""
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "aarch64"
    return m


def _check_reachable(fetch: Callable[[str], Any]) -> tuple[str, str]:
    try:
        payload = fetch(f"{_GITHUB_API}/repos/{_nemoclaw.UPSTREAM_REPO}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return "FAIL", f"unreachable: {e}"
    if isinstance(payload, dict) and payload.get("full_name") == _nemoclaw.UPSTREAM_REPO:
        return "PASS", f"{_nemoclaw.UPSTREAM_REPO} resolves"
    return "FAIL", f"unexpected payload for {_nemoclaw.UPSTREAM_REPO}"


def _check_tag_exists(fetch: Callable[[str], Any]) -> tuple[str, str]:
    try:
        payload = fetch(f"{_GITHUB_API}/repos/{_nemoclaw.UPSTREAM_REPO}/tags")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return "FAIL", f"tag-list fetch failed: {e}"
    if not isinstance(payload, list):
        return "FAIL", "tag-list response was not a JSON array"
    for entry in payload:
        if isinstance(entry, dict) and entry.get("name") == _nemoclaw.NEMOCLAW_VERSION:
            return "PASS", f"tag {_nemoclaw.NEMOCLAW_VERSION} present upstream"
    return "FAIL", f"tag {_nemoclaw.NEMOCLAW_VERSION} not found in first page of tags"


def _check_sha(fetch_bytes: Callable[[str], bytes] | None = None) -> tuple[str, str]:
    """Verify pinned INSTALL_SH_SHA256 against live upstream install.sh.

    Tests inject a stub bytes-fetcher via monkeypatch of
    ``_default_fetch_bytes`` on this module.
    """
    expected = _nemoclaw.INSTALL_SH_SHA256
    if not expected:
        return "UNKNOWN", "INSTALL_SH_SHA256 not pinned"
    if fetch_bytes is None:
        fetch_bytes = _default_fetch_bytes
    try:
        import hashlib

        raw = fetch_bytes(_nemoclaw.install_sh_url())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return "FAIL", f"install.sh fetch failed: {e}"
    actual = hashlib.sha256(raw).hexdigest()
    if actual == expected:
        return "PASS", f"install.sh sha256 matches ({actual[:12]}…)"
    return (
        "FAIL",
        f"install.sh sha256 drift: pin={expected[:12]}… "
        f"actual={actual[:12]}…",
    )


def _check_arch_match() -> tuple[str, str]:
    arch = _current_arch()
    if arch in _nemoclaw.SUPPORTED_ARCHES:
        return "PASS", f"local arch {arch} in {list(_nemoclaw.SUPPORTED_ARCHES)}"
    return (
        "FAIL",
        f"local arch {arch} not in SUPPORTED_ARCHES {list(_nemoclaw.SUPPORTED_ARCHES)}",
    )


def _print_row(check: str, status: str, detail: str) -> None:
    typer.echo(f"  {check:<14} {status:<8} {detail}")


def doctor_nemoclaw() -> None:
    """Run the four checks and print a pass/fail table.

    Tests inject a stub network fetch by
    ``monkeypatch.setattr(probe_mod, "_default_fetch", ...)`` — the
    module-level indirection avoids a ``Callable`` parameter on the
    Typer command (Typer cannot render it as a click option and refuses
    to load the entire app).
    """
    fetch = _default_fetch

    typer.echo(
        f"NemoClaw substrate probe (pin: {_nemoclaw.NEMOCLAW_VERSION}, "
        f"repo: {_nemoclaw.UPSTREAM_REPO})"
    )
    typer.echo("")
    typer.echo(f"  {'CHECK':<14} {'STATUS':<8} DETAIL")

    results: list[tuple[str, str, str]] = []
    for name, fn in (
        ("reachable", lambda: _check_reachable(fetch)),
        ("tag-exists", lambda: _check_tag_exists(fetch)),
        ("correct-sha", _check_sha),
        ("arch-match", _check_arch_match),
    ):
        status, detail = fn()
        _print_row(name, status, detail)
        results.append((name, status, detail))

    typer.echo("")
    if all(r[1] == "PASS" for r in results):
        typer.echo("All checks passed.")
        return
    failed = [r[0] for r in results if r[1] != "PASS"]
    typer.echo(f"Non-passing checks: {', '.join(failed)}")
    raise typer.Exit(code=1)

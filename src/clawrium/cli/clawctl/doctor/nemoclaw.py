"""`clawctl doctor nemoclaw` — Phase 1 read-only probe (issue #943).

Contract: fetch upstream release metadata for the pinned
``clawrium.core.nemoclaw.NEMOCLAW_VERSION`` and print a small table with
three checks — ``reachable``, ``correct-sha``, ``arch-match``. Exits
non-zero on any FAIL / UNKNOWN so CI + shell pipelines can gate on it.

The probe never downloads the tarball. It hits two endpoints only:

- ``GET /repos/NVIDIA/NemoClaw`` — confirms the repo resolves.
- ``GET /repos/NVIDIA/NemoClaw/tags`` — confirms the pinned tag exists.

Phase-1 pins ship with ``TARBALL_SHA256`` sentinels of ``None`` (the
tarball artefacts are frozen upstream during phase-2 release
preparation). Until then, ``correct-sha`` is reported as
``pending-upstream-freeze`` — the probe still fails so an operator does
not mistake it for green, but the message distinguishes "we haven't
frozen the SHA yet" from "the SHA drifted".
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


def _check_sha() -> tuple[str, str]:
    arch = _current_arch()
    expected = _nemoclaw.TARBALL_SHA256.get(arch)
    if arch not in _nemoclaw.SUPPORTED_ARCHES:
        return "FAIL", f"arch {arch!r} not in SUPPORTED_ARCHES"
    if expected is None:
        return "UNKNOWN", "pending-upstream-freeze"
    return "PASS", f"sha256 pinned for {arch}: {expected[:12]}…"


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

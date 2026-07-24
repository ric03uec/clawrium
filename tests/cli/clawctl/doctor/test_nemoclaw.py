"""Tests for `clawctl doctor nemoclaw` — Phase 1 of #11 / #943.

The probe is pure-local except for two GitHub API endpoints; we stub
the fetch callable so tests never hit the network.
"""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.doctor import nemoclaw as probe_mod
from clawrium.core import nemoclaw as nemoclaw_mod

runner = CliRunner()


def _fake_fetch_ok(url: str) -> Any:
    if url.endswith(f"/repos/{nemoclaw_mod.UPSTREAM_REPO}"):
        return {"full_name": nemoclaw_mod.UPSTREAM_REPO}
    if url.endswith(f"/repos/{nemoclaw_mod.UPSTREAM_REPO}/tags"):
        return [{"name": nemoclaw_mod.NEMOCLAW_VERSION}]
    raise AssertionError(f"unexpected url: {url}")


def _fake_fetch_repo_missing(url: str) -> Any:
    raise OSError("network down")


def _fake_fetch_tag_missing(url: str) -> Any:
    if url.endswith(f"/repos/{nemoclaw_mod.UPSTREAM_REPO}"):
        return {"full_name": nemoclaw_mod.UPSTREAM_REPO}
    if url.endswith("/tags"):
        return [{"name": "v0.0.1"}]
    raise AssertionError(f"unexpected url: {url}")


def test_doctor_pending_sha_fails_non_zero(monkeypatch):
    """Phase 1 pins ship with SHA=None → correct-sha is UNKNOWN
    → command must exit non-zero (green would falsely reassure
    operators before the upstream tarball is frozen)."""
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_ok)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1, result.output
    assert "reachable" in result.output
    assert "PASS" in result.output
    assert "tag-exists" in result.output
    assert "pending-upstream-freeze" in result.output
    assert "correct-sha" in result.output


def test_doctor_all_pass_when_sha_pinned(monkeypatch):
    """When SHA is pinned for the local arch, all four checks pass and
    the command exits 0."""
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setitem(nemoclaw_mod.TARBALL_SHA256, "x86_64", "a" * 64)
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_ok)
    try:
        result = runner.invoke(app, ["doctor", "nemoclaw"])
    finally:
        nemoclaw_mod.TARBALL_SHA256["x86_64"] = None
    assert result.exit_code == 0, result.output
    assert "All checks passed" in result.output


def test_doctor_unreachable_repo_fails(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_repo_missing)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "unreachable" in result.output


def test_doctor_missing_tag_fails(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_tag_missing)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_doctor_unsupported_arch_fails(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "riscv64")
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_ok)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1
    assert "arch-match" in result.output
    assert "SUPPORTED_ARCHES" in result.output


def test_tarball_url_rejects_unknown_arch():
    with pytest.raises(ValueError, match="unsupported arch"):
        nemoclaw_mod.tarball_url("riscv64")


def test_tarball_url_shape():
    url = nemoclaw_mod.tarball_url("x86_64")
    assert url.startswith("https://github.com/NVIDIA/NemoClaw/releases/download/")
    assert nemoclaw_mod.NEMOCLAW_VERSION in url
    assert "x86_64" in url

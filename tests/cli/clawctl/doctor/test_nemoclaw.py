"""Tests for `clawctl doctor nemoclaw`.

The probe hits GitHub API + raw.githubusercontent.com; we stub both
fetch callables so tests never hit the network.
"""

from __future__ import annotations

import hashlib
from typing import Any

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.doctor import nemoclaw as probe_mod
from clawrium.core import nemoclaw as nemoclaw_mod

runner = CliRunner()

_FAKE_INSTALL_SH_BYTES = b"#!/usr/bin/env bash\n# fake install.sh\n"
_FAKE_INSTALL_SH_SHA256 = hashlib.sha256(_FAKE_INSTALL_SH_BYTES).hexdigest()


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


def _fake_fetch_bytes_matching(url: str) -> bytes:
    assert url == nemoclaw_mod.install_sh_url()
    return _FAKE_INSTALL_SH_BYTES


def _fake_fetch_bytes_drift(url: str) -> bytes:
    return b"#!/usr/bin/env bash\n# tampered\n"


def _fake_fetch_bytes_fails(url: str) -> bytes:
    raise OSError("install.sh fetch failed")


def test_doctor_all_pass_when_install_sh_sha_matches(monkeypatch):
    """Happy path: repo reachable, tag exists, install.sh SHA matches
    the pin, arch supported → exit 0."""
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(nemoclaw_mod, "INSTALL_SH_SHA256", _FAKE_INSTALL_SH_SHA256)
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_ok)
    monkeypatch.setattr(probe_mod, "_default_fetch_bytes", _fake_fetch_bytes_matching)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 0, result.output
    assert "All checks passed" in result.output
    assert "install.sh sha256 matches" in result.output


def test_doctor_sha_drift_fails(monkeypatch):
    """Upstream install.sh serves different bytes than the pin → FAIL."""
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(nemoclaw_mod, "INSTALL_SH_SHA256", _FAKE_INSTALL_SH_SHA256)
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_ok)
    monkeypatch.setattr(probe_mod, "_default_fetch_bytes", _fake_fetch_bytes_drift)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1, result.output
    assert "install.sh sha256 drift" in result.output


def test_doctor_sha_fetch_failure_fails(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(nemoclaw_mod, "INSTALL_SH_SHA256", _FAKE_INSTALL_SH_SHA256)
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_ok)
    monkeypatch.setattr(probe_mod, "_default_fetch_bytes", _fake_fetch_bytes_fails)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1
    assert "install.sh fetch failed" in result.output


def test_doctor_unpinned_sha_reports_unknown(monkeypatch):
    """If INSTALL_SH_SHA256 is empty (should never ship), report UNKNOWN
    and exit non-zero rather than silently green."""
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(nemoclaw_mod, "INSTALL_SH_SHA256", "")
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_ok)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1
    assert "INSTALL_SH_SHA256 not pinned" in result.output


def test_doctor_unreachable_repo_fails(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(nemoclaw_mod, "INSTALL_SH_SHA256", _FAKE_INSTALL_SH_SHA256)
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_repo_missing)
    monkeypatch.setattr(probe_mod, "_default_fetch_bytes", _fake_fetch_bytes_matching)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "unreachable" in result.output


def test_doctor_missing_tag_fails(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(nemoclaw_mod, "INSTALL_SH_SHA256", _FAKE_INSTALL_SH_SHA256)
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_tag_missing)
    monkeypatch.setattr(probe_mod, "_default_fetch_bytes", _fake_fetch_bytes_matching)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_doctor_unsupported_arch_fails(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "riscv64")
    monkeypatch.setattr(nemoclaw_mod, "INSTALL_SH_SHA256", _FAKE_INSTALL_SH_SHA256)
    monkeypatch.setattr(probe_mod, "_default_fetch", _fake_fetch_ok)
    monkeypatch.setattr(probe_mod, "_default_fetch_bytes", _fake_fetch_bytes_matching)
    result = runner.invoke(app, ["doctor", "nemoclaw"])
    assert result.exit_code == 1
    assert "arch-match" in result.output
    assert "SUPPORTED_ARCHES" in result.output


def test_install_sh_url_shape():
    url = nemoclaw_mod.install_sh_url()
    assert url == (
        "https://raw.githubusercontent.com/NVIDIA/NemoClaw/"
        f"{nemoclaw_mod.NEMOCLAW_VERSION}/install.sh"
    )


def test_install_sh_url_override_version():
    url = nemoclaw_mod.install_sh_url("v0.0.50")
    assert url.endswith("/v0.0.50/install.sh")

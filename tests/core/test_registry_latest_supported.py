"""Tests for `registry.latest_supported_version` (issue #592)."""

from __future__ import annotations

import pytest

from clawrium.core.registry import latest_supported_version


@pytest.mark.parametrize(
    "claw_name,os_,os_version,arch,expected",
    [
        ("openclaw", "ubuntu", "24.04", "x86_64", "2026.6.11"),
        ("openclaw", "ubuntu", "22.04", "x86_64", "2026.6.11"),
        ("openclaw", "macos", "14.5", "arm64", "2026.6.11"),
        # Pin the exact macOS floor — if the manifest spec were tightened
        # to `>=14.5`, the 13.7 exclusion row below would still return
        # None and the regression would go undetected.
        ("openclaw", "macos", "14.0", "arm64", "2026.6.11"),
        ("hermes", "ubuntu", "24.04", "x86_64", "2026.7.1"),
        ("hermes", "ubuntu", "22.04", "x86_64", "2026.7.1"),
        ("hermes", "macos", "14.5", "arm64", "2026.7.1"),
    ],
)
def test_latest_supported_per_host_filter(
    claw_name, os_, os_version, arch, expected
):
    hardware = {"os": os_, "os_version": os_version, "architecture": arch}
    assert latest_supported_version(claw_name, hardware) == expected


@pytest.mark.parametrize(
    "os_,os_version,arch",
    [
        ("macos", "13.7", "arm64"),
        ("macos", "14.5", "x86_64"),
    ],
)
def test_openclaw_macos_boundary_exclusions(os_, os_version, arch):
    """openclaw macOS entries: arm64-only and require os_version >=14."""
    hardware = {"os": os_, "os_version": os_version, "architecture": arch}
    assert latest_supported_version("openclaw", hardware) is None


def test_latest_supported_returns_none_when_no_platform_matches():
    """openclaw has no Linux aarch64 entry — ubuntu/aarch64 host returns None.

    (macOS/arm64 is supported since 2026.5.28; see the macos row in the
    parametrize table above.)
    """
    hardware = {"os": "ubuntu", "os_version": "24.04", "architecture": "aarch64"}
    assert latest_supported_version("openclaw", hardware) is None


def test_latest_supported_returns_none_for_unknown_os():
    hardware = {"os": "debian", "os_version": "12", "architecture": "x86_64"}
    assert latest_supported_version("openclaw", hardware) is None

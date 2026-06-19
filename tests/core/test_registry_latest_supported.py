"""Tests for `registry.latest_supported_version` (issue #592)."""

from __future__ import annotations

import pytest

from clawrium.core.registry import latest_supported_version


@pytest.mark.parametrize(
    "claw_name,os_,os_version,arch,expected",
    [
        ("openclaw", "ubuntu", "24.04", "x86_64", "2026.6.8"),
        ("openclaw", "ubuntu", "22.04", "x86_64", "2026.6.8"),
        ("hermes", "ubuntu", "24.04", "x86_64", "2026.5.29.2"),
        ("hermes", "ubuntu", "22.04", "x86_64", "2026.5.29.2"),
        ("hermes", "macos", "14.5", "arm64", "2026.5.29.2"),
    ],
)
def test_latest_supported_per_host_filter(
    claw_name, os_, os_version, arch, expected
):
    hardware = {"os": os_, "os_version": os_version, "architecture": arch}
    assert latest_supported_version(claw_name, hardware) == expected


def test_latest_supported_returns_none_when_no_platform_matches():
    """openclaw is x86_64-only — aarch64 host returns None."""
    hardware = {"os": "ubuntu", "os_version": "24.04", "architecture": "aarch64"}
    assert latest_supported_version("openclaw", hardware) is None


def test_latest_supported_returns_none_for_unknown_os():
    hardware = {"os": "debian", "os_version": "12", "architecture": "x86_64"}
    assert latest_supported_version("openclaw", hardware) is None

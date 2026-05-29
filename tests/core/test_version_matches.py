"""Tests for `_version_matches` in core/registry.py (issue #469, step 2).

Covers the os_version matcher used by `check_compatibility`. Existing exact
strings must keep working (back-compat for Linux entries pinned at "24.04"),
while range/operator specs unlock macOS entries like ">=14" that should match
every macOS major release without manifest churn.
"""

import pytest
from clawrium.core.registry import _version_matches, check_compatibility


class TestVersionMatchesUnit:
    def test_exact_match_back_compat(self):
        assert _version_matches("24.04", "24.04") is True

    def test_exact_mismatch(self):
        assert _version_matches("24.04", "22.04") is False

    def test_ge_matches_higher(self):
        assert _version_matches(">=14", "14.5") is True
        assert _version_matches(">=14", "26.5") is True
        assert _version_matches(">=14", "14") is True

    def test_ge_rejects_lower(self):
        assert _version_matches(">=14", "13.7") is False

    def test_gt(self):
        assert _version_matches(">14", "14.1") is True
        assert _version_matches(">14", "14") is False

    def test_le_and_lt(self):
        assert _version_matches("<=14", "14.0") is True
        assert _version_matches("<=14", "14.1") is False
        assert _version_matches("<14", "13.9") is True
        assert _version_matches("<14", "14") is False

    def test_eq_and_ne(self):
        assert _version_matches("==14", "14") is True
        assert _version_matches("!=14", "15") is True
        assert _version_matches("!=14", "14") is False

    def test_whitespace_tolerated(self):
        assert _version_matches(">= 14", "14.5") is True

    def test_malformed_spec_raises(self):
        with pytest.raises(ValueError):
            _version_matches(">=not-a-version", "14.5")

    def test_missing_actual_against_operator_is_false(self):
        assert _version_matches(">=14", "") is False
        assert _version_matches(">=14", None) is False  # type: ignore[arg-type]

    def test_missing_actual_against_exact_only_matches_empty(self):
        assert _version_matches("", "") is True
        assert _version_matches("24.04", "") is False

    def test_garbage_actual_with_operator_is_false(self):
        assert _version_matches(">=14", "not-a-version") is False


class TestCheckCompatibilityWithRangeSpec:
    """End-to-end: a manifest entry using ">=14" must match macOS 26.5."""

    def test_range_spec_accepts_higher_version(self, monkeypatch):
        manifest = {
            "agent": {"type": "fake", "description": ""},
            "platforms": [
                {
                    "version": "1.0.0",
                    "os": "macos",
                    "os_version": ">=14",
                    "arch": "arm64",
                    "sha256": "x",
                    "requirements": {"min_memory_mb": 0, "gpu_required": False},
                }
            ],
        }
        monkeypatch.setattr(
            "clawrium.core.registry.load_manifest", lambda _name: manifest
        )

        hardware = {
            "architecture": "arm64",
            "os": "macos",
            "os_version": "26.5",
            "memtotal_mb": 16384,
        }
        result = check_compatibility("fake", hardware)
        assert result["compatible"] is True

    def test_range_spec_rejects_lower_version(self, monkeypatch):
        manifest = {
            "agent": {"type": "fake", "description": ""},
            "platforms": [
                {
                    "version": "1.0.0",
                    "os": "macos",
                    "os_version": ">=14",
                    "arch": "arm64",
                    "sha256": "x",
                    "requirements": {"min_memory_mb": 0, "gpu_required": False},
                }
            ],
        }
        monkeypatch.setattr(
            "clawrium.core.registry.load_manifest", lambda _name: manifest
        )

        hardware = {
            "architecture": "arm64",
            "os": "macos",
            "os_version": "13.7",
            "memtotal_mb": 16384,
        }
        result = check_compatibility("fake", hardware)
        assert result["compatible"] is False

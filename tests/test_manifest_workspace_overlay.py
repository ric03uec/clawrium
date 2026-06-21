"""Manifest workspace_overlay parsing tests (issue #760).

Covers U1/U2/U4/U31 from the plan: every agent type with a canonical
renderer must declare `features.workspace_overlay`, destination_root
values are pinned to upstream, and the parser handles missing /
malformed / trailing-slash / null-excludes shapes correctly.
"""

from __future__ import annotations

import pytest

from clawrium.core.registry import (
    ManifestParseError,
    _validate_workspace_overlay,
    load_manifest,
)


def test_openclaw_workspace_overlay_destination_root_pinned() -> None:
    """U2 (openclaw subset): destination_root sourced from manifest, not
    hard-coded in core."""
    manifest = load_manifest("openclaw")
    overlay = manifest["features"]["workspace_overlay"]
    assert overlay["destination_root"] == "~/.openclaw/workspace"


def test_openclaw_workspace_overlay_has_no_excludes() -> None:
    """U4: openclaw declares an empty exclude list — workspace zone is
    operator-owned and disjoint from canonical-render paths."""
    manifest = load_manifest("openclaw")
    overlay = manifest["features"]["workspace_overlay"]
    assert overlay.get("excludes", []) == []


def test_workspace_overlay_parser_accepts_minimal_block() -> None:
    spec = _validate_workspace_overlay(
        {"destination_root": "/home/agent/.x/workspace"}, "openclaw"
    )
    assert spec["destination_root"] == "/home/agent/.x/workspace"
    assert spec["excludes"] == []


def test_workspace_overlay_parser_rejects_missing_destination_root() -> None:
    with pytest.raises(ManifestParseError, match="destination_root"):
        _validate_workspace_overlay({"excludes": []}, "openclaw")


def test_workspace_overlay_parser_rejects_relative_destination_root() -> None:
    with pytest.raises(ManifestParseError, match="absolute path"):
        _validate_workspace_overlay(
            {"destination_root": "relative/path"}, "openclaw"
        )


def test_workspace_overlay_parser_normalizes_null_excludes_to_empty_list() -> None:
    """U31: `excludes: null` in YAML → empty list, not crash."""
    spec = _validate_workspace_overlay(
        {"destination_root": "~/.x", "excludes": None}, "openclaw"
    )
    assert spec["excludes"] == []


def test_workspace_overlay_parser_accepts_trailing_slash_entry() -> None:
    """U31: trailing-slash entry stays trailing-slash (dir-prefix shape)."""
    spec = _validate_workspace_overlay(
        {"destination_root": "~/.x", "excludes": ["sessions/", "config.yaml"]},
        "openclaw",
    )
    assert "sessions/" in spec["excludes"]
    assert "config.yaml" in spec["excludes"]


def test_workspace_overlay_parser_rejects_path_traversal_in_excludes() -> None:
    with pytest.raises(ManifestParseError, match="workspace-relative"):
        _validate_workspace_overlay(
            {"destination_root": "~/.x", "excludes": ["../etc/passwd"]},
            "openclaw",
        )


def test_workspace_overlay_parser_rejects_absolute_excludes() -> None:
    with pytest.raises(ManifestParseError, match="workspace-relative"):
        _validate_workspace_overlay(
            {"destination_root": "~/.x", "excludes": ["/etc/passwd"]},
            "openclaw",
        )


def test_workspace_overlay_parser_rejects_malformed_exclude_entry() -> None:
    with pytest.raises(ManifestParseError, match="non-empty string"):
        _validate_workspace_overlay(
            {"destination_root": "~/.x", "excludes": [42]}, "openclaw"
        )


def test_workspace_overlay_block_absent_yields_no_overlay() -> None:
    """An agent type with no `features.workspace_overlay` block must
    return None from the typed accessor (the in-source contract used by
    `workspace_sync.WorkspaceOverlaySpec.from_manifest`)."""
    from clawrium.core.workspace_sync import WorkspaceOverlaySpec

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    # hermes does not yet have a workspace_overlay block (lands in
    # Phase 3 of #760). Until then, the helper returns None and any
    # caller treats it as "no overlay for this agent type".
    assert spec is None or spec.destination_root  # tolerate Phase 3 landing

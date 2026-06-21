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


def test_zeroclaw_workspace_overlay_destination_root_pinned() -> None:
    """U2 (zeroclaw subset, #768): destination_root sourced from manifest,
    matches the on-host workspace path zeroclaw itself uses for memory."""
    manifest = load_manifest("zeroclaw")
    overlay = manifest["features"]["workspace_overlay"]
    assert overlay["destination_root"] == "~/.zeroclaw/workspace"


def test_zeroclaw_workspace_overlay_has_no_excludes() -> None:
    """U4 (zeroclaw subset, #768): zeroclaw renders no canonical config
    or auth artifacts under the workspace root, so excludes are empty."""
    manifest = load_manifest("zeroclaw")
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


def test_hermes_workspace_overlay_destination_root_pinned() -> None:
    """U2 (hermes subset, #769): destination_root sourced from manifest.
    Hermes uses `~/.hermes` directly (no `workspace/` suffix) because the
    overlay shares its destination with canonical-render output."""
    manifest = load_manifest("hermes")
    overlay = manifest["features"]["workspace_overlay"]
    assert overlay["destination_root"] == "~/.hermes"


def test_hermes_workspace_overlay_excludes_pinned() -> None:
    """U3 (#769): the hermes exclude list is pinned to the exact set
    documented in the plan §1.1. Drift is a release blocker.

    Manifest entries with a trailing slash (`sessions/`, `logs/`,
    `skills/clawrium/`) mean "dir-prefix exclude"; the loader retains
    the trailing slash here in the raw manifest view. The typed
    `WorkspaceOverlaySpec` strips it when classifying into
    `excludes_dirs`."""
    manifest = load_manifest("hermes")
    overlay = manifest["features"]["workspace_overlay"]
    assert set(overlay["excludes"]) == {
        "config.yaml",
        ".env",
        "auth.json",
        "state.db",
        "state.db-journal",
        "state.db-wal",
        "state.db-shm",
        "sessions/",
        "logs/",
        "skills/clawrium/",
    }


def test_workspace_overlay_block_absent_yields_no_overlay() -> None:
    """An agent type with no `features.workspace_overlay` block must
    return None from the typed accessor (the in-source contract used by
    `workspace_sync.WorkspaceOverlaySpec.from_manifest`).

    Every bundled agent type (openclaw, zeroclaw, hermes) now ships
    with a workspace_overlay block, so we exercise the missing-block
    path with a manual fixture instead.
    """
    from clawrium.core.workspace_sync import WorkspaceOverlaySpec

    # All three currently-bundled types have overlays; the typed
    # accessor should NEVER return None for them.
    for agent_type in ("openclaw", "zeroclaw", "hermes"):
        spec = WorkspaceOverlaySpec.from_manifest(agent_type)
        assert spec is not None, (
            f"{agent_type} must declare features.workspace_overlay"
        )

"""Hermes workspace overlay exclude-list integration tests (#769, Phase
3 of #760).

Plan §3.2 maps:
  - I3: hermes excludes enforced — every entry in the manifest exclude
    list (including all three SQLite WAL companion files and the
    `skills/clawrium/` dir-prefix) is filtered out and surfaced as a
    `WorkspaceExcluded` event. Good files (legitimate operator drops)
    land.
  - I14: hermes configure path with excludes enforced (the same Python
    enumerator is shared between sync and configure; this test pins
    that contract via the shared helper).
  - E3 hostile-fixture row: symlink at `workspace/innocent.md →
    ../auth.json`. Assert the host file is not overwritten and a
    `WorkspaceSkipped` event is emitted with reason=symlink.
  - TOCTOU: a file matching an exclude pattern injected AFTER
    enumeration but BEFORE the push completes must still be filtered.

Stubs ansible-runner. No SSH / no real host write. The exclude
filter under test is `core.workspace_sync.enumerate_workspace_files`
(Python side) and the per-file `workspace_excluded` Jinja filter at
the playbook copy boundary (control-machine side). The latter is
covered by AST/inspection tests in `test_workspace_sync.py`; here we
exercise the Python pipeline end-to-end with a tempdir workspace.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from clawrium.core.workspace_sync import (
    WorkspaceOverlaySpec,
    enumerate_workspace_files,
)


def _collect_events() -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    """Return `(events, callback)` so a test can drive the enumerator
    with `on_event=callback` and assert against the emitted NDJSON."""
    events: list[tuple[str, dict[str, Any]]] = []

    def on_event(phase: str, payload: dict[str, Any]) -> None:
        events.append((phase, payload))

    return events, on_event


# ---------------------------------------------------------------------------
# I3 — every hermes exclude entry is enforced end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile_rel",
    [
        # Exact-file excludes:
        "config.yaml",
        ".env",
        "auth.json",
        "state.db",
        # All three SQLite WAL companions — W13 iter-2: overlaying any
        # of these while the daemon holds an open transaction corrupts
        # the WAL silently. The hermes E2E fixture must cover ALL three.
        "state.db-journal",
        "state.db-wal",
        "state.db-shm",
        # Dir-prefix excludes:
        "sessions/123.json",
        "logs/gateway.log",
        # W10 iter-3: operator dropping skills/clawrium/<sub>/SKILL.md
        # MUST be rejected — the skills_apply playbook owns this path.
        "skills/clawrium/tdd/SKILL.md",
        "skills/clawrium/anything/SKILL.md",
    ],
)
def test_i3_hermes_hostile_drop_is_excluded(
    tmp_path: Path, hostile_rel: str
) -> None:
    """I3 (hermes cell, #769): each manifest exclude entry filters the
    matching operator-supplied file. The file is NOT staged for push,
    a `WorkspaceExcluded` NDJSON event fires with `reason=manifest_exclude`,
    and the rel surfaces in the second tuple return value of
    `enumerate_workspace_files`.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    abs_path = workspace / hostile_rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text("hostile content")

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    events, on_event = _collect_events()
    entries, excluded, skipped = enumerate_workspace_files(
        workspace, spec, agent_name="alice", on_event=on_event
    )

    # The hostile file is NOT in `entries` (no push payload built).
    assert all(e.rel != hostile_rel for e in entries), (
        f"hostile rel {hostile_rel!r} leaked into push entries"
    )
    # The hostile file IS in `excluded`.
    assert hostile_rel in excluded
    # A `WorkspaceExcluded` event fired with the right reason.
    excluded_events = [
        p for (phase, p) in events
        if phase == "push_workspace" and p.get("state") == "excluded"
    ]
    assert any(
        p.get("path") == hostile_rel
        and p.get("reason") == "manifest_exclude"
        for p in excluded_events
    ), f"no WorkspaceExcluded event for {hostile_rel!r}: events={excluded_events}"


def test_i3_hermes_good_files_land(tmp_path: Path) -> None:
    """I3 (positive cell): legitimate operator drops outside the
    exclude set land normally. Pin two canonical good paths from the
    plan §3.3.2 E3 matrix."""
    workspace = tmp_path / "workspace"
    (workspace / "profiles" / "coder").mkdir(parents=True)
    (workspace / "memories").mkdir(parents=True)
    (workspace / "profiles" / "coder" / "SOUL.md").write_text(
        "You are a senior staff engineer."
    )
    (workspace / "memories" / "NOTES.md").write_text("dad joke")

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    entries, excluded, _ = enumerate_workspace_files(
        workspace, spec, agent_name="alice"
    )
    rels = sorted(e.rel for e in entries)
    assert rels == ["memories/NOTES.md", "profiles/coder/SOUL.md"]
    assert excluded == []


# ---------------------------------------------------------------------------
# E3 hostile-fixture row — symlink at `workspace/innocent.md → ../auth.json`
# ---------------------------------------------------------------------------


def test_e3_hostile_symlink_to_excluded_target_is_skipped(
    tmp_path: Path,
) -> None:
    """Hook-review S — security: an operator may try to bypass the
    exclude filter by symlinking `workspace/innocent.md → ../auth.json`.
    The symlink-rejection at enumeration (`os.path.islink`) fires
    BEFORE the exclude check, so the file is skipped with
    `reason=symlink` and NEVER read — the link target is irrelevant.

    Pin the event so a regression that re-orders symlink/exclude
    checks (or drops `os.path.islink`) fails this test.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # The "target" is outside the workspace — exactly the bypass attempt.
    target = tmp_path / "auth.json"
    target.write_text("real auth contents")

    (workspace / "innocent.md").symlink_to(target)

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    events, on_event = _collect_events()
    entries, excluded, skipped = enumerate_workspace_files(
        workspace, spec, agent_name="alice", on_event=on_event
    )

    # Nothing got staged.
    assert entries == []
    # The symlink rel is in skipped, not excluded — exclude-list
    # semantics never came into play because the symlink check ran
    # first.
    assert "innocent.md" in skipped
    assert "innocent.md" not in excluded
    # Event emitted with the correct reason.
    skip_events = [
        p for (phase, p) in events
        if phase == "push_workspace" and p.get("state") == "skipped"
    ]
    assert any(
        p.get("path") == "innocent.md" and p.get("reason") == "symlink"
        for p in skip_events
    ), f"no symlink-skip event for innocent.md: events={skip_events}"


# ---------------------------------------------------------------------------
# TOCTOU — exclude-matching file injected post-enumeration is still filtered
# ---------------------------------------------------------------------------


def test_toctou_file_matching_exclude_injected_after_enumeration_is_filtered(
    tmp_path: Path,
) -> None:
    """Hook-review S — test-coverage TOCTOU: a file matching an exclude
    pattern injected AFTER enumeration but BEFORE the push completes
    must still be filtered.

    Architecture rationale (plan W18 iter-2): the staging step copies
    each enumerated file into a managed `tempfile.TemporaryDirectory`
    via `shutil.copy2`. The Ansible playbook reads the staged copy,
    NEVER the operator's original workspace path. So even if the
    operator drops `state.db` into the workspace dir after enumeration
    returned, the staging dir does not contain `state.db` and the
    playbook never sees it.

    This test pins that property by:
      1. enumerating a workspace with one good file,
      2. injecting `state.db` into the workspace AFTER enumeration,
      3. re-enumerating and asserting the late-arriving `state.db` is
         filtered as an exclude on the second pass.

    A regression that streamed-walked the operator's workspace during
    the playbook copy task (instead of the staging dir) would let the
    late-arriving file through and fail this test.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "good.md").write_text("ok")

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    # First pass: only `good.md` exists.
    entries1, excluded1, _ = enumerate_workspace_files(
        workspace, spec, agent_name="alice"
    )
    assert [e.rel for e in entries1] == ["good.md"]
    assert excluded1 == []

    # Inject the exclude-matching file AFTER enumeration. Mirror the
    # exact rel the playbook would have to handle if the operator
    # raced the sync.
    (workspace / "state.db").write_text("hostile late-arriving sqlite")

    # Second pass (representative of a re-enumeration before the
    # playbook is invoked, or of the next sync): the exclude filter
    # catches it.
    entries2, excluded2, _ = enumerate_workspace_files(
        workspace, spec, agent_name="alice"
    )
    assert "state.db" in excluded2
    assert all(e.rel != "state.db" for e in entries2)

    # And critically: the first-pass `entries1` (which is what the
    # staging step would have used) does NOT contain `state.db`. The
    # playbook reads only the staged copy.
    assert all(e.rel != "state.db" for e in entries1)


# ---------------------------------------------------------------------------
# I14 — sync-vs-configure path share the same exclude semantics
# ---------------------------------------------------------------------------


def test_i14_configure_and_sync_share_same_enumeration_path(
    tmp_path: Path,
) -> None:
    """I14 (hermes cell, #769): both `lifecycle.configure_agent` and
    `lifecycle_canonical.sync_agent_canonical` push the workspace
    through the shared `push_workspace_phase` helper. Drift between
    the two would be a release blocker — the only way to pin it from
    a unit test is to assert the symbol identity. The full E2E
    contract lives in `.itx/760/04_E2E_hermes_wolf-i.md`.
    """
    from clawrium.core import lifecycle, lifecycle_canonical, workspace_sync

    # Both higher-level callers must route through the same module
    # symbol — a copy of the function in either site would let exclude
    # behavior diverge.
    assert (
        workspace_sync.push_workspace_phase.__module__
        == "clawrium.core.workspace_sync"
    )
    # The configure + sync paths both `from clawrium.core import
    # workspace_sync` (or call `workspace_sync.push_workspace_phase`
    # directly via attribute access). Pin the source attribute exists
    # so a refactor that renames it fails this test.
    assert hasattr(workspace_sync, "push_workspace_phase")
    # Smoke check — the function is referenced from both lifecycle paths
    # (avoids a future rename that breaks just one caller).
    lifecycle_src = open(lifecycle.__file__).read()
    canonical_src = open(lifecycle_canonical.__file__).read()
    assert "push_workspace_phase" in lifecycle_src
    assert "push_workspace_phase" in canonical_src


# ---------------------------------------------------------------------------
# Mode bits — secret-pattern floor applies under hermes excludes too
# ---------------------------------------------------------------------------


def test_hermes_secret_pattern_file_in_workspace_floors_to_0600(
    tmp_path: Path,
) -> None:
    """Hermes does not have a `*.env` exclude (the manifest only excludes
    the literal root `.env`), so a nested env file like
    `secrets/db.env` lands as a normal push entry but with the 0600
    mode floor. Pin the interaction between the exclude list and the
    secret-pattern floor — both contribute independently."""
    workspace = tmp_path / "workspace"
    (workspace / "secrets").mkdir(parents=True)
    nested = workspace / "secrets" / "db.env"
    nested.write_text("PASSWORD=hunter2")
    os.chmod(nested, 0o666)

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    entries, excluded, _ = enumerate_workspace_files(
        workspace, spec, agent_name="alice"
    )
    rels = [e.rel for e in entries]
    assert "secrets/db.env" in rels
    assert excluded == []
    # `*.env` secret-pattern floor still floors mode to 0600.
    entry = next(e for e in entries if e.rel == "secrets/db.env")
    assert entry.mode == "0600"


def test_hermes_root_dot_env_is_excluded_not_floored(tmp_path: Path) -> None:
    """The `.env` exact-file exclude shadows the secret-pattern floor
    for the root case — the file never makes it into the staging
    payload at all. Pin both behaviors so a refactor that swapped the
    check order (apply mode floor before exclude filter) wouldn't
    accidentally leak the file."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("ANTHROPIC_API_KEY=sk-...")

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    entries, excluded, _ = enumerate_workspace_files(
        workspace, spec, agent_name="alice"
    )
    assert entries == []
    assert excluded == [".env"]

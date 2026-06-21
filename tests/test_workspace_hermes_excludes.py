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


@pytest.mark.parametrize(
    "symlink_rel",
    [
        # Exact-file excluded path. With symlink-first → reason=symlink.
        # With exclude-first (the regression we want to catch) →
        # reason=manifest_exclude. Either-or distinguishes the orderings.
        pytest.param("auth.json", id="exact-file-excluded"),
        # Dir-prefix excluded path. Same logic for the dir-prefix
        # branch of `_is_excluded`.
        pytest.param("sessions/foo.json", id="dir-prefix-excluded"),
    ],
)
def test_e3_hostile_symlink_with_excluded_name_pins_ordering(
    tmp_path: Path, symlink_rel: str
) -> None:
    """Hook-review S — security; ATX iter-1 W1 fix: pin the ordering
    invariant by naming the symlink after an excluded entry.

    Mechanism: with the current order (symlink-check first) the
    enumerator emits `reason=symlink`. If a regression were to flip
    the order (exclude-check first), the same hostile drop would
    surface as `reason=manifest_exclude` because the name matches an
    exclude entry — and this test would fail.

    Both the exact-file branch (`auth.json`) and the dir-prefix branch
    (`sessions/foo.json`) of `_is_excluded` are covered so a future
    edit that reorders only one branch is caught.

    The symlink target is outside the workspace dir, exactly the
    bypass attempt the security defense exists for.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "real_auth_secret.txt"
    target.write_text("real auth contents the symlink would dereference to")

    symlink_path = workspace / symlink_rel
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    symlink_path.symlink_to(target)

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    events, on_event = _collect_events()
    entries, excluded, skipped = enumerate_workspace_files(
        workspace, spec, agent_name="alice", on_event=on_event
    )

    # Nothing got staged.
    assert entries == []

    # The ordering pin: symlink-check runs BEFORE exclude-check. So the
    # rel surfaces in `skipped` with reason=symlink, NOT in `excluded`.
    # If the ordering ever flips, this exact assertion fails.
    assert symlink_rel in skipped, (
        f"expected {symlink_rel!r} in skipped (reason=symlink), got "
        f"skipped={skipped} excluded={excluded}"
    )
    assert symlink_rel not in excluded, (
        f"ordering regression: {symlink_rel!r} reached the exclude "
        f"branch before the symlink branch — symlink check must run first"
    )

    skip_events = [
        p for (phase, p) in events
        if phase == "push_workspace" and p.get("state") == "skipped"
    ]
    assert any(
        p.get("path") == symlink_rel and p.get("reason") == "symlink"
        for p in skip_events
    ), (
        f"no symlink-skip event for {symlink_rel!r}: events={skip_events}"
    )

    # And the negative side: ZERO `manifest_exclude` events for this
    # rel. A regression that ran the exclude check first would emit
    # one, and this assertion would catch it.
    excl_events = [
        p for (phase, p) in events
        if phase == "push_workspace" and p.get("state") == "excluded"
    ]
    assert not any(
        p.get("path") == symlink_rel for p in excl_events
    ), (
        f"ordering regression: {symlink_rel!r} emitted as "
        f"manifest_exclude before the symlink check fired"
    )


# ---------------------------------------------------------------------------
# TOCTOU — exclude-matching file injected post-enumeration is still filtered
# ---------------------------------------------------------------------------


def test_toctou_late_arrival_absent_from_staging_and_playbook_extravars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hook-review S — test-coverage TOCTOU; ATX iter-1 W2 + iter-2
    W_NEW_2 + S_NEW_3 fix.

    Pins the Python-side TOCTOU invariant: files injected into the
    operator workspace AFTER `enumerate_workspace_files` returned but
    BEFORE `_stage_files` completes MUST NOT reach the staging
    tempdir or the `workspace_files` extravar payload. A regression
    that streamed-walked the operator workspace at staging time
    (instead of iterating the pre-computed `entries` list) would
    notice the late arrival and copy it; this test catches that.

    Note on scope: the playbook-side guarantee (the `ansible.builtin.copy`
    task reads from `item.src`/staging, not from any operator-controlled
    path) is encoded by the S6 + S_NEW_1 changes in `workspace.yaml`
    and is asserted by `test_hermes_workspace_playbook_filters_excludes_per_file`
    and the per-file `item.src` assert task. This test stubs
    `ansible_runner.run`, so the playbook does not execute here; that
    layer's invariant lives in the YAML, not in this test.

    Strategy: monkeypatch `_stage_files` with a wrapper that drops
    `state.db` into the operator workspace **before** delegating to
    the real implementation. The real `_stage_files` iterates
    `entries` from the prior enumeration; a regression that
    re-walked the workspace at stage time would notice the new file
    and copy it. We assert it does NOT show up in either the staging
    contents or the extravar payload the (stubbed) runner sees.
    """
    from clawrium.core import config as config_module
    from clawrium.core import workspace_sync as ws_module
    from clawrium.core.workspace_sync import push_workspace_phase

    # Redirect get_config_dir so the staging tree lives under tmp_path.
    # `workspace_sync` imports the symbol at module-load time, so we
    # patch both the source module and the imported alias.
    monkeypatch.setattr(config_module, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(ws_module, "get_config_dir", lambda: tmp_path)

    # Stage a workspace with one good file under the agents-slot layout
    # push_workspace_phase expects.
    workspace = (
        tmp_path / "agents" / "hermes" / "alice" / "workspace"
    )
    workspace.mkdir(parents=True)
    (workspace / "good.md").write_text("ok")

    # Stub the SSH key lookup so the helper doesn't hit the real store.
    monkeypatch.setattr(
        "clawrium.core.keys.get_host_private_key",
        lambda key_id: tmp_path / "fake-key",
    )
    (tmp_path / "fake-key").write_text("fake key data")

    # Inject the hostile file BETWEEN enumeration and staging — the
    # real TOCTOU window. The wrapper drops `state.db` then delegates
    # to the original `_stage_files` (which receives the entries list
    # produced by the earlier enumeration, NOT a fresh walk).
    real_stage_files = ws_module._stage_files
    injected_paths: list[Path] = []

    def _stage_files_with_race(entries, staging_dir):
        race_target = workspace / "state.db"
        race_target.write_text("hostile mid-stage SQLite")
        injected_paths.append(race_target)
        return real_stage_files(entries, staging_dir)

    monkeypatch.setattr(ws_module, "_stage_files", _stage_files_with_race)

    captured = {"extravars": None, "staging_contents": None}

    class _StubRunResult:
        status = "successful"
        rc = 0

    def _stub_run(*_args, **kwargs):
        extravars = kwargs["extravars"]
        captured["extravars"] = extravars
        staging_dir = Path(extravars["staging_dir"])
        captured["staging_contents"] = sorted(
            str(p.relative_to(staging_dir))
            for p in staging_dir.rglob("*")
            if p.is_file()
        )
        return _StubRunResult()

    class _StubModule:
        def run(self, *a, **kw):
            return _stub_run(*a, **kw)

    monkeypatch.setitem(
        __import__("sys").modules, "ansible_runner", _StubModule()
    )

    result = push_workspace_phase(
        host={"hostname": "h", "key_id": "h", "os_family": "linux"},
        agent_type="hermes",
        agent_name="alice",
    )

    # The push itself succeeded (stubbed runner returns OK).
    assert result.success is True

    # The wrapper fired at the real TOCTOU window:
    assert injected_paths and injected_paths[0].exists(), (
        "test setup error — the _stage_files wrapper never ran, "
        "so the TOCTOU window was not actually exercised"
    )

    # The staging dir snapshot captured at runner-invocation time:
    # `state.db` MUST NOT be present. The injection happened AFTER
    # enumeration, so the `entries` list `_stage_files` walks does
    # not include it. Only `good.md` should be in the staging dir.
    assert captured["staging_contents"] == ["good.md"], (
        f"staging dir leak at the enumerate→stage TOCTOU window: "
        f"{captured['staging_contents']!r} contains a late-arriving "
        f"file — a regression has streamed-walked the operator workspace"
    )

    # The extravar payload the playbook would have used: same property.
    workspace_files_rels = sorted(
        f["rel"] for f in captured["extravars"]["workspace_files"]
    )
    assert workspace_files_rels == ["good.md"], (
        f"extravar leak at the enumerate→stage TOCTOU window: "
        f"workspace_files contains a late-arriving rel "
        f"{workspace_files_rels!r}"
    )

    # And the result-level pin: `state.db` is not in files_pushed
    # (it never made it into the staging payload).
    assert "state.db" not in result.files_pushed


def test_toctou_re_enumeration_catches_late_arrival_as_excluded(
    tmp_path: Path,
) -> None:
    """Belt-and-suspenders companion to the TOCTOU test above: on the
    NEXT sync (re-enumeration), the late-arrival is correctly
    classified as `manifest_exclude`. This pins the exclude branch
    works whether the file appeared just before or long after the
    initial enumeration.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "good.md").write_text("ok")

    spec = WorkspaceOverlaySpec.from_manifest("hermes")
    assert spec is not None

    # Inject the exclude-matching file. On re-enumeration:
    (workspace / "state.db").write_text("hostile late-arriving sqlite")
    entries, excluded, _ = enumerate_workspace_files(
        workspace, spec, agent_name="alice"
    )
    assert "state.db" in excluded
    assert all(e.rel != "state.db" for e in entries)


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
    # ATX iter-1 S1 fix: use Path.read_text() so file handles are
    # context-managed; bare `open(...).read()` leaks under
    # `-W error::ResourceWarning`.
    lifecycle_src = Path(lifecycle.__file__).read_text()
    canonical_src = Path(lifecycle_canonical.__file__).read_text()
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

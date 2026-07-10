# Issue #871 Plan

## Summary

Fix zeroclaw memory persistence so operator-edited memory files live in the local control-plane workspace overlay, survive `clawctl agent upgrade`, and remain consistent across read, write, delete, sync, and upgrade flows.

## Problem

`clawctl agent memory edit` currently writes memory files directly to the remote host via the zeroclaw `memory_write.yaml` playbook. The local overlay under `~/.config/clawrium/agents/zeroclaw/<agent>/workspace/` is not updated, but `push_workspace_phase()` only syncs files from that local overlay. During upgrade, `clawctl agent upgrade` runs `run_installation(..., force=True)` and then restarts the agent, but it does not call workspace sync. That leaves the local control-plane with no persisted copy to restore, so memory/persona files can disappear from the remote workspace.

## Goals

- Make the local control-plane workspace overlay the source of truth for zeroclaw memory files.
- Persist successful memory writes locally as well as remotely.
- Mirror successful memory deletes locally so later syncs do not resurrect deleted files.
- Read from the local overlay first, with a legacy remote fallback when local state is missing.
- Ensure the `agent upgrade` path rehydrates overlay-backed files onto the remote host.
- Add regression coverage for the data-loss path.

## Non-Goals

- Redesigning the full workspace overlay system.
- Changing GUI or CLI surface area beyond behavior inherited from core memory helpers.
- Expanding zeroclaw memory file allowlists or limits.

## Implementation Plan

### 1. Add local overlay persistence helpers in `src/clawrium/core/memory.py`

- Add small helpers to resolve the local workspace overlay path for an agent memory file and ensure its parent directory exists.
- Reuse existing validation and per-agent resolution logic so the write/read/delete code paths stay centralized in `core/memory.py`.

### 2. Make memory reads overlay-first with legacy fallback

- Update `read_memory_file()` to:
  - resolve and validate the target agent/file as it does today,
  - return the local overlay copy when it exists,
  - fall back to the current remote playbook read path when the local copy is absent.
- Keep the fallback so existing agents with remote-only memory state still work before their next edit/sync/upgrade.

### 3. Mirror successful writes and deletes into the local overlay

- Update `write_memory_file()` so a successful remote write also writes the same bytes into the local workspace overlay.
- Update `delete_memory_files()` so successful remote deletes also remove the local overlay copies.
- Preserve failure semantics: do not mutate local state when the remote operation fails.

### 4. Restore overlay files during upgrade/reinstall

- Update the upgrade/install path so `clawctl agent upgrade` re-pushes workspace overlay files after installation and before the post-install restart flow completes.
- Prefer reusing the existing `push_workspace_phase()` contract rather than creating a second restore implementation.
- Ensure zeroclaw’s existing gateway-token rotation invariants remain intact when this path runs.

### 5. Add regression tests

- Extend `tests/test_core_memory.py` to cover:
  - local-overlay-first reads,
  - remote fallback reads when local state is absent,
  - successful write mirroring into the local overlay,
  - successful delete mirroring from the local overlay,
  - no local mutation when remote playbook execution fails.
- Extend upgrade/install coverage to prove overlay-backed memory files are restored on the upgrade path that currently reproduces the bug.
- Update any existing tests whose expectations assume remote-only memory behavior.

### 6. Update release notes

- Add a `### Fixed` entry to the root `CHANGELOG.md` describing that zeroclaw memory/persona files now persist through upgrade because the control-plane overlay is kept in sync and restored.

## Risks And Checks

- Upgrade restore must happen on the real `agent upgrade` control path, not only on `agent sync`, otherwise the reported reproduction remains broken.
- Delete parity is required; otherwise a later sync will recreate files the operator intentionally removed.
- Legacy remote fallback must remain narrow so it does not silently hide local-overlay regressions.
- Test coverage should target the exact upgrade path (`run_installation` + post-install lifecycle flow), not only isolated helper behavior.

## Subtasks

No GitHub subtasks are needed. This is one tightly-scoped data-loss fix with shared core logic and regression coverage, and splitting it would add coordination overhead without reducing implementation risk.

## Validation

- `make test`
- `make lint`
- Targeted tests covering core memory behavior and upgrade/install regression cases

## Prompt Log

## Plan Create

**Stage**: plan
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-10T05:45:19Z
**Model**: openai/gpt-5.4

```prompt
871
```

**Output**: Created the implementation plan for issue #871 covering local memory-overlay persistence, upgrade rehydration, tests, and release-note updates.

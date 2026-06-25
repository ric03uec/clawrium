# Issue #771 — Phase 5: zeroclaw workspace overlay on macOS

Parent: #760. Predecessor: #770 (openclaw macOS GA — PR #799 open at start of work).

## Scope (verbatim from #771)

Ship workspace overlay sync for **zeroclaw on macOS**, end-to-end on
`esper-macmini`. Mirrors Phase 2 (#768) exit criteria but on
`/Users/<name>/.zeroclaw/workspace/`. Bearer-rotation invariant
(#437) must hold identically.

## Approach

1. Replace `src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml`
   stub with a real copy pipeline. Body mirrors the openclaw macOS
   playbook (already merged via #770) with one trivial textual delta:
   the documentation banner names zeroclaw and references its
   memory-tree colocation rationale.
2. Per-OS deltas (vs zeroclaw Linux):
   - `/Users/<agent_name>/` prefix (not `/home/`).
   - `group: staff` literal (not `{{ agent_name }}`).
   - `..` segment rejection on `workspace_dest_root` (mirrors
     openclaw macOS ATX iter-1 W1 hardening).
   - `item.mode` regex pin (mirrors openclaw macOS ATX iter-1 W7/S6
     hardening). The Linux zeroclaw playbook does not yet have this;
     we are intentionally tightening macOS without re-validating the
     Ubuntu surface (same scope discipline as #770 Callouts).
3. Add unit tests mirroring the openclaw macOS body invariants:
   stub-removal, `/Users/` prefix, `..` rejection, `group: staff`,
   `copy + follow: no`. Parametrize over the agent type where
   neighboring tests already do so.
4. Extend `tests/test_workspace_zeroclaw_bearer_rotation.py` I-pair-A/B/C
   with `os_family="darwin"` parametrization so the bearer-rotation
   invariant is pinned identically across Linux and macOS code paths.
5. Update AGENTS.md workspace overlay table: zeroclaw row no longer
   "macOS deferred (Phase 5)" — instead "macOS GA via #771".
6. CHANGELOG `### Added` entry under `[Unreleased]`.

## Cross-issue ATX findings carried forward (from #770 → #719 review)

- **B4 (bearer rotation #437)**: E2E checklist includes sha256-only
  bearer hash diff for configure / sync / `launchctl kickstart -k`
  restart. Never materialize raw bearer.
- **B5 (lifecycle-verb completeness on macOS)**: E2E matrix covers
  `stop` and `remove` on esper-macmini in addition to install /
  configure / sync.
- **W3 (dispatcher-only invariant)**: no `when: ansible_os_family ==
  "Darwin"` guards inside `workspace.yaml` or the macOS variant.
- **W4 (`ansible_user_dir` ban)**: literal `/Users/<agent_name>/...`
  pattern only.
- **W11 / S5 (Python 3.9 PEP 604)**: no new Python module under
  `platform/registry/zeroclaw/` for this phase (playbook-only
  change). Audit step verifies the existing files still compile under
  3.9 if any are touched.

## Exit Criteria (verbatim from #771)

### Code

- `playbook_resolver` routing tested for `os_family="darwin"`
- No `if Darwin` branches inside `workspace.yaml`

### Tests

- Unit: playbook-structure test extended with darwin-dispatch row for
  zeroclaw.
- Integration: `os_family="darwin"` path lands files at
  `/Users/<name>/.zeroclaw/workspace/`; bearer-rotation invariant
  verified end-to-end (I-pair-A/B/C parametrized for macOS).
- `make test` + `make lint` clean.

### E2E on esper-macmini

Captured at `.itx/760/06_E2E_zeroclaw_esper-macmini.md`.

### Process

- ATX review via CLI (operator directive: NOT MCP).
- AGENTS.md updated.

## Files

- `src/clawrium/platform/registry/zeroclaw/playbooks/workspace_macos.yaml` — replace stub
- `tests/test_workspace_sync.py` — extend with zeroclaw macOS invariants
- `tests/test_workspace_zeroclaw_bearer_rotation.py` — darwin parametrization
- `AGENTS.md` — note macOS GA for zeroclaw
- `CHANGELOG.md` — `[Unreleased] > Added`
- `.itx/760/06_E2E_zeroclaw_esper-macmini.md` — NEW E2E log
- `.itx/771/00_PLAN.md` — this file
- `.itx/771/01_EXECUTION.md` — execution log
- `.itx/771/atx-session.json` — ATX session metadata

## Branch / PR

- Branch: `issue-771-zeroclaw-workspace-macos`
- PR base: `issue-770-openclaw-workspace-macos` (Phase 4 open as PR #799,
  not yet merged). Stacked PR.

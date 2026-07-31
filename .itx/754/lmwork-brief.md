Work on issue #754 in this worktree. Read it first: `gh issue view 754`

## Scope fence

Touch ONLY:
- `src/clawrium/core/openclaw_version.py` (NEW — shared live-version resolver, extracted from `lifecycle_canonical.py`)
- `src/clawrium/core/lifecycle_canonical.py` (delete the internal `_get_host_openclaw_version*` triad and import from the new module; keep the public re-export if lifecycle.py:2951 already imports it)
- `src/clawrium/core/lifecycle.py` (update the import at line 2951 if the symbol path changes)
- `src/clawrium/cli/clawctl/agent/upgrade.py` (comparator rewrite: use live version, not snapshot)
- `tests/core/test_openclaw_version.py` (NEW — tests for the extracted resolver)
- `tests/cli/clawctl/agent/test_upgrade.py` (existing or new — the 6 T1–T6 tests from the issue)
- `.itx/754/` (run artifacts — brief, worker.done, judge rounds)

Do NOT touch:
- Any playbook, template, or manifest.
- Zeroclaw / hermes upgrade paths — issue plan point 3 says "same flow for zeroclaw / hermes each gets its own live-version resolver" but that is out-of-scope for this PR. Only fix the openclaw path.
- Preflight code in `lifecycle_canonical.py` other than moving the resolver — do NOT alter preflight semantics.
- `src/clawrium/cli/agent.py` and other legacy hybrid `cli/*.py` files (they are being removed in #707).

## Tasks

1. **Extract the resolver.** Create `src/clawrium/core/openclaw_version.py`. Move `_get_host_openclaw_version_linux`, `_get_host_openclaw_version_macos`, and the dispatcher `_get_host_openclaw_version` from `src/clawrium/core/lifecycle_canonical.py` (currently at lines ~243, ~266, ~300) into the new module. Rename to `get_host_openclaw_version` (public). Keep helper signatures identical. Preserve the OS-fork dispatcher shape per the "dispatcher-only OS fork" invariant in AGENTS.md.

2. **Update `lifecycle_canonical.py`** to import `get_host_openclaw_version` from the new module wherever `_get_host_openclaw_version` was called. If `src/clawrium/core/lifecycle.py:2951` imports `_get_host_openclaw_version` from lifecycle_canonical, update that import to point at the new module.

3. **Rewrite `src/clawrium/cli/clawctl/agent/upgrade.py`** for the openclaw comparator. Read the current file first. The new logic (from the issue body):
   ```
   live = get_host_openclaw_version(...)
   manifest_max = load_manifest(claw_type).max_version
   if live >= manifest_max:
       emit "already at latest ({live})"
       # do NOT auto-correct the snapshot; respect operator intent
       no-op
   else:
       run install playbook with claw_version=manifest_max
       update snapshot to manifest_max
   ```
   Only change the openclaw branch. Zeroclaw and hermes branches stay as-is.

4. **Write the tests** listed in the issue body as T1–T6:
   - T1: `test_upgrade_no_op_when_live_equals_max` — live=2026.6.8, manifest_max=2026.6.8, snapshot=2026.3.13 → exit 0, no install run, snapshot stays 2026.3.13
   - T2: `test_upgrade_no_op_when_live_above_max` — live=2026.7.0, manifest_max=2026.6.8 → exit 0, no install, snapshot untouched
   - T3: `test_upgrade_runs_when_live_below_max` — live=2026.5.28, manifest_max=2026.6.8, snapshot=2026.6.8 → install runs, snapshot becomes 2026.6.8
   - T4: `test_upgrade_corrects_false_already_at_max_snapshot` — live=2026.3.13, snapshot=2026.6.8, manifest_max=2026.6.8 → install runs (the wolf-i scenario), snapshot updates to 2026.6.8
   - T5: `test_upgrade_no_op_does_not_open_install_playbook` — T1 setup, assert `run_installation` not called
   - T6: `test_upgrade_uses_shared_resolver` — mock the shared resolver, assert both preflight and upgrade call it (i.e., both code paths import from `core/openclaw_version.py`)
   - Plus at least one direct unit test for `get_host_openclaw_version` in `tests/core/test_openclaw_version.py` — a happy-path test that exercises the dispatcher with a mocked ssh client. Mirror the mock pattern in any existing `tests/core/test_lifecycle_canonical*.py`.

5. **Run `make lint && make test`.** Do NOT commit if either fails — fix and re-run until both pass.

6. **Update the root `CHANGELOG.md`** under `## [Unreleased]`:
   - Under `### Fixed`, add one line: "clawctl agent upgrade` now compares against the live openclaw version on the host, not the hosts.json snapshot (#754)"
   - Under `### Changed`, add one line for the resolver extraction if the module split is user-visible enough to note; otherwise skip.
   - Nothing under `### BREAKING`.

## Pattern to follow

- **The resolver extraction pattern:** look at other `src/clawrium/core/*.py` modules that expose OS-forked helpers (e.g. `playbook_resolver.py` and its consumers). The dispatcher lives at module level, the per-OS impls are private, callers import only the public dispatcher.
- **The upgrade-comparator pattern:** PR #751 is the in-repo precedent — it added `_get_host_openclaw_version` for preflight. Read `src/clawrium/core/lifecycle_canonical.py` around lines 243–330 to see the shape. Your extraction is a pure move + rename; the logic is unchanged.
- **The tests:** look at `tests/cli/clawctl/agent/` for the mocking style used in existing upgrade tests. Follow it exactly.

## Rules

- Commit locally. Do NOT push. Do NOT open a PR. lmjudge will open the PR in a later step.
- Do not add features, refactors, or abstractions beyond the tasks above. No zeroclaw/hermes upgrade parity work — that is deliberately deferred.
- If a task turns out to be already done (e.g., the resolver is already in a shared module), stop and say so in `.itx/754/lmwork-worker.done` — do not invent work.
- Commit `.itx/754/` along with your code changes.
- One commit per logical unit is fine; a single squashed commit is also fine — just make sure lint and tests pass at the tip.
- When finished, run: `echo done > .itx/754/lmwork-worker.done`

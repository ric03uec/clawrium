# Issue #411 — Orchestrator Manifest

**Started**: 2026-06-07T06:30:00Z
**Branch**: `issue-411-ad-hoc-skills`
**Worktree**: `/home/devashish/workspace/ric03uec/clawrium-issue-411`
**Mode**: autonomous, ATX review per phase, fleet poll every 15 min
**Source of truth**: [`.itx/411/01_SCAFFOLD.md`](./01_SCAFFOLD.md)

## Phase status

| # | Phase | Status | Commit | ATX | Notes |
|---|---|---|---|---|---|
| 1+2 | Catalog migration + Core refactor | ready-to-commit | pending | iter 1 rating 1-2/5; 5 blockers fixed | combined; validator depends on Phase 2 symbols |
| 3 | CLI surface | pending | — | — | — |
| 4 | GUI backend | pending | — | — | — |
| 5 | GUI frontend | pending | — | — | — |
| 6 | Slash command + docs | pending | — | — | — |
| 7 | Tests + E2E | pending | — | — | AC-1 + AC-2 + negative AC |

**Why Phase 1+2 combined**: the rewritten `scripts/validate_skills.py`
uses the Phase 2 core symbols (`SOURCES`, single `_load_schema()`,
single `agent-skill.schema.json`). Splitting would leave Phase 1 with
a broken validator that can't import its dependencies. ATX reviewer
explicitly recommended this — "batch Phase 1 + Phase 2 from same
commit so the invariant is never broken" (registry-manifest-reviewer
B2 fix option b).

## ATX iteration 1 — Phase 1+2 (resolved)

Rating: 1-2/5. Five blockers, all addressed in this commit:

| # | Status | Issue | Fix |
|---|---|---|---|
| B1 | Fixed | `tests/test_wheel_contents.py:144` hard-codes `clawrium/_skills/clawrium/tdd/SKILL.md` (deleted) | Assert `clawrium/_skills/vetted/tdd/SKILL.md` |
| B2 | Fixed | `scripts/validate_skills.py` imports `REGISTRIES` and references deleted per-claw schemas; `tests/test_validate_skills_script.py` collection-errors | Validator rewritten for flat layout (SOURCES + single schema); test module rewritten end-to-end against new fixture model (24 tests, all pass) |
| B3 | Fixed | `skills/README.md` uses retired `clm` entrypoint | Three `clm` → `clawctl` substitutions |
| B4 | Fixed | No schema-validation test for the 6 vetted skills | New `tests/test_vetted_skills_schema.py` — parametrized jsonschema validation; 13 tests, all pass |
| B5 | Fixed | `metadata` field used by 5/6 vetted skills but absent from schema | Added `metadata` to `agent-skill.schema.json` with `cadence`, `trigger`, `outputs` sub-fields |

Warnings:
| # | Status | Issue |
|---|---|---|
| W1 | Fixed | AGENTS.md quickstart + Skill Source Key Concept updated |
| W2 | Deferred | `docs/skills/authoring-clawrium.md` — Phase 6 |
| W3 | Deferred | `docs/skills/index.md` 10+ stale refs — Phase 6 |
| W4 | Acknowledged | Tags convention inconsistent between tdd and hermes-lineage skills — will revisit when 7th skill lands |
| W5 | Tracked | `tests/test_gui_skills_routes.py` references `core_skills.REGISTRIES` — Phase 4 must update |

Local checks:
- `make lint` clean (ruff + next-lint).
- `uv run pytest tests/test_vetted_skills_schema.py tests/test_validate_skills_script.py tests/test_wheel_contents.py` → 43 passed.

ATX iteration 2 verification of these fixes was interrupted by the
user mid-call (pivot to orchestrate mode). Documented as Callout in
the PR; the child claude in the orchestrator tmux window will run
iteration 2 before pushing Phase 3.

## Inherited from worktree (uncommitted at start)

Worktree was set up earlier and already contains Phase 1 and Phase 2
changes uncommitted. Captured for accountability before splitting into
per-phase commits.

Phase 1 (catalog):
- delete `skills/clawrium/tdd/{SKILL.md,_meta.yaml}`
- delete `skills/hermes/{README.md,blog-author,daily-digest,docs-sync,issue-triage,release-watcher}/`
- delete `skills/openclaw/README.md`, `skills/zeroclaw/README.md`
- delete `skills/_schema/clawrium.schema.json`, `skills/_schema/native/`
- modify `skills/README.md`
- new `skills/_schema/agent-skill.schema.json`
- new `skills/vetted/{tdd,blog-author,daily-digest,docs-sync,issue-triage,release-watcher}/SKILL.md`

Phase 2 (core):
- modify `src/clawrium/core/skills.py`
- modify `src/clawrium/core/skills_apply.py`
- modify `src/clawrium/core/skills_state.py`
- new `src/clawrium/core/skills_local.py`

Lint passes on the current worktree (`make lint` ✓).

## Fleet poll log

| Timestamp (UTC) | Status | Notes |
|---|---|---|

## ATX review log

| Phase | Iter | Rating | Cost | Time | Agents | Status |
|---|---|---|---|---|---|---|

## Notes / blockers

- Worktree was missing `src/clawrium/gui/frontend/` — copied from the
  main checkout to unblock `make lint`. Not committed (not tracked).
- pyproject.toml `force-include` was **not** updated — the existing
  `"skills" = "clawrium/_skills"` pattern still captures `skills/vetted/`
  by descent, so a more specific entry is redundant. Documented in
  Phase 1 commit message.

---

<details>
<summary>Prompt Log</summary>

## Orchestrator setup

**Stage**: orchestrator
**Skill**: /itx-execute
**Timestamp**: 2026-06-07T06:30:00Z
**Model**: claude-opus-4-7

```prompt
cool. go ahead and do this. continue work. make sure atx reivew happens for everything. dont interrput me. keep polling every 15 mins to check status of the fleet. use an orchestrator manifest to track work. what the fuck. you just got stuck for 6 hours
```

**Output**: `.itx/411/02_ORCHESTRATOR.md`, recurring fleet poll cron `7,22,37,52 * * * *`, 7-phase TaskCreate queue, switched to existing worktree at `clawrium-issue-411`.

</details>

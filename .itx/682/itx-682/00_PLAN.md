# V11 SDLC Smoke Test Plan (issue #682)

Authoritative source: [`.sdlc/SMOKE-TEST-RUNBOOK.md`](../../.sdlc/SMOKE-TEST-RUNBOOK.md). This plan only records the V11-specific deltas. Read the runbook first.

## Outcome
V11 SDLC pipeline run produces a single CHANGELOG entry and a Discord announcement, validating the env-skill + `clawctl agent exec` model. **This round additionally measures full pipeline wall-clock time and skips CI waits — both the triage plan PR and the exec CHANGELOG PR are merged ~5 seconds after open.**

## Runbook version note

Runbook §1a (added 2026-06-08T17:06 PT) and §5.3 now codify the "5s sleep + `--admin` merge, no CI wait" pattern as the **default** for TC-3. V11's only remaining delta vs the runbook is the full-pipeline timing capture.

| Area | Runbook default | V11 delta |
|---|---|---|
| Exec PR (TC-3) merge | Sleep 5s, then `gh pr merge --admin --squash --delete-branch` | Unchanged — runbook now matches the original V11 ask |
| Reporting | Per-TC time budgets only (§10) | **Capture T0…T7 UTC, post `full_time = T7 − T0` (mm:ss) + per-stage deltas as a final comment on #682; mirror to `.sdlc/SMOKE-TEST-V11.md`** |

Everything else follows the runbook verbatim.

## Pre-flight findings (2026-06-08T23:58Z, corrected after user signal "v10 is done")

| Check | Result |
|---|---|
| Agent fleet ready | ✅ all 4 `ready` |
| Only `*-env` skill attached | ✅ exactly one per agent |
| Snapshot bytes on host | ✅ maurice 11870 / triage 11474 / exec 11163 / gtm 10851 |
| gh auth + git credential helper | ✅ all 4 authed |
| Workstation tooling | ✅ gh / clawctl / ssh key all present |
| Previous round (V10/#679) landed | ✅ closed 2026-06-09T00:27:59Z; V9+V10 lines on remote main |
| Local main sync | ⚠️ 4 commits behind origin; `git pull --ff-only` blocked by untracked `.itx/{678,679,682}/`, `.sdlc/`, `docs-drift-watchdog-cron.md` |
| CHANGELOG scaffold | ⚠️ V7…V10 are all bare lines, no `## [Unreleased]` / `### Internal` headings — spec drift for 4 rounds, not blocking V11, file a follow-up |

### Pre-flight remediation (must happen before TC-2)

No PR0 needed. Two prep steps:

1. **Local sync**: move/stash untracked `.itx/{678,679,682}/` away (they conflict with remote's `.itx/678/00_PLAN.md` and `.itx/679/00_PLAN.md` from the V9/V10 rounds; mine for #682 stays in working tree but isn't committed). Then `git pull --ff-only origin main`.
2. **File CHANGELOG scaffold follow-up issue**: `CHANGELOG.md missing [Unreleased] / ### Internal headings — exec instructions silently drifted for 4 rounds`. Tag `bug`, `agent-created`. NOT blocking V11.

## Pipeline (in execution order)

1. **Pre-flight check** — DONE (see findings above).
2. **Local sync + scaffold follow-up issue** — sync local main with origin; file CHANGELOG-scaffold follow-up issue. No PR.
3. **T0 — orchestrator anchors the round.** Issue #682 already exists. Record T0 = now (UTC), **after** local sync completes.
4. **TC-2 — Triage** (runbook §5.2). Trigger `clawctl agent exec clawrium-triage -- chat --query "$PROMPT"` with `N=682`, `<n>=11`, Discord channel id `1513395156852674590`. Triage labels, writes `.itx/682/00_PLAN.md` on `triage/682-smoke-v11`, opens plan PR, self-reviews, self-merges.
   - Record **T1 = TC-2 start**, **T2 = plan PR merged**.
5. **TC-3 — Exec, with NO CI wait** (runbook §5.3, now the runbook default). Trigger `clawctl agent exec clawrium-exec -- chat --query "$PROMPT"` with `N=682`, `TRIAGE_PR=<from-T2>`, `ROUND=11`, Discord channel id `1506153398117077092`. Exec writes `CHANGELOG.md` line on `exec/682-smoke-v11`, runs `make test-py` + `make lint-py` (this is exec's own gate, kept — the CI bypass is on the merge side only), pushes, opens PR. Do NOT let exec self-merge.
   - Resume pattern from runbook §5.3 applies if the 120s chat ceiling cuts exec off mid-flow.
   - Record **T3 = TC-3 start**.
   - Record **T4 = exec PR opened**.
   - **`sleep 5`**.
   - `gh pr merge <exec-PR> --repo ric03uec/clawrium --squash --delete-branch --admin`. The `--admin` flag bypasses any required status checks; this is the runbook's documented pattern for smoke-test PRs only.
   - Record **T5 = exec PR merged**.
6. **TC-4 — GTM** (runbook §5.4). Trigger `clawctl agent exec clawrium-gtm -- chat --query "$PROMPT"` with `N=682`, `PR=<exec-PR>`, `ROUND=11`, Discord channel id `1494197384094416906`. GTM posts announcement + `[gtm] done:` comment.
   - Record **T6 = TC-4 start**, **T7 = `[gtm] done:` comment posted**.
7. **End-of-run check** (runbook §6). `gh issue view 682` shows `state: CLOSED`, ≥4 comments.
8. **Post-merge CI sweep** (ATX-S1). After T5, poll `gh run list --branch main --limit 1 --json conclusion,status,headSha,url` for the commit that closed the exec PR. If the run finishes `failure`, open a follow-up issue immediately (`bug`, `agent-created`) capturing the run URL — admin-merge means a red `main` is silently possible and the orchestrator must catch it explicitly. This sweep does NOT block T7 / TC-4 (already complete by then), it's a post-hoc guard.
9. **Timing report.** Compute:
   - **`full_time = T7 − T0`** (mm:ss) — the headline number #682 asks for
   - `triage_dt = T2 − T1`
   - `exec_dt = T5 − T3` (TC-3 start → exec PR merged; includes the 5s sleep)
   - `merge_wait = T5 − T4` (~5s + admin-merge round-trip)
   - `gtm_dt = T7 − T6`
   - Post all absolute UTC timestamps (T0…T7) and all five durations as a final comment on #682. Include the T0 anchor convention note.
10. **Per-round log.** Create `.sdlc/SMOKE-TEST-V11.md` per runbook §9, mirroring V9 format. Note in §"Workarounds applied": "Admin-merged exec PR after 5s sleep — runbook §5.3 default for smoke-test PRs."

## Files this plan will cause to change

Through pipeline execution, not directly:

- `.itx/682/00_PLAN.md` — written by triage on the `triage/682-smoke-v11` branch (this file, mirrored).
- `CHANGELOG.md` — one line under `[Unreleased]` / `### Internal` on `exec/682-smoke-v11`.
- `.sdlc/SMOKE-TEST-V11.md` — orchestrator-authored round log.

**No other files touched.** Runbook B6 ("Exec edits files outside spec") applies — verify `git diff --stat` on the exec branch is CHANGELOG-only before merging.

## Risks specific to V11

- **Admin-merging bypasses CI.** A CHANGELOG-only change is low blast radius, but the merge is fundamentally unverified — anything from a malformed markdown line to an unrelated test regression (e.g. someone else's commit on `main` interacting with this one) lands silently. `make lint-py` is a Python linter and does **not** check markdown; the local exec-side `make test-py` only covers Python tests, not changelog/markdown structure. The actual guards are (a) the small, mechanical nature of the diff (one CHANGELOG line) and (b) the post-merge CI sweep (step 8) catching anything red after the fact.
- **The 5-second sleep is fixed wall-clock**, not "wait for first CI check to register". If GitHub hasn't enqueued the checks yet, `--admin` merges cleanly anyway. If a check fires after merge it'll be on the merged commit, not the PR — captured by step 8.
- **T0 anchor choice matters for the reported `full_time`.** Definition: T0 = the moment the orchestrator triggers TC-2 (`clawctl agent exec clawrium-triage …`). TC-1 (issue filing) is excluded because it ran days ago when the runbook queue was seeded. Note this convention in the final comment so readers don't compare apples to oranges across rounds.

## Test Strategy

- Pipeline acceptance criteria per TC are in runbook §5.2 / §5.3 / §5.4 — don't restate.
- The V11-specific extras to verify:
  - Exec PR merged via `--admin` (visible in `gh pr view --json mergeStateStatus,mergedBy`).
  - No CI workflow finished before merge (`gh pr checks <exec-PR>` taken at T4 should show pending / not-started).
  - Post-merge `main` CI run conclusion captured (step 8 — sweep `gh run list --branch main --limit 1`).
  - Final #682 comment contains all eight timestamps (T0…T7) and the five durations including `full_time` mm:ss.
  - `.sdlc/SMOKE-TEST-V11.md` exists and matches the V9 shape.

## Subtasks

None — single-orchestrator execution, same as #677 / #678 / #679. The four "agent legs" are runtime, not subtask issues.

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-08T23:58:35Z
**Model**: claude-opus-4-7

```prompt
create a plan for 682, Do not wait for ci to finish for prs, just merge after 5 seconds, calculate fulltime of the smoke test
```

**Output**: V11 smoke-test plan layered on the `.sdlc/SMOKE-TEST-RUNBOOK.md` flow — overrides the runbook only on the exec-PR merge step (5s sleep + `--admin`, no CI wait) and adds T0…T5 timestamp capture plus a `full_time` reporting comment on #682. First draft was wrong: it collapsed the four-agent pipeline into a single direct PR and ignored the runbook entirely; this revision restores the Maurice/Triage/Exec/GTM flow.

# V12 SDLC Smoke Test Plan — Issue #683

Driven by [`.sdlc/SMOKE-TEST-RUNBOOK.md`](../../.sdlc/SMOKE-TEST-RUNBOOK.md). V12 round per the queue table (§ "Current round queue"). Pattern matches #678 (V9), #679 (V10), #682 (V11).

## Outcome
End-to-end run of the four-agent pipeline (maurice → triage → exec → gtm) closes #683 with:
- one `### Internal` line under `[Unreleased]` in `CHANGELOG.md`
- one Discord announcement in `🥁-announcements` (channel `1494197384094416906`)
- a recorded **fulltime** (wall-clock duration from issue creation to GTM done) in `.sdlc/SMOKE-TEST-V12.md` and as a closing comment on #683

No code changes — CHANGELOG-only diff per runbook §1 (TC-3 row).

## Deviation from runbook
The runbook already encodes "no CI wait" for the exec PR (§5.3 step 16: `sleep 5 && gh pr merge --admin`). This round adds **one** thing on top:

- **Fulltime measurement**: capture `T_start` (issue createdAt) and `T_end` (GTM `[gtm] done` comment createdAt), compute the delta, write it into the round log and post it as the final comment on #683.

Triage's plan PR self-merge (§5.2 step 12) and exec's orchestrator admin-merge (§5.3 step 16) both stay as-defined in the runbook — neither waits for CI.

## Prerequisites (runbook §2)
1. §2.1: `clawctl agent get` shows all four `clawrium-{maurice,triage,exec,gtm}` `ready`.
2. §2.2: `clawctl agent skill get --agent <each>` shows exactly one `clawrium/<agent>-env` skill per agent.
3. §2.3: ping each agent, then verify `.skills_prompt_snapshot.json` on wolf lists each `*-env` SKILL.md.
4. §2.4: `gh auth status` probe via triage (B3 / #649 sanity).

## Steps (mapped to runbook §1a "High-level execution summary")

1. **T_start capture** — `gh issue view 683 --repo ric03uec/clawrium --json createdAt --jq .createdAt` → record as `T_start`. TC-1 (issue creation) already complete (this issue exists with the three labels and the Outcome/DoD body).

2. **TC-2 Triage** — trigger via the §5.2 prompt with `N=683`, `ROUND=12`, channel ID `1513395156852674590`. Triage relabels, branches `triage/683-smoke-v12`, writes this plan, opens plan PR, self-reviews, **self-merges** (`gh pr merge --squash --delete-branch`, no sleep, no `--admin`, no CI wait — per §5.2 step 12). Captures `TRIAGE_PR`.

3. **TC-3 Exec** — trigger via the §5.3 prompt with `N=683`, `TRIAGE_PR=<from step 2>`, `ROUND=12`, channel ID `1506153398117077092`. Exec branches `exec/683-smoke-v12`, appends to `CHANGELOG.md`:
   ```
   - V12 SDLC smoke test ran end-to-end with clawrium-maurice (issue prep), clawrium-triage (plan #<TRIAGE_PR> merged), clawrium-exec (this PR), clawrium-gtm (announcement). (#683)
   ```
   Runs `make test-py` + `make lint-py` **locally** (must pass before PR — §5.3 "MUST still pass locally"). Opens PR with `Closes #683`. Exec does NOT merge.

4. **Orchestrator merges exec PR** — `sleep 5 && gh pr merge <EXEC_PR> --repo ric03uec/clawrium --squash --delete-branch --admin` (runbook §5.3 step 16). `--admin` required to bypass branch protection while CI is pending; this is the documented smoke-test-only exception. #683 auto-closes via `Closes #683`.

5. **TC-4 GTM** — trigger via the §5.4 prompt with `N=683`, `PR=<EXEC_PR>`, `ROUND=12`, channel ID `1494197384094416906`. GTM posts a single announcement with real PR title + URL (no placeholders), then posts `[gtm] done` comment on #683.

6. **T_end capture** — read the `[gtm] done` comment timestamp:
   ```
   gh issue view 683 --repo ric03uec/clawrium --json comments \
     --jq '[.comments[] | select(.body | startswith("[gtm] done"))][-1].createdAt'
   ```
   → record as `T_end`.

7. **Compute fulltime** —
   ```
   python3 -c "from datetime import datetime as d; \
     s=d.fromisoformat('$T_start'.replace('Z','+00:00')); \
     e=d.fromisoformat('$T_end'.replace('Z','+00:00')); \
     delta=e-s; \
     print(f'{int(delta.total_seconds())}s ({delta})')"
   ```

8. **Round log** — create `.sdlc/SMOKE-TEST-V12.md` following the §9 template (TC-1…TC-4 sections + final summary table). Final summary table MUST include a `Fulltime` row with `T_start`, `T_end`, and the computed delta.

9. **Post fulltime comment** — final comment on #683:
   ```
   [orchestrator] fulltime: <hh:mm:ss> (T_start=<iso> → T_end=<iso>)
   ```

## End-of-run checks (runbook §6)
- `gh issue view 683 --json state` → `CLOSED`.
- ≥4 comments on #683 (triage, exec, gtm, orchestrator-fulltime).
- `git log -1 -- CHANGELOG.md` shows exactly one new V12 line under `### Internal`.
- `🥁-announcements` shows exactly one V12 message (no duplicates, no `<placeholder>` leaks).
- `gh pr list --state merged --search "683 in:title,body"` shows two merged PRs (plan + exec).

## Files to Modify
- `CHANGELOG.md` — one line under `[Unreleased]` / `### Internal` (by exec in step 3).
- `.itx/683/00_PLAN.md` — this file (committed by triage on `triage/683-smoke-v12` in step 2).
- `.sdlc/SMOKE-TEST-V12.md` — round log written by orchestrator in step 8, including fulltime row.

## Risks / known blockers (runbook §7)
- **B1 #663**: never `agent chat`; always `agent exec -- chat --query` for all triggers.
- **B2 #665**: literal channel IDs in every `send_message` (1513395156852674590 / 1506153398117077092 / 1494197384094416906).
- **B4** (120s chat ceiling): TC-3 timeout during `make test-py` is normal — plan for one §5.3 "Resume pattern" call.
- **B5 #676**: ubuntu async flake is not a concern this round — orchestrator admin-merges 5s after open regardless of CI.
- **B6**: exec scope discipline — verify `git diff --stat` shows `CHANGELOG.md` only before merging.
- **Fulltime accuracy**: `T_start` is anchored to GitHub's `issue.createdAt` and `T_end` to the `[gtm] done` `comment.createdAt`; both are server-side timestamps, so the delta is deterministic and reproducible after the fact (re-derivable from `gh issue view 683 --json createdAt,comments`).

## Subtasks
None — single-task execution. Pattern matches #677 / #678 / #679 / #682.

## Total budget
Runbook §10 baseline is **~3–5 min per round** (V12 inherits this since CI is not waited on). Fulltime measurement adds ~10s for the timestamp queries + log write. Target: report fulltime, do not gate on it.

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-08T00:00:00Z
**Model**: claude-opus-4-7

```prompt
create a plan for 683, Do not wait for ci to finish for prs, just merge after 5 seconds, calculate fulltime of the smoke test
```

```prompt
update this with changes in sdlc runbook
```

**Output**: V12 SDLC smoke test plan rewritten to follow `.sdlc/SMOKE-TEST-RUNBOOK.md` step-by-step (§1a/§5.2/§5.3/§5.4/§6/§9). The "no CI wait, merge ~5s after PR open" behavior is already encoded in runbook §5.3 step 16 (orchestrator admin-merge); the only V12-specific addition is fulltime measurement (`T_start` = issue createdAt, `T_end` = GTM `[gtm] done` comment createdAt), written to `.sdlc/SMOKE-TEST-V12.md` and posted as a final `[orchestrator] fulltime: ...` comment on #683.

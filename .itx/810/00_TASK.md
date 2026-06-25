# Orchestration Brief — Issue #810

You own GitHub issue **#810** end-to-end in this worktree. The parent operator (devashish) has spawned three parallel claude sessions, one per bug (#810, #811, #812). They share root cause adjacency with the wolf-i openclaw failed-install history (#790 verification report).

## The Bug (tl;dr)
Failed `clawctl agent create` for openclaw leaves stale integration attachments on the agent record. A later `clawctl agent sync` then fails on a version-gate check (`brave plugin requires >= 2026.6.9`) even though the operator never asked to attach it in this session. Manual `clawctl agent integration detach` is the only unblock today — exact same anti-pattern as the documented `clawctl_upgrade_strips_attachments` class.

Read the full issue first: `gh issue view 810`.

## What "Done" Looks Like
1. **Extensive plan** capturing: root-cause hypothesis, solution options (with trade-offs), chosen approach, exact file-level changes, test strategy, and a **detailed live-host UAT plan**.
2. **Implementation** that lands the chosen fix.
3. **UAT executed against live agents** — capture transcripts under `.itx/810/evidence/`.
4. **atx CLI review iteration** until rating > 3/5 and no blockers.
5. Committed locally on branch `issue-810`. **Do NOT push and do NOT open a PR** — the operator handles that.

## Required Workflow
1. `/itx-plan-create 810` — extensive plan as described above.
2. `/itx-plan-scaffold 810` — phased exit-criteria checklist.
3. `/itx-execute 810` — implement.
4. `/itx-verify` — `make lint && make test`.
5. **Real-host UAT** (see below).
6. **atx CLI review** (see below).
7. Commit locally — stop there.

## Live Host Inventory
| Host | OS | Notes |
|---|---|---|
| `wolf-i` | linux | Where this bug was surfaced; openclaw record currently in failed-install state. Primary repro target. |
| `kevin` | linux/arm | Clean repro target if wolf-i state is too contaminated. |
| `mac-test` | darwin/arm64 | macOS coverage if change touches OS-fork paths. |
| `esper-macmini` | darwin | Secondary macOS option. |

Use `clawctl host get` to confirm reachability before UAT.

## UAT Expectations
- **Repro the bug first** on a live host (transcript → `.itx/810/evidence/<host>/00-baseline-repro.txt`) to prove the plan's understanding matches reality.
- **After fix**, re-run the exact same sequence on the same host(s) and capture a green transcript.
- For #810 specifically: simulate (or use) a `status=failed, installed_at=null` openclaw record with an integration that requires a newer version than installed. Validate that `clawctl agent sync` either routes cleanly to repair semantics or treats the version-gate as a warning when the daemon isn't running — whichever the plan picked.
- Cover both **happy path** (clean repair) and **degenerate cases** (e.g., what if the operator detaches mid-recovery; what if the upstream version subsequently catches up).

## atx CLI Review
The standalone CLI is at `/home/devashish/bin/atx`. Use it — **not** the MCP `mcp__atx__request_review` tool, even though `.claude/itx-config.json` defaults to MCP.

```
atx review --help        # see options
atx task --help
```

Iterate until rating > 3/5 with all blockers fixed or justified `Out-of-scope`. Record each round in the commit message per AGENTS.md `<commit-format-atx>` section.

## Constraints
- Honor project memory `feedback_no_push_without_ask`: never push, never open a PR.
- Honor `feedback_no_pr_without_real_host_uat`: PR body (when the operator opens it) must reflect live-host UAT — capture everything they'd need.
- Honor `feedback_run_make_lint_before_push`: ruff before pytest. `make lint && make test`.
- Honor `dispatcher-only_os_fork`: if you end up touching macOS paths, use parallel files routed by dispatcher, not `if Darwin` branches.
- Don't drift from the demo-pipeline replay-first rule if you happen to touch demo assets.

## Related Context
- Issue #790 verification report (callout C1): `.itx/790/03_VERIFY.md` on branch `verify/790-real-host` if you can fetch it; otherwise the full callout is quoted in the #810 issue body.
- Bug-class memory: `clawctl_upgrade_strips_attachments`.
- Sibling sessions are working #811 (zeroclaw control-plane/host divergence) and #812 (openclaw gateway port not bound after green sync). Don't coordinate directly; if you find shared root-cause, surface it in the plan and the operator will reconcile.

Start now. Begin with `gh issue view 810`.

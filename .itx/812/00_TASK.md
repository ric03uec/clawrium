# Orchestration Brief — Issue #812

You own GitHub issue **#812** end-to-end in this worktree. The parent operator (devashish) has spawned three parallel claude sessions, one per bug (#810, #811, #812). All three were surfaced during real-host verification of #790 on `wolf-i`.

## The Bug (tl;dr)
`clawctl agent sync` for openclaw on `wolf-i` (gateway port 40198) ends with `verify: checking unit is active` → `synced (drift=0)`. But on the host: `ss -tlnp | grep 40198` returns nothing and `curl http://127.0.0.1:40198/` returns `000`. The same sync against `esper-mac-oc` (Darwin openclaw) and `clawrium-exec` (hermes) returns HTTP 200 — so the issue is wolf-i-runtime-specific, not a sync-pipeline class bug. Possibly shares root cause with #810's failed-install history on wolf-i.

Read the full issue first: `gh issue view 812`.

## What "Done" Looks Like
1. **Extensive plan** capturing:
   - Root-cause hypothesis split: (a) the daemon crashes on startup vs. (b) the daemon runs but fails to bind vs. (c) the systemd unit reports `active` prematurely. Investigate `journalctl -u openclaw-wolf-i.service --since='<sync time>'` to disambiguate.
   - Whether this is shared root-cause with #810's wolf-i failed-install history (the issue body explicitly flags this).
   - Solution options: (i) `lifecycle.verify_agent` probes the gateway port and fails the sync, (ii) `sync` emits a yellow warning post-restart if port isn't bound, (iii) a separate `agent doctor` extension. Pick one with trade-offs documented.
   - Exact file-level changes, test strategy, and a **detailed live-host UAT plan**.
2. **Implementation** that lands the chosen fix.
3. **UAT executed against live agents** — capture transcripts under `.itx/812/evidence/`.
4. **atx CLI review iteration** until rating > 3/5 and no blockers.
5. Committed locally on branch `issue-812`. **Do NOT push and do NOT open a PR** — the operator handles that.

## Required Workflow
1. `/itx-plan-create 812`
2. `/itx-plan-scaffold 812`
3. `/itx-execute 812`
4. `/itx-verify`
5. Real-host UAT (see below)
6. atx CLI review (see below)
7. Commit locally — stop there.

## Live Host Inventory
| Host | OS | Notes |
|---|---|---|
| `wolf-i` | linux | Carries the broken openclaw runtime today. Primary UAT target. |
| `kevin` | linux/arm | For inducing a fresh "port-not-bound" repro on a clean openclaw install (e.g. kill the daemon or swap the unit ExecStart to a `sleep 9999` no-op). |
| `mac-test` | darwin/arm64 | For the working-baseline contrast: openclaw on macOS does bind correctly per the issue. Use this to prove the new probe doesn't false-positive on a healthy daemon. |
| `esper-macmini` | darwin | Secondary macOS option; `esper-mac-oc` openclaw was the contrast case in #790. |

Use `clawctl host get` to confirm reachability.

## UAT Expectations
- **Capture wolf-i baseline first**: `clawctl agent sync wolf-i` then `clawctl agent shell wolf-i -- 'ss -tlnp | grep 40198 ; curl -sf -o /dev/null -w "%{http_code}\\n" --max-time 4 http://127.0.0.1:40198/'` → `.itx/812/evidence/wolf-i/00-baseline.txt`.
- Also `journalctl -u openclaw-wolf-i.service --since='15min ago' -n 200 --no-pager` → `.itx/812/evidence/wolf-i/01-journal.txt`. Read it before settling on a root cause.
- **After fix**, `sync` should NOT print `synced (drift=0)` when the port isn't bound — either fail the sync with a repair hint, or emit a yellow warning. Capture transcripts on wolf-i proving the new behavior.
- **Negative-control**: run the same fixed sync against the working macOS openclaw (`esper-mac-oc` or whatever you can attach on `mac-test`/`esper-macmini`) and prove the probe doesn't false-positive on a healthy daemon. Transcript → `.itx/812/evidence/<mac-host>/`.
- **Induced repro on kevin**: if you can reproduce the symptom by mucking with the systemd unit on a clean install, capture that too — it strengthens the fix's coverage claim.

## atx CLI Review
The standalone CLI is at `/home/devashish/bin/atx`. Use **it** — not the MCP tool.

```
atx review --help
atx task --help
```

Iterate until rating > 3/5 with blockers fixed or justified. Record each round in the commit message per AGENTS.md `<commit-format-atx>` section.

## Constraints
- Project memory: `feedback_no_push_without_ask`, `feedback_no_pr_without_real_host_uat`, `feedback_run_make_lint_before_push`, `dispatcher-only_os_fork`.
- If your fix touches `lifecycle.verify_agent`, mind that **all three** of `configure`, `sync`, `restart` go through it for zeroclaw (Gateway Token Lifecycle invariant). Don't accidentally regress #437.
- Native dashboards (#478/#491): openclaw serves SPA on the same port as `gateway.port`, bind=wildcard. If your probe checks the gateway port, it implicitly also probes the dashboard — fine, but document it.

## Related Context
- Issue #790 verification report (callout C3): quoted in the issue body, including the `groupb` open-url probe table.
- Sibling sessions: #810 (openclaw stale attachments after failed install — same wolf-i host) and #811 (zeroclaw describe/state divergence). **#812's issue body explicitly flags possible shared root cause with #810** — if you find it, surface in the plan.

Start now. Begin with `gh issue view 812`.

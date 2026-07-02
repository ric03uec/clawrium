# Orchestration Brief — Issue #811

You own GitHub issue **#811** end-to-end in this worktree. The parent operator (devashish) has spawned three parallel claude sessions, one per bug (#810, #811, #812). All three were surfaced during real-host verification of #790 on `wolf-i`.

## The Bug (tl;dr)
zeroclaw agent `clawrium-d01` on wolf-i reports `status=ready, installed_at=2026-05-19` in `clawctl agent describe` and renders normally in the GUI — but on the host, `/home/clawrium-d01/.zeroclaw/` doesn't exist and `zeroclaw-clawrium-d01.service` is gone. Control plane and host state have silently diverged. `clawctl agent sync` only discovers it after running render + diff + write, then fails on `Unit zeroclaw-clawrium-d01.service not found.`

Read the full issue first: `gh issue view 811`.

## What "Done" Looks Like
1. **Extensive plan** capturing: root-cause hypothesis (host-state-probe gap in reconciler vs. sync-validate gap vs. both), solution options with trade-offs, chosen approach, exact file-level changes, test strategy, and a **detailed live-host UAT plan**. The plan MUST take a position on the open question in the issue: *should `clawctl agent get` / `agent describe` reflect on-host state, or is the current "what the control plane thinks" semantic intentional?* Pick one and document.
2. **Implementation** that lands the chosen fix.
3. **UAT executed against live agents** — capture transcripts under `.itx/811/evidence/`.
4. **atx CLI review iteration** until rating > 3/5 and no blockers.
5. Committed locally on branch `issue-811`. **Do NOT push and do NOT open a PR** — the operator handles that.

## Required Workflow
1. `/itx-plan-create 811`
2. `/itx-plan-scaffold 811`
3. `/itx-execute 811`
4. `/itx-verify`
5. Real-host UAT (see below)
6. atx CLI review (see below)
7. Commit locally — stop there.

## Live Host Inventory
| Host | OS | Notes |
|---|---|---|
| `wolf-i` | linux | Carries the bug today — `clawrium-d01` is exactly in this divergent state. Primary UAT target. |
| `kevin` | linux/arm | For creating a fresh repro (induce divergence by deleting `~/.zeroclaw` + the systemd unit manually) without polluting wolf-i. |
| `mac-test` | darwin/arm64 | macOS coverage if your fix lives in `core/render.py`, the status reconciler, or `clawctl agent describe` — these are OS-agnostic. |
| `esper-macmini` | darwin | Secondary macOS option. |

Use `clawctl host get` to confirm reachability.

## UAT Expectations
- **Capture the existing wolf-i baseline** before touching anything: `clawctl agent describe clawrium-d01`, `clawctl agent shell clawrium-d01 -- 'ls -la ~/.zeroclaw/ 2>&1; ls /etc/systemd/system/*zeroclaw* 2>&1'` → `.itx/811/evidence/wolf-i/00-baseline.txt`.
- **After fix**, the divergent state should be detected — either by `describe`/`get` reporting `degraded`/`unhealthy`, or by `sync`'s validate phase failing fast with a clear repair instruction. Capture transcripts proving the new behavior.
- **Independently induce divergence** on `kevin`: install a clean zeroclaw, then manually `rm -rf ~/.zeroclaw` + `systemctl disable --now zeroclaw-* && rm /etc/systemd/system/zeroclaw-*` on the host, and re-run `clawctl agent describe`/`sync`. Confirm same detection. Save transcripts → `.itx/811/evidence/kevin/`.
- Cover **happy path** (state still matches) and **degenerate path** (only home dir missing, or only systemd unit missing, or both).

## atx CLI Review
The standalone CLI is at `/home/devashish/bin/atx`. Use **it** — not the MCP `mcp__atx__request_review` tool, even though `.claude/itx-config.json` defaults to MCP.

```
atx review --help
atx task --help
```

Iterate until rating > 3/5 with blockers fixed or justified. Record each round in the commit message per AGENTS.md `<commit-format-atx>` section.

## Constraints
- Project memory: `feedback_no_push_without_ask`, `feedback_no_pr_without_real_host_uat`, `feedback_run_make_lint_before_push`, `dispatcher-only_os_fork`.
- Honor the Gateway Token Lifecycle rules (zeroclaw): every `configure`/`sync`/`restart` rotates the gateway bearer. Your fix must not regress that.
- If you touch `clawctl agent describe` or `clawctl agent get`, mind the GUI shape — `gui/routes/fleet.py` consumes the same field.

## Related Context
- Issue #790 verification report (callout C2): full sequence quoted in the issue body.
- Sibling sessions: #810 (openclaw stale attachments post-failed-install) and #812 (openclaw gateway port not bound after green sync). If you find shared root-cause with #811's "describe lies about state", surface it in the plan.

Start now. Begin with `gh issue view 811`.

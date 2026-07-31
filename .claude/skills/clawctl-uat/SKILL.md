---
name: clawctl-uat
description: Run the daily end-to-end UAT for clawrium on a real host — install fresh agents of every type, verify existing agents survive, file (and close) a dated issue with the report
argument-hint: "[<YYYY-MM-DD>] | [--host <alias>]"
---

# Daily Live UAT

Run the daily lifecycle sweep for clawrium on a real host. Every day this
skill installs one fresh agent per type, walks it through create → configure →
start → exec, exercises the marquee behaviour checks, verifies pre-existing
agents on the same host are undisturbed, cleans up, and files a dated GitHub
issue containing the report.

This is a **verification skill**, not a build skill. It never changes source
code. Its only side effects on the tree are `.itx/uat-daily/<date>/` artifacts.

## When to run

- Daily, from cron or `/schedule`, at a fixed local time (default 10:00 PT so
  the operator sees the report over their morning coffee).
- Manually after a significant merge, when you want a real-host smoke check
  before cutting a release.
- Before an on-call handoff, when you want to know the state of every managed
  host in one place.

Don't run this more than once per day per host — the ephemeral agent names are
namespaced by date (`uatYYYYMMDD-*`) and running twice will collide on
`agent create`.

## Modes

- `` (no args) — run today's UAT in UTC. Default host: `wolf-i`.
- `<YYYY-MM-DD>` — backfill for that date (uses the date literally in artifact
  paths and issue titles; still runs against the live fleet, so backfilling
  yesterday tests today's fleet with yesterday's label).
- `--host <alias>` — override the default host. Useful for a per-host UAT
  sweep (`clawctl:uat --host mac-test`).

## Preflight

Refuse to start unless:

```bash
git -C /home/devashish/workspace/ric03uec/clawrium rev-parse --is-inside-work-tree
uv run --directory /home/devashish/workspace/ric03uec/clawrium clawctl --version
uv run --directory /home/devashish/workspace/ric03uec/clawrium clawctl host get | grep -q <HOST>
command -v gh && gh auth status
```

Only one UAT session per host per day. Check for an existing artifact dir:

```bash
DATE=$(date -u +%Y-%m-%d)
if [ -d /home/devashish/workspace/ric03uec/clawrium/.itx/uat-daily/$DATE ]; then
  echo "Already ran today for $DATE. Delete .itx/uat-daily/$DATE/ to rerun."
  exit 0
fi
```

## The loop

| # | Step | Owner |
|---|---|---|
| 0 | Preflight; render template | orchestrator |
| 1 | Baseline — snapshot fleet, prove existing agents respond | orchestrator |
| 2 | Install — one fresh agent per type on `HOST` | orchestrator |
| 3 | Configure + Start — walk each fresh agent to `ready` | orchestrator |
| 4 | Marquee — narrow behaviour checks per type | orchestrator |
| 5 | Regression — re-run baseline; existing agents unchanged | orchestrator |
| 6 | Cleanup — delete fresh agents, diff against baseline | orchestrator |
| 7 | Write report | orchestrator |
| 8 | File + close GitHub issue "daily live UAT run <date>" | orchestrator |
| 9 | Append ledger entry | orchestrator |

Full step-by-step in `template.md` (sibling file). This SKILL.md is the
policy; `template.md` is the runbook.

## Render + execute

The template lives at `.claude/skills/clawctl-uat/template.md` (or
`.opencode/skills/clawctl-uat/template.md`, byte-identical). At the start of
each run, substitute the placeholders and copy the rendered plan into the
per-date artifact dir so the exact plan used for that run is preserved
alongside the report:

```bash
DATE=$(date -u +%Y-%m-%d)
DATE_COMPACT=$(date -u +%Y%m%d)
HOST=${HOST:-wolf-i}
PROVIDER=${PROVIDER:-clm-openrouter}
PREFIX="uat${DATE_COMPACT}"
DIR=/home/devashish/workspace/ric03uec/clawrium/.itx/uat-daily/$DATE
mkdir -p "$DIR"

sed -e "s/{{DATE}}/$DATE/g" \
    -e "s/{{DATE_COMPACT}}/$DATE_COMPACT/g" \
    -e "s/{{HOST}}/$HOST/g" \
    -e "s/{{PROVIDER}}/$PROVIDER/g" \
    -e "s/{{PREFIX}}/$PREFIX/g" \
  .claude/skills/clawctl-uat/template.md > "$DIR/plan.md"
```

Then execute the plan phase-by-phase. Do not batch phases — each phase writes
its own log so a mid-run abort leaves useful forensics.

## Filing the issue

Every run files one GitHub issue titled `daily live UAT run <date>`. This is
the searchable historical record. The issue body is the full report.

Close semantics:

- **PASS** — close immediately with a comment noting the verdict. The issue
  exists for search + audit; there is nothing to action.
- **FAIL** — leave open, apply `agent-blocked` label so it lands in the
  operator's queue.
- **PARTIAL** (some phases PASS, some FAIL, cleanup succeeded) — leave open,
  no `agent-blocked` — the operator triages severity.

```bash
gh issue create \
  --title "daily live UAT run $DATE" \
  --label "authored-by:local_qwen" \
  --body-file "$DIR/report.md"

ISSUE_NUM=$(gh issue list --search "daily live UAT run $DATE in:title" \
              --state open --json number --jq '.[0].number')

case "$VERDICT" in
  PASS)    gh issue close $ISSUE_NUM --comment "PASS. Report body has full log." ;;
  FAIL)    gh issue edit $ISSUE_NUM --add-label "agent-blocked" ;;
  PARTIAL) : ;;
esac
```

**Never create a new label.** The two used above (`authored-by:local_qwen`,
`agent-blocked`) already exist in the repo per the `clawctl-lmwork` skill's
label discipline. If either goes missing, comment on the issue and stop.

## Ledger

Append one line to `.itx/uat-daily-ledger.jsonl` in the main checkout (not in
a worktree — this file is cross-run, and lives on `main`):

```json
{"date":"2026-07-31","host":"wolf-i","verdict":"PASS","issue":123,"phases":{"preflight":"PASS","baseline":"PASS","install":"PASS","configure_start":"PASS","marquee":"PASS","regression":"PASS","cleanup":"PASS"},"anomalies":0,"ts":"2026-07-31T05:55:00Z"}
```

After ~30 runs this tells you which host has the highest false-fail rate,
which agent-type install path is flakiest, and which days correlate with
merges that need better test coverage.

## Anomalies vs blockers

Anomalies (stale error hints, hidden flags, verb-drift) go in the report's
Anomalies section as one-liners with severity `BLOCKER / WARN / NOTE`. Only
`BLOCKER` counts against the phase verdict. A run with three `WARN` anomalies
but every phase green is still PASS.

## Non-goals

- **Not** a replacement for `make test`. Unit tests catch code-shape bugs; this
  catches host-shape bugs.
- **Not** a security review. Use ATX (`atx review request`) for that on the PR
  being verified.
- **Not** a place to test speculative behaviour. Only checks landed on `main`
  belong in the marquee phase.
- **Not** allowed to modify source code. If a UAT reveals a bug, file a
  separate issue for the bug; this skill's issue records only what was
  observed, not what to fix.

## Recovery from a stuck run

If the artifact dir for today exists but no issue was filed, the previous run
died mid-flight. Check `.itx/uat-daily/<date>/` for the last log written, and
look for orphaned `uat<date>-*` agents in `clawctl agent get`. Delete those
first, then either delete the artifact dir to start clean or manually finish
Phase 6 + reporting.

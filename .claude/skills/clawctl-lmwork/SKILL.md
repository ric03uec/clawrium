---
name: clawctl-lmwork
description: Find work for the idle local LLM stack (Qwen3.6-27B on inx) and orchestrate it to a merged-ready PR via a pi worker and a Claude Code judge in tmux
argument-hint: "[<issue-number>] | scan | status"
---

# Local-Model Work Dispatch

Keep the local inference stack busy on clawrium work it can actually
finish, and drive that work to a reviewed PR without babysitting.

This skill is **clawrium-only**. The selection criteria and the
staleness checks below encode this repo's conventions; they do not
transfer.

## Roles

Three actors. Do not invent a fourth.

| Role | Is | Where |
|---|---|---|
| **orchestrator** | the session running this skill | your current window |
| **lmworker** | `pi` interactive, Qwen3.6-27B via `vllm-inx` | window `lmworker` |
| **lmjudge** | `claude --dangerously-skip-permissions` interactive | window `lmjudge` |

The orchestrator **never calls the local stack directly.** No `curl` to
LiteLLM, no API calls. It always spins up a pi harness and types into
it, exactly as a human would in an interactive session. That is the
entire point of driving this through tmux.

The orchestrator also does **not** touch source code, run tests, or
review diffs. lmworker writes; lmjudge reviews; lmworker calls ATX.
This mirrors the orchestration contract in
[`itx-execute`](../itx-execute/SKILL.md#orchestration-contract).

## Modes

- `scan` — harvest + staleness-check + classify, label `agent-ready`, dispatch nothing.
- `<issue-number>` — run the full loop for one issue.
- `status` — report in-flight sessions **and reconcile labels** (see below).
- no args — `scan`, then dispatch the top T1 candidate.

## Preflight

Refuse to start unless all of these hold:

```bash
ssh inx 'docker ps --format "{{.Names}}"' | grep -q vllm-qwen3.6-27b-fp8   # stack up
command -v pi && command -v tmux && command -v atx                         # tooling
atx server status | grep -q 'Running: true'                                # atx daemon
atx project status                                                         # project registered
```

Cap **2 issues in flight** — vLLM runs `num_seq=3`, and lmjudge is
Anthropic-side so it does not contend for the local stack.

## The loop

| # | Step | Owner |
|---|---|---|
| 0 | Preflight; count in-flight sessions | orchestrator |
| 1 | Harvest candidates | orchestrator |
| 2 | Staleness check → `DISPATCH` / `RESCOPE` / `CLOSE-REC` / `TRAP` | orchestrator |
| 3 | Classify T1 / T2 / park; label `agent-ready` | orchestrator |
| 4 | Create worktree + session + two windows | orchestrator |
| 5 | Write `<worktree>/.itx/<N>/lmwork-brief.md` | orchestrator |
| 6 | Claim issue (`in-progress`); send brief to `lmworker` window | orchestrator |
| 7 | Implement, commit locally | **lmworker** |
| 8 | Wait for idle; send review request to `lmjudge` window | orchestrator |
| 9 | Review; verdict `SATISFIED` or `REVISE` | **lmjudge** |
| 10 | `REVISE` → relay findings into the live pi session; back to 7. Max 3 rounds | orchestrator |
| 11 | `SATISFIED` → send the ATX command to `lmworker` | orchestrator |
| 12 | Run ATX, fix blockers. Max 3 iterations | **lmworker** |
| 13 | Open the PR; flip issue to `in-review` | **lmjudge** / orchestrator |
| 14 | Comment the outcome on the issue | orchestrator |
| 15 | Append to `.itx/lmwork-ledger.jsonl` | orchestrator |

Either ceiling exhausted → the PR opens anyway with `[ITX-STUCK]` and
Callouts, per the itx-execute contract. Never block waiting on the user.

## Labels

**Never create a label.** Every label below already exists. If a needed
label is missing, comment on the issue and stop — do not invent one.

| Label | Meaning here |
|---|---|
| `agent-ready` | T1 verdict: dispatchable as-is. Set by `scan`, cleared at dispatch. |
| `planning` | T2 verdict: needs decomposition before it can be dispatched. |
| `needs-triage` | Parked: the issue's own scope is too large; a human must split it. |
| `invalid` | `TRAP` — the issue as written is wrong and would cause harm if followed. |
| `complexity:xs\|s\|m\|l\|xl` | Size recorded at classify time. |
| `authored-by:local_qwen` | The local stack touched this — issue and PR alike. Sticky; never removed. |
| `in-progress` | Dispatched; a tmux session is live. |
| `in-review` | PR open, awaiting the user's merge. |
| `agent-blocked` | `TRAP` at staleness, or an `[ITX-STUCK]` PR. |

### Harvest verdicts are persisted, so the next pass reads instead of rescans

Every scanned issue leaves a verdict label behind. **An issue carrying no
verdict label has never been scanned** — that is the signal the next pass
uses to find new work. The one exception is `CLOSE-REC`, which is
identified by the orchestrator's prior comment instead.

| Verdict | Labels written | Next pass |
|---|---|---|
| T1 | `agent-ready` + `complexity:*` | dispatch |
| T2 | `planning` + `complexity:*` | decompose, flip to `agent-ready` |
| Park | `needs-triage` + `complexity:*` | skip until a human splits it |
| `TRAP` | `agent-blocked`, `invalid` | never dispatch |
| `CLOSE-REC` | none — comment only | recognized by the prior comment |

`CLOSE-REC` gets no label deliberately. No existing label means "already
delivered by shipped code" — `duplicate` means duplicate-of-an-issue, and
stretching it would corrupt a label other workflows rely on. The
orchestrator's own comment carries the evidence and is more informative
than a label would be. Closing stays the user's call.

**Verdicts persist; staleness does not.** `HEAD` moves between passes, so
step 2 re-runs on every labeled issue. Only step 3 classification is
skipped. A verdict label is a cached *judgment*, never a cached fact
about the code.

### Transitions

| Loop step | Event | Add | Remove | Board |
|---|---|---|---|---|
| 2 | Staleness = `TRAP` | `agent-blocked`, `invalid` | — | Blocked |
| 2 | Staleness = `CLOSE-REC` | — (comment only) | — | — |
| 3 | Classified T1 | `agent-ready`, `complexity:*` | `planning` | Next-up |
| 3 | Classified T2 | `planning`, `complexity:*` | — | Next-up |
| 3 | T2 decomposed | `agent-ready` | `planning` | Next-up |
| 3 | Parked | `needs-triage`, `complexity:*` | — | — |
| 6 | Dispatched to lmworker | `authored-by:local_qwen`, `in-progress` | `agent-ready` | Executing |
| 7–12 | Judge rounds, ATX | — | — | Executing |
| 13 | PR opened, clean | `in-review` | `in-progress` | Executing |
| 13 | PR opened `[ITX-STUCK]` | `in-review`, `agent-blocked` | `in-progress` | Blocked |
| — | User merges (swept by `status`) | — | `in-review`, `agent-blocked` | Done |

Two invariants:

- `in-progress` and `in-review` are **mutually exclusive**. Never both.
- `authored-by:local_qwen` is additive and permanent. It survives close,
  and is the queryable record of what the stack has shipped.

`in-progress` / `in-review` are also
[`itx-triage`](../itx-triage/SKILL.md)'s workflow ladder — claiming an
issue with `in-progress` stops triage from re-triaging it mid-run.

Board Status is project #1's `Status` field (`Backlog | Next-up |
Planning | Executing | Done | Blocked`). It is optional garnish; the
labels are the source of truth. Skip it silently if `gh project` lacks
scope — never fail a run over it.

---

## Step 1 — Harvest

Two sources.

**Open issues.** `gh issue list --state open --limit 200 --json number,title,labels`.

Then sort by what a previous pass already decided. **Do not re-classify
anything that already carries a verdict label** — that is the entire
point of writing them.

| Carries | Action |
|---|---|
| `agent-ready` | front of the queue. Re-run step 2 only; skip step 3. |
| `planning` | decompose into a task chain, flip to `agent-ready`, dispatch. |
| `needs-triage` | skip — a human must split the scope first. |
| `agent-blocked` or `invalid` | skip until the user clears it. |
| `in-progress` / `in-review` | skip — another run owns it. |
| no label, but an orchestrator `CLOSE-REC` comment already exists | skip — already assessed; do not comment again. |
| **none of the above** | unscanned. Run steps 2–3 and write a verdict. |

Check for a prior `CLOSE-REC` comment *before* falling through to the
last row, otherwise every pass re-derives the same verdict and posts a
duplicate comment:

```bash
gh issue view <N> --json comments \
  --jq '[.comments[] | select(.body | startswith("CLOSE-REC"))] | length'
```

Orchestrator comments for that verdict must therefore **begin with the
literal token `CLOSE-REC`** so this check is cheap and unambiguous.

Only that last row costs a full classification pass. On a warm backlog
`scan` is cheap: it re-checks staleness on the already-labeled queue and
does real work only on issues opened since the last run.

**Generated work** — renewable, no issue required, and the steady-state
filler when the issue queue is dry:

```bash
# doc-mirror drift (AGENTS.md: canonical docs/ → website/docs/)
for c in docs/agent-support/*.md docs/installation.md docs/host-preparation.md; do
  w="website/$c"; [ -f "$w" ] && { n=$(diff "$c" "$w" | grep -c '^[<>]'); \
    [ "$n" -gt 0 ] && echo "$c: $n lines"; }
done
```

Mirror drift is the single highest-confidence task class for this model —
the direction is always canonical → website, never the reverse, and the
only permitted divergence is Docusaurus frontmatter, the mirror-warning
comment, and absolute-path link rewrites.

## Step 2 — Staleness check (never delegate this)

The backlog contains issues that are already fixed, point at orphaned
modules, or whose literal instructions would *reintroduce* a bug. A 27B
asked "is this already fixed?" answers confidently and wrongly, so the
orchestrator does this itself, against current `HEAD`:

- Does every file/symbol the issue cites still exist? (line numbers drift; symbols matter)
- Is the cited module still imported by anything? `src/clawrium/cli/agent.py` is orphaned — fixes there are invisible to users (#707).
- Has the behavior already shipped under another name? (e.g. #645 was superseded by the Workspace Overlay, #760)
- Does the requested change **contradict** a documented contract in AGENTS.md?

Outcomes:

| Verdict | Action | Label |
|---|---|---|
| `DISPATCH` | issue is accurate as written | → step 3 |
| `RESCOPE` | partly done — the brief fences off the completed parts | → step 3 |
| `CLOSE-REC` | already delivered; comment the evidence on the issue, dispatch nothing | none |
| `TRAP` | following it literally would cause harm; comment why, **never dispatch** | `agent-blocked`, `invalid` |

```bash
gh issue edit <N> --add-label "agent-blocked,invalid"    # TRAP only
```

`invalid` carries *why* — the issue as written is wrong, not merely
blocked on something. That distinction is what stops a later pass from
retrying it once the "block" looks cleared.

**Known trap: #432.** Fixed by #649 via `_setup_github_integration` in
`lifecycle_canonical.py`. Its instructions say to add the task to
`configure.yaml` — which the modern CLI never invokes, and which is the
exact anti-pattern AGENTS.md §"Integration Binary Install" forbids.

## Step 3 — Classify

Four checks, from 20 prior `authored-by:local_qwen` PRs (18 merged):

1. Does the issue carry a real DoD, or can the orchestrator write one?
2. Can the orchestrator name **every** file to change in the brief? Search radius is where this model degrades fastest — it pattern-matches well and explores badly.
3. Is there an in-repo precedent to copy, by path? Every merged PR was a pattern-match.
4. Does sign-off require a real SSH host?

- All four favourable → **T1**, dispatch as-is.
- 1–3 weak → **T2**, orchestrator decomposes into a numbered task chain first, then dispatches.
- Real-host UAT required → code can still be written; the PR lands with an `[UNRESOLVED]` Callout stating UAT is the user's.
- Issue itself needs scope decomposition → **park**, do not dispatch.

Write the verdict before moving on. This is what lets the next pass skip
classification entirely:

```bash
gh issue edit <N> --add-label "agent-ready,complexity:s"                  # T1
gh issue edit <N> --add-label "planning,complexity:m"                     # T2
gh issue edit <N> --add-label "needs-triage,complexity:l"                 # parked
gh issue edit <N> --add-label "agent-blocked,invalid"                     # TRAP (step 2)
gh issue edit <N> --add-label "agent-ready" --remove-label "planning"     # T2 decomposed
```

A rescope can change the size, so clear the old complexity label before
writing the new one — otherwise an issue accumulates two and the next
pass cannot tell which is current:

```bash
gh issue edit <N> --remove-label "complexity:xs,complexity:s,complexity:m,complexity:l,complexity:xl" \
                  --add-label "complexity:s"
```

`scan` marks and stops there. The standing queues are then:

```bash
gh issue list --label agent-ready    # dispatchable now
gh issue list --label planning       # needs decomposition first
gh issue list --label needs-triage   # waiting on a human to split
```

## Step 4 — Session and windows

One session per issue. Two **windows** — not split panes.

```bash
N=<issue>; SLUG=<slug>
BRANCH="issue-${N}-${SLUG}"
WT="$(dirname "$(git rev-parse --show-toplevel)")/clawrium-issue-${N}"
S="clawrium-${N}-lmwork"

git worktree add "$WT" -b "$BRANCH" main
mkdir -p "$WT/.itx/${N}"

tmux new-session -d -s "$S" -n lmworker -c "$WT"
tmux send-keys -t "$S:lmworker" "pi --provider vllm-inx --model Qwen3.6-27B" Enter

tmux new-window -t "$S" -n lmjudge -c "$WT"
tmux send-keys -t "$S:lmjudge" "claude --dangerously-skip-permissions" Enter
```

Both sit idle at their prompts. Attach with `tmux attach -t clawrium-<N>-lmwork`.

`pi` resolves `VLLM_INX_KEY` from the env var, else from
`~/.pi/agent/extensions/.env`. If neither is populated:

```bash
ssh inx "sed -n 's/^LITELLM_MASTER_KEY=/VLLM_INX_KEY=/p' /home/devashish/vllm/env/vllm.env" \
  > ~/.pi/agent/extensions/.env
chmod 600 ~/.pi/agent/extensions/.env
```

The rewrite happens **on inx**, so the key never becomes a literal
argument in the orchestrator's command line, shell history, or agent
transcript — it travels only through the SSH stream into the file. The
inx runbook is explicit that this key is read on-host and never pasted
into chat or docs; a `$(ssh …)` substitution would violate that.

**Trust model.** lmjudge runs with `--dangerously-skip-permissions`, so
it rebases, opens PRs, and applies labels without confirmation. That is
acceptable only because the worktree is local, the branch is disposable,
and the PR still requires the user's merge. It is *not* a claim that
lmjudge's inputs are trusted: lmworker-authored code and GitHub issue
text both reach it. Two consequences the orchestrator must hold to —
never widen lmjudge's reach to `main`, and never let it merge.

Issue titles and bodies from `gh issue view` are attacker-influenceable
(anyone can file an issue). Before echoing them into the terminal or a
brief, strip bidi and zero-width codepoints, so a crafted title cannot
reorder what the orchestrator's log appears to say:

```bash
gh issue view "$N" --json title,body --jq '.title, .body' | python3 -c \
  "import sys,re;sys.stdout.write(re.sub(r'[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]','',sys.stdin.read()))"
```

Two things about that command are deliberate.

The codepoints are written as `\uXXXX` **escapes, never as literal
characters.** A filter that contains the very invisible characters it
strips is self-erasing: one editor normalization, clipboard round-trip,
or renderer pass silently eats them and leaves a regex that matches
nothing — and it still looks correct on screen.

Do **not** reach for `tr -d` here. These codepoints are multi-byte in
UTF-8, so a byte-range delete removes continuation bytes and leaves
mangled text behind rather than removing the character — it corrupts
the input instead of sanitizing it.

This mirrors `cli/output/_sanitize.py:sanitize_passthrough`, which
AGENTS.md already mandates for operator-controlled strings. Apply the
same filter to `.itx/<N>/lmwork-judge-<round>.md` before pasting it into
lmworker — see the pipe in step 10 below. lmjudge reads issue text
unsanitized, so anything it quotes verbatim would otherwise ride into the
worker's terminal.

**Serialization rule.** Both windows share one worktree. Never have both
agents active at once — send to `lmjudge` only after `lmworker` is idle,
and vice versa. Concurrent edits and review in one working directory
produce garbage reviews.

## Step 5 — Brief

Write `$WT/.itx/<N>/lmwork-brief.md` — inside the worktree, so it commits
onto the branch. This is the message typed into pi verbatim.

All run artifacts for an issue live in `.itx/<N>/` alongside the plan and
scaffold — brief, judge rounds, and the worker-done hint. Per AGENTS.md
`.itx/` is committed with the change, so these files land in the PR as the
record of how the issue was executed. They are exempt from the scope fence.

```markdown
Work on issue #<N> in this worktree. Read it first: `gh issue view <N>`

## Scope fence
Touch ONLY: <explicit file list> (plus .itx/<N>/ for run artifacts)
Do NOT touch: <explicit exclusions, incl. anything the staleness check found already done>

## Tasks
1. <one concrete change, with the file it lands in>
2. ...

## Pattern to follow
<path to the in-repo precedent> — mirror its structure.

## Rules
- Commit locally. Do NOT push. Do NOT open a PR.
- Do not add features, refactors, or abstractions beyond the tasks above.
- If a task turns out to be already done, stop and say so — do not invent work.
- Commit .itx/<N>/ along with your changes.
- When finished, run: echo done > .itx/<N>/lmwork-worker.done
```

Fence hard. Every prior failure came from the model going wide, not
from it being unable to make the change.

## Steps 6–10 — Drive the agents

Multi-line files go in via the paste buffer, **never** `send-keys
"$(cat …)"`. A brief is multi-line markdown, and `send-keys` turns each
embedded newline into a Return — which submits the brief to pi
line-by-line, so the model starts work on a fragment before it has read
the scope fence. `load-buffer` + `paste-buffer` delivers it as one
message.

```bash
# 6 — claim the issue, then hand work to lmworker
gh issue edit "$N" --add-label "authored-by:local_qwen,in-progress" \
                   --remove-label "agent-ready"
tmux load-buffer -b lmwork ".itx/${N}/lmwork-brief.md"
tmux paste-buffer -b lmwork -t "$S:lmworker"
tmux send-keys -t "$S:lmworker" Enter

# 8 — hand review to lmjudge, once lmworker is idle (single line: send-keys is fine)
tmux send-keys -t "$S:lmjudge" "Read .claude/skills/clawctl-lmwork/judge.md and follow it for issue #${N}, round 1." Enter

# 10 — relay findings into the LIVE pi session; context is intact, do not restate the brief
#      sanitize first — lmjudge reads attacker-influenceable issue text
python3 -c \
  "import sys,re;sys.stdout.write(re.sub(r'[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]','',sys.stdin.read()))" \
  < ".itx/${N}/lmwork-judge-1.md" | tmux load-buffer -b lmwork -
tmux paste-buffer -b lmwork -t "$S:lmworker"
tmux send-keys -t "$S:lmworker" Enter
```

### Idle detection

Interactive panes give no exit code. Poll:

```bash
tmux capture-pane -p -t "$S:lmworker" | tail -30
```

Treat as idle when the capture is **byte-identical across two
consecutive polls** and the tail shows an input prompt. Poll every
**~90 seconds** — a 27B task runs minutes; faster polling is noise.

`.itx/<N>/lmwork-worker.done` is a liveness hint only. It is **never**
proof the work is correct — this model's documented failure mode is
claiming completion when the work is unfinished (PRs #883, #879, both
closed for exactly this). Correctness is lmjudge's call, always.

If a window is idle but the tail shows the agent asking a question,
answer it from repo conventions and send the answer. Do not escalate to
the user mid-run.

## Step 12 — ATX (called by lmworker)

`atx` v26.07.09. **`atx review` is the wrong command here.** Session mode
requires Claude Code hooks to have captured the changes; lmworker is
`pi`, so its edits are invisible to those hooks and the review comes back
empty. Use the stateless one-shot:

```bash
# worktree name == branch name
WT_NAME=$(atx project worktrees list --format json \
  | jq -r --arg b "$BRANCH" '.worktrees[] | select(.branch==$b) | .name')

atx review request \
  --prompt "Review the full diff of this branch against main (git diff main...HEAD) for issue #<N>." \
  --worktree "$WT_NAME" \
  --format json \
  --timeout 15m
```

If the branch does not appear in `atx project worktrees list`, drop
`--worktree` and run the command from inside the worktree directory.

Sent to the pane as:

```bash
tmux send-keys -t "$S:lmworker" \
  "Run: atx review request --prompt 'Review the full diff of this branch against main (git diff main...HEAD) for issue #${N}.' --worktree '${WT_NAME}' --format json --timeout 15m — then fix every blocking issue it reports and commit." Enter
```

Useful surface:

| Command | Use |
|---|---|
| `atx review request -p "<scope>" --format json` | stateless review; the only correct variant for pi-authored changes |
| `atx review --format json` | session mode; **only** when a Claude Code session authored the changes |
| `atx task list --format json --status running` | is a review still in flight |
| `atx task cancel <id>` | recover a hung review |
| `--effort low\|medium\|high\|xhigh\|xtreme` | per-call effort override |

Output is the v2 envelope: `atx_review.*` plus `caller_instructions`.

**Reading the rating.** The `.rating` field in `atx task list --format json`
is a coarse aggregate that can disagree with the leader's `Rating: N/5`
line inside `.result`. **Trust the review body, not the JSON field**, and
never `tail -n` the CLI output — the full body is authoritative.

Ceiling: 3 iterations. Clear at Rating > 3/5 with no blockers.

## Step 13 — PR (opened by lmjudge)

lmjudge opens the PR, not lmworker. The model that wrote the code is the
wrong one to certify it — that is the precise failure that closed #883
and #879.

```bash
tmux send-keys -t "$S:lmjudge" "Open the PR for #${N}. Use .github/PULL_REQUEST_TEMPLATE.md verbatim. Rebase on origin/main first. Include the ATX Review Summary and a Callouts section. Apply the existing label authored-by:local_qwen. Do not create any new labels." Enter
```

Requirements:

- `.github/PULL_REQUEST_TEMPLATE.md` **verbatim** — not an ad-hoc shape.
- **Rebase on `origin/main` before opening.** Long-lived branches drift and regress content; that is what closed #883 and #879. Same-day land or bounce.
- ATX Review Summary table per AGENTS.md `<pr-format-atx>`.
- Callouts section, even if `_None._`
- Apply the **existing** `authored-by:local_qwen` label to the PR. **Never create a new label.**

Once the PR is open, the orchestrator flips the issue:

```bash
gh issue edit "$N" --add-label "in-review" --remove-label "in-progress"
gh issue edit "$N" --add-label "agent-blocked"     # [ITX-STUCK] PRs only
```

## Step 14 — Issue comment

The orchestrator comments the outcome on the issue: what shipped, what
was found already-done, and anything deferred. Applying existing labels
is allowed and expected; **creating** one never is.

For `CLOSE-REC` and `TRAP` verdicts, comment the evidence and stop. The
close decision is the user's.

## Step 15 — Ledger

The ledger is cross-issue, so it lives in the **main checkout**, not the
worktree — it never rides along in any one issue's PR. Append one line to
`.itx/lmwork-ledger.jsonl`:

```json
{"issue":123,"tier":"T1","shape":"doc-mirror-sync","judge_rounds":1,"atx_iterations":1,"atx_rating":4,"outcome":"pr-opened","pr":940,"ts":"2026-07-30T12:00:00Z"}
```

`shape` is the task archetype (`doc-mirror-sync`, `dead-code-delete`,
`guard-clause-widen`, `symbol-extract`, `middleware-add`,
`test-coverage-add`, …). After ~20 runs the ledger tells you which
shapes clear first try, and the step-3 criteria get tuned from data
instead of judgment.

## `status` mode — the reconciling sweep

Nothing polls for merges. `status` reconciles instead, and running it is
what returns issues to a clean state. For every issue carrying
`in-progress` or `in-review`:

```bash
gh issue list --label "in-progress" --json number,title
gh issue list --label "in-review"  --json number,title
tmux ls 2>/dev/null | grep lmwork
```

| Observed | Action |
|---|---|
| `in-review`, linked PR **merged** | remove `in-review` **and `agent-blocked`**; board `Done`; kill session; remove worktree |
| `in-review`, linked PR **closed unmerged** | remove `in-review`, add `agent-blocked`, comment why |
| `in-review`, PR still open | leave alone |
| `in-progress`, tmux session live | leave alone; report current round |
| `in-progress`, **no** live session | stale claim from a crashed run — remove `in-progress`, restore `agent-ready`, comment that the run aborted |

That last row is the one that matters. Without it a killed terminal
strands an issue as permanently "in progress", and the next `scan`
silently skips it forever.

## Cleanup

```bash
git worktree remove ../clawrium-issue-<N>    # --force if dirty
tmux kill-session -t clawrium-<N>-lmwork
```

Leave both in place while the PR is open — reviewers may ask for changes,
and the live pi session still holds the full context.

## Current queue

Re-derive with `scan`; this is the 2026-07-30 baseline.

**T1 — dispatch as-is:** #418 (rescoped: `_safe_serve` already fixed),
#642, #707 Ph.2–3, #788 Ph.1, #754, #122 (rescoped to `--description`),
#140 (pin the schema shape first — the PRD body and plan comment
disagree), #342 test-coverage subset, plus live doc-mirror drift.

**T2 — decompose first:** #826 Ph.1, #149 (B7/B8), #343 (npm pin),
#573, #693, #460 CRUD half, #586, #141 (pin the redaction list —
bearer-token leak risk), #788 Ph.2, #707 Ph.4, #657 (orchestrator
defines the tag vocabulary; lmworker applies it to 6 files).

**TRAP:** #432. **CLOSE-REC:** #451, #133, #99.

**Park:** anything needing product design, upstream research, a new
agent type, or architecture selection.

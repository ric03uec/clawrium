# Issue #629 — Configure Maurice as the project manager agent

Issue: https://github.com/ric03uec/clawrium/issues/629

## Issue Creation

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-06-06T00:00:00Z
**Model**: claude-opus-4-7

```prompt
configure maurice as the project manager agent for clawrium. maurice has two
high level tasks: find new work and decide work pipeline for agents (this list
will grow). use the existing configuration for maurice to understand what its
current configuration looks like including soul, models, cron jobs etc. dont
create an issue first. lets plan this out end to end first. also, maurice will
use a selection of models from this list [qwen3-coder-next, nemotron-cascade-2,
glm-4.7-flash, gemma4, minimax-m2.7:cloud, glm-4.6:cloud, qwen3-coder:30b
variants, gpt-oss:20b variants, olmo-3.1:32b variants, qwen2.5:72b,
deepseek-r1:70b, ...] which is available to it and include some cloud models as
well for high level reasoning tasks. go do the research first.

Follow-ups during planning:
- "release watcher is NOT checking upstream. do a better job. also use the
  actual skills from the agent to build this context, not the control plane
  data. other sources are any discussions in hackernews about agentic
  capabilities that can make this agent better (do a daily scan)."
- Labels: needs-triage, agent-created, source:upstream-deps, source:community,
  complexity:<x>.
- "hermes supports multiple attachments. do a better job."
- "use deepseek/deepseek-v4-flash from openrouter (create this provider) and
  use this for the agent as the primary. for now, make all profiles use this
  model."
- "work finder release should be called work finder upstream"
```

**Output**: GitHub issue #629 — single parent with 7 phases (labels+LABELS.md,
provider+profiles, new skills, cron schedule, SOUL update, control-plane
reconciliation, validation).

## Revision (same session)

After label audit and flow review with devashish, the plan was revised:

- **No Discord DM** for work-discovery output. Maurice writes GitHub issues
  directly. The only filter for humans is the `agent-created` label.
- **Mandatory dedup gate**: at most 3 `gh issue list --search` queries per
  candidate, including closed issues. Only on no match does Maurice create
  a new issue. The dedup queries are written into the new issue body as an
  audit trail.
- **Source-bump priority ladder**: when a match is found and the surfacing
  source is new for that issue, Maurice posts a parseable
  `[maurice:source-bump]` comment and bumps priority one rung
  ((none) → p3 → p2 → p1). Three or more distinct source bumps force
  `priority:p1`. Same source twice is a no-op.
- **Endpoint of Maurice's responsibility is `issue-triage`** — execution flow
  is human territory.
- **Labels**: do NOT create `type:feature`; keep `enhancement`. Reuse the
  existing `complexity:xs|s|m|l|xl`. Create 3 `source:*` labels (teal/blue
  family) and 3 `priority:p1|p2|p3` labels.
- **Validation**: a few human-watched live loops, not an automated harness.

Issue #629 body was updated to reflect the above.

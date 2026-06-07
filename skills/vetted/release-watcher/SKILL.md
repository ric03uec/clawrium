---
name: release-watcher
description: Watch upstream *Claw releases and clawrium discussions; surface top 3 feature candidates to Devashish via Discord DM for approve/skip.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]
metadata:
  cadence: "daily"
  trigger: "cron"
  outputs: ["discord-dm", "github-issue"]
---

# release-watcher

Once per day, scan upstream `*Claw` releases and the
`ric03uec/clawrium` GitHub Discussions for feature ideas that could
land in clawrium. Surface the top 3 candidates to Devashish via Discord
DM with an approve / skip pattern. On approval, file a GitHub issue.

## Inputs

- Releases (last 7 days, GitHub API):
  - `openclaw/openclaw` releases
  - `zeroclaw/zeroclaw` releases
  - `nousresearch/hermes` releases
  - Any additional supported `*Claw` repos listed in
    `platform/registry/*/manifest.yaml` (look up dynamically; don't
    hardcode).
- `gh api repos/ric03uec/clawrium/discussions` — open discussions
  updated in the last 7 days, sorted by reaction count.
- Memory key `release-watcher:seen` — release tag IDs already
  presented, so candidates don't repeat across days.

## Scoring

Pick the 3 candidates that score highest on:

1. **User-facing**: does this change something a clawrium user would
   directly touch (CLI, GUI, agent behavior, install flow)?
2. **Fits clawrium's surface**: matches an existing primitive
   (agent type, integration, channel, skill) rather than introducing
   a new top-level concept.
3. **Cheap to land**: rough fit in an afternoon's work, not a quarter.

Skip:

- Pure internal refactors in the upstream project.
- Features that depend on infrastructure clawrium does not have
  (custom kernels, GPU sharding, etc.).
- Anything already covered by an open issue (check before suggesting).

## Output — Discord DM

Send a single DM to user `740723459344302120` (Devashish) in the
project guild. **Slack is not used** — the original issue proposed
Slack DM for this flow; release-watcher uses Discord DM in the same
guild instead.

Format:

```
Release watch — <YYYY-MM-DD> — 3 candidates

1. <project> <tag> — <one-line rationale>
   <link>

2. <project> <tag> — <one-line rationale>
   <link>

3. <project> <tag> — <one-line rationale>
   <link>

Reply: `approve 1 2` to file issues, `skip all`, or `skip 3` to drop
the third while keeping 1+2 in tomorrow's pool.
```

Wait up to 24 hours for a reply. If no reply by next run, treat as
`skip all` and move on — do not nag.

## On approval

For each approved candidate, create a GitHub issue on
`ric03uec/clawrium`:

- Title: `<verb> <feature> from <project> <tag>`
- Body: link to the upstream release notes + the one-line rationale.
- Labels: best-effort `type:*` and `area:*` from the candidate
  description. Do **not** apply `agent-ready`.
- Assign no one — Devashish chooses the owner later.

Append the candidate's release tag to `release-watcher:seen`.

## Hard constraints

- One DM per day. If nothing crosses the bar, send a one-liner:
  "Release watch — quiet day, no candidates." Silence reads as broken.
- Do not file issues without an explicit `approve N` from Devashish.
- Never apply the `agent-ready` label (PAT-blocked).
- Discussions are read-only here — do not post a comment in the
  discussion thread itself.

## Anti-patterns

- Presenting 5 candidates because they all "look promising." 3 is the
  cap; rank harder.
- Re-presenting yesterday's `skip` items the next day. Use the
  memory key.
- Filing an issue then immediately self-assigning a triage label.
  Triage is `issue-triage`'s job; let that skill run on the new
  issue.

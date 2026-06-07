---
name: issue-triage
description: Triage new and updated GitHub issues on ric03uec/clawrium — apply type/complexity/area labels and draft a planning file.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]
metadata:
  cadence: "every 10 minutes"
  trigger: "poll"
  outputs: ["labels", "pull-request"]
---

# issue-triage

Triage incoming work on `ric03uec/clawrium`. Run on a 10-minute poll cycle.
The loop is: find issues that need triage → read them carefully → apply
labels → draft a planning file as a PR.

## Inputs

For each candidate issue:

- Title and body.
- Current labels (skip if `needs-triage` is absent or the issue already
  has a `type:*` label).
- The repo's `LABELS.md` for the allowed taxonomy. **Do not invent labels.**

Candidates are issues opened or updated in the last 15 minutes (giving
the poll a 5-minute overlap so nothing is missed during a slow run). Use:

```bash
gh issue list --repo ric03uec/clawrium \
  --search "sort:updated-desc updated:>$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --json number,title,body,labels,updatedAt
```

## Output

- Apply labels from the taxonomy in `LABELS.md`. At minimum: one
  `type:*`, one `complexity:*`, one `area:*`. Add `needs-review` when
  the issue lacks a clear Definition of Done.
- Open a PR adding `.itx/active/<issue-number>/plan.md` with a one-page
  scaffold (Outcome / Approach / Files / Risk). Title:
  `chore(triage): draft plan for #<n>`. Body links to the issue.

## Hard constraints

- **Never** apply the `agent-ready` label. The PAT denies it; even if it
  did not, this label is a human decision.
- **Never** push directly to `main` or merge a PR. PRs target `main`
  with a feature branch named `triage/<issue-number>-<slug>`.
- If the issue body is empty or one sentence, label `needs-review` and
  leave a single short comment asking for Outcome + Definition of Done.
  Do not invent requirements.
- If `LABELS.md` is missing or unreadable, stop and post a `[ITX-STUCK]`
  comment on the issue rather than guessing label names.

## Anti-patterns

- Re-labeling issues that already have a `type:*` label — assume a
  human or earlier triage decided. Touch only the missing dimensions.
- Drafting an `.itx/active/<n>/plan.md` that exceeds one page. The plan
  is a starting point for `/itx:plan-create`, not a substitute for it.
- Commenting on the issue with summaries of the body. The body is the
  source of truth; do not paraphrase it back.

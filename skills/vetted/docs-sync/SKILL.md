---
name: docs-sync
description: Detect user-visible changes from the last 24h of commits on main and propose doc and scenario updates as PRs.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]
metadata:
  cadence: "daily"
  trigger: "cron"
  outputs: ["pull-request"]
---

# docs-sync

Once per day, find code changes that altered user-visible behavior and
propose corresponding updates to `docs/` and `scenarios/`. The goal is
that anyone running the documented commands or following the scenarios
hits the same surface real users hit today.

## Inputs

- `git log --since='24 hours ago' --first-parent main` for the commit
  set (first-parent skips merge-squash internals when present).
- `git diff <prev>..<head>` per logical change.
- The current state of `docs/` and `scenarios/`.

## Triage rule — what counts as "user-visible"

Include a change in scope when **any** of the following is true:

- Adds, renames, removes, or changes the signature of a `clm` CLI
  command or option (`src/clawrium/cli/`).
- Changes a documented config path or env var.
- Changes an installation, configuration, or onboarding stage.
- Changes a GUI route, control, or visible label.
- Changes output of a `clm ps`-style status command in a way a user
  would notice.

Exclude pure refactors, test-only changes, dependency bumps that do
not change observable behavior, and internal log strings.

## Output

For each cluster of related changes, open **one** PR titled:

`docs(<area>): sync with <one-line behavior change>`

PR contents:

- Doc edits limited to the surface that actually changed.
- Scenario updates limited to scenarios the change actually breaks.
- **Hard cap: 2 new scenarios per run.** Prefer updating an existing
  scenario over adding a new one. If you would exceed the cap, leave
  a TODO comment in the PR body listing the deferred scenarios.

## Hard constraints

- Do not edit `docs/` purely for tone or grammar — out of scope.
- Do not touch `AGENTS.md`, `CLAUDE.md`, or `.itx/` from this skill.
- If the diff is unclear, open the PR anyway with `[draft]` in the
  title and request input from the author of the originating commit
  (one short PR-body line: "@<author> — please confirm the
  user-facing wording").
- Never merge your own PRs. The PR opens against `main` and waits for
  human review.

## Anti-patterns

- Bulk-updating every doc that mentions a renamed term. Touch only the
  paths the diff actually changes.
- Inventing scenarios that the code doesn't exercise. Scenarios must
  be runnable on a fresh checkout.
- Producing one mega-PR for a day's worth of changes. One PR per
  logical doc unit, even if that means three PRs in a single run.

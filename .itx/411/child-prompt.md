# Child execution prompt — Phases 3-7 of #411

You are resuming work on issue #411 in the worktree at
`/home/devashish/workspace/ric03uec/clawrium-issue-411`, branch
`issue-411-ad-hoc-skills`, PR #634 already open against `main`.

## Where things stand

Phases 1 and 2 are done and committed (commit on this branch:
"feat(skills): Phase 1+2 — flat catalog migration + core refactor for
#411"). PR #634 is open. Local `make lint` is clean and the new test
files pass (43 tests).

Read these before doing anything:

- `.itx/411/00_PLAN.md` — overall design
- `.itx/411/01_SCAFFOLD.md` — 7-phase scaffold with entry/exit criteria
- `.itx/411/02_ORCHESTRATOR.md` — orchestrator manifest (current state)

## Your job

Work through Phases 3 through 7 sequentially **on the same branch**
(`issue-411-ad-hoc-skills`) and **push to the same PR** (#634).
One commit per phase. Do not open new PRs.

Before each commit:

1. Run `make lint` — must pass.
2. Run the tests touched by that phase — must pass.
3. Request ATX review via `mcp__atx__request_review` with a scoped
   prompt naming only the phase's diff. Iterate until rating > 3/5
   and no blockers. AGENTS.md §"If MCP Review Enabled" is the
   contract.
4. Commit with the ATX summary in the commit body (template:
   AGENTS.md §commit-format-atx).
5. `git push` to update PR #634.
6. Update `.itx/411/02_ORCHESTRATOR.md` Phase status row.

Also, **before Phase 3**: re-run ATX iteration 2 on the existing
Phase 1+2 commit to verify the 5 blocker fixes. If iteration 2
returns new blockers, address them as an amend or a follow-up commit
on the same branch; update PR body. The Phase 1+2 commit message
documents that iteration 2 was interrupted — this is the place to
close it out.

## Phase entry/exit criteria

Phase 3 — CLI surface:
- `cli/skill.py` adds `add`, `edit`, `remove`; `list` shows `Source` +
  `Supported on`; `show` renders source badge + supported-claws.
- `cli/agent_skill.py` parses new refs, surfaces `ClawNotSupported`.
- Exit: `clm --help` etc. render without errors; `make lint` clean.

Phase 4 — GUI backend:
- `gui/routes/skills.py` CRUD endpoints (GET unified list, POST/PUT/
  DELETE for local-source skills) with vetted-read-only +
  name-immutable enforcement.
- Update `tests/test_gui_skills_routes.py` (currently breaks at
  Phase 2 — `core_skills.REGISTRIES` no longer exists).
- Exit: `make test` passes for new route tests.

Phase 5 — GUI frontend:
- `gui/src/app/skills/page.tsx` flat list + Create modal.
- New `skill-create-form.tsx`, hooks, types refactor.
- Exit: `make test` + `pnpm build` pass.

Phase 6 — Slash command + docs:
- `.claude/commands/skill-create.md`.
- Sweep `docs/skills/` for stale refs (W2, W3 from the Phase 1+2
  ATX). At minimum rewrite `docs/skills/authoring-clawrium.md` and
  `docs/skills/index.md` for the vetted/local model.

Phase 7 — Tests + E2E + final ATX:
- Rewrite `tests/core/test_skills*.py`, `tests/cli/test_skill*.py`,
  `tests/gui/routes/test_skills.py`, frontend tests.
- `make test` + `make lint` clean, no xfail / skip markers related
  to this issue.
- AC-1 (CLI E2E) and AC-2 (GUI E2E) against a real Hermes agent;
  capture outputs into PR #634 body.
- Negative AC: openclaw/zeroclaw `attach` exits non-zero with
  `ClawNotSupported`; GUI install button disabled with tooltip.

## Operating rules

- **Do not block on user input.** No `AskUserQuestion`. When in doubt,
  follow existing project standards (CLAUDE.md, AGENTS.md, neighboring
  code) and record the decision as a `[DECISION]` Callout in the PR
  body when you next update it.
- **One PR.** Same branch, same PR. Do not open new PRs.
- **ATX per phase.** Best-effort fallback chain per
  `/itx:execute` §"ATX Review (resilient, non-blocking)". Persist
  `.itx/411/atx-session.json` so this session can resume across
  interruptions.
- **Update the manifest** (`02_ORCHESTRATOR.md`) after every phase.
- **Real-host AC**: the `mac-test` host (`100.120.88.97`, darwin/arm64)
  is the standing real-host verification target — use it without
  asking.

When all 7 phases are done and the final ATX cleared, update PR #634
body with the full iteration history (AGENTS.md §pr-format-atx) and
the AC-1/AC-2/negative-AC captures, then stand down.

Start by reading the three `.itx/411/*.md` files in order, then
running ATX iteration 2 on the existing HEAD.

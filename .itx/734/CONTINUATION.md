# Issue #734 — Execution Continuation

**Read this BEFORE any other action.** Spawned by parent session on 2026-06-19 to drive existing staged work to a PR. **Updated at 20:44** after first child claude died — see "Run 1 history" below.

## State on entry (Run 2)

- Worktree: `/home/devashish/workspace/ric03uec/clawrium-issue-734` — **already exists; DO NOT recreate**.
- Branch: `issue-734-brave-integration` (tracking `origin/main`; no upstream of its own yet).
- HEAD: at the merge commit of PR #735 (the planning-doc PR). The branch is even with main; nothing committed yet for the feature work.
- **~23 files staged, no commits.** Includes most of Phase 1 (registry, render, templates, lifecycle, CLI, openclaw playbook + macOS sibling, tests) and Phase 2 (docs + CHANGELOG + website mirror), plus run-1's hermes name-mapping fix and the planning docs themselves. See `git status --short` for the full list.
- **`.itx/734/01_SCAFFOLD.md` is now present** (was missing from run 1 — fixed).

## Run 1 history (what already happened)

A previous claude session was spawned with this same CONTINUATION.md and worked for a short time before exiting (tmux session disappeared, no commits, no PR). What it did before dying:

- Moved hermes `BRAVE_API_KEY` → `BRAVE_SEARCH_API_KEY` name-mapping **out of Jinja and into `render_hermes()` Python** (`src/clawrium/core/render.py` around line 961). This is the correct #622 invariant fix — DO NOT revert.
- Simplified the hermes Jinja template's brave branch to just read the already-normalized `BRAVE_SEARCH_API_KEY` from creds. Comment in the template explains where the rename lives.
- That's it. No commit. No tests run. No ATX call. No PR.

Both of run 1's edits are already `git add`-staged by the parent before Run 2 starts. You do not need to redo them.

## Likely cause of run-1 death

Run 1 was spawned without `.itx/734/01_SCAFFOLD.md` in the worktree (the scaffold lived only on `main`, not on `issue-734-brave-integration`). Without the scaffold, run 1 had no per-phase exit criteria to march against. It likely fixed the most obvious gap from this file's "gap-check" list (hermes name-mapping), couldn't orient on what was next, and exited.

For run 2: the scaffold is now in place. Use it. Phases 1 and 2 are 90% done; your job is to drive to PR.
- Phase 3 (live host verification) is NOT in scope for this autonomous session — it requires operator action on `espresso` / `clawrium-d01` / an openclaw ≥2026.4.10 host.

## Hard overrides for this run

1. **ATX CLI ONLY.** Use `atx review --format json` (CLI). Do NOT call `mcp__atx__request_review`. Override `.claude/itx-config.json`'s `mcp.review_enabled: true` for this run — treat MCP as unavailable and go straight to the CLI step of the detection chain. Reason: user explicitly asked for CLI in this run.
2. **DO NOT recreate the worktree.** It already exists. The `/itx-execute` skill's worktree-mode steps don't apply — you're already inside the worktree and running in regular mode.
3. **DO NOT reset the branch or unstage existing work.** The previous session staged ~1169 lines across 21 files; verify and build on it, don't throw it away.
4. **No live host verification.** Phase 3 of `.itx/734/01_SCAFFOLD.md` is NOT in scope here. Record it as `[TODO-FOLLOWUP]` in the PR Callouts section with the per-agent smoke checklist from the scaffold's Phase 3 exit criteria.
5. **No `git push` to main, ever.** This branch only.

## Required execution sequence

1. `git status --short` and `git diff --cached --stat` to inventory the staged work.
2. Read `.itx/734/00_PLAN.md` (plan) and `.itx/734/01_SCAFFOLD.md` (scaffold).
3. Compare staged work against Phase 1 + Phase 2 exit criteria. Identify gaps. Specifically check:
   - Is `src/clawrium/gui/routes/integrations.py` updated, or only the test file? If route is missing, add it.
   - Are byte-locks present for hermes / zeroclaw / openclaw brave renders?
   - Does the zeroclaw template emit BOTH `Environment=BRAVE_API_KEY=…` AND `Environment=ZEROCLAW_web_search__search_provider="brave"`? Negative test asserting both?
   - Does `render_hermes` (Python) name-map `BRAVE_API_KEY` → `BRAVE_SEARCH_API_KEY`, NOT the Jinja template?
   - Openclaw lifecycle preflight at `< 2026.4.10` → `typer.Exit(1)` with the documented message?
   - `_do_pair()` invariant pinned (#437) — no `--no-rotate` branch added?
   - Openclaw playbook task `no_log: true` + sentinel-guarded plugin install pinned to `@openclaw/brave-plugin@2026.6.8`?
   - macOS sibling `configure_macos.yaml` present; no `when: ansible_os_family == 'Darwin'` in `configure.yaml`?
4. Fix any identified gaps.
5. Run `make test` from the worktree root. Fix failures until green.
6. Run `make lint`. Fix until clean.
7. Commit on `issue-734-brave-integration` with a Conventional Commits message: `feat(integrations): add brave web-search API key integration\n\nCloses #734`. **Never commit to main.**
8. `git push -u origin issue-734-brave-integration`.
9. **Run ATX review via CLI**: `atx review --format json --timeout 15m`. Parse the JSON output. Persist `.itx/734/atx-session.json` per the skill's session-id-persistence rules — note `transport: "cli"`.
10. Iterate up to 3 times. Address every `B*` blocker. After each fix, re-run `make test` + `make lint`, commit, push, re-run `atx review`.
11. If the 3rd iteration still has unresolved blockers, open the PR anyway (per skill non-blocking contract) with `[ITX-STUCK]` marker comment and every unresolved blocker as a Callout.
12. PR title: `feat(integrations): brave web-search API key`. PR body MUST follow the `<pr-format-atx>` template in `AGENTS.md` (Summary / ATX Review Summary / iteration history / Callouts). Use `Co-Authored-By: @atx-ci <269048218+atx-ci@users.noreply.github.com>` and `Co-Authored-By: Claude <noreply@anthropic.com>`.
13. PR Callouts MUST include:
    - `[TODO-FOLLOWUP]` for Phase 3 live verification with the hermes/zeroclaw/openclaw smoke checklist from the scaffold.
    - `[DECISION]` for any non-obvious choices made during gap-fixing.
    - `[ENVIRONMENT] ATX review path: CLI (per operator override; MCP available but not used).`

## Invariants pinned by the plan — verify in tests

- **#437** — `_do_pair()` called unconditionally on every sync that touches `.zeroclaw/env` or `~/.openclaw/env`. No `--no-rotate`. Assertable via mock on `_do_pair`.
- **#622** — Hermes `BRAVE_SEARCH_API_KEY` written exclusively by `render_hermes()` via canonical Jinja; `configure.yaml` uses `ansible.builtin.copy` of pre-rendered bytes. No `lineinfile`, no Ansible-side `template:`.
- **Dispatcher-only OS fork** — macOS branching lives in `playbook_resolver.py`; `*_macos.yaml` siblings. NO `when: ansible_os_family == 'Darwin'` inside `configure.yaml`.

## What "done" looks like

PR open against `main`, ATX review iteration history attached, all blockers Fixed or Out-of-scope, Callouts section present including the `[TODO-FOLLOWUP]` for Phase 3. Then this session stands down.

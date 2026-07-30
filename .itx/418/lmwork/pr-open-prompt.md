Open the PR for issue #418 now. All prerequisites clear:

- Branch: `issue-418-harden-gui-static`
- Two commits on branch: `d973f2e` (main fix — TrustedHostMiddleware + settings redaction + types.ts + test sweep + CHANGELOG) and `d2ffc3f` (middleware ordering fix so TrustedHost is outermost — Starlette insert(0,…) semantics)
- lmjudge round 1: VERDICT: SATISFIED (see `.lmwork/418/judge-1.md`)
- ATX iter 1: Rating 3/5 — 2 warnings (both fixed in d2ffc3f)
- ATX iter 2: Rating 4/5 — no blockers, no warnings, 2 suggestions (skipped as out of scope)

## Steps

1. `git fetch origin && git rebase origin/main` inside this worktree. If clean, push. If conflicts, stop and write the conflict summary to `.lmwork/418/pr-blocked.md` — do not force any resolution.
2. Push branch: `git push -u origin issue-418-harden-gui-static`
3. Open the PR with `gh pr create`, using `.github/PULL_REQUEST_TEMPLATE.md` **verbatim** as the body scaffold. Fill each section per AGENTS.md.
4. Include an **ATX Review Summary** block per AGENTS.md `<pr-format-atx>`:
   - Final Review: Rating 4/5 (from ATX iter 2)
   - Two review rounds:
     - Round 1 (ATX id `3a016e63`) — Rating 3/5, 2 warnings (middleware ordering, tracker singleton reset)
     - Round 2 (ATX id `608fd7d7`) — Rating 4/5, no blockers, 2 suggestions
   - Add the `Co-Authored-By: @atx-ci` trailer
5. Include a **Callouts** section covering:
   - Task 1 (path traversal, `_safe_serve`) was already fixed pre-existing; this PR ships Tasks 2 (TrustedHostMiddleware) and 3 (settings redaction).
   - Scope-fence widening in `correction-2.md`: updated 6 existing GUI test files to use `TestClient(app, base_url="http://localhost:36000")` so they carry an allowed Host header under the new middleware.
   - Residual exposure: `config_dir` and `usage_db` remain in `/api/settings` — both are consumed by frontend cards (`about-card.tsx`, `token-tracking-card.tsx`); dropping them would break UX.
6. Apply the **existing** label `authored-by:local_qwen`. Do NOT create any new label. Use `gh pr edit <n> --add-label authored-by:local_qwen`.
7. Reply with the PR URL when done.

## Important constraints

- Do NOT amend or squash the commits — leave them as-is (two separate commits tell the review story).
- Do NOT --force push.
- Do NOT create any new label.
- Do NOT edit source files or tests; the branch is frozen.

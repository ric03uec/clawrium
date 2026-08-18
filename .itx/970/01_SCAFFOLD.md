# Execution Scaffolding — Issue #970

**Mode**: single-phase

The change is mechanical (frontmatter rewrite + duplicate-line delete + cross-ref updates) and touches many files but represents a single concern. Splitting into subtasks would fragment atomic changes that must land together — e.g. renaming a SKILL.md `name:` without updating its cross-refs in AGENTS.md would leave the docs referencing a non-existent trigger.

Sub-issue #971 (length cleanup for `itx-execute` and `.claude/CONFIG.md`) is tracked separately and is out of scope here.

---

### Phase 1: Rename `itx:X` → `itx-X` and drop duplicate `name:` body line

**Entry Criteria** (must be true to start):

- Plan #970 approved (done — this scaffold exists).
- Sub-issue #971 filed for deferred Fix 3 (done — #971 open and sub-linked).
- Working tree clean; branch `issue-970-<slug>` created from up-to-date `main`.
- Fresh worktrees only: verify `src/clawrium/gui/frontend` exists (copy from main checkout if missing, per the `fresh-worktree lint trap` memory).

**Work Items** (ordered — each is independently reversible but they must all land in the same PR):

1. **Frontmatter rewrite (13 files).** For every `.claude/skills/itx-*/SKILL.md`, change `name: itx:<verb>` → `name: itx-<verb>`.
2. **Duplicate `name:` body-line delete (13 files).** Remove the single `name: itx-<verb>` line that appears immediately after the closing `---` in each of the same 13 files.
3. **Cross-reference sweep.** Update every `/itx:<verb>` occurrence to `/itx-<verb>` in:
   - `AGENTS.md`
   - `CONTRIBUTING.md`
   - `.claude/CONFIG.md`
   - `.claude/skills/sync-upstream/SKILL.md`
   - Inline examples + prompt-log blocks inside each renamed SKILL.md
4. **Grep verification.** `grep -rn "itx:" .claude/ AGENTS.md CLAUDE.md CONTRIBUTING.md docs/ README.md` must return zero matches. Any hit is a missed cross-ref — fix and re-run.
5. **Lint + tests.** `make lint && make test` (lint first — per the `run make lint before push` memory, CI runs ruff before pytest).
6. **Real-host UAT.** In a fresh Claude Code session (any host is fine — this is a harness-only change, no daemon involvement), invoke each of `/itx-plan-create`, `/itx-verify`, `/itx-note test note` and confirm the harness triggers the renamed skills. Record the session + outputs in the PR body under Testing.

**Exit Criteria** (must all be true to complete):

- All 13 SKILL.md files: `name:` matches `^itx-[a-z-]+$`; no duplicate `name:` line in body.
- `grep -rn "itx:" .claude/ AGENTS.md CLAUDE.md CONTRIBUTING.md docs/ README.md` → zero matches.
- `make lint` passes.
- `make test` passes.
- Real-host UAT recorded in PR body: which host, which commands, observed behavior.
- PR body uses `.github/PULL_REQUEST_TEMPLATE.md` verbatim (Summary / Changes / Testing / ATX Review) per the `PR template required` memory.
- PR body prominently flags the breaking change (`/itx:X` → `/itx-X`) so operators can update saved prompts / muscle memory.
- PR body notes that the user's auto-memory files reference `/itx:execute` — these live outside the repo and are not modified by this PR.

**Dependencies**: None.

**Files Affected**:

*Modified (17 files):*

- `.claude/skills/itx-bug-new/SKILL.md` — frontmatter + duplicate line + inline refs
- `.claude/skills/itx-bug-update/SKILL.md` — same
- `.claude/skills/itx-execute/SKILL.md` — same (largest surface — many inline `/itx:execute` self-refs)
- `.claude/skills/itx-issue-new/SKILL.md` — same
- `.claude/skills/itx-issue-update/SKILL.md` — same
- `.claude/skills/itx-note/SKILL.md` — same
- `.claude/skills/itx-plan-create/SKILL.md` — same
- `.claude/skills/itx-plan-scaffold/SKILL.md` — same
- `.claude/skills/itx-pr-status/SKILL.md` — same
- `.claude/skills/itx-release/SKILL.md` — same
- `.claude/skills/itx-review-pr/SKILL.md` — same
- `.claude/skills/itx-triage/SKILL.md` — same
- `.claude/skills/itx-verify/SKILL.md` — same
- `.claude/skills/sync-upstream/SKILL.md` — cross-refs only (lines 185, 300, 326)
- `AGENTS.md` — cross-refs only (workflow table + inline)
- `CONTRIBUTING.md` — cross-refs only
- `.claude/CONFIG.md` — cross-refs only (Used-by lines)

*Unmodified but verified:*

- `CLAUDE.md` — inherits AGENTS.md via `@AGENTS.md`, no direct edit
- `README.md` — grep confirmed clean
- `docs/` — grep confirmed clean

**Complexity**: simple (mechanical, no logic change, no runtime coupling)

**Recovery Guidance**:

- Grep failure in step 4 → re-open the file at the reported line, replace, re-grep.
- Lint failure → almost certainly a stray colon in a file grep missed; re-run the wider grep.
- UAT failure (harness doesn't trigger a renamed skill) → check the frontmatter `name:` matches the invocation exactly; re-check the duplicate-line delete didn't corrupt the frontmatter block by removing the wrong line.

---

## Scaffolding

**Stage**: scaffolding
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-08-18T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 970
```

**Output**: Single-phase execution scaffold with entry/exit criteria for the `itx:X` → `itx-X` rename + duplicate-`name:` cleanup PR. Sub-issue #971 covers deferred length cleanup.

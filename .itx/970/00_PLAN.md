# Plan — Issue #970: Skill names use colon, outside documented charset

## Overview

Anthropic's SKILL.md `name:` field must match `[a-z0-9-]{1,64}`. Thirteen skills under `.claude/skills/itx-*/SKILL.md` use `name: itx:<verb>` (colon). Directory names already use the hyphen form. Rename the frontmatter `name:` and update every cross-reference. Bundle a cheap cosmetic fix (duplicate `name:` body line, leftover from slash-command conversion) into the same PR. Track length cleanup for `itx-execute/SKILL.md` (767 lines) and `.claude/CONFIG.md` (150 lines, no TOC) as a separate follow-up issue.

## Scope Decision

- **Fix 1** (rename `itx:X` → `itx-X`): included
- **Fix 2** (drop duplicate `name:` body line): included, same PR
- **Fix 3** (split `itx-execute`, add `CONFIG.md` TOC): deferred to follow-up sub-issue

## Files to Modify

**Frontmatter + duplicate body line — 13 SKILL.md:**

- `.claude/skills/itx-bug-new/SKILL.md`
- `.claude/skills/itx-bug-update/SKILL.md`
- `.claude/skills/itx-execute/SKILL.md`
- `.claude/skills/itx-issue-new/SKILL.md`
- `.claude/skills/itx-issue-update/SKILL.md`
- `.claude/skills/itx-note/SKILL.md`
- `.claude/skills/itx-plan-create/SKILL.md`
- `.claude/skills/itx-plan-scaffold/SKILL.md`
- `.claude/skills/itx-pr-status/SKILL.md`
- `.claude/skills/itx-release/SKILL.md`
- `.claude/skills/itx-review-pr/SKILL.md`
- `.claude/skills/itx-triage/SKILL.md`
- `.claude/skills/itx-verify/SKILL.md`

**Cross-reference updates:**

- `AGENTS.md` — lines 85, 110, 433, 438, 453–460, 469–470, 482
- `CONTRIBUTING.md` — lines 3, 17, 20, 23, 43, 72–76, 103, 142, 154, 167, 180
- `.claude/CONFIG.md` — lines 27, 59, 76, 95
- `.claude/skills/sync-upstream/SKILL.md` — lines 185, 300, 326
- Inline `/itx:...` references and prompt-log blocks inside each renamed SKILL.md

## Steps

1. Rewrite `name:` in all 13 SKILL.md frontmatters (`itx:X` → `itx-X`).
2. Delete the duplicate `name: itx-X` body line immediately after the closing `---` in the same 13 files.
3. Update every remaining `/itx:X` reference in AGENTS.md, CONTRIBUTING.md, `.claude/CONFIG.md`, `.claude/skills/sync-upstream/SKILL.md`, and the 13 SKILL.md files themselves.
4. Verify: `grep -rn "itx:" .claude/ AGENTS.md CLAUDE.md CONTRIBUTING.md docs/ README.md` returns zero matches.
5. `make lint && make test`.
6. Real-host UAT: invoke `/itx-plan-create`, `/itx-verify`, `/itx-note` in a fresh session; confirm the harness loads the renamed skills. Record host + observed behavior in the PR body.

## Test Strategy

- No unit-test coverage of skill frontmatter — skills load in the harness, not clawrium's Python. Verification is grep-based and real-host UAT.
- Optional hardening (out of scope): a `make lint` grep check enforcing `^[a-z0-9-]{1,64}$` on all `.claude/skills/*/SKILL.md` `name:` values. File as future improvement if useful.

## Risks

- **Breaking change for saved prompts/scripts** using `/itx:X`. No compat shim available (harness has no alias mechanism). Mitigation: call out prominently in PR body.
- **Missed cross-ref**: enforced by the grep verification in step 4.
- **User's own auto-memory** references `/itx:execute` in a few files (outside repo) — flag in PR body so user can update manually.

## Subtasks

- Fix 3 tracked as separate follow-up sub-issue (see comment).

---

## Planning

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-08-18T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create https://github.com/ric03uec/clawrium/issues/970 . give me plan only no file changes
```

**Output**: Plan for renaming `itx:X` → `itx-X` across 13 skills + cross-refs; Fix 3 deferred to a follow-up sub-issue.

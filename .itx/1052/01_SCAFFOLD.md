# Execution Scaffolding — #1052

**Mode**: one small PR from the `issue-1052-hard-delete` worktree, covering linked subtasks #1057 and #1058.

## Phase 1: Local fallback

**Entry**: existing remote-delete behavior and local artifact paths identified.

**Work**: tag remote-playbook failure; add a local-only helper for the exact agent that deletes instance secrets, agent state, workspace, then its record. Missing artifacts are successful no-ops, real failures leave the record to retry.

**Exit**: remote failure alone preserves local state; explicit local cleanup removes only the selected agent. No changes to successful remote-delete behavior.

## Phase 2: CLI and verification

**Entry**: phase 1 complete.

**Work**: add a separate default-no hard-delete confirmation and explicit non-interactive flags; update focused tests, CLI reference, and changelog.

**Exit**: focused tests, `make test`, `make lint`, and Linux-only UAT pass; review the narrow diff before one PR.

## Scaffold Prompt Log

**Stage**: scaffold
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-10-09T19:29:34Z
**Model**: openai/gpt-6-sol

```prompt
/itx-plan 1052 in a worktree. all plan files go in the worktree
```

**Output**: Revised on 2026-10-09 to match the minimal single-PR scope.

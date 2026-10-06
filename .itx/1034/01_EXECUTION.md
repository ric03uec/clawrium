## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-06T02:02:53Z
**Model**: GPT Terra (medium thinking)

```prompt
Execute /itx-execute 1034 as the implementation worker.

Read AGENTS.md, .claude/skills/itx-execute/SKILL.md, the full GitHub issue #1034, and the #1031 plan before editing. Make a task checklist and carry out issue #1034's scope, including meaningful tests, make test, make lint, manual self-review, changelog when behavior is introduced, and prompt log. Copy the parent plan exactly into .itx/1031/00_PLAN.md.

Base and PR base: main. Branch: issue-1034-codex-foundation. Do not implement #1035-#1037 prematurely; make contracts ready for downstream work.

Stage files and use the prescribed stateless ATX review command; fix all blockers and repeat until leader rating >3/5 with none. Then commit, push, and open a main-targeting PR with tests, ATX history, Callouts, and Closes #1034.
```

**Output**: Started implementation of the Codex foundation subtask in its dedicated worktree.

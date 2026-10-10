# Execution — #1052

Implement in the existing `issue-1052-hard-delete` worktree. Phase 1 is scoped core cleanup (#1057); phase 2 is CLI opt-in, tests, docs, and changelog (#1058). Validate with `make test`, `make lint`, and a Linux-only, real-host UAT. Request ATX reviews and resolve blockers before opening the PR.

## Execution Prompt Log

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-09T21:32:06Z
**Model**: openai/gpt-6-sol (orchestrator); openai-codex/gpt-5.6-terra (medium, interactive Pi implementation)

```prompt
ok/ use /itx-execute to implement this in a worktre. send pr after atx rviews are done. use pi with terra (medium) for this in interactive sssion and do a real host uat for validation. only linux host is savailble os use that only
```

**Output**: Implemented the narrowed hard-delete fallback in this worktree. Linux-only `wolf-i` UAT passed; `make test` passed (5,678 Python tests, 369 GUI tests), `make lint` passed. ATX reviewed twice: one blocker fixed, final rating 4.5/5 with no blockers. One PR will cover #1052 and its linked subtasks.

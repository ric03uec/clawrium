# Issue #1040 — Execution

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-07T01:04:35Z
**Model**: openai-codex/gpt-5.6-terra (medium)

```prompt
Execute /itx-execute 1040 on issue-1040-pi-codex-oauth as an interactive worker. Read issue #1040, AGENTS.md, the parent plan, existing #1038 OpenRouter implementation, and make a task checklist. Implement Pi built-in openai-codex OAuth provider selection and dedicated-agent scoped login, refresh or actionable reauthentication, CLI and GUI chat plus native exec, tests and docs; never copy controller ~/.pi or print tokens, and do not substitute OPENAI_API_KEY. This branch starts from the last COMMITTED #1038 state solely for parallel work; #1038 security fixes and #1039 Bedrock edits are still uncommitted elsewhere. Avoid altering other worktrees. Before any PR, rebase this branch onto the final #1039 branch after #1038 and #1039 pass ATX, resolve integration conflicts, run make test and make lint and fresh scoped stateless ATX until rendered leader >3/5 with zero blockers. Wolf-i real OAuth native exec, CLI, GUI, refresh or re-login, and agent deletion plus remote cleanup are mandatory before declaring #1040 complete; operator interactive login may be needed, never fake UAT. Record progress in .itx/1040/01_EXECUTION.md and report blockers honestly. Do not open a PR or merge without orchestrator handoff of final stacked base.
```

**Output**: Began #1040 execution with an explicit checklist. Confirmed Pi 0.73.1’s bundled `pi-ai` catalog supports the bounded `openai-codex` models `gpt-5.1`, `gpt-5.1-codex-max`, `gpt-5.1-codex-mini`, `gpt-5.2`, `gpt-5.2-codex`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.4`, `gpt-5.4-mini`, and `gpt-5.5`; Pi stores and lock-refreshes OAuth only in the dedicated agent directory’s `auth.json` and directs failed refreshes to native `/login`. No controller Pi auth state or environment credentials were read.

## Progress — 2026-10-07T01:20:00Z

Implemented the bounded `openai-codex` selection, agent-scoped interactive SSH TTY login, native Codex chat routing, stale credential cleanup, and tests. Provider records retain only non-secret provider/model metadata; Pi reads and refreshes OAuth only as the dedicated OS user. The login command explicitly unsets OpenAI, OpenRouter, and AWS credential variables before starting Pi. Focused regression suite: **53 passed**; `make lint-py`: **passed**. `make test-py` was started after initializing this worktree with the required `make build-ui` + `uv sync`, but the full 5,236-test invocation exceeded the 120-second command window; this is not a pass and will be rerun after stack rebase. Live wolf-i OAuth login/UAT has not been attempted and remains required.

## Draft-PR Override — 2026-10-07T01:33:39Z

Per user priority override, committed and pushed `06d0e2b44d1c3705a7484568d21d80f7d24ab7b1` and opened regular stacked PR [#1048](https://github.com/ric03uec/clawrium/pull/1048) against `issue-1039-pi-bedrock`. `make test` passed (5237 passed, 2 skipped) and `make lint` passed before commit. The PR explicitly records that #1039 integration/rebase, stateless ATX review, and live wolf-i interactive OAuth/inference/refresh/delete UAT remain pending; it makes no claim those gates passed.

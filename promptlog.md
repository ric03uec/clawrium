## Entry 001: ITX Authored-By Labels

**Date**: 2026-07-08

**Artifacts Created**:
- `.opencode/skills/itx-execute/SKILL.md`
- `promptlog.md`

### Original Prompt
> update the itx skill to also add these labels when they create a pr or when they send aninstruction to creat ethe pr to an agent.

### Follow-up Clarifications
None.

### Design Decisions
- Updated `.opencode/skills/itx-execute/SKILL.md` because it is the skill that opens PRs and defines the child-session/orchestrator PR contract.
- Added an explicit `authored-by:*` label contract rather than relying on examples alone, so both direct execution and spawned child sessions inherit the same rule.
- Listed the exact supported labels currently present in the repository to prevent drift or ad hoc label creation.
- Required exactly one authored-by label per PR, with a specific rule that local Qwen runs must use `authored-by:local_qwen` instead of the generic `authored-by:qwen`.
- Wired the label into the example `gh pr create` commands and added a repair path via `gh pr edit` for PRs opened without the label.

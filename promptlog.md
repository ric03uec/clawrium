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

## Entry 002: Cross-Harness ITX Commands

**Date**: 2026-09-08

**Artifacts Created**:
- `docs/architecture/itx-cross-harness-commands.md`
- `.pi/settings.json`
- `.pi/package.json`
- `.pi/extensions/itx-command-aliases.js`
- `tests/test_itx_skill_harnesses.py`
- `.claude/skills/itx-*/SKILL.md`
- `.opencode/commands/itx-*.md` (removed)
- `.opencode/skills/itx-*/SKILL.md` (removed)
- `.opencode/skills/sync-upstream/SKILL.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `AGENTS.md`
- `CONTRIBUTING.md`
- `.claude/CONFIG.md`
- `CHANGELOG.md`
- `promptlog.md`

### Original Prompt
> theres a itx-release slash command availabe in claude code for this project. how cani make itx  ommands availabe to both opencode and pi? no changes. just give me plan

### Follow-up Clarifications
- "ok. create a plan and make these changes and sdocument them."

### Design Decisions
- Kept `.claude/skills/itx-*/SKILL.md` as the only canonical workflow source because both OpenCode and Pi can load Agent Skills from that directory.
- Removed stale OpenCode ITX commands and skill copies because explicit commands shadow canonical skills and both copies had already drifted.
- Added one dynamic Pi extension that discovers canonical skill names and delegates exact `/itx-*` aliases to Pi's native `/skill:itx-*` commands, avoiding copied prompt templates and a second name manifest.
- Kept `.claude/itx-config.json` as the shared configuration path to avoid an unrelated migration.
- Kept `itx-execute` orchestrate mode and its tmux-backed standalone worktree path Claude Code-specific instead of mixing a child-runner redesign into command availability; both paths now preflight the launcher before mutating worktrees.
- Made automated review transport capability-based: attempt an ATX MCP tool available in the current harness, fall through to the stateless `atx` CLI when MCP is unavailable, fails, or times out, then use manual review only if CLI is unavailable, stopped, fails, or times out. Shared config no longer pins a Claude-specific MCP identifier.
- Updated the pull request template and the retained OpenCode `sync-upstream` skill so they do not direct contributors to removed or harness-specific commands.
- Required Pi 0.84.2 or newer, documented its repository-root scope, and queued alias delegation as a follow-up message so invocation remains valid while Pi is streaming.
- Added contract tests for canonical names, recursive absence of OpenCode shadows, Pi discovery, alias coverage, argument forwarding, queued delivery, and harness-neutral review configuration.

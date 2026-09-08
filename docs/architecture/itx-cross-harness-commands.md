# Cross-Harness ITX Commands - Implementation Plan

> **Status**: Implemented
> **Date**: 2026-09-08

## Problem

The ITX workflows have three competing definitions:

- complete, current skills under `.claude/skills/itx-*/SKILL.md`
- shortened OpenCode commands under `.opencode/commands/itx-*.md`
- older OpenCode skill copies under `.opencode/skills/itx-*/SKILL.md`

OpenCode command precedence causes the shortened commands to shadow the
canonical skills. Pi has no project configuration, so it does not discover the
skills or expose the same `/itx-*` command names.

## Customer Outcome

A contributor can invoke the same `/itx-*` workflows from Claude Code,
OpenCode, or Pi, while maintainers update one canonical skill definition.

## Plan

### Phase 1: Establish One Source

1. Keep the thirteen `.claude/skills/itx-*/SKILL.md` files canonical.
2. Remove only ITX command and skill copies from `.opencode/`.
3. Preserve unrelated OpenCode commands and skills.
4. Replace direct harness API names in canonical prose where the workflow does
   not require a particular harness.

### Phase 2: Add Pi Discovery and Aliases

1. Configure Pi to load `../.claude/skills` as a project skill directory.
2. Leave Pi's native `/skill:itx-*` commands enabled.
3. Add one project extension that discovers canonical ITX skills at startup,
   registers exact `/itx-*` aliases, and forwards arguments to the native skill
   command as a queued follow-up message.
4. Avoid copied Pi prompt templates or a manually maintained skill-name list.
5. Require Pi 0.84.2 or newer and a repository-root launch; Pi project settings
   and extensions are current-directory scoped.

### Phase 3: Prevent Drift

Add repository tests that enforce:

- the expected thirteen canonical skill names exist and match their directories
- no ITX command or skill shadow exists recursively in any singular or plural
  OpenCode discovery root, including command frontmatter name overrides
- Pi loads the canonical directory and enables skill commands
- Pi registers every canonical skill as an exact-name alias
- alias arguments reach the native Pi skill command unchanged
- review transport selection is not pinned to one harness's MCP tool name and
  failed or timed-out MCP requests fall through to CLI before manual review

### Phase 4: Document and Verify

1. Document invocation, ownership, and reload behavior in `CONTRIBUTING.md` and
   `AGENTS.md`.
2. Record the behavior in `CHANGELOG.md` and the design prompt in
   `promptlog.md`.
3. Run the focused contract tests, `make test`, and `make lint`.

## Compatibility Boundary

This change makes the workflows discoverable and usable in all three
harnesses. It does not redesign child orchestration. `itx-execute` orchestrate
mode and the tmux-backed standalone worktree path continue to launch Claude
Code child sessions with the `claude` CLI. Both preflight the launcher before
creating worktrees. Making child execution select the active harness is a
separate behavior change.

Automated review is harness-neutral at the workflow layer: attempt an available
ATX MCP tool, fall through to the stateless `atx` CLI when MCP is unavailable,
fails, or times out, then use the manual checklist if CLI is unavailable,
stopped, fails, or times out. The shared config does not contain a
harness-specific tool identifier.

Pi exact-name aliases require Pi 0.84.2 or newer and are available when Pi is
started at the repository root, where it loads the tracked `.pi/` project
configuration.

The shared workflow configuration remains `.claude/itx-config.json`. Its path
is historical, but moving it would add migration work without improving command
availability.

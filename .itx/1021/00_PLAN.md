# Issue #1021: Native Claude Configuration for New Agents

## Goal

Make newly created Claude Code agents usable from their normal shell after
OAuth configuration without Clawrium-specific credential environment hooks.

## Product Output

- The new agent user's `~/.bashrc` exposes the agent-owned Claude binary and
  disables Claude's self-updater, which conflicts with Clawrium's pinned npm
  installation.
- Configure and canonical sync render Claude's native global files:
  `~/.claude/settings.json`, `~/.claude.json`, and OAuth
  `~/.claude/.credentials.json`.
- OAuth agents skip the Claude login-method picker and enter normal workspace
  trust flow.
- `clawctl agent shell` runs without Claude-specific environment injection.

## Scope

1. Update Linux and macOS Claude install playbooks to add an idempotent,
   marker-delimited PATH and `DISABLE_AUTOUPDATER=1` block to the newly created
   agent user's shell configuration.
2. Replace the custom credential environment file and profile hook with
   native Claude file rendering in configure playbooks and canonical sync.
3. Render OAuth as `claudeAiOauth.accessToken` in the private native
   credentials file and render `hasCompletedOnboarding` in `~/.claude.json`.
4. Remove the Claude-special case from the agent-shell command construction.
5. Update focused Linux/macOS, credential, sync, and command-shell tests;
   document the native-file contract and changelog entry.

## Non-Goals

- Migrate or repair existing Claude agents.
- Add an unverified persistent API-key credential schema.
- Create a Claude service, gateway, UI, PTY, or chat command.
- Authorize controller SSH keys or register agents with Herdr.

## Implementation Notes

- OAuth is the supported credential mode for this work. The standard
  `~/.claude/.credentials.json` field is `claudeAiOauth.accessToken`.
- Credential rendering remains private (`0600`) and no-log. Only the storage
  location changes; token values must not appear in diffs, events, or output.
- The pinned package is still upgraded only through Clawrium. The shell export
  disables the upstream self-updater, not authentication.
- New-agent-only scope permits native config files to be rendered from
  templates rather than merging legacy state.

## Verification

- Focused tests for Linux and macOS playbooks, credential confidentiality,
  canonical sync, and generic `agent shell` behavior.
- Run `make test` and `make lint`.
- Review the final diff for retained install-only/no-daemon boundaries.

## Prompt Log

**Stage**: plan
**Skill**: /itx-plan-create
**Timestamp**: 2026-10-04T17:15:41Z
**Model**: openai/gpt-5.6-terra

```prompt
cool. create a plan and do this (in a worktree in tmux pane)
```

**Output**: Created the implementation plan for native Claude configuration on new agents.

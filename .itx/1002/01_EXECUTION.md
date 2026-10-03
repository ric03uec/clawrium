# Issue #1002 — Cross-layer verification and removal ordering

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T09:06:38Z
**Model**: gpt-5.6-terra

```prompt
Execute only GitHub issue #1002 in this worktree. You are a Pi worker in a sequential stacked-PR pipeline. Read AGENTS.md, issue #1002, parent #989, `.itx/989/00_PLAN.md`, `.itx/989/01_SCAFFOLD.md`, and all inherited changes. Create and maintain a task checklist before edits.

Scope: cross-layer verification and removal-ordering only. Strengthen tests/invariants that prove remote cleanup runs before local secrets and hosts.json state are removed. For the `claude` agent, removal must clean only dedicated resources: full dedicated `~/.claude`, agent user/home, agent-owned install prefix, managed startup hook, and remote credential file. It must never delete global/shared Claude installations or any project `.claude` outside the dedicated agent home. Preserve remote-first ordering and OS-specific playbook selection. You may fix a validated integration/removal race inherited from #998 only if it belongs to this cross-layer verification/removal scope; otherwise document it as a Callout.

Out of scope: i-wolf E2E (#1003), docs/help (#1001), new settings schema, provider credential model/activation changes, native shell behavior changes, daemon/chat/gateway/UI work. Do not invoke Claude. Do not ask the user questions and do not merge.

Run focused tests plus `make test` and `make lint`. Request stateless ATX CLI review against this branch/worktree using `atx review request --worktree <worktree-name> --prompt "Review the full diff against issue-1000-claude-native-command-path" --format json --timeout 15m`; address blockers for at most 3 iterations and persist `.itx/1002/atx-session.json`. Write `.itx/1002/01_EXECUTION.md` including the required execution prompt log. Commit, push, and open one PR based on `issue-1000-claude-native-command-path`, not main. PR must say `Stacked on top of issue-1000-claude-native-command-path`, include the AGENTS ATX review format and a `## Callouts` section. Handoff is the open PR.
```

**Output**: Added lifecycle and remove-playbook invariants that prove remote-first Claude removal without widening resource ownership.

### Implementation

- Replaced in-memory-only removal checks with persisted `hosts.json` and encrypted-instance-secret tests. They prove a failed remote cleanup preserves both local records, while a successful cleanup calls the OS-specific remote playbook before local secrets, agent state, and `hosts.json` removal.
- Parameterized successful removal coverage for Linux and Darwin and asserted the resolver selects the matching Claude remove runbook.
- Added remove-playbook allowlist invariants for both OSes: only dedicated-home paths, the owned install prefix, managed hook and credential file, the dedicated account/home, and ownership marker may be removed. The tests reject shared installation locations, package-manager/Claude executable cleanup, and ordering drift.

### Validation

- Focused: `uv run pytest tests/platform/test_claude_install_boundary.py tests/core/test_claude_lifecycle.py tests/core/test_claude_settings.py tests/core/test_claude_credentials.py tests/core/test_claude_credential_activation.py tests/core/test_agent_shell.py tests/cli/clawctl/agent/test_claude_lifecycle.py tests/cli/clawctl/agent/test_shell.py` — 207 passed.
- Full: `make test` — 4,989 passed, 2 skipped; GUI: 366 passed.
- Full: `make lint` — passed.

### ATX Review

- Iteration 1: stateless CLI review revision `0f006119-c539-493e-8e28-cdd9c2a7ba22`; rating 5/5, no blockers, warnings, or suggestions. Cost: $0.24; time: 1m 24s. Session metadata: `.itx/1002/atx-session.json`.

## Callouts

- [ENVIRONMENT] `.itx/989/00_PLAN.md` and `.itx/989/01_SCAFFOLD.md` are absent from this worktree and all repository refs; the parent issue's Phase 7 scaffold comment and inherited execution records supplied the available planning contract.
- [DECISION] No inherited #998 integration/removal race was independently validated, so no activation implementation was changed.
  - Why: this issue's persisted lifecycle tests directly cover the relevant remote-cleanup/local-state boundary without expanding its activation scope.
  - Reviewer: confirm or push back.

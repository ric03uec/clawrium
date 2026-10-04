# Issue #1018 Execution Plan

## Phase 1: Scoped Herdr Provisioning

- Add Linux/macOS Herdr playbooks with exact upstream version, assets, and
  checksums; install a root-owned shared system-PATH binary idempotently.
- Add resolver and installer orchestration so only `hermes` and `claude` run
  the Herdr playbook after generic base setup and before their agent playbook.
- Prove excluded types retain the current base-plus-agent installation path.

## Phase 2: Hermes Integration And Contracts

- Install the official Herdr Hermes integration from the Hermes Ansible
  playbooks after the runtime exists, as the agent user, based on actual
  plugin/configuration state.
- Make the canonical Hermes renderer preserve the exact upstream integration
  configuration through configure and sync.
- Keep Claude binary-only; add static, render, removal-isolation, and docs
  coverage.

## Phase 3: Verification And i-wolf E2E

- Run formatting, full tests, and lint.
- Add/run a redacted i-wolf E2E for fresh Hermes and Claude agents. Verify
  Hermes plugin/config persistence, Claude `claude --version` plus
  `herdr --version` and no plugin, binary reuse, and cleanup isolation.
- Request ATX CLI review over the full branch diff. Persist review metadata;
  resolve blockers in at most three rounds; commit, push, and open one PR
  against `main` with review history and `## Callouts`. Do not merge.

## Prompt Log

**Stage**: execution-child-creation
**Skill**: /itx-execute orchestrate
**Timestamp**: 2026-10-04T03:09:40Z
**Model**: openai/gpt-5.6-terra

```prompt
Execute the linked child for #994 as the single implementation PR using Pi
with gpt-5.6-terra, tmux, and ATX CLI reviews.
```

**Output**: Sequential implementation, validation, E2E, and review plan for
the executor.

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-04T03:12:20Z
**Model**: gpt-5.6-terra

```prompt
Execute child issue #1018 for parent #994 in this worktree. Implement scoped Ansible-only Herdr support for Hermes and Claude, run the specified verification and i-wolf E2E, obtain ATX CLI review, then open one PR without merging.
```

**Output**: Began sequential implementation with a scoped provisioning, integration, E2E, verification, and review checklist.

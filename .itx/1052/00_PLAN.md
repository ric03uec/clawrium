# Implementation Plan — #1052: Delete unreachable agents

## Outcome

`clawctl agent delete <name>` still tries remote removal first. If that attempt fails, an operator can explicitly forget the agent locally. The CLI states clearly that remote services, configuration, and data remain for manual cleanup. Without separate consent, the local record stays.

## Small implementation

1. Mark only the existing remote-playbook failure result in `core/lifecycle.py`. Do not offer the fallback for missing hosts/playbooks or local-update errors after successful remote removal.
2. Add one local-only cleanup function that removes this instance's secrets, existing local agent state, and workspace directory, then removes its exact hosts.json entry. Missing files are already deleted; a real cleanup failure keeps the record for retry. Do not change the ordinary successful remote-delete path or unrelated tunnel handling.
3. In `cli/clawctl/agent/delete.py`, add `--hard-delete`. On a failed remote attempt, show a default-no interactive prompt; non-interactive automation requires both `--yes --hard-delete`. A bare `--yes` never approves local-only deletion.
4. Add focused regression tests for remote failure with no opt-in, explicit local-only cleanup, repeatable missing-file cleanup, and preservation of another agent. Update the CLI reference and root unreleased changelog.

## Verification

Run focused tests, `make lint`, and the required `make test` before commit. Validate the final command on the available Linux host only. Request a focused ATX review of the replacement diff; assess findings against this scope before opening one PR.

## Plan Prompt Log

**Stage**: plan
**Skill**: /itx-plan-create
**Timestamp**: 2026-10-09T19:29:34Z
**Model**: openai/gpt-6-sol

```prompt
/itx-plan 1052 in a worktree. all plan files go in the worktree
```

**Output**: Revised on 2026-10-09 to the minimal local-only fallback requested during execution. Linked subtasks #1057 and #1058 are implemented together in this issue worktree.

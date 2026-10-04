# Issue #1000 — Claude native command path execution

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T08:51:37Z
**Model**: gpt-5.6-terra

```prompt
Execute only GitHub issue #1000 in this worktree. This is a stacked change: your branch `issue-1000-claude-native-command-path` is based on `issue-998-claude-credential-activation`; create the PR against `issue-998-claude-credential-activation` and state `Stacked on top of issue-998-claude-credential-activation` in its body. Read AGENTS.md, issue #1000, parent #989 and its planning artifacts, and inherited changes first. Create and maintain a task checklist before edits.

Strict scope: retain/formalize the existing finite native command path `clawctl agent shell NAME -- COMMAND` for the new daemonless `claude` type. It is non-interactive and completion-only. Do NOT add `agent exec`, a no-command shell, a PTY, direct SSH, `claude` invocation, chat, gateway, service, ports, or web UI. Ensure expected `claude` shell behavior/help/error handling is type-aware and that its credential activation from #998 remains compatible, but do not modify credential activation implementation except where strictly necessary to formalize the command-path contract. Do not implement #1002 verification/removal, #1003 E2E, #1001 docs, or any unrelated lifecycle/settings/provider work.

Implement tests for this narrow contract. Use apply_patch for manual edits, preserve unrelated/inherited work, and do not ask the user questions; record non-obvious decisions or blockers as PR Callouts. Run `make test` and `make lint`. Run stateless ATX CLI review (not session review) with `atx review request --worktree <resolved-worktree-name> --prompt "Review the full diff of this branch against issue-998-claude-credential-activation." --format json --timeout 15m`, up to 3 iterations. Persist `.itx/1000/atx-session.json` and append `.itx/1000/01_EXECUTION.md`; commit both. Commit, push, and open the stacked PR. Do not merge. Handoff only after the PR exists with full test/lint/review results and `## Callouts`.
```

**Output**: Formalized the completion-only Claude command-shell contract, covered type-aware credential activation and errors, and opened a stacked PR after validation and review.

### Implementation

- Declared `clawctl agent shell <name> -- <command>` as the supported finite native path for daemonless Claude Code in CLI help; it documents no TTY, no prompt, and mandatory command completion.
- Made the empty-command error type-aware for Claude while preserving the generic shell behavior for other types.
- Passed the resolved agent type from `safe_resolve_agent()` to the core shell runner, including type-keyed legacy Claude records.
- Bound managed credential-hook activation to that resolved type. For Claude, the prelude clears stale inherited Claude credential variables, requires the private managed hook, and fails before the caller command if hook activation fails.
- Added focused CLI/core coverage for help, mandatory explicit commands, exit propagation, legacy records, encoded command composition, stale credentials, and fail-closed hook errors.

### Validation

- Focused: `uv run pytest tests/cli/clawctl/agent/test_shell.py tests/core/test_agent_shell.py tests/core/test_claude_credential_activation.py` — 121 passed after the final fail-closed coverage.
- `make test` — 4,988 passed, 2 skipped; GUI: 366 passed.
- `make lint` — passed (Ruff and Next ESLint).

### ATX review

The requested stateless review command ran three times against worktree `issue-1000-claude-native-command-path`.

| Iteration | Revision | Review-body rating | Result |
|---|---|---:|---|
| 1 | `8d51363a-1969-46fb-b3cf-875dbe4417e4` | 2/5 | Fixed resolved-type propagation, legacy-record activation, and composed-runner coverage. The concurrent configure-directory blocker was inherited from #998 and outside this branch's requested diff/scope. |
| 2 | `7086ad7d-5061-43aa-b543-219ac12c62c0` | 3/5 | No blockers; fixed the remaining authoritative-resolved-type warning. The lifecycle activation warnings target inherited #998 sync behavior outside #1000 scope. |
| 3 | `8555a7bb-31ed-4500-aaa2-63a9dc583fa6` | 2/5 | Fixed B1 after the review: clear stale variables and fail closed unless the managed hook sources successfully. The three-review cap prevented a fourth request; the final code was self-reviewed and passed the full suite and lint. |

Total ATX cost: $2.53. Review metadata is persisted in `atx-session.json`.

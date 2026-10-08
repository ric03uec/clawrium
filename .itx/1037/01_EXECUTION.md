## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-06T08:35:00Z
**Model**: GPT Terra

```prompt
Read /tmp/opencode/clawrium-1037-worker.md and implement issue #1037 end-to-end. Stay interactive in tmux; sole code worker in this worktree. Native real-host mac-test UAT explicitly deferred by user, document Callout and retain automated coverage. Base issue-1036-codex-sync. Neutral stateless ATX CLI raw leader >3/5 and no blockers before commit/PR; continue substantive fixes beyond skill iteration ceiling. No biased rating prompt/review shopping, no atx-session.json in SCM, no amend/force/merge. Complete CLI/GUI chat and parent docs/acceptance, make test/lint, then stacked PR. Report URL and actual review evidence.
```

**Output**: Implemented the finite shared Codex CLI/GUI chat transport, documentation, automated coverage, and parent acceptance evidence. Native real-host mac-test UAT remains intentionally deferred by user direction.

## Parent #1031 acceptance verification

- Dedicated Codex agent, selection-only OAuth import, and refresh-safe private activation were delivered in stacked predecessors #1034–#1036.
- This child adds `codex exec --json -` / `codex exec resume --json <thread-id> -` chat through one bounded backend used by CLI and GUI, with JSONL, timeout, cancellation, continuation/reset, and redaction coverage.
- Documentation covers supported targets, lifecycle, OAuth ownership, exec/shell, CLI/GUI chat, and unavailable daemon operations.
- **Callout — deferred real host UAT:** Native mac-test OAuth activation/chat UAT was explicitly deferred by the user. Automated macOS playbook and chat coverage is retained; do not claim native real-host macOS validation until that UAT is run.

## Integration with current main

- Merged `origin/main` (including the Pi OAuth agent) without discarding the pre-existing macOS Codex readiness fix. Both agent types retain their own CLI and GUI chat dispatch.
- Tightened browser session isolation across agent replacement/host reassignment, rejected stale in-flight Codex replies with HTTP 409, and returned sanitized HTTP 502 for backend errors before streaming begins. Pi's cache now rejects exhausted locked capacity with HTTP 503 instead of growing unbounded.
- Exercised the actual macOS readiness wrapper, public Pi/Codex CLI dispatch, supported chat manifest types, GUI error boundaries, and session reinstallation races.
- `make test`: 5,673 Python passed, 2 skipped; 369 GUI passed. `make lint`: Python and GUI passed. Review uncovered an incomplete-turn JSONL protocol gap, which was fixed and covered by regression tests. Earlier terminal-output and Pi error-context suggestions remain warnings.
- **Live OAuth UAT remains unverified** until a real Codex login/entitlement is available on the operator machine and mac-test.

## Execution Continuation

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-08T04:03:30Z
**Model**: openai/gpt-6-sol

```prompt
you're now the orchestraot to take this to completion. contine to send prs till this is done
```

**Output**: Integrated #1037 with current main, resolved Codex/Pi GUI session isolation and error boundaries, and verified tests and lint before opening the chat PR. Real-host OAuth validation is tracked separately.

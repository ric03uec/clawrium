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

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T17:00:41Z
**Model**: gpt-5.6-terra

```prompt
Implement GitHub issue #1013 on branch `issue-1013-claude-oauth-provider`, stacked on `issue-1001-claude-docs-help`. Make Claude OAuth a first-class normal provider selection. Use the supported `claude setup-token` local export through a private non-logging subprocess adapter; keep token and command output only in memory, normalize and validate it, redact all errors, and do not require an environment-token import. Do not read or copy a keychain, browser profile, database, OAuth file, or `~/.claude`. Store the selected credential only in the existing per-Claude-agent per-instance secret contract, preserve OAuth/API-key mutual exclusion, and use inherited #998 sync activation. Use fake adapters/readers in tests, and prove attach invokes the supported local reader rather than requiring an environment token. Run focused tests, make test, make lint, and up to three ATX review iterations. Persist the execution and ATX session artifacts, then commit, push, and open a stacked PR with the required Callouts.
```

**Output**: Added a Claude-only OAuth provider type, Linux-supported Claude Code reader, attachment flow, docs, and regression coverage.

### Scope decisions

- `claude setup-token` is the sole normal import path. The reader runs only on Linux controllers, captures both streams in memory, removes inherited credential environment variables, and returns only a normalized token to the existing Claude per-instance secret boundary.
- The implementation never opens or copies a keychain, browser profile, credential database, guessed OAuth file, or `~/.claude` path. Non-Linux controllers fail closed.
- `claude-oauth` is selection-only: it has no provider-scoped credentials or model catalog. It may be attached only to Claude agents, and its token is never written to `providers.json` or `hosts.json`.
- Reattaching the same provider refreshes the local OAuth credential. A reader/store failure rolls back only the exact metadata written by this invocation; cancellation cleanup preserves the original cancellation while removing this invocation's metadata if unchanged.
- Inherited #998 configure/sync activation is used without daemon, service, chat, UI, gateway, or E2E work.

### Review and Callout

ATX review completed three iterations. The final review identified missing cancellation cleanup coverage; it was added after the review. No fourth review was requested because the task caps review at three iterations.

> **Callout — existing secret-store architecture:** ATX noted that the repository-wide per-instance secrets implementation does not add a new at-rest encryption layer for this provider. Per explicit user direction, #1013 uses the repository's established per-instance secret contract and does not broaden into a global secret-storage redesign. The OAuth path adds no metadata, output, logging, or credential transport exposure beyond that existing contract.

### Validation

- Focused provider/credential suite: `224 passed` before the final cancellation addition; `28 passed` for the updated Claude OAuth and credential tests.
- Full suite: `5004 passed, 2 skipped`; GUI: `366 passed`.
- `make lint`: Python Ruff and GUI ESLint passed after the final provider-only cancellation tweak.

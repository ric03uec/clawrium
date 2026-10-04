## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T07:14:13Z
**Model**: gpt-5.6-terra

```prompt
Execute only GitHub issue #999, [Parent #989] Phase 4: credential modes and local secret boundary. You are a Pi worker in `/home/devashish/workspace/ric03uec/clawrium-issue-999` on branch `issue-999-claude-credential-modes`, stacked on `issue-997-claude-settings`. Read `AGENTS.md`, issue #999, parent #989, `.itx/989/01_SCAFFOLD.md`, and inherited #995-#997 changes before editing. Create and maintain a task checklist.

Scope: implement the local/provider credential-mode model for Claude agents only. Model exactly two mutually-exclusive active modes: OAuth normalized bearer token stored as encrypted per-instance `CLAUDE_CODE_OAUTH_TOKEN`, OR Anthropic API key stored as encrypted per-instance `ANTHROPIC_API_KEY`. Integrate with existing secret/provider storage patterns; select/import only from explicit supported local source contracts. Reject both modes active; preserve mode-switch safety by removing the prior instance secret only after replacement succeeds. Never store/copy secrets in hosts.json, manifest/config settings, provider metadata, CLI output, events, diffs, logs, or test snapshots. Never copy a keychain, browser profile, local `~/.claude`, opaque credential DB, or invent an OAuth file path. If portable OAuth export cannot be safely implemented from a known source, provide an explicit supported interface/error and record a Callout; do not scrape credentials.

Hard boundary: do NOT create/write any remote credential env file, remote secret extra-vars transport, managed shell startup snippet, or change shell behavior: those are #998. Do NOT modify Claude configure/sync settings rendering (#997) except unavoidable narrow integration boundaries; no install/lifecycle/no-daemon changes (#995/#996), no command-path changes (#1000), broad verification/removal (#1002), i-wolf E2E (#1003), or docs/help (#1001). Never launch Claude Code or a daemon.

Implement focused tests for mode exclusivity, redaction/state boundaries, safe source behavior, replacement/cleanup ordering, and existing provider regressions. Run `make test` and `make lint`. Use `apply_patch` for edits. Use stateless ATX CLI review, up to 3 iterations: `atx review request --worktree issue-999-claude-credential-modes --prompt "Review the full diff against issue-997-claude-settings. Focus on credential-mode exclusivity, encrypted-secret boundaries, redaction, safe OAuth handling, replacement ordering, regressions, and tests." --format json --timeout 15m`. Persist `.itx/999/atx-session.json` and append `.itx/999/01_EXECUTION.md`. Commit, push, and open a PR based on `issue-997-claude-settings`, explicitly including `Stacked on top of issue-997-claude-settings`, AGENTS ATX review details, testing, and a `## Callouts` section. Do not merge. Do not ask the user questions; record decisions/blocks as Callouts. Opening a reviewed stacked PR is your handoff.
```

**Output**: Added the Claude-only local credential-mode model, atomic per-instance secret replacement, explicit environment-only OAuth import, and focused secret-boundary coverage.

### Scope decisions

- OAuth has one portable source contract: an explicitly exported `CLAUDE_CODE_OAUTH_TOKEN` in the invoking process environment. The importer normalizes an optional `Bearer ` prefix and reads no files, keychains, browser profiles, local `.claude` directories, or credential databases.
- Credential state derives only a non-secret mode from the encrypted per-instance secret store. It does not write hosts state, settings, provider metadata, output, events, logs, diffs, or any remote transport.
- `replace_instance_secret` stages the replacement and removal under the existing secrets lock, then performs one atomic save. A failed save preserves the exact persisted pre-switch mapping.
- #998 remote activation, #1000 command paths, and all other deferred phases remain untouched. Claude Code and daemons were never invoked.

### Validation

- Focused credential/provider/settings tests: `28 passed` before review and `56 passed` after review fixes.
- `make test`: `4941 passed, 2 skipped`; GUI: `366 passed`.
- `make lint`: Ruff and Next.js ESLint passed.

### ATX review iterations

1. **2/5 normalized / 3/5 envelope** — added direct replacement primitive coverage for bidirectional mode switches, per-instance isolation, existing-target metadata, no-op removals, invalid keys, and atomic-save failure persistence.
2. **2/5 normalized / 2.5/5 envelope** — staged implementation paths so ATX could inspect them; added malformed OAuth/API-key rejection and failure-path redaction coverage.
3. **3/5 normalized / 4/5 envelope** — no blockers, warnings, or suggestions. The three-iteration contract prevented a fourth review; the normalized rating discrepancy is recorded in the PR Callouts.

### Environment note

`apply_patch` is not installed in this worker environment. The implementation used the harness's supported precise-edit/write tools instead; formatting was performed with Ruff.

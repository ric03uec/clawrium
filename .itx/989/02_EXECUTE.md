# Issue #989 — Execution Evidence

## Summary

Implemented the first stacked PR for Claude API-key authentication. Claude now uses exactly one credential mode at a time: a private API-key environment artifact or its native OAuth credentials artifact. Configure and sync replace the selected artifact before removing the stale opposite artifact; shell commands activate only the API-key environment when selected.

## Verification

- Focused regression suite: `128 passed in 1.91s`
- Full suite: `make test` passed.
- Lint: `make lint` passed.
- UI build: `make build-ui` passed.
- `git diff --check` passed; a repository scan found no reference to the protected test credential file.

## Isolated wolf-i validation (redacted)

A fresh `claude-api-key-e2e` agent was created on `wolf-i`, loaded with the protected test credential through stdin, and synced. The following secret-free assertions passed:

- API-key environment was non-empty in `clawctl agent shell`.
- OAuth token environment was empty.
- `~/.claude/clawrium-credentials.env` was owned by the dedicated agent user and mode `0600`.
- Native OAuth credentials artifact was absent.
- `settings.json` contained neither credential variable.

One minimal Claude prompt (`Reply exactly: OK`) was attempted with output and error content retained only in a transient remote directory and never displayed. It returned `AUTH_PROMPT_RESULT=failed`; it did **not** match the redacted invalid/unauthorized-credential classification. Therefore this execution does not claim that the protected credential authenticated successfully.

The dedicated agent was deleted successfully afterward; its local state was absent, and the pre-existing `claude-wolf` agent record remained present. A direct SSH account-removal spot check could not run because this control session does not have a direct public-key route to `wolf-i`; the normal `clawctl agent delete` remote cleanup completed successfully.

## Execute Log

**Stage**: execute
**Skill**: /itx-execute
**Timestamp**: 2026-10-04T21:37:17Z
**Model**: gpt-5.6-terra

```prompt
Implement first stacked PR for Clawrium #989 on feat/claude-api-key-auth. Restore secure, mutually exclusive Claude API-key configuration/sync while preserving native OAuth. Validate a fresh isolated agent on wolf-i using the protected local test key without exposing it; run tests, lint, ATX review, commit, push, and open a PR.
```

**Output**: Implemented Claude API-key credential activation, recorded redacted verification evidence, and retained the authenticated-prompt result without exposing a credential.

## Final Verification and ATX Review

- Final `make test`: `5058 passed, 2 skipped` (plus `366` GUI tests).
- Final `make lint`: Python Ruff and GUI ESLint passed.
- `git diff --check` passed; the final tracked diff contains no protected test credential reference and no unrelated Herdr reconciliation formatting.
- ATX review iteration 1: 3.5/5, no blockers; corrected inaccurate atomic-switch documentation and added verified stale-artifact cleanup/rollback.
- ATX review iteration 2: 2.5/5, blockers found in rollback preservation and transport-exception handling; fixed by privately backing up/restoring an existing selected artifact in configure playbooks and staging canonical-sync credentials before cleanup.
- ATX review iteration 3: 4/5, no blockers. Its backup-cleanup warning was addressed afterward by placing backup, replacement, stale cleanup, and backup deletion inside one rescue-capable playbook block; final full tests and lint passed after that adjustment. Three review iterations were the requested maximum.

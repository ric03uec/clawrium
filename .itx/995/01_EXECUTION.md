## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T05:16:00Z
**Model**: pi-coding-agent

```prompt
Execute only issue #995: add install-only first-class `claude` type with dedicated account/home/prefix, pinned package install and state recording, strict no-invocation/no-auth/no-service/no-UI boundaries, owned-resource removal, tests, logs, test/lint, ATX review, commit/push/PR.
```

**Output**: Added the scoped Claude install/remove registry boundary, validation, tests, and ATX review record.

### Scope correction

The initial ATX review identified macOS lifecycle removal dispatch. The user explicitly deferred all lifecycle.py and no-daemon behavior to #996, so those changes and their tests were reverted. The finding is recorded as deferred in the PR Callouts.

### ATX review iterations

1. **1/5** — fixed account adoption/deletion, immutable package-version, and marker ownership issues.
2. **3/5** — hardened root-owned marker permissions; lifecycle behavior remained explicitly deferred to #996.
3. **2/5 body / 4/5 envelope** — ATX requested complete marker-predicate regression assertions. The assertions were tightened after the final review; the three-iteration ceiling prevented a fourth request. Full tests and lint passed afterward.

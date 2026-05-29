## Phase 1 — Drop `--canonical` flag

**Stage**: execute-phase-1
**Skill**: /itx:execute (manual invocation)
**Timestamp**: 2026-05-29T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Execute Phase 1 of issue #560 in this worktree.

Scope:
- src/clawrium/cli/clawctl/agent/sync.py: remove --canonical and --force typer Options; delete the if canonical / else branch; canonical pipeline becomes unconditional default.
- src/clawrium/core/lifecycle.py:1718-1790: delete the legacy Discord/Slack hydration block (the conditional reading agent_record.config.channels.discord).
- src/clawrium/core/lifecycle.py: grep + delete any other dead code under configure_agent reachable only from the legacy sync path.
- tests/cli/clawctl/agent/test_sync*.py and related: drop --canonical from test invocations; rewrite tests that exercised the legacy path to assert canonical-as-default.

Workflow:
1. Implement changes; run make test + make lint.
2. Commit with --no-verify; push; open stacked PR on fix/zeroclaw-full-config-template.
3. Run ATX review CLI up to 3 rounds; fix blockers between rounds.
4. If still blocked after 3, leave PR open with [ITX-STUCK] comment.
```

**Output**:
- PR #566 opened, base `fix/zeroclaw-full-config-template`.
- 4 commits delivered:
  - `3bf604d` — initial drop of `--canonical` + `--force`; legacy `sync_fn` fork removed.
  - `84fb521` — ATX round 1 fixes: `--force` restored (operational deadlock), `_PHASES` drop of `re-pairing gateway`, docstring refresh, 4 error-path tests, W4/W5/W7 test tightening.
  - `fcef53d` — ATX round 2 W-level fixes: `--force` forwarding test, `--workspace` propagation test, stale-comment cleanup, tighter `--canonical` regression guard.
  - `397d76a` — ATX round 3 residual stale-comment fix.
- `src/clawrium/core/lifecycle.py:1718-1790` Discord/Slack hydration **NOT** deleted (TODO-FOLLOWUP): the block is inside `configure_agent`, which is still invoked by `start_agent` and `clawctl agent configure` (both out of #560 scope per the plan).
- Tests at baseline (45 pre-existing zeroclaw failures unrelated to this PR remain); lint clean.

**ATX status**: `[ITX-STUCK]` after 3 rounds. Unresolved blockers:
- **B1** — `sync_agent_canonical` does not re-pair the zeroclaw gateway bearer (#437 invariant regression once canonical becomes default path).
- **B2** — `sync_agent_canonical` does not advance the agent state machine to READY (`start_agent` gates on READY → `provider attach → sync → start` is broken end-to-end).
- **B3** — `_open_ssh` uses `paramiko.AutoAddPolicy` (pre-existing, surfaced now that canonical is the only path).
- Several warnings (W-unbound, W-macOS, W-new-2/3) documented in PR Callouts.

Stuck comment with full reasoning: https://github.com/ric03uec/clawrium/pull/566#issuecomment-4580628728

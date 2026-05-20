# Issue #424: Hermes Discord `allowed_channels` lacks comma-only guard + empty-channel warning

URL: https://github.com/ric03uec/clawrium/issues/424

## Execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-20
**Model**: claude-opus-4-7

```prompt
fix issue 424
```

**Output**: Added comma-only guard + empty-channel `[yellow]Note:[/yellow]` to the hermes Discord `allowed_channels` branch in `src/clawrium/cli/agent.py`, mirroring the zeroclaw `allowed_users` / `allowed_guilds` guards from #422. Added four regression tests under `TestRunChannelsStageHermesDiscord`: comma-only rejection with full no-side-effects contract, parametrized empty-channel warning across both `require_mention` values, valid happy-path with companion-field structural guards, and duplicate-preservation pin.

Plan source: the issue body contained the full fix sketch with file/line pointers and proposed test names, so no separate `00_PLAN.md` was authored. The fix was executed against that sketch.

ATX review iterations:
- Round 1 (3/5, BLOCKED on B1): test missing no-mutation assertion. Fixed B1 + W1–W6 (bulk-assign parity, severity prefix, confirm patch, len/require_mention guards, happy-path test, defensive `(raw or "").strip()` form).
- Round 2 (3/5, no blockers but below merge threshold): five new warnings (incomplete no-mutation contract, missing severity prefix, tautological assertion, dedup behavior, structural completeness). All addressed via secret-store assert_not_called, severity-prefix assert, parametrize over `require_mention_value`, dedup pin test, companion-field assertions.
- Round 3 (4/5, no blockers, merge threshold met): three small warnings (Note severity prefix, complete_stage call assertions, confirm assert_not_called on rejection). Closed post-review as test-only tightening with no production-code change.

# Execution Log — Issue #795

Phase 3 of #790: prune the legacy `config.provider/providers/channels`
mirror from existing `hosts.json` files at `load_hosts()` time.

## Changes

- `src/clawrium/core/hosts.py` — `_prune_agent_config_mirror()` strips
  Group A keys from every agent record; module-level guard (real `raise
  RuntimeError`, not `assert`) prevents future maintainers from
  widening the prune set into Group B (`gateway`/`dashboard`/`api_server`).
- `tests/core/test_hosts.py` (new file) — 16 tests covering Group A
  strip (parametrized), Group B preservation, byte-stable load→save
  round-trip on both Group-A-residue and clean input, and the defensive
  `isinstance` branches for non-dict records / non-dict config /
  missing-config / missing-agents cases. Multi-host × multi-agent
  fan-out test covers the loop semantics.
- `CHANGELOG.md` — entry under `### Changed` describing the on-disk
  shrink.

## ATX Review

- Iter 1 — aggregate 4/5, 0 blockers, 4 warnings (W1 negative-list
  guard, W2 defensive-branch tests, W3 multi-host fan-out, W4
  parametrize). All addressed.
- Iter 2 — aggregate 4/5, 0 blockers, 1 new warning (W1: `assert`
  stripped under `python -O`) + 8 suggestions. W1 fixed by switching
  to `if/raise RuntimeError`. S6 (idempotence test should assert
  Group A bytes absent from on-disk JSON) and S7 (strip test should
  assert exact key set) also applied. Other suggestions documented
  as Callouts on the PR.

No iter-3 — already above the 3/5 threshold with no blockers; W1
fix was a pure tightening.

## Prompt Log

### Execution

**Stage**: execute
**Skill**: /itx:execute
**Timestamp**: 2026-06-23T23:30:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 795 --pr-base=issue-794-stop-writing-config-mirror — Stacked on top of issue-794-stop-writing-config-mirror (PR #802, itself stacked on PR #800). Use atx CLI (atx review request) for review, NOT MCP. Plan: issue #795 + .itx/790/01_SCAFFOLD.md (Phase 3). Open PR against issue-794-stop-writing-config-mirror, not main. Include Callouts in PR body.
```

**Output**: `src/clawrium/core/hosts.py` + `tests/core/test_hosts.py`
(new) + `CHANGELOG.md` updated. PR opened against
`issue-794-stop-writing-config-mirror`.

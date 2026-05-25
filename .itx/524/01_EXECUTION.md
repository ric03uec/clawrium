# Issue #524 — Flat help sweep

## Execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-25T08:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:execute 524
```

**Output**: Added `rich_markup_mode=None` to all 37 `typer.Typer(...)` instances
across `src/clawrium/cli/` (both the `clawctl` and legacy `clm` command trees).
Added `tests/cli/test_help_flatness.py` as a regression guard. Updated a stale
comment + assertion in `tests/cli/agent/test_configure_no_channel_prompts.py`.

ATX review iterations stored as JSON under `.itx/524/atx-review-{1,2}.json`.

# Execute log — issue #860

**Stage**: execute
**Skill**: /itx:execute (manual)
**Base**: `origin/main` @ `fd9e72f`
**Branch**: `fix/issue-860-remove-dead-channels-wizard`
**Model**: claude-opus-4-7

## Prompt

```prompt
go ahead and execute . use atx cli to rview
```

## Changes applied

- `src/clawrium/cli/agent.py`: deleted `_build_legacy_discord_channels_block`
  (lines 777-806), deleted `_sync_channel_config` (lines 715-774, orphaned
  after the wizard-body removal per ATX iter-2 S1), deleted the ~640-line
  unreachable body under `raise typer.Exit(code=2)` in `_run_channels_stage`
  (former lines 877-1514). Changed `_run_channels_stage` return type from
  `-> bool` to `-> NoReturn` (ATX iter-1 W1) and added `NoReturn` to the
  typing import. Tightened docstring.
- `tests/cli/agent/test_legacy_discord_channels_block.py`: deleted — its
  subject function is gone.
- `tests/cli/agent/test_configure_no_channel_prompts.py`: tightened
  `exit_code != 0` → `== 1` on the two channels-stage tests (ATX iter-1
  W2; corrected from the reviewer's suggested `== 2` because the observable
  exit path is clawctl's `emit_error` default of 1, not the legacy
  driver's raise).
- `tests/cli/clawctl/agent/test_configure_errors.py`: same tightening on
  `test_channels_stage_deprecation_fires_before_agent_lookup`.
- `CHANGELOG.md`: `### Internal` entry describing the removal.

## Verification

- `make lint`: green (ruff + eslint).
- `make test`: 4630 passed / 8 skipped / 0 failed.
- Grep sanity:
  - `_build_legacy_discord_channels_block` — zero refs anywhere.
  - `_sync_channel_config` — zero refs anywhere.
  - `typer.prompt` inside `_run_channels_stage` — none (both remaining
    `typer.prompt` calls in the file are in `_run_providers_stage` /
    `_run_identity_stage`).

## ATX review iterations

| # | Rating | Blockers | Cost | Time | Outcome |
|---|--------|----------|------|------|---------|
| 1 | 4/5 | 0 | $1.13 | 3m 46s | W1 (`-> NoReturn`), W2 (`== 1` assertions) — both fixed |
| 2 | 4/5 | 0 | $1.90 | 6m 21s | S1 (`_sync_channel_config` orphaned) — fixed. Remaining findings pre-existing / out of scope. |

Final rating: 4/5, no blocking issues.

## Notes / deferred

- Iter-2 W1: two pre-existing `--channel` flag tests still use `!= 0`.
  Structurally similar to what we tightened but not introduced by this
  diff — out of scope.
- Iter-2 S2: pre-existing `rich_escape` gap on `claw_type` in the
  deprecation branch we preserved — out of scope, low severity.
- Iter-2 S3: `stdin_not_tty` fixture missing on one test — pre-existing,
  test still passes without it.
- Iter-1 W3: no test for the `channel_examples is None` (openclaw /
  nemoclaw) branch of the deprecation prelude. Low priority follow-up.
- Full removal of `_run_channels_stage` (still wired into legacy driver
  STAGES dispatchers) is deferred to #707.

**Output**: single commit ready on `fix/issue-860-remove-dead-channels-wizard`;
awaiting user's go-ahead to push / open PR.

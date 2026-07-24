# Issue #860 — Remove unreachable `_run_channels_stage` dead code

**Base:** `origin/main` @ `fd9e72f`
**Labels:** `agent-ready`, `complexity:s`
**Type:** Pure dead-code removal — no user-visible behavior change.

## Problem (verified against current main)

`src/clawrium/cli/agent.py:_run_channels_stage` (line 808) prints a
deprecation notice and unconditionally `raise typer.Exit(code=2)` at
**line 876**. The remainder of the function — **lines 877 → 1514, ~640
lines** — is unreachable:

- Imports (`get_instance_key`, `set_instance_secret`) inside the dead
  body.
- Interactive `typer.prompt(...)` calls for guild ID, channel ID, user
  ID, Discord/Slack tokens (`hide_input=True`), allowed_channels,
  home_channel, stream mode, etc.
- Persistence via `complete_stage(..., StageStatus.COMPLETE, ...)`
  (line 1502) inside the dead branch.
- Call to `_build_legacy_discord_channels_block(...)` at line 1236 —
  the **only production call site** of that helper.

The function ends at line 1514; the next `def` (`_run_validate_stage`)
starts at line 1517.

## Drift check — issue is still accurate

- Deprecation exit at line 876: ✅ present, unconditional.
- Dead body from 877 → 1514: ✅ present, unreachable.
- The `# WARNING (orig audit: ATX #794 iter-2 W5)` comment (lines
  829-835) explicitly names this issue's cleanup as pending "alongside
  the legacy `clawctl` driver retirement (#707)". #707 is still open
  per [clawctl vs legacy CLI split](../../.claude/…) memory, but #860
  is a self-contained slice — removing the dead body does not require
  #707 to land first.
- `_run_channels_stage` is still wired into the legacy driver's stage
  dispatchers at `agent.py:2171` and `agent.py:2216`. It stays wired;
  only the body shrinks (the deprecation exit is preserved).
- The modern `clawctl` path in `src/clawrium/cli/clawctl/agent/configure.py`
  already returns its own deprecation exit for `--stage channels`
  (lines 174-179) and does NOT call `_run_channels_stage`, so those
  code paths are unaffected.

## Scope of change

### 1. `src/clawrium/cli/agent.py`

- Delete lines **877 → 1514** (the entire dead body under `raise
  typer.Exit(code=2)`).
- Delete `_build_legacy_discord_channels_block` at lines **777 → 806**.
  After removing the dead body its only remaining reference is the
  isolated test file (below), which we also remove — the helper has
  no other production caller.
- Preserve the deprecation prelude (lines 823-876) as-is: the
  `_channel_types_by_agent` dict, both console.print branches, and
  the unconditional `raise typer.Exit(code=2)`.
- Preserve `_run_channels_stage`'s signature — it stays in the STAGES
  dispatchers at 2171/2216. The docstring should be tightened to
  describe the current (deprecation-only) behavior; drop the "Returns:
  True if stage completed successfully" line since it now always
  raises.
- No imports at module top need removing: `re`, `StageStatus`,
  `complete_stage`, `typer`, `console` are all still used elsewhere.
  (Verified via grep — see grep summary at bottom.)

### 2. `tests/cli/agent/test_legacy_discord_channels_block.py`

Delete the file. Its three tests exclusively exercise
`_build_legacy_discord_channels_block`, which no longer exists after
this change. The file's own docstring acknowledges the helper exists
"specifically so this invariant can be exercised in isolation" for
the wizard body we're removing.

### 3. Tests that MUST continue to pass unchanged

Re-run these to confirm the deprecation contract is intact:

- `tests/cli/agent/test_configure_no_channel_prompts.py`
  - `test_configure_channels_stage_emits_deprecation_pointer` — asserts
    `--stage channels` prints "deprecated" + both `clawctl channel
    registry create` and `clawctl agent channel attach` pointers.
  - `test_configure_stage_channels_fires_before_agent_resolution` —
    asserts the deprecation fires before agent lookup.
  - `test_configure_module_has_no_channel_prompt_calls` — static
    check that `clawctl/agent/configure.py` has no channel prompts.
    Unaffected (targets a different file).
  - `test_stage_help_text_omits_channels_from_valid_values` —
    unaffected.
- `tests/cli/clawctl/agent/test_configure_errors.py::test_channels_stage_deprecation_fires_before_agent_lookup`
  — same contract via the clawctl path.
- `tests/test_hermes_onboarding.py`, `tests/test_registry.py`,
  `tests/test_onboarding.py`, `tests/test_install.py` — all reference
  the `channels` stage name inside manifests / state machines, none
  call `_run_channels_stage`. Unaffected.

### 4. Changelog

Add one line under `## [Unreleased] / ### Internal` in root
`CHANGELOG.md` (per AGENTS.md changelog rules; this is not
user-visible so `### Fixed`/`### Changed` are the wrong sections):

```
### Internal
- Remove ~640 lines of unreachable legacy wizard body from
  `_run_channels_stage` (#860). No user-visible change; the
  `--stage channels` path continues to exit 2 with the modern
  `clawctl channel` guidance.
```

Confirm the `### Internal` subsection scaffold from commit `547b4ec`
is in place; if not, add it under `[Unreleased]`.

## Non-goals

- Do NOT remove `_run_channels_stage` itself — it is still dispatched
  from the legacy driver's STAGES tables (agent.py:2171, 2216). That
  removal belongs to #707 (legacy CLI retirement).
- Do NOT touch the `clawctl` deprecation branch in
  `src/clawrium/cli/clawctl/agent/configure.py`. Already correct.
- Do NOT change onboarding state machine, `STAGES`,
  `STATE_RESUME_IDX`, or `can_skip_stage` — the `channels` stage
  entry stays, only its wizard implementation shrinks.

## Verification plan

Local:
- `make lint` — ruff must pass.
- `make test` — full suite. Expected passing:
  - all preserved deprecation-pointer tests listed above.
  - full `tests/cli/agent/` and `tests/cli/clawctl/agent/` dirs.
  - full `tests/test_onboarding.py`, `test_hermes_onboarding.py`,
    `test_registry*.py`, `test_install.py`.
- Grep sanity after edit:
  - `grep -n "_build_legacy_discord_channels_block" src/ tests/` → no
    hits.
  - `grep -n "typer.prompt" src/clawrium/cli/agent.py` — should show
    zero hits inside `_run_channels_stage`'s remaining ~70-line body.
  - `wc -l src/clawrium/cli/agent.py` — should shrink by ~670 lines.

Real-host UAT — **not required** for this change per the memory rule.
Justification: (a) the removed code is provably unreachable (guarded
by unconditional `raise` at line 876, verified via mypy/pytest), and
(b) the two deprecation tests directly cover the only exit path an
operator can reach via `--stage channels`. There is no on-host
behavior to observe. Note this justification in the PR body.

## Risk

- **Low.** Removing code below an unconditional `raise` cannot change
  runtime behavior. The only observable surface is the deprecation
  message the operator sees — the tests pin that message verbatim.
- One indirect risk: `_build_legacy_discord_channels_block` was
  written (per PR #747 W1) to lock in an invariant against a future
  revert. That invariant becomes moot once its only production caller
  is deleted, so removing the helper + its test does not lose
  coverage — there is no code path left that could regress the shape.

## Estimated size

- src/clawrium/cli/agent.py: **−670 lines** (~640 dead body + ~30
  helper) / **+~5 lines** (tightened docstring).
- tests/cli/agent/test_legacy_discord_channels_block.py: **−72
  lines** (file deletion).
- CHANGELOG.md: **+~4 lines**.

## Suggested commit shape

Single commit:

```
refactor(cli/agent): remove unreachable channels-stage wizard body

_run_channels_stage's body under the unconditional
`raise typer.Exit(code=2)` (line 876) was ~640 lines of dead
interactive wizard code. Drop it, and drop
`_build_legacy_discord_channels_block` (its only production caller
lived in that dead body). The deprecation prelude and exit code are
preserved verbatim, so `clawctl agent configure <name> --stage
channels` continues to print the same guidance and exit 2.

Closes #860
```

## Grep summary (verified pre-plan against `fd9e72f`)

- `_run_channels_stage` production refs: `agent.py:808 (def)`,
  `agent.py:2171`, `agent.py:2216`. Test refs: mentions only, no
  direct calls. ✅ safe to keep the function shell.
- `_build_legacy_discord_channels_block` refs: `agent.py:777 (def)`,
  `agent.py:1236 (dead body)`, plus the one dedicated test file.
  ✅ safe to delete both helper and test.
- Deprecation-exit test contract (message + before-agent-resolution)
  is enforced by two independent test files, one per CLI driver.
  ✅ removal cannot silently regress the user-visible surface.

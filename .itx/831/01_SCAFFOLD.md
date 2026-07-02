# Issue #831 — Phased execution

## Phase 1: Render plumbing

**Entry**: branch checked out, plan written.

**Tasks**:
- Add `context_window: int = 0` to `AttachedProviderInputs` dataclass
  in `src/clawrium/core/render.py`.
- In `build_render_inputs` (hermes branch), populate
  `context_window=int(entry_record.get("context_window") or 0)` when
  constructing each `AttachedProviderInputs`.

**Exit**: existing tests still pass (no behavior change yet — template
ignores the new field). `make lint` clean.

## Phase 2: Template

**Tasks**:
- Edit `hermes-config.canonical.yaml.j2` litellm branch:
  - Primary `model:` block: after `default:`, conditionally emit
    `  context_length: {{ provider.context_window }}` when
    `provider.context_window`.
  - Aux loop (litellm path): after `model:`, conditionally emit
    `    context_length: {{ entry.context_window }}` when
    `entry.context_window`.
- Do NOT touch any other branch.

**Exit**: visual diff inspection of template output for litellm cases
matches expected shape.

## Phase 3: Render tests

**Tasks**: add 4 render tests in `tests/core/test_render.py`:
- `test_hermes_litellm_primary_no_context_window_omits_context_length`
- `test_hermes_litellm_primary_with_context_window_emits_context_length`
  (check `context_length: 131072` appears, positioned after `default:`)
- `test_hermes_litellm_aux_with_context_window_emits_context_length`
- `test_hermes_openrouter_with_litellm_aux_only_aux_emits_context_length`

**Exit**: `make test` green (4 new tests pass + no regressions).

## Phase 4: CLI flag

**Tasks**:
- `clawctl provider registry create`: add `--context-window` Option;
  if provided, persist to the litellm record. Reject if used with a
  non-litellm `--type`.
- `clawctl provider registry edit`: add `--context-window` Option;
  reject if record type is not litellm; persist to record on update.

**Exit**: `make test` covers CLI roundtrip.

## Phase 5: CLI tests + changelog

**Tasks**:
- Add CLI tests for create + edit with `--context-window` flag.
- Add `### Added` entry to `CHANGELOG.md` `[Unreleased]`.

**Exit**: `make lint && make test` all green.

## Phase 6: Real-host UAT

Run UAT steps from 00_PLAN.md against `clawrium-gtm` on `wolf-i`.
Capture evidence: rendered YAML snippet, doctor status, dashboard
status. Stop on first failure and report.

## Phase 7: Commit + PR

- Commit all changes incl. `.itx/831/` files.
- Push branch.
- `gh pr create` with ATX review section template (request first
  review round; iterate until rating > 3 and no blockers).
- DO NOT merge.

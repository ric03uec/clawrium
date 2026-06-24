# Execution Log — Issue #793

Phase 1 of #790: fix the GUI read path so the agent landing page and
`clawctl agent get` resolve the model from the tier-1 `providers`
attachment list + `providers.json`, not from the stale
`config.provider.default_model` mirror in `hosts.json`.

## Summary of changes

- `src/clawrium/cli/tui/data.py`
  - Added `_resolve_provider_display(claw_record)` returning
    `(provider_name, provider_type, model)`. Precedence mirrors
    `core/render.py:build_render_inputs` lines 644–646.
  - Replaced the three duplicated inline blocks in
    `get_fleet_data_local`, `get_fleet_data`, and `_build_agent_identity`
    with calls to the helper.
  - Narrowed the IO-error `except` to
    `(ProvidersFileCorruptedError, OSError)`.
  - Deleted the now-unused `_resolve_provider_name`.
- `src/clawrium/cli/clawctl/agent/describe.py:83` — dropped the
  `config.get("channels")` fallback (intentional Phase 1 scope; see
  Callouts in PR body).
- `tests/test_tui/test_tui_data.py` — added unit tests for the helper,
  the regression test `test_build_agent_identity_ignores_stale_tier2_provider`,
  IO-error / invalid-name / garbage-entry / missing-type / missing-default-model
  branch tests; updated the no-attachment test to seed a stale
  `config.provider` mirror so it doubles as a regression gate.
- `tests/test_gui_routes_fleet.py` — added
  `test_fleet_endpoint_returns_tier1_model` and
  `test_fleet_endpoint_broken_attachment_fails_closed`.
- `tests/test_gui_fleet_health.py` — migrated `test_local_fields_populated`
  to the tier-1 + providers.json shape.

## ATX Review

- Iteration 1: rating 3/5, no blockers, 8 warnings, 6 suggestions.
- Iteration 2: rating 4/5, no blockers, remaining items are suggestions
  only. Clears the ITX merge bar (rating > 3/5 and zero blockers).

Session metadata in `atx-session.json` next to this file.

## Verification

- `make lint-py` clean.
- `uv run pytest` — 3926 passed, 8 skipped (no failures).
- Manual GUI verification deferred to PR review (see Callouts).

---

## Prompt Log

### Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-06-23T20:30:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 793 — use atx CLI (atx review) for review, NOT MCP. The implementation plan lives in issue #793 and its parent .itx/790/01_SCAFFOLD.md (Phase 1). Open the PR against main when done. Include the Callouts section in the PR body per the skill spec.
```

**Output**: Phase 1 implementation across 5 files, 2 ATX review iterations
(3/5 → 4/5), branch `issue-793-fix-gui-read-path` ready to push.

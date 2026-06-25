# Issue #819 — Execution log

## Summary

Single-file fix: add `litellm` branch to
`src/clawrium/platform/registry/openclaw/templates/verify_config.py:_expected_model_id`.

The canonical renderer (post-#756) emits `<provider-name>/<model>` for
litellm providers; the verify script fell through and expected the
raw `default_model`, so every `clawctl agent configure --stage
providers --provider <litellm>` failed at the `Verify openclaw.json
configuration` Ansible task with `no_log: true` masking the cause.

Provider overlay already includes `name`
(`src/clawrium/core/lifecycle.py:605`), so the verify script needed
no extravar plumbing changes — the expected JSON dumped to
`/tmp/clawrium_expected_config_<name>.json` already carries
`provider.name` for every attached provider.

## Changes

- `src/clawrium/platform/registry/openclaw/templates/verify_config.py`
  — add `provider_type == "litellm"` branch, prefix with
  `provider.get("name")`. Defensive fall-through when `name` is
  missing.
- `tests/test_verify_config_script.py` — four new tests covering:
  normalize unprefixed → prefixed, already-prefixed not double-
  prefixed, on-host unprefixed fails verify, missing `name` falls
  through.
- `CHANGELOG.md` — `### Fixed` entry referencing #819.

## Verification

- `make lint-py` → All checks passed.
- `make test-py` → 4037 passed, 8 skipped (pre-existing wheel
  skips; unrelated).

## Stage execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-06-24T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:execute 819

The issue #819 body already has the full root cause + fix plan...
Single-file fix in src/clawrium/platform/registry/openclaw/templates/verify_config.py (S-sized).
```

**Output**: 1 file fix + 4 tests + changelog entry; full suite green.

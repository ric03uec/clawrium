# Release v26.6.2 prompt log

## Release

**Stage**: release
**Skill**: /itx-release
**Timestamp**: 2026-06-15T04:26:31Z
**Model**: claude-opus-4-7

```prompt
plan the next release
```

**Output**: Cut `release/v26.6.2` (PR #709) — bumped `pyproject.toml` /
`uv.lock` / `AGENTS.md` to 26.6.2; synced `clawrium==26.6.2` /
`clawctl 26.6.2` in `docs/installation.md`, `website/docs/installation.md`,
`website/docs/guides/quickstart.md`, `website/docs/scenarios/101.md`;
restructured root `CHANGELOG.md` with BREAKING / Added / Changed / Fixed /
Documentation sections, then archived to `docs/releases/26.6.2/CHANGELOG.md`
and reset root to the empty `[Unreleased]` template. Documented BREAKING
removal of the legacy `clm` CLI entry point (#706). Manual review only —
no ATX requested for the release PR (Stop-hook ATX still ran and returned
4/5 with 4 non-blocking suggestions; S1–S4 addressed in a follow-up commit
on the same branch).

**Test status at cut**:

- `make lint` — pass (ruff + next-lint)
- `make test` (pre-edit) — 3402 passed / 2 skipped (backend); 278 passed
  (frontend, 26 files)
- `make test` (post-edit, after all release-bump edits) — 3402 passed / 2
  skipped (backend); 278 passed (frontend, 26 files)
- Stale-mention scan (`git grep '\b26\.6\.1\b'` excluding
  `docs/releases/26.6.1/` and `website/build/`) — clean
- Diff-scope guard (9 files vs known-set regex) — clean

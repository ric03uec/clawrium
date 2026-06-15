# Release v26.6.3 prompt log

## Release

**Stage**: release
**Skill**: /itx-release
**Timestamp**: 2026-06-15T05:16:48Z
**Model**: claude-opus-4-7

```prompt
plan the next release
```

(Continuation of the same `/itx-release` invocation that produced the
abandoned `v26.6.2` artifact.)

**Output**: Cut `release/v26.6.3` after `v26.6.2` was burned by GitHub's
immutable-releases policy. The original release branch landed via PR
#709 and a `v26.6.2` GitHub release was created, but `publish.yml`
failed at the `make test` step on a test-isolation race in
`src/clawrium/gui/routes/fleet.py` (module-level `asyncio.Semaphore` +
lifespan-shutdown executor races, both surfaced by PR #706's collection
re-ordering). A hotfix PR #710 landed the fleet.py + server.py fix on
main. Deleting the `v26.6.2` GitHub release and tag succeeded, but
re-tagging `v26.6.2` was permanently rejected with
`tag_name was used by an immutable release` (HTTP 422). GitHub locks
tag names forever once attached to a published release, so the cleanest
path forward was to ship the same content (release bumps + hotfix)
under `v26.6.3`.

This release PR therefore:

- Bumps `pyproject.toml` / `uv.lock` / `AGENTS.md` to `26.6.3`.
- Syncs `clawrium==26.6.3` / `clawctl 26.6.3` in
  `docs/installation.md`, `website/docs/installation.md`,
  `website/docs/guides/quickstart.md`, `website/docs/scenarios/101.md`.
- Renames `docs/releases/26.6.2/` → `docs/releases/26.6.3/`, updates
  the archive heading to `[26.6.3]`, rewrites the "Curation at release
  cut" preamble to capture the `v26.6.2` → `v26.6.3` pivot, and adds
  the #710 hotfix under `### Fixed`.
- Leaves the root `CHANGELOG.md` as the empty `[Unreleased]` template
  that PR #709 already reset it to.

**Test status at cut**:

- `make lint` — pass (ruff + next-lint)
- `make test` — 3402 passed / 2 skipped (backend); 278 passed
  (frontend, 26 files)
- Stale-mention scan (`git grep '\b26\.6\.2\b'` excluding
  `docs/releases/26.6.2/` and `website/build/`) — only the
  intentional historical references in
  `docs/releases/26.6.3/CHANGELOG.md` remain
- The hotfix in #710 was reproduced locally on Python 3.14 before the
  fix and verified to clear after.

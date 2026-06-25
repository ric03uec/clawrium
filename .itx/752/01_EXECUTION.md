# Issue #752 — Execution Log

## Context

The core bug from #752 (`_get_host_openclaw_version` hardcoding
`/home/<agent>/.openclaw/bin/openclaw` and breaking on macOS hosts) was
already addressed in commit 4aeeb55 (PR #818, "fix(macos): openclaw E2E
support"). That commit introduced:

- `_get_host_openclaw_version_linux` (uses `/home`)
- `_get_host_openclaw_version_macos` (uses `/Users`)
- Dispatcher `_get_host_openclaw_version` that takes `os_family`
- Test classes covering both OSes (`TestGetHostOpenclawVersionLinux`,
  `TestGetHostOpenclawVersionMacos`, `TestGetHostOpenclawVersionDispatcher`)
- Call-site plumbing `os_family=host.get("os_family", "linux")` in
  `sync_agent_canonical`

The bug is no longer reachable. The issue was open because nobody
explicitly closed it after the side-effect fix.

## What this PR does

This PR is the **tightening pass**: the two OS variants
(`_get_host_openclaw_version_linux` and `_get_host_openclaw_version_macos`)
were hardcoding `/home` and `/Users` literals via a local `home_root=`
kwarg to `_build_openclaw_version_probe`. The project invariant
(CLAUDE.md / AGENTS.md) says the OS→home-root mapping must come from
the single seam `core.playbook_resolver.home_root_for`. This PR
consolidates the variants onto that seam.

## Changes

1. `src/clawrium/core/lifecycle_canonical.py`:
   - Import `home_root_for` from `clawrium.core.playbook_resolver`.
   - `_get_host_openclaw_version_linux` passes
     `home_root=home_root_for("linux")` instead of literal `"/home"`.
   - `_get_host_openclaw_version_macos` passes
     `home_root=home_root_for("darwin")` instead of literal `"/Users"`.

2. `tests/core/test_lifecycle_canonical.py`:
   - New `TestGetHostOpenclawVersionHomeRootSeam` class with three tests:
     - `test_linux_variant_uses_home_root_for_linux` — monkeypatches
       the seam to a sentinel root and asserts the Linux variant
       picks it up (and does NOT contain the historical `/home` literal).
     - `test_macos_variant_uses_home_root_for_darwin` — symmetric
       pin for the macOS variant.
     - `test_resolver_currently_maps_to_expected_roots` — end-to-end
       assertion that the unpatched seam currently produces
       `/home/...` on Linux and `/Users/...` on macOS, using literal
       expected values (not the live resolver) so a hardcoded-literal
       revert in production would not silently pass.

3. `CHANGELOG.md`: one entry under `## [Unreleased] → ### Changed`
   noting the seam consolidation.

## ATX Review Path

- ATX CLI (`atx review request`) per user constraint, NOT the MCP path.

## Iter 1

- Rating 3.5/5.
- B1: `test_seam_matches_resolver_for_both_oses` was tautological
  (used `hrf('linux')` to build both production input and expected
  output — would pass against a hardcoded literal revert). Fixed by
  renaming to `test_resolver_currently_maps_to_expected_roots` and
  using literal `/home/wolf-i/...` and `/Users/wolf-m/...` as
  expected values.
- B2: CHANGELOG entry was under `### Fixed` but described a
  behaviorally-equivalent refactor. Moved to `### Changed`.
- S1: Fake helpers used `assert os_family == "linux"` — replaced with
  `raise ValueError` so it survives `python -O`.
- S2: Dropped redundant local `from clawrium.core import
  lifecycle_canonical as mod` import; tests now use the module-level
  `lc` alias directly with `monkeypatch.setattr(lc, "home_root_for",
  ...)`.

## Iter 2

- Rating 4.5/5, no blockers. "Ready to merge — all four iter-1
  findings are correctly resolved with no new issues introduced."

## Test Results

- `make lint-py`: passed.
- `make test-py`: 4036 passed, 8 skipped.
- The 24 tests in the `_get_host_openclaw_version*` family all pass,
  including the 3 new seam-pin tests.

---

## Execution Stage

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-06-24T22:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 752 — Read the issue body first; constraints: work in
this worktree, ATX via CLI (not MCP), home_root_for seam invariant,
tests for both OSes, lint+test before PR, ATX format closing #752.
```

**Output**: Seam-consolidation refactor for the openclaw version
probe + 3 new regression-guard tests + changelog entry. 2 ATX
iterations (3.5/5 → 4.5/5). Ready to merge.

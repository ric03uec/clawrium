# Execution Log: issue #592

## Execute

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-06-01T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:execute 592 (worktree mode; subtasks #598 and #599 are post-merge manual verification and out-of-scope for this PR)
```

**Output**: Implemented `clawctl agent upgrade` per plan §"CLI surface":
- Bumped openclaw → 2026.5.28 (manifest + install playbook default).
- Bumped hermes → v2026.5.29.2 (manifest with fresh sha256 of upstream
  install.sh + install playbook default).
- Zeroclaw left unchanged per plan §"Decisions".
- New `clawctl agent upgrade <name> [--yes] [--skip-drift-check] [-o json]`
  subcommand wired into the clawctl agent typer app.
- Added `registry.latest_supported_version()` helper; surfaced in the
  agent-detail GUI response and rendered as an "Upgrade available" badge
  in `overview-tab.tsx`.
- Rewrote `website/docs/reference/cli/agent.md` §"### upgrade" to match
  the max-only forward semantics.
- Added 4 test files covering every row of the plan's test strategy
  (17 new Python tests + 3 new vitest cases; full suite green).
- Subtasks #598 / #599 are post-merge manual install verification on real
  Ubuntu hosts — not executed in this worktree.

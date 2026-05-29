# Execution log — issue #557

## Execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-29T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:execute 557 --pr-base=issue-556-build-render-inputs
```

**Output**: F4 (`clawctl agent doctor`) + F8 (`clawctl agent sync --dry-run --diff`) for parent #555. Adds:

- `src/clawrium/cli/clawctl/agent/doctor.py` — local-only diagnostic that surfaces declared vs resolved attachments and rendered file digests via `build_render_inputs`. Never emits secret values.
- `src/clawrium/core/render_diff.py` — paramiko-based host file reader + per-file unified diff helper.
- `--diff` flag on `clawctl agent sync` (implies `--dry-run`).
- `docs/operations/sync.md` — canonical "before you sync" check documentation.
- `tests/fixtures/audit_2026_05_29.json` + schema-gate test pinning the 10-agent reference baseline from #555.
- Unit tests for doctor + sync diff (no SSH required).

Out of scope (deferred to other subtasks of #555):

- F3 lifecycle wiring (sync_agent reading on-host state, refusing destructive ops without `--force`).
- F5 migration command + end-to-end render test against real container hosts (the audit fixture is currently a schema-pinned baseline, not a full doctor-output diff).

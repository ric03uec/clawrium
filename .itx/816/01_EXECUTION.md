# Issue #816 — openclaw upstream pin 2026.6.9 → 2026.6.11

## Execution notes

Manifest-only bump per the issue body. Three new `platforms[]` entries
appended (ubuntu 24.04/x86_64, ubuntu 22.04/x86_64, macos ≥14/arm64)
mirroring the shape of the 2026.6.9 entries. The `plugins.brave` block
at the top of the manifest is unchanged — brave has an independent
release cadence and per the issue body is out of scope.

### Files touched

| Path | Change |
|---|---|
| `src/clawrium/platform/registry/openclaw/manifest.yaml` | +27 lines: three `platforms[]` entries for `2026.6.11` |
| `CHANGELOG.md` | +6 lines under `## [Unreleased] ### Changed` |
| `tests/core/test_registry_latest_supported.py` | Update expected `latest_supported_version` from `2026.6.9` → `2026.6.11` for ubuntu rows |
| `tests/test_gui_agent_detail_latest_version.py` | Same expected-value update |
| `tests/cli/test_agent_upgrade.py` | `_write_host(..., "2026.6.9")` → `"2026.6.11"` — the "already at max" no-op test seeds a host at the new manifest max |

### sha256

Not populated. The issue body asks for a real sha256 per row, but:
- No existing manifest entry declares sha256.
- `install.py:801` treats sha256 as optional (`matched_entry.get("sha256", "")`).
- `playbooks/install.yaml:129` omits the checksum gate when the value
  is empty. The inline comment there explicitly calls sha256 hardening
  "a separate hardening follow-up because the openclaw installer URL
  is unpinned and the digest rotates upstream without a manifest bump."
- The previous 2026.5.28 → 2026.6.8 → 2026.6.9 bumps all landed
  without sha256.

Following existing project convention. Recorded as a Callout on the PR.

### Real-host UAT

The issue's DoD requires E2E on ubuntu 24.04, ubuntu 22.04, and
`mac-test` (100.120.88.97). This session cannot drive real-host UAT
end-to-end (no interactive shell / hosts.json context on those boxes
from a Claude session that only has the worktree checkout). PR opens
with the UAT boxes unticked; the user is expected to run the matrix
before merging. Recorded as a Callout.

## Prompt Log

## execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-07-01T23:30:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 816
```

**Output**: manifest bump + CHANGELOG entry + 3 test files updated to match the new manifest max; make lint + make test both green.

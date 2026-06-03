# Issue #430 — Operator can manage config files for zeroclaw agents

## Problem

`clm` currently exposes 7 zeroclaw workspace files via `clm agent memory show/edit/delete`, but `HEARTBEAT.md` overlaps with zeroclaw's runtime heartbeat/cron concerns. Additionally, the `edit` path in CLI and GUI both require files to exist on disk — if a file was deleted or never seeded, operators have no in-product way to create it without SSH access.

## Approach

- Remove `HEARTBEAT.md` from all zeroclaw memory allowlists (Python constants + Ansible playbooks) — new agents continue to have the file seeded at install, but `clm` stops surfacing it
- Add "create if missing" behavior to `clm agent memory edit` for allowlisted files
- Update GUI memory tab to show all canonical files with present/missing badges and a "Create" action for missing files
- Update tests to reflect 6-file surface and add coverage for the create-if-missing path

## Files Touched

**Backend:**
- `src/clawrium/core/memory.py` — remove HEARTBEAT.md from allowlists, update comments

**Playbooks:**
- `src/clawrium/platform/registry/zeroclaw/playbooks/memory_info.yaml` — drop HEARTBEAT.md from loop
- `src/clawrium/platform/registry/zeroclaw/playbooks/memory_write.yaml` — drop from allowlist
- `src/clawrium/platform/registry/zeroclaw/playbooks/memory_delete.yaml` — drop from allowlist

**CLI:**
- `src/clawrium/cli/memory.py` — add create-if-missing prompt in `edit_cmd`

**GUI:**
- `gui/src/components/agent-detail/memory-tab.tsx` — show all canonical files, add missing badge and Create action

**Tests:**
- `tests/test_core_memory.py` — update assertions for 6-file surface, add create-if-missing test
- `tests/test_registry_zeroclaw.py` — update test names and assertions from 7 to 6 files

## Phases

### Phase 1: Backend allowlist changes

**Entry criteria:** Issue #430 open, worktree created

**Changes:**
1. Edit `src/clawrium/core/memory.py`:
   - Remove `"HEARTBEAT.md"` from `MEMORY_TOP_LEVEL_FILES["zeroclaw"]` tuple
   - Remove `"HEARTBEAT.md"` from `_MEMORY_WRITE_ALLOWED_FILES["zeroclaw"]` tuple
   - Update comment on line 118: "7 personality files" → "6 personality files"
   - Note: `_MEMORY_DELETE_ALLOWED_FILES` derives from `_MEMORY_WRITE_ALLOWED_FILES`, auto-updates

2. Edit `src/clawrium/platform/registry/zeroclaw/playbooks/memory_info.yaml`:
   - Remove `- HEARTBEAT.md` from `memory_top_level_files` list (line 18)
   - Update comment on line 2: "all 7 personality" → "all 6 personality"

3. Edit `src/clawrium/platform/registry/zeroclaw/playbooks/memory_write.yaml`:
   - Remove `- HEARTBEAT.md` from `memory_write_allowed_files` list (line 21)
   - Update comment on line 8: "(7 personality files)" → "(6 personality files)"

4. Edit `src/clawrium/platform/registry/zeroclaw/playbooks/memory_delete.yaml`:
   - Remove `- HEARTBEAT.md` from `memory_delete_allowed_files` list (line 21)
   - Update comment on line 5: "the 7 personality files" → "the 6 personality files"

**Exit criteria:** `make lint` passes, all allowlist references to HEARTBEAT.md removed

**Verification:**
```bash
grep -r "HEARTBEAT" src/clawrium/core/memory.py src/clawrium/platform/registry/zeroclaw/playbooks/
# Should only match in configure.yaml (for install-time seeding)
```

### Phase 2: CLI create-if-missing behavior

**Entry criteria:** Phase 1 complete

**Changes:**
1. Edit `src/clawrium/cli/memory.py` in `edit_cmd` (around lines 352–361):
   - After `read_memory_file` returns `None`, check if the filename is in the allowlist
   - If allowlisted: prompt `"File '<X>' doesn't exist on the agent. Create it? [y/N]"`
   - Honor `--force` to skip the prompt (auto-confirm)
   - On confirm: open `$EDITOR` with empty buffer; on save, `write_memory_file` creates the file
   - If not allowlisted: keep existing rejection path (unsupported file error)

**Implementation notes:**
- Need to import or reference the allowlist from `clawrium.core.memory`
- The allowlist check should use `_MEMORY_WRITE_ALLOWED_FILES` from `memory.py`
- Empty buffer means `original_hash` starts as SHA256 of empty string
- `write_memory_file` already handles creating new files on remote

**Exit criteria:** `clm agent memory edit <agent> USER.md` works when USER.md is missing

**Verification:**
```bash
# Manual test on a live agent (after Phase 4 tests pass)
clm agent memory edit <test-agent> USER.md  # when USER.md is deleted
# Should prompt to create, open editor, save successfully
```

### Phase 3: GUI memory tab updates

**Entry criteria:** Phase 2 complete

**Changes:**
1. Edit `gui/src/components/agent-detail/memory-tab.tsx`:
   - Remove the `existingFiles` filter (line 58): `const existingFiles = memoryInfo.files.filter((f) => f.exists);`
   - Render all canonical files returned by the API
   - For missing files (`!f.exists`): greyed name + "missing" badge
   - Clicking a missing file opens editor with empty content
   - Add "Create" button that PUTs to `/memory/{filename}` endpoint

**Implementation notes:**
- The API already returns all files with `exists: true/false`
- Need to distinguish between:
  - Existing file: normal edit flow (current behavior)
  - Missing file: empty content + Create button (new behavior)
- The `saveMutation` already uses `api.updateMemoryFile` which PUTs to the endpoint

**Exit criteria:** GUI shows all 6 canonical files with present/missing badges; Create action works for missing files

**Verification:**
```bash
# Start GUI, navigate to agent memory tab
# Delete a file on the agent host, refresh GUI
# File should show as "missing" with Create button
```

### Phase 4: Test updates

**Entry criteria:** Phases 1–3 complete

**Changes:**
1. Edit `tests/test_registry_zeroclaw.py`:
   - Rename `test_zeroclaw_memory_info_lists_seven_personality_files` → `test_zeroclaw_memory_info_lists_six_personality_files`
   - Update docstring: "all 7 personality files" → "all 6 personality files"
   - Update assertion: expect 6 files, not 7
   - Update HEARTBEAT.md assertions (remove from expected lists)
   - Update comment on line 423: "All 7 personality files" → "All 6 personality files"

2. Edit `tests/test_core_memory.py`:
   - Remove `HEARTBEAT.md` from zeroclaw allowlist assertions (lines 125, 1832, 1867)
   - Add new test: `test_edit_creates_missing_allowlisted_file` — verify edit prompt and create flow

**New test case (test_core_memory.py):**
```python
def test_edit_creates_missing_allowlisted_file(monkeypatch, mock_agent):
    """edit_cmd should prompt to create missing allowlisted files."""
    # Mock read_memory_file to return None (file missing)
    # Mock write_memory_file to succeed
    # Simulate user confirming create prompt
    # Verify write_memory_file called with empty content initially
    # Verify editor opened with empty buffer
```

**Exit criteria:** `make test` passes with all assertions updated

**Verification:**
```bash
make test  # All tests pass
make lint  # No lint errors
```

### Phase 5: Final verification

**Entry criteria:** Phases 1–4 complete, all tests pass

**Verification checklist:**
- [ ] `clm agent memory show <agent>` lists 6 files for zeroclaw (no HEARTBEAT.md)
- [ ] `clm agent memory edit <agent> HEARTBEAT.md` rejected with "unsupported file" error
- [ ] `clm agent memory delete <agent> --file HEARTBEAT.md` rejected
- [ ] `clm agent memory edit <agent> USER.md` works when USER.md is missing (prompts, creates)
- [ ] GUI memory tab shows all 6 canonical files with present/missing badges
- [ ] GUI "Create" action exists for missing files
- [ ] Existing agents' HEARTBEAT.md still present on disk (no migration)
- [ ] Fresh `clm agent install` still seeds HEARTBEAT.md on remote workspace
- [ ] `make test` and `make lint` are green

## Risks / Unknowns

1. **Allowlist import in CLI**: The `edit_cmd` in `memory.py` needs to check if a filename is allowlisted. Currently `_MEMORY_WRITE_ALLOWED_FILES` is not exported. Options:
   - Export it from `clawrium.core.memory` (adds to public API)
   - Add a helper function `is_file_writable(claw_type, filename)` to memory.py
   - Duplicate the check via try/catch on `write_memory_file` (less clean)
   
   **Recommendation**: Add a helper function `is_file_writable` to keep the allowlist encapsulated.

2. **GUI create button UX**: Need to decide if "Create" is a separate button or if clicking a missing file automatically enters create mode. Issue says "Clicking opens the editor with empty content and a 'Create' button" — so the flow is:
   - Click missing file → editor opens with empty content
   - User edits → clicks "Create" (not "Save") → PUT to API
   
   This requires tracking `isCreating` state separate from `isEditing`.

3. **Empty content validation**: Should creating an empty file be allowed? The issue doesn't specify. Current behavior for write operations uses `MAX_MEMORY_CONTENT_BYTES` as upper bound; empty files are technically valid. Recommend allowing empty creates — operators can add content later.

4. **Test coverage for GUI**: The issue doesn't require GUI tests. The CLI create-if-missing behavior is tested in `test_core_memory.py`. If GUI tests exist, add coverage there; otherwise, verify manually.

5. **Backward compat for remote HEARTBEAT.md**: Existing agents will still have `HEARTBEAT.md` on disk. Zeroclaw runtime continues to read it. No migration needed. Fresh installs still get the file seeded via `configure.yaml` playbook.

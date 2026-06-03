## Execute

**Stage**: execute
**Skill**: /kanban-worker
**Timestamp**: 2026-05-26T00:55:00Z
**Model**: z-ai/glm-5

```prompt
work kanban task t_5c0c06b3
```

**Output**: Implemented all 5 phases of the issue #430 plan:

1. **Phase 1** - Backend allowlist changes:
   - Removed HEARTBEAT.md from MEMORY_TOP_LEVEL_FILES and _MEMORY_WRITE_ALLOWED_FILES
   - Updated memory_info.yaml, memory_write.yaml, memory_delete.yaml playbooks
   - Updated all comments from "7 personality files" to "6"

2. **Phase 2** - CLI create-if-missing behavior:
   - Added is_file_writable() helper to core/memory.py
   - Modified edit_cmd to distinguish between unreachable agent and missing file
   - Added prompt to create missing allowlisted files
   - Honors --force flag to skip confirmation

3. **Phase 3** - GUI memory tab updates:
   - Removed existingFiles filter to show all canonical files
   - Added missing badge for files that don't exist
   - Added isCreating state for create flow
   - Added "Create" button for missing files

4. **Phase 4** - Test updates:
   - Renamed and updated test functions for 6-file surface
   - Added TestIsFileWritable class with comprehensive coverage

5. **Phase 5** - Final verification:
   - Lint passes (Python + JS)
   - 3315 tests pass (5 unrelated CLI init failures pre-existing)
   - All memory-related tests pass

**Commits**:
- 4dcdb37 feat(memory): remove HEARTBEAT.md from zeroclaw memory surface (phase 1)
- c60f790 feat(cli): add create-if-missing for allowlisted memory files (phase 2)
- 33e68dc feat(gui): show missing memory files with create action (phase 3)
- 4a8c711 test: update tests for 6-file memory surface + is_file_writable (phase 4)

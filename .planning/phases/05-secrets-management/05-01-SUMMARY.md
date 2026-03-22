---
phase: 05-secrets-management
plan: 01
subsystem: secrets-management
tags: [core, security, storage, tdd]
dependency_graph:
  requires: [config]
  provides: [secrets-storage, manifest-secrets-schema]
  affects: [registry]
tech_stack:
  added: []
  patterns: [fcntl-locking, atomic-writes, iso8601-timestamps]
key_files:
  created:
    - src/clawrium/core/secrets.py
    - tests/test_secrets.py
  modified:
    - src/clawrium/platform/registry/openclaw/manifest.yaml
    - src/clawrium/core/registry.py
decisions:
  - "Use same locking and atomic write patterns as hosts.py for consistency"
  - "Secrets stored as dict[str, SecretEntry] not list for O(1) key lookup"
  - "list_secrets() returns keys only (not values) for security"
  - "set_secret() preserves created_at on updates, allows description override"
metrics:
  duration_seconds: 189
  tasks_completed: 2
  files_created: 2
  files_modified: 2
  tests_added: 15
  commits: 3
  completed_at: "2026-03-22T21:14:36Z"
---

# Phase 05 Plan 01: Core Secrets Storage Summary

**One-liner:** File-based secret storage with fcntl locking, atomic writes, mode 600 permissions, and manifest schema extension for required/optional secrets.

## What Was Built

Created foundational secrets management infrastructure:

1. **secrets.py** — CRUD operations for secret storage with SecretEntry metadata (key, value, created_at, updated_at, description)
2. **Extended manifest schema** — Added required_secrets and optional_secrets fields to ClawManifest, implemented in openclaw manifest
3. **Comprehensive tests** — 15 test cases covering all CRUD operations, file permissions, concurrent access, and edge cases

## Tasks Completed

### Task 1: Create secrets storage module (TDD)

**RED Phase (commit 30ad353):**
- Created test_secrets.py with 15 failing tests covering all behaviors
- Tests verify CRUD operations, file permissions, timestamps, concurrent access

**GREEN Phase (commit 4e5c386):**
- Implemented secrets.py with all CRUD operations
- Used fcntl.flock for concurrent access protection (replicating hosts.py pattern)
- Atomic writes with temp file + rename
- File permissions enforced at 0o600 on every save
- ISO 8601 timestamps for created_at and updated_at
- SecretEntry TypedDict with complete metadata
- All 228 tests pass

**Files:**
- src/clawrium/core/secrets.py (249 lines)
- tests/test_secrets.py (257 lines)

**Exports:**
- `load_secrets() -> dict[str, SecretEntry]`
- `save_secrets(secrets: dict[str, SecretEntry]) -> None`
- `get_secret(key: str) -> SecretEntry | None`
- `set_secret(key: str, value: str, description: str = "") -> bool`
- `remove_secret(key: str) -> bool`
- `list_secrets() -> list[str]`
- `SECRETS_FILE = "secrets.json"`
- `SecretEntry`, `SecretsFileCorruptedError`, `DuplicateSecretError`

### Task 2: Extend manifest schema with secrets requirements

**Implementation (commit 2975b13):**
- Added required_secrets and optional_secrets to openclaw manifest.yaml
- Extended ClawManifest TypedDict with NotRequired secret fields
- Created SecretDefinition TypedDict (key, description)
- Implemented get_required_secrets() and get_optional_secrets() helper functions
- All existing registry tests still pass

**Files:**
- src/clawrium/platform/registry/openclaw/manifest.yaml
- src/clawrium/core/registry.py

**Manifest structure:**
```yaml
required_secrets:
  - key: OPENAI_API_KEY
    description: "OpenAI API key for LLM requests"
optional_secrets:
  - key: ANTHROPIC_API_KEY
    description: "Anthropic API key for Claude models"
```

## Deviations from Plan

None — plan executed exactly as written.

## Integration Points

**Consumed by this plan:**
- `clawrium.core.config.get_config_dir()` — Storage location for secrets.json
- `clawrium.core.config.init_config_dir()` — Config directory initialization

**Provided by this plan:**
- Secrets CRUD API for future CLI commands (clm secret add/remove/list)
- Manifest secrets schema for install validation (future plan)
- Foundation for SEC-01 (secret storage) and SEC-03 (validation) requirements

**Future integration:**
- Phase 05 Plan 02 will use get_required_secrets() to validate secrets before install
- CLI commands will use set_secret(), get_secret(), remove_secret() for user interactions

## Known Stubs

None — all functionality is fully implemented and tested.

## Test Coverage

**New tests:** 15 test cases in test_secrets.py
- Load/save operations (empty file, valid JSON, invalid JSON)
- File permissions (mode 0o600 enforcement)
- CRUD operations (create, read, update, delete)
- Timestamp handling (created_at preserved, updated_at updated)
- Edge cases (missing keys, empty lists, concurrent writes)

**All tests pass:** 228/228 (100%)

## Verification Results

All verification criteria met:

✅ secrets.py implements all CRUD operations with fcntl locking
✅ File permissions enforced at 0o600 on every save
✅ Manifest schema extended with required_secrets and optional_secrets
✅ All existing tests pass, new secrets tests pass

## Self-Check: PASSED

**Created files verified:**
- ✅ src/clawrium/core/secrets.py exists
- ✅ tests/test_secrets.py exists

**Modified files verified:**
- ✅ src/clawrium/platform/registry/openclaw/manifest.yaml contains required_secrets
- ✅ src/clawrium/core/registry.py contains SecretDefinition and getter functions

**Commits verified:**
- ✅ 30ad353: test(05-01): add failing test for secrets storage module
- ✅ 4e5c386: feat(05-01): implement secrets storage module
- ✅ 2975b13: feat(05-01): extend manifest schema with secrets requirements

**Tests verified:**
- ✅ All 228 tests pass
- ✅ New test_secrets.py contains 15 tests
- ✅ Secrets module functions exported correctly

## Next Steps

Phase 05 Plan 02 will build on this foundation to:
1. Implement secret validation before claw installation
2. Create CLI commands for secret management (clm secret add/list/remove)
3. Integrate with install workflow to check required secrets

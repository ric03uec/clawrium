---
phase: 06-make-secrets-specific-to-installed-claws-not-global
plan: 01
subsystem: core/secrets
tags: [refactoring, per-instance, storage, breaking-change]
dependencies:
  requires: [phase-05-secrets-management]
  provides: [per-instance-secret-storage, instance-key-format]
  affects: [cli-secret-commands]
tech_stack:
  added: []
  patterns: [nested-json-structure, legacy-compatibility-layer]
key_files:
  created: []
  modified:
    - src/clawrium/core/secrets.py
    - tests/test_secrets.py
    - src/clawrium/cli/secret.py
    - tests/test_cli_secret.py
decisions:
  - Use nested JSON structure: {instance_key: {secret_key: SecretEntry}}
  - Instance key format: "host:claw_type:claw_name"
  - Legacy __global__ namespace for backward compatibility with existing CLI
  - Keep old global functions working until CLI is updated in Plan 02
metrics:
  duration: 427
  tasks: 1
  files: 4
  completed: 2026-03-22T22:28:38Z
---

# Phase 06 Plan 01: Refactor Secrets to Per-Instance Storage Summary

**One-liner:** Nested JSON storage structure enabling per-claw-instance secrets with instance key format "host:claw_type:claw_name"

## What Was Built

Refactored the secrets module from global scope to per-claw-instance scoping. Each installed claw instance now has its own isolated set of secrets, enabling fleet-wide secret management where the same key can have different values per instance.

**Key capabilities:**
- Per-instance secret storage with nested JSON: `{instance_key: {secret_key: SecretEntry}}`
- Instance key format: `host:claw_type:claw_name` (e.g., `wolf:openclaw:work`)
- Same secret key can store different values per instance
- Legacy compatibility layer using `__global__` namespace for existing CLI
- All file locking and atomic write patterns preserved

## Tasks Completed

### Task 1: Refactor secrets module for per-instance storage ✅
**Commit:** 790040c, 0979c64
**Files:** src/clawrium/core/secrets.py, tests/test_secrets.py, src/clawrium/cli/secret.py, tests/test_cli_secret.py

**Changes:**
- Modified `load_secrets()` return type from `dict[str, SecretEntry]` to `dict[str, dict[str, SecretEntry]]`
- Modified `save_secrets()` to accept nested structure
- Added `get_instance_key(host, claw_type, claw_name) -> str` for instance key generation
- Added `get_instance_secrets(instance_key) -> dict[str, SecretEntry]` for retrieving instance secrets
- Added `set_instance_secret(instance_key, key, value, description)` for setting per-instance secrets
- Added `remove_instance_secret(instance_key, key)` for removing per-instance secrets
- Added `list_instances_with_secrets() -> list[str]` for listing instance keys with secrets
- Added `ClawNotFoundError` exception class
- Kept legacy functions (`get_secret`, `set_secret`, `remove_secret`, `list_secrets`) using `__global__` namespace
- Updated CLI secret list command to read from `__global__` namespace
- Added TDD tests for all per-instance operations
- Updated existing CLI tests to check `__global__` namespace
- File permissions remain 0o600
- Same fcntl locking and atomic write patterns

**Verification:**
```bash
make test  # 257 tests pass
make lint  # All checks passed
```

## Deviations from Plan

None - plan executed exactly as written.

## Technical Decisions

### Storage Structure
Changed from flat `dict[str, SecretEntry]` to nested `dict[str, dict[str, SecretEntry]]` where:
- Top-level keys are instance keys in format `host:claw_type:claw_name`
- Second-level keys are secret keys (e.g., `OPENAI_API_KEY`)
- Values are `SecretEntry` TypedDict with timestamps and description

**Rationale:** Enables same secret key to have different values per instance while maintaining type safety and existing SecretEntry structure.

### Legacy Compatibility Layer
Kept old global functions (`get_secret`, `set_secret`, `remove_secret`, `list_secrets`) working by using special `__global__` instance key for backward compatibility.

**Rationale:** Existing CLI commands (Phase 05) depend on global functions. Breaking them would require updating CLI in the same task, violating single-responsibility. CLI will be updated in Plan 02.

### Instance Key Format
Chose colon-separated format `host:claw_type:claw_name` per D-08 decision.

**Rationale:**
- Colon is not valid in hostnames, claw types, or claw names (enforced by validation)
- Easily parsable and human-readable
- Consistent with decision D-08 from phase context

## Known Limitations

- Legacy `__global__` namespace will be removed in Plan 02 when CLI is updated
- No validation that instance exists in hosts.json yet (will be added when `get_installed_claw()` is implemented in Plan 02)
- CLI still uses old global functions (intentional - will be updated in Plan 02)

## Next Steps

Plan 02 will:
1. Add `get_installed_claw(claw_name)` function to validate claws exist in hosts registry
2. Update CLI secret commands to use per-instance functions
3. Remove `__global__` namespace and legacy functions
4. Add claw name as first positional argument to CLI commands

## Files Modified

- `src/clawrium/core/secrets.py` - Core refactoring with nested structure and new functions
- `tests/test_secrets.py` - Tests for per-instance operations
- `src/clawrium/cli/secret.py` - Updated list command to read from __global__
- `tests/test_cli_secret.py` - Updated test assertions for __global__ namespace

## Commits

- `0979c64` - test(06-01): add failing tests for per-instance secrets (TDD RED)
- `790040c` - feat(06-01): implement per-instance secret storage (TDD GREEN)

## Self-Check: PASSED

**Created files exist:** N/A (no new files created)

**Modified files exist:**
```bash
[ -f "src/clawrium/core/secrets.py" ] && echo "FOUND: src/clawrium/core/secrets.py"
[ -f "tests/test_secrets.py" ] && echo "FOUND: tests/test_secrets.py"
[ -f "src/clawrium/cli/secret.py" ] && echo "FOUND: src/clawrium/cli/secret.py"
[ -f "tests/test_cli_secret.py" ] && echo "FOUND: tests/test_cli_secret.py"
```

**Commits exist:**
```bash
git log --oneline --all | grep -q "0979c64" && echo "FOUND: 0979c64"
git log --oneline --all | grep -q "790040c" && echo "FOUND: 790040c"
```

All files and commits verified.

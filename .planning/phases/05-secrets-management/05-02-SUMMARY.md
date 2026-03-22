---
phase: 05-secrets-management
plan: 02
subsystem: secrets-management
tags: [cli, security, ux, tdd]
dependency_graph:
  requires: [secrets-storage, registry-secrets-schema]
  provides: [secret-cli-commands]
  affects: [user-workflow]
tech_stack:
  added: []
  patterns: [typer-cli, masked-input, confirmation-prompts, table-output]
key_files:
  created:
    - src/clawrium/cli/secret.py
    - tests/test_cli_secret.py
  modified:
    - src/clawrium/cli/main.py
decisions:
  - "Named CLI functions set_cmd/list_cmd/remove_cmd to avoid shadowing Python builtins"
  - "Used getpass.getpass for masked secret input"
  - "Overwrite confirmation skippable with --yes flag following host remove pattern"
  - "Missing required secrets displayed grouped by claw type in list output"
metrics:
  duration_seconds: 209
  tasks_completed: 2
  files_created: 2
  files_modified: 1
  tests_added: 14
  commits: 2
  completed_at: "2026-03-22T21:20:21Z"
---

# Phase 05 Plan 02: CLI Secret Commands Summary

**One-liner:** Interactive CLI commands for secret management (set, list, remove) with masked input, confirmation prompts, and missing required secrets detection.

## What Was Built

Created user-facing CLI commands for secret management:

1. **secret.py** — Typer CLI module with set, list, remove commands
2. **main.py integration** — Registered secret subcommand in main CLI
3. **Comprehensive tests** — 14 test cases covering all CLI behaviors and edge cases

## Tasks Completed

### Task 1: Create secret CLI commands (TDD)

**RED Phase (commit 360ad95):**
- Created test_cli_secret.py with 14 failing tests
- Tests cover set (create/update/confirmation), list (table/missing secrets), remove (confirmation/force)

**GREEN Phase (commit 3fbe7f0):**
- Implemented secret.py with three commands:
  - `set_cmd`: Masked input via getpass, overwrite confirmation, --yes flag
  - `list_cmd`: Table with Key/Description/Updated, missing required secrets section
  - `remove_cmd`: Confirmation prompt, --force flag
- Fixed naming conflict: renamed functions to avoid shadowing Python's `set()`
- Registered secret_app in main.py
- All 242 tests pass

**Files:**
- src/clawrium/cli/secret.py (164 lines)
- tests/test_cli_secret.py (279 lines)
- src/clawrium/cli/main.py (updated)

**Commands:**
```bash
clm secret set KEY [--description DESC] [--yes]
clm secret list
clm secret remove KEY [--force]
```

### Task 2: Register secret subcommand in main CLI

**Completed as part of Task 1 GREEN phase:**
- Added import: `from clawrium.cli.secret import secret_app`
- Added registration: `app.add_typer(secret_app, name="secret")`
- Help text displays correctly in `clm --help` and `clm secret --help`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Function naming shadowed Python builtin**
- **Found during:** Task 1 GREEN phase
- **Issue:** Named CLI function `set()` shadowed Python's built-in `set()`, causing TypeError when checking missing secrets
- **Fix:** Renamed functions to `set_cmd`, `list_cmd`, `remove_cmd` with explicit `@command(name="...")` decorators
- **Files modified:** src/clawrium/cli/secret.py
- **Commit:** 3fbe7f0

## Integration Points

**Consumed by this plan:**
- `clawrium.core.secrets` — CRUD operations (get_secret, set_secret, remove_secret, list_secrets, load_secrets)
- `clawrium.core.registry` — get_required_secrets, list_claws for missing secrets detection

**Provided by this plan:**
- User-facing CLI for secret management (SEC-01, SEC-02, SEC-03 requirements)
- Interactive workflows with masked input and confirmations
- Visual feedback on missing required secrets per claw type

**Future integration:**
- Install workflow will use this CLI to prompt users for missing secrets before proceeding
- Users can pre-populate secrets before installing claws

## Known Stubs

None — all functionality is fully implemented and tested.

## Test Coverage

**New tests:** 14 test cases in test_cli_secret.py
- Secret set: create, update with confirmation, --yes flag, empty value rejection
- Secret list: empty state, table display, value hiding, missing required secrets
- Secret remove: confirmation, --force flag, non-existent key error

**All tests pass:** 242/242 (100%)

## Verification Results

All verification criteria met:

✅ `clm secret set KEY` prompts for masked input and stores secret
✅ `clm secret list` shows keys (not values) and missing required secrets
✅ `clm secret remove KEY` prompts for confirmation and removes
✅ All tests pass
✅ No secret values ever displayed in output
✅ Help text displays correctly

## Self-Check: PASSED

**Created files verified:**
- ✅ src/clawrium/cli/secret.py exists and contains secret_app
- ✅ tests/test_cli_secret.py exists with 14 tests

**Modified files verified:**
- ✅ src/clawrium/cli/main.py imports secret_app
- ✅ src/clawrium/cli/main.py registers secret subcommand

**Commits verified:**
- ✅ 360ad95: test(05-02): add failing tests for secret CLI commands
- ✅ 3fbe7f0: feat(05-02): implement secret CLI commands

**Tests verified:**
- ✅ All 242 tests pass (14 new CLI tests)
- ✅ `clm secret --help` shows set, list, remove commands
- ✅ `clm --help` shows secret in command list

## Next Steps

Phase 05 is complete. Secret management infrastructure is now fully functional:
- Core storage (Plan 01) ✅
- CLI commands (Plan 02) ✅

Users can now:
1. Set secrets with masked input: `clm secret set OPENAI_API_KEY`
2. List stored secrets: `clm secret list`
3. See which secrets are missing for each claw type
4. Remove secrets with confirmation: `clm secret remove KEY`

Next phase will integrate secret validation into the install workflow.

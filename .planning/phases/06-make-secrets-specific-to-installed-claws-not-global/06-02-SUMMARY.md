---
phase: 06-make-secrets-specific-to-installed-claws-not-global
plan: 02
subsystem: cli/secret
tags: [cli-refactoring, per-instance, breaking-change]
dependencies:
  requires: [06-01]
  provides: [per-claw-cli-commands]
  affects: [user-workflows]
tech_stack:
  added: []
  patterns: [claw-validation, instance-key-lookup, grouped-display]
key_files:
  created: []
  modified:
    - src/clawrium/cli/secret.py
    - src/clawrium/core/secrets.py
    - tests/test_cli_secret.py
decisions:
  - CLI commands now require claw_name as first positional argument
  - Secrets only settable for installed claws (validated via get_installed_claw)
  - List command shows secrets grouped by claw with host names
  - Remove command requires both claw_name and key
  - Legacy global functions removed from CLI (still exist in core for compatibility)
metrics:
  duration: 411
  tasks: 2
  files: 3
  completed: 2026-03-22T22:38:20Z
---

# Phase 06 Plan 02: Update CLI Secret Commands for Per-Claw Scoping Summary

**One-liner:** CLI secret commands refactored to use per-claw scoping with claw name as first positional argument and grouped list display

## What Was Built

Updated all CLI secret commands to use per-claw scoping. Users now manage secrets per claw instance using `clm secret set <clawname> KEY`, and the list command shows secrets grouped by claw with missing required secrets per instance.

**Key capabilities:**
- `clm secret set <clawname> KEY` - Set secrets for specific installed claw
- `clm secret list` - Shows secrets grouped by claw instance with host names
- `clm secret remove <clawname> KEY` - Remove secrets from specific claw
- Validates claw exists before accepting secrets (raises ClawNotFoundError)
- Shows missing required secrets per claw instance in list output
- All commands work with per-instance secret storage from Plan 01

## Tasks Completed

### Task 1: Update CLI set command for per-claw secrets ✅
**Commit:** e1690f2
**Files:** src/clawrium/cli/secret.py, src/clawrium/core/secrets.py, tests/test_cli_secret.py

**Changes:**
- Added `get_installed_claw(claw_name)` function in secrets.py
  - Searches all hosts for claw with matching name
  - Returns tuple of (hostname, claw_type, claw_name)
  - Raises ClawNotFoundError if claw not found
- Modified `set_cmd` signature to require claw_name as first positional argument
- Updated set_cmd implementation:
  - Validates claw exists using get_installed_claw
  - Gets instance_key from get_instance_key(hostname, claw_type, claw_name)
  - Uses set_instance_secret instead of set_secret
  - Shows claw name in success/error messages
- Updated all existing set tests to create hosts with claws
- Added new tests:
  - test_secret_set_with_claw - Creates secret for installed claw
  - test_secret_set_claw_not_found - Error when claw doesn't exist
  - test_secret_set_with_claw_update_confirmed - Update flow works

**Verification:**
```bash
uv run pytest tests/test_cli_secret.py -k "set" -v  # All set tests pass
```

### Task 2: Update CLI list and remove commands ✅
**Commit:** d9f299b
**Files:** src/clawrium/cli/secret.py, tests/test_cli_secret.py

**Changes:**
- Modified `list_cmd` to show per-claw grouping:
  - Loads all hosts with load_hosts()
  - Iterates over hosts and their installed claws
  - For each claw: shows instance key, stored secrets table, missing required secrets
  - Shows "No claws installed" when hosts.json is empty
  - Display format:
    ```
    Claw: opc-work (wolf)
    Key              | Description      | Updated
    OPENAI_API_KEY   | OpenAI API key   | 2026-03-22
    Missing: ANTHROPIC_API_KEY (Anthropic API key for Claude models)
    ```
- Modified `remove_cmd` signature to require claw_name as first positional argument
- Updated remove_cmd implementation:
  - Validates claw exists using get_installed_claw
  - Gets instance_key
  - Uses remove_instance_secret instead of remove_secret
  - Shows claw name in confirmation and success messages
- Updated all existing list and remove tests to create hosts with claws
- Added new tests:
  - test_secret_list_grouped_by_claw - Shows multiple claws with secrets
  - test_secret_list_shows_missing_required - Shows missing secrets per claw
  - test_secret_list_no_claws_installed - Appropriate message when no claws
  - test_secret_remove_with_claw - Removes from specific claw
  - test_secret_remove_claw_not_found - Error when claw doesn't exist

**Verification:**
```bash
make test  # 273 tests pass
make lint  # All checks passed
```

## Deviations from Plan

None - plan executed exactly as written.

## Technical Decisions

### Claw Validation via get_installed_claw()
Added helper function to validate claw exists before accepting secrets. Searches all hosts for matching claw name.

**Rationale:** Prevents secrets being created for non-existent claws. Cleaner than checking inside each CLI command. Provides consistent error messages.

### Grouped List Display
Changed list output from flat global table to per-claw grouping with host names.

**Rationale:** Users need to see which secrets belong to which claw instance. Host name provides context for multi-host fleets. Missing secrets shown per instance for clarity.

### Breaking Change - Command Signature
All commands now require claw_name as first positional argument.

**Rationale:** Per decision D-10 from phase context. Makes per-instance scoping explicit. Forces users to think about which claw they're configuring. Breaking change is acceptable for v1 (no stable users yet).

## Known Limitations

None - all functionality working as planned.

## Next Steps

Plan 03 will integrate per-claw secrets with the health check system to show degraded status when required secrets are missing.

## Files Modified

- `src/clawrium/core/secrets.py` - Added get_installed_claw() function
- `src/clawrium/cli/secret.py` - Updated set_cmd, list_cmd, remove_cmd for per-claw scoping
- `tests/test_cli_secret.py` - Updated all tests for per-claw pattern, added 8 new tests

## Commits

- `e1690f2` - feat(06-02): update CLI set command for per-claw secrets
- `d9f299b` - feat(06-02): update CLI list and remove commands for per-claw secrets

## Self-Check: PASSED

**Modified files exist:**
```bash
[ -f "src/clawrium/core/secrets.py" ] && echo "FOUND: src/clawrium/core/secrets.py"
[ -f "src/clawrium/cli/secret.py" ] && echo "FOUND: src/clawrium/cli/secret.py"
[ -f "tests/test_cli_secret.py" ] && echo "FOUND: tests/test_cli_secret.py"
```

**Commits exist:**
```bash
git log --oneline --all | grep -q "e1690f2" && echo "FOUND: e1690f2"
git log --oneline --all | grep -q "d9f299b" && echo "FOUND: d9f299b"
```

All files and commits verified.

---
phase: quick
plan: 260321-jld
subsystem: core/hardware
tags: [bug-fix, ansible-runner, hardware-detection]
dependency-graph:
  requires: []
  provides:
    - working hardware detection via ansible-runner
  affects:
    - clm host add command
tech-stack:
  added: []
  patterns:
    - inventory dict passed directly to ansible_runner.run
key-files:
  created: []
  modified:
    - src/clawrium/core/hardware.py
    - tests/test_hardware.py
decisions:
  - Pass inventory dict directly to ansible_runner.run instead of relying on file discovery
  - Remove redundant file-based inventory operations for cleaner code
metrics:
  duration: 2 minutes
  completed: 2026-03-21
---

# Quick Task 260321-jld: Fix Hardware Detection ansible-runner Issue Summary

**One-liner:** Fixed hardware detection by passing inventory dict directly to ansible_runner.run calls

## What Was Done

### Root Cause

The `gather_hardware()` function in `src/clawrium/core/hardware.py` was writing inventory to `{tmpdir}/inventory/hosts.json` but NOT passing the `inventory` parameter to `ansible_runner.run()`. While ansible-runner can auto-discover inventory files, the `host_pattern` parameter requires explicit inventory passing for reliable host matching.

### Fix Applied

1. Added `inventory=inventory` parameter to both `ansible_runner.run()` calls (setup module and lspci shell command)
2. Removed redundant file-based inventory operations (no longer needed)
3. Removed unused `json` and `Path` imports

## Commits

| Commit | Type | Description |
|--------|------|-------------|
| 1963ad5 | test | Add failing test for inventory parameter (TDD RED) |
| 979063c | fix | Pass inventory to ansible_runner.run calls (TDD GREEN) |
| fe4561d | refactor | Remove unused inventory file operations (TDD REFACTOR) |

## Files Modified

### src/clawrium/core/hardware.py

**Before:**
```python
ansible_runner.run(
    private_data_dir=tmpdir,
    host_pattern=hostname,  # Matches nothing without inventory param
    module="setup",
    ...
)
```

**After:**
```python
ansible_runner.run(
    private_data_dir=tmpdir,
    inventory=inventory,    # Pass inventory dict directly
    host_pattern=hostname,
    module="setup",
    ...
)
```

### tests/test_hardware.py

Added `test_gather_hardware_passes_inventory_to_runner()` which:
- Captures kwargs passed to ansible_runner.run
- Verifies both calls receive inventory parameter
- Validates inventory structure with correct host vars

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- All 122 tests pass
- Lint passes on modified source file
- Code follows TDD pattern (RED-GREEN-REFACTOR)

## GitHub Issue

Resolves: https://github.com/ric03uec/clawrium/issues/3

## Self-Check: PASSED

- [x] src/clawrium/core/hardware.py exists and contains `inventory=inventory`
- [x] tests/test_hardware.py exists and contains new test
- [x] Commit 1963ad5 exists (test)
- [x] Commit 979063c exists (fix)
- [x] Commit fe4561d exists (refactor)

---
phase: quick
plan: 260321-jux
subsystem: core/hardware
tags: [security, test-coverage, code-review]
dependency-graph:
  requires: []
  provides:
    - SSH key path validation
    - Complete RuntimeError test coverage
    - GPU detection for compute cards
tech-stack:
  added: []
  patterns:
    - TypedDict for return types
    - Path validation before external tool usage
key-files:
  created: []
  modified:
    - src/clawrium/core/hardware.py
    - tests/test_hardware.py
decisions:
  - SSH keys must be in ~/.ssh or ~/.config/clawrium
  - GPU failures encoded in return value, not silently discarded
metrics:
  duration: 5 minutes
  completed: 2026-03-21
---

# Quick Task 260321-jux: ATX Review Fixes Summary

**One-liner:** Fixed all blocking issues and warnings from ATX code review

## ATX Review Response

### Blocking Issues Fixed

| # | Issue | Fix |
|---|-------|-----|
| 1 | SSH key path - no validation | Added `_validate_ssh_key()` that resolves path, checks allowed dirs (~/.ssh, ~/.config/clawrium), verifies permissions (0600/0400) |
| 2 | test_gather_hardware_full - wrong mock structure | Changed to `Mock(side_effect=[SetupResult(), GpuResult()])` with distinct results per call |
| 3 | Three RuntimeError paths untested | Added `test_gather_hardware_timeout_raises`, `test_gather_hardware_failed_raises`, `test_gather_hardware_no_facts_raises` |

### Warnings Addressed

| # | Warning | Fix |
|---|---------|-----|
| 1 | GPU detection misses compute cards | Changed grep to `"vga|3d controller|display"` |
| 2 | GPU failure silently discarded | Now logs warning and sets `gpu.error` in return |
| 3 | No typed schema | Added `HardwareInfo` and `GpuInfo` TypedDicts |
| 4 | SSH key permissions not checked | Added permission check in `_validate_ssh_key()` |
| 5 | TemporaryDirectory no explicit permissions | Added `os.chmod(tmpdir, 0o700)` |

### Additional Test Coverage

- `test_parse_ansible_facts_all_missing` - empty facts dict
- `test_detect_gpu_unknown` - Cirrus Logic vendor
- `test_detect_gpu_3d_controller` - NVIDIA compute cards
- `test_gather_hardware_no_ssh_key` - inventory without key
- `test_gather_hardware_gpu_failure_logged` - caplog verification
- `test_ssh_key_outside_allowed_dir_raises` - security boundary
- `test_ssh_key_insecure_permissions_raises` - 0644 rejection
- `test_ssh_key_not_exists_raises` - nonexistent file

## Commit

| Commit | Type | Description |
|--------|------|-------------|
| 397640b | fix(security) | Address ATX review blocking issues and warnings |

## Files Modified

### src/clawrium/core/hardware.py

- Added `HardwareInfo` and `GpuInfo` TypedDicts
- Added `_validate_ssh_key()` function
- Updated `parse_gpu_output()` to return `GpuInfo` with error field
- Updated `gather_hardware()` to validate SSH keys, set tmpdir permissions, log GPU failures
- Changed lspci grep to catch 3D controllers

### tests/test_hardware.py

- Fixed `test_gather_hardware_full` with `side_effect` pattern
- Added 11 new tests for comprehensive coverage

## Verification Results

- 133 tests pass (11 new)
- Lint passes on modified files
- All blocking issues resolved

## Self-Check: PASSED

- [x] SSH key validation raises ValueError for paths outside ~/.ssh and ~/.config/clawrium
- [x] SSH key validation raises ValueError for insecure permissions
- [x] test_gather_hardware_full uses distinct mocks per call
- [x] RuntimeError tests cover timeout, failed, no-facts paths
- [x] GPU detection catches "3D controller" class
- [x] GPU failures logged and encoded in return value

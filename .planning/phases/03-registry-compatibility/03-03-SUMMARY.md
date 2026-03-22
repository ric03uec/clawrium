---
phase: 03-registry-compatibility
plan: 03
subsystem: registry
tags: [compatibility, validation, sparse-matrix]
dependency_graph:
  requires: [03-01, 03-02]
  provides: [compatibility-checking]
  affects: [install-flow]
tech_stack:
  added: [packaging.specifiers]
  patterns: [sparse-matrix-matching, requirement-validation]
key_files:
  created: []
  modified:
    - src/clawrium/core/registry.py
    - tests/test_registry.py
decisions:
  - Sparse matrix matching: only explicit manifest entries are valid (no partial matches)
  - Specific failure reasons: "Requires X, host has Y" format for clarity
  - Dependency checking deferred: hardware dict doesn't include installed packages in v1
  - OS/arch/version must all match for entry to be considered
metrics:
  duration_seconds: 128
  tasks_completed: 1
  tests_added: 8
  files_modified: 2
  commits: 2
  completed_date: "2026-03-21"
---

# Phase 03 Plan 03: Compatibility Checking Summary

**One-liner:** Sparse matrix compatibility validation between host hardware and claw requirements with specific failure reasons

## What Was Built

Implemented `check_compatibility()` function that validates whether a host meets all requirements for a specific claw. The function uses sparse matrix matching - only explicitly supported platform combinations (OS + version + arch) are valid. Provides detailed failure reasons when requirements aren't met.

### Core Functionality

1. **CompatibilityResult TypedDict**: Structured result with `compatible` bool, `matched_entry`, and `reasons` list
2. **check_compatibility() function**: Main validation logic that checks:
   - OS match (exact string match)
   - OS version match (exact string match)
   - Architecture match (exact string match)
   - Memory requirement (>= min_memory_mb)
   - GPU requirement (if gpu_required=true, must be present)
   - Dependencies (infrastructure ready, checking deferred to future phases)

3. **Sparse Matrix Matching**: Function iterates through manifest entries and returns success on first match. All requirements must pass for an entry to match.

4. **Specific Failure Reasons**: Examples:
   - "Requires ubuntu 24.04, host has debian 12"
   - "Requires x86_64, host has aarch64"
   - "Requires 2048MB RAM, host has 1024MB"
   - "Requires GPU, host has none"

### Test Coverage

Added 8 comprehensive tests:
- `test_check_compatibility_matching`: Validates matching hardware returns compatible=True
- `test_check_compatibility_wrong_os`: Tests OS mismatch detection
- `test_check_compatibility_wrong_arch`: Tests architecture mismatch detection
- `test_check_compatibility_wrong_os_version`: Tests OS version mismatch detection
- `test_check_compatibility_insufficient_memory`: Tests memory requirement validation
- `test_check_compatibility_gpu_required`: Tests GPU requirement logic
- `test_check_compatibility_all_requirements_met`: Tests with all requirements exceeded
- `test_check_compatibility_nonexistent_claw`: Tests error handling for missing manifests

All tests pass, including existing 6 registry tests.

## Deviations from Plan

None - plan executed exactly as written.

## Key Decisions

1. **Sparse Matrix Approach**: Only explicitly supported combinations are valid. If host is Ubuntu 24.04 x86_64 but manifest only has Ubuntu 22.04 x86_64, it fails. No "close enough" matching.

2. **OS Version as String**: Comparing OS versions as exact strings (e.g., "24.04" == "24.04"), not as semver. This is correct for Ubuntu's versioning scheme.

3. **Dependency Checking Deferred**: While `_check_dependency_version()` helper exists and uses packaging.specifiers, actual dependency validation is deferred because HardwareInfo doesn't include installed package information in v1.

4. **Multiple Failure Reasons**: Function collects all failures across all manifest entries and deduplicates them. This helps users understand all potential issues, not just the first one.

## Integration Points

- **Used by Phase 5 (Install Flow)**: `check_compatibility()` will be called before attempting claw installation
- **Depends on Phase 3 Plan 1**: Uses `ManifestEntry`, `Requirements`, and `load_manifest()`
- **Depends on Phase 3 Plan 2**: Uses `HardwareInfo` TypedDict with OS and OS version fields
- **Consumes**: Manifest YAML files from `platform/registry/<claw>/manifest.yaml`

## Known Limitations

1. **Dependency Checking Not Implemented**: While infrastructure exists, we don't validate dependencies because `HardwareInfo` doesn't include installed package versions. This would require extending hardware detection in a future phase.

2. **GPU Vendor Not Validated**: Currently checks GPU presence only, not specific vendor requirements (e.g., "NVIDIA GTX 1080 or better").

3. **No Version Range Matching**: Function accepts optional specific version, but doesn't support version ranges like ">=0.1.0,<2.0.0".

## Files Changed

### Modified
- **src/clawrium/core/registry.py** (145 lines added):
  - Added `CompatibilityResult` TypedDict
  - Added `_check_dependency_version()` helper
  - Added `check_compatibility()` function
  - Imported `packaging.specifiers.SpecifierSet`

- **tests/test_registry.py** (185 lines added):
  - Added 8 compatibility checking tests
  - All tests use realistic hardware dicts matching HardwareInfo schema

### Created
None (all additions to existing files)

## Verification Results

All acceptance criteria met:

```bash
# CompatibilityResult type exists
✓ src/clawrium/core/registry.py contains "class CompatibilityResult" (line 44)

# check_compatibility function exists
✓ src/clawrium/core/registry.py contains "def check_compatibility(" (line 198)

# packaging import exists
✓ src/clawrium/core/registry.py contains "from packaging" (lines 12-13)

# Tests exist and pass
✓ test_check_compatibility_matching PASSED
✓ test_check_compatibility_wrong_os PASSED
✓ test_check_compatibility_wrong_arch PASSED
✓ test_check_compatibility_insufficient_memory PASSED
✓ test_check_compatibility_gpu_required PASSED
✓ test_check_compatibility_all_requirements_met PASSED
✓ test_check_compatibility_nonexistent_claw PASSED
✓ test_check_compatibility_wrong_os_version PASSED

# All registry tests pass
✓ 14 tests passed (6 existing + 8 new)
```

Manual verification:
```python
result = check_compatibility('openclaw', hardware)
# Returns: Compatible: True, Matched entry version: 0.1.0, Reasons: []
```

## Next Steps

1. **Phase 3 Plan 4**: Implement `clm registry show <claw>` command to display manifest details
2. **Phase 5**: Use `check_compatibility()` in install flow before attempting claw installation
3. **Future**: Extend hardware detection to gather installed package versions for dependency checking

## Self-Check: PASSED

All files and commits verified:

**Files:**
- ✓ src/clawrium/core/registry.py exists and contains CompatibilityResult, check_compatibility
- ✓ tests/test_registry.py exists and contains 8 new compatibility tests

**Commits:**
- ✓ 20ab2e8: test(03-03): add failing tests for compatibility checking
- ✓ 8112bbd: feat(03-03): implement compatibility checking

**Tests:**
- ✓ All 14 tests in test_registry.py pass
- ✓ Compatibility tests cover all requirement types
- ✓ Manual verification confirms function works as expected

---
phase: 03-registry-compatibility
plan: 02
subsystem: hardware
tags: [ansible, hardware-detection, os-detection, facts]

# Dependency graph
requires:
  - phase: 02-host-management
    provides: Hardware detection via Ansible facts (HardwareInfo TypedDict, gather_hardware function)
provides:
  - Extended HardwareInfo TypedDict with os and os_version fields
  - OS detection from ansible_distribution and ansible_distribution_version facts
  - Default to "unknown" when OS facts are missing
affects: [03-registry-compatibility, 05-install-flow]

# Tech tracking
tech-stack:
  added: []
  patterns: [Ansible facts for OS detection, lowercase OS name normalization]

key-files:
  created: []
  modified:
    - src/clawrium/core/hardware.py
    - tests/test_hardware.py

key-decisions:
  - "Lowercase OS names for consistency (Ubuntu -> ubuntu)"
  - "Default to 'unknown' for missing OS facts rather than failing"
  - "Extract OS info from existing Ansible facts (ansible_distribution, ansible_distribution_version)"

patterns-established:
  - "OS detection follows same pattern as other hardware facts (extract from Ansible setup module)"
  - "TDD approach with RED-GREEN-REFACTOR cycle for type extensions"

requirements-completed: [REG-03]

# Metrics
duration: 2min
completed: 2026-03-21
---

# Phase 03 Plan 02: OS Detection in Hardware Info Summary

**Extended HardwareInfo with OS detection from Ansible facts (ansible_distribution → os, ansible_distribution_version → os_version)**

## Performance

- **Duration:** 2m 7s
- **Started:** 2026-03-21T22:30:01Z
- **Completed:** 2026-03-21T22:32:08Z
- **Tasks:** 1 (TDD with RED-GREEN phases)
- **Files modified:** 2

## Accomplishments
- Extended HardwareInfo TypedDict with os and os_version fields
- Implemented OS detection from ansible_distribution and ansible_distribution_version facts
- Normalized OS names to lowercase (Ubuntu → ubuntu) for consistency
- Default to "unknown" when OS facts are missing (graceful degradation)
- All 143 tests pass including 2 new OS detection tests

## Task Commits

Each task was committed atomically following TDD cycle:

1. **Task 1: Extend HardwareInfo with OS detection** (TDD)
   - RED: `95a3155` (test: add failing test for OS detection in HardwareInfo)
   - GREEN: `3feb214` (feat: implement OS detection in HardwareInfo)

## Files Created/Modified
- `src/clawrium/core/hardware.py` - Extended HardwareInfo TypedDict with os/os_version fields, updated extract_hardware_from_facts() to extract ansible_distribution and ansible_distribution_version
- `tests/test_hardware.py` - Added test_parse_ansible_facts_os_detection and test_parse_ansible_facts_os_missing, updated test_gather_hardware_full to verify OS fields

## Decisions Made

**OS name normalization:** Lowercase OS names (Ubuntu → ubuntu) for consistent comparison in future compatibility checking.

**Graceful degradation:** Default to "unknown" rather than failing when OS facts are missing. This matches the pattern for other hardware fields (architecture, processor_cores, etc.).

**Reuse existing infrastructure:** OS detection uses the existing gather_hardware() and extract_hardware_from_facts() pattern from Phase 2. No new Ansible calls needed - OS facts already gathered by setup module.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation followed existing hardware detection patterns established in Phase 2.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 03-03 (compatibility checking function). HardwareInfo now includes all fields needed for claw manifest compatibility validation:
- OS (ansible_distribution → lowercase)
- OS version (ansible_distribution_version)
- Architecture (existing)
- Memory (existing)
- GPU (existing)

Host records stored via `clm host add` now automatically include OS information for future compatibility checks.

---
*Phase: 03-registry-compatibility*
*Completed: 2026-03-21*

## Self-Check: PASSED

All files created, all commits exist, all tests pass (143/143).

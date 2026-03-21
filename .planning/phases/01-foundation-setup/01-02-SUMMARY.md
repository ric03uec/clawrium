---
phase: 01-foundation-setup
plan: 02
subsystem: cli
tags: [typer, rich, dependency-detection, shutil, subprocess]

# Dependency graph
requires:
  - phase: 01-01
    provides: "Basic CLI structure with clm init command, config directory management"
provides:
  - "Dependency detection module for Python, Ansible, ansible-runner"
  - "Rich-formatted dependency status table in clm init"
  - "Exit code 1 when dependencies missing"
  - "Actionable install instructions for missing dependencies"
affects: [02-host-management, 03-openclaw-install]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "shutil.which() for binary detection"
    - "subprocess.run() for version parsing"
    - "importlib.util.find_spec() for Python package detection"
    - "Rich Table for formatted CLI output"
    - "Dataclass pattern for structured status objects"

key-files:
  created:
    - "src/clawrium/core/deps.py"
    - "tests/test_deps.py"
  modified:
    - "src/clawrium/cli/init.py"
    - "tests/test_cli_init.py"

key-decisions:
  - "Use pipx recommendation for Ansible install (Ubuntu externally-managed-environment compatibility)"
  - "Display version for found dependencies, path fallback if version unavailable"
  - "Table-based output instead of plain text for better readability"

patterns-established:
  - "DependencyStatus dataclass pattern for check results (name, found, version, path, install_hint)"
  - "Separate check functions per dependency (check_python, check_ansible, check_ansible_runner)"
  - "Exit with code 1 when any required dependency missing"

requirements-completed: [INIT-02]

# Metrics
duration: 152s
completed: 2026-03-21
---

# Phase 01 Plan 02: Dependency Detection Summary

**Dependency status table in clm init showing Python, Ansible, ansible-runner with OK/MISSING indicators and pipx install recommendations**

## Performance

- **Duration:** 2min 32s
- **Started:** 2026-03-21T02:09:17Z
- **Completed:** 2026-03-21T02:11:49Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Dependency detection module with check functions for Python, Ansible, ansible-runner
- Rich-formatted table showing dependency status with color-coded OK/MISSING indicators
- Actionable install instructions recommending pipx for Ansible (Ubuntu compatibility)
- Exit code 1 enforcement when dependencies missing
- 100% test coverage for dependency detection logic
- 93% overall project test coverage

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement dependency detection module** - `e5c227b` (feat, TDD)
2. **Task 2: Integrate dependency check into clm init** - `65de4c4` (feat)

_Note: Task 1 followed TDD pattern (test → implementation)_

## Files Created/Modified
- `src/clawrium/core/deps.py` - Dependency detection functions with DependencyStatus dataclass, checks for Python/Ansible/ansible-runner
- `tests/test_deps.py` - Comprehensive tests for all dependency check functions (10 tests)
- `src/clawrium/cli/init.py` - Enhanced init command with dependency table display and exit code enforcement
- `tests/test_cli_init.py` - Added dependency-related tests (4 new tests: table display, OK status, exit codes, install hints)

## Decisions Made

1. **pipx recommendation for Ansible**: Install hint uses "pipx install ansible (recommended) or sudo apt install ansible" to respect Ubuntu's PEP 668 externally-managed-environment while still showing apt as fallback
2. **Version vs Path display**: Show version if available, fall back to path for packages without version attribute
3. **Table wrapping tolerance**: Tests check for "pipx" and "install ansible" separately to handle Rich table column wrapping

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test assertion for wrapped table output**
- **Found during:** Task 2 verification
- **Issue:** Test assertion `assert "pipx install ansible" in result.output` failed because Rich table wraps text across rows ("Install via: pipx" on one line, "install ansible" on next)
- **Fix:** Changed assertion to check for "pipx" and "install ansible" separately, handling wrapped output
- **Files modified:** tests/test_cli_init.py
- **Verification:** All 9 CLI tests pass
- **Committed in:** 65de4c4 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor test fix to handle table formatting behavior. No functional changes.

## Issues Encountered
None - plan executed smoothly

## User Setup Required
None - no external service configuration required

## Next Phase Readiness
- Dependency detection complete, ready for host management features
- Config directory initialized, ready for inventory and secrets storage
- All dependencies verified before proceeding with Ansible execution

## Self-Check: PASSED

All claims verified:
- FOUND: src/clawrium/core/deps.py
- FOUND: tests/test_deps.py
- FOUND: e5c227b (Task 1 commit)
- FOUND: 65de4c4 (Task 2 commit)

---
*Phase: 01-foundation-setup*
*Completed: 2026-03-21*

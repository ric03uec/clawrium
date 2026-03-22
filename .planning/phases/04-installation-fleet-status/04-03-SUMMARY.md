---
phase: 04-installation-fleet-status
plan: 03
subsystem: core
tags: [installation, health-check, state-tracking]
requirements: [INST-04, STAT-01]

dependency_graph:
  requires:
    - 04-01 (base playbook and installation orchestration)
  provides:
    - claw installation state tracking in host records
    - live health checking via SSH
  affects:
    - host records (now include claws dict)
    - installation flow (tracks state transitions)

tech_stack:
  added:
    - datetime (Python stdlib) for ISO timestamps
  patterns:
    - State machine (installing → installed/failed)
    - Live SSH checks via ansible_runner
    - Process detection with pgrep

key_files:
  created:
    - src/clawrium/core/health.py (live health checking module)
    - tests/test_health.py (health check tests)
  modified:
    - src/clawrium/core/install.py (state tracking in run_installation)
    - tests/test_hosts.py (claw tracking tests)
    - tests/test_install.py (install state update tests)

decisions:
  - Use ISO 8601 timestamps for installed_at field
  - Track claw user in host record for process ownership checking
  - Use pgrep for process detection (simple, portable)
  - Health check timeout set to 15s (shorter than install timeout)
  - Return NOT_INSTALLED status when claw not in host record

metrics:
  duration_seconds: 336
  tasks_completed: 2
  files_created: 2
  files_modified: 3
  tests_added: 9
  completed_at: "2026-03-22T04:28:14Z"
---

# Phase 04 Plan 03: Installation State Tracking and Health Checks Summary

Claw installation state tracking with success/failure recording and live SSH-based health checking for process status.

## Objective Achieved

Extended host records to track installed claws with their state (installing/installed/failed), and implemented live health checking to determine if claw processes are running on remote hosts.

## Execution Flow

### Task 1: Add claw installation tracking to host records
**Status:** Complete ✓
**Commit:** 8e9c0f2

**Approach:**
- Extended host record schema with `claws` dict containing per-claw state
- Modified `run_installation()` to set `installing` status before playbook execution
- Wrapped playbook execution in try-except to track failures
- Set `installed` status on success with ISO timestamp
- Set `failed` status on exception with error message

**Schema added:**
```python
{
    "hostname": str,
    "claws": {
        "openclaw": {
            "version": "0.1.0",
            "status": "installed" | "failed" | "installing",
            "installed_at": "ISO timestamp",
            "error": str | None,
            "user": "opc-hostname"  # per D-07
        }
    }
}
```

**Key changes:**
- `install.py` imports `datetime` and `timezone` for timestamps
- Three state update functions: `set_installing`, `set_installed`, `set_failed`
- All use `update_host()` for atomic updates
- Claw user extracted from hostname (e.g., `opc-testhost` for `testhost`)

**Tests added:**
- `test_host_claw_tracking_installed` - verify installed state structure
- `test_host_claw_tracking_failed` - verify failed state with error
- `test_install_updates_host_on_success` - verify state transitions
- `test_install_updates_host_on_failure` - verify failure tracking

**Test challenges:**
- Mock needed to simulate persistent state between `update_host` calls
- Captured before/after status to verify transitions
- All tests pass (185 total)

### Task 2: Create health check module for live claw status
**Status:** Complete ✓
**Commit:** 288e82a

**Approach:**
- Created new module `health.py` with live SSH-based health checking
- Implemented `ClawStatus` enum (RUNNING, STOPPED, UNKNOWN, NOT_INSTALLED)
- Used ansible_runner with shell module to run `pgrep` for process detection
- Returns structured `HealthResult` with status, user, error

**Implementation:**
```python
def check_claw_health(claw_name: str, host: dict) -> HealthResult
def check_all_claws_on_host(host: dict) -> list[HealthResult]
```

**Process detection:**
- Command: `pgrep -u {claw_user} node >/dev/null 2>&1 && echo RUNNING || echo STOPPED`
- Checks for node process owned by claw user
- 15-second timeout for SSH check

**Error handling:**
- NOT_INSTALLED: claw not in host record
- UNKNOWN: missing SSH key, SSH timeout, SSH failure, no claw user
- Errors include descriptive messages for debugging

**Tests added:**
- `test_health_check_running` - process found
- `test_health_check_stopped` - process not found
- `test_health_check_ssh_fails` - SSH error handling
- `test_health_check_not_installed` - claw not tracked
- `test_health_check_no_ssh_key` - missing credentials
- `test_health_check_timeout` - timeout handling
- `test_check_all_claws_on_host` - bulk checking

**All tests use mocks for:**
- `get_host_private_key` (returns fake path)
- `ansible_runner.run` (returns mock result with events)

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- [x] Host records contain `claws` dict after installation
- [x] Failed installations have `status="failed"` with error message
- [x] `check_claw_health` performs live SSH check (not cached)
- [x] Health check returns correct status for all scenarios
- [x] All 185 tests pass

## Requirements Completed

- **INST-04:** Error tracking - ✓ Failed installations recorded in host record with error details
- **STAT-01:** Fleet status foundation - ✓ Health checking infrastructure in place

## Next Steps

These modules provide the foundation for:
- Plan 04-04: Fleet status display (will use `check_all_claws_on_host`)
- Future claw lifecycle commands (start/stop/restart - will use health checks)
- Installation error diagnostics (query failed installations from host records)

## Known Limitations

- Health check only detects node processes (OpenClaw-specific)
- No differentiation between multiple node processes owned by same user
- No version verification (assumes any node process is the claw)

These limitations are acceptable for v1 (OpenClaw-only). Future enhancements can add:
- Process name matching (`openclaw` in command line)
- PID file validation
- Version query via claw API

## Self-Check: PASSED

All files created and commits verified:
- FOUND: src/clawrium/core/health.py
- FOUND: tests/test_health.py
- FOUND: 8e9c0f2 (Task 1 commit)
- FOUND: 288e82a (Task 2 commit)

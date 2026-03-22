---
phase: 04-installation-fleet-status
plan: 02
subsystem: cli
tags: [installation, cli, interactive, progress-display]
requires: [04-01]
provides: [install-command, interactive-install-flow]
affects: [cli-ux, install-experience]
tech-stack:
  added: [typer-prompts, rich-panel, rich-progress]
  patterns: [hybrid-invocation, confirmation-dialog, progress-spinner]
key-files:
  created:
    - src/clawrium/cli/install.py
    - tests/test_cli_install.py
  modified:
    - src/clawrium/cli/main.py
decisions:
  - Hybrid invocation pattern: interactive prompts when flags missing, direct execution with flags
  - Rich Panel for confirmation summary with installation details
  - Rich Progress spinner for real-time installation feedback
  - Exit 0 on cancellation to distinguish from errors (exit 1)
  - Compatibility checking before confirmation to fail fast
metrics:
  duration_seconds: 280
  tasks_completed: 1
  tests_added: 8
  commits: 3
completed_at: "2026-03-22T04:27:24Z"
---

# Phase 04 Plan 02: Install CLI Command Summary

**One-liner:** Interactive install command with Rich progress display and confirmation dialog wrapping core install module

## What Was Built

Created `clm install` CLI command providing polished UX for claw installation with:
- Interactive prompts for claw and host selection when flags not provided
- Confirmation dialog showing installation summary (claw, version, host, specs)
- Rich spinner progress display during installation phases
- Support for `--claw`, `--host`, `--yes` flags for non-interactive automation
- Clear error messages for incompatibility and installation failures
- Proper exit codes (0 for cancellation, 1 for errors)

The command bridges user interaction with the core install module, implementing the D-01 hybrid invocation pattern and D-02/D-03 UX requirements.

## Implementation Notes

### CLI Flow
1. **Selection Phase**: Prompt for claw/host if flags not provided
   - Claw list from registry with version and description
   - Host list with architecture and memory
   - Input validation with clear error messages

2. **Validation Phase**: Check compatibility before showing confirmation
   - Load claw manifest
   - Get host record
   - Run compatibility check
   - Fail fast with clear incompatibility reasons

3. **Confirmation Phase**: Show summary panel and confirm
   - Panel displays claw, version, host, architecture, memory
   - `--yes` flag skips confirmation for automation
   - Cancellation exits cleanly with code 0

4. **Installation Phase**: Run with progress feedback
   - Rich spinner with stage/message updates
   - Progress updates via callback from core install
   - Success message on completion
   - Error display on failure (exit 1)

### Testing Strategy

All tests follow CliRunner pattern from test_cli_host.py:
- Mock isolation using `isolated_config` fixture
- Test helper `create_host()` for host record setup
- Test helper `create_test_keypair()` for SSH key setup
- Patch `run_installation` to avoid actual playbook execution
- Input simulation via `input` parameter for prompts

8 test scenarios covering:
- Claw selection prompt when `--claw` not provided
- Host selection prompt when `--host` not provided
- Flag overrides skip prompts
- Confirmation summary display
- `--yes` skips confirmation
- Cancellation exits 0
- InstallationError handling (exit 1)
- Incompatibility detection and rejection

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Bug] Fixed indentation error in core/install.py**
- **Found during:** Test execution (GREEN phase)
- **Issue:** Line 164 had malformed `try:` block from previous task, causing ImportError
- **Fix:** Removed empty try block, adjusted indentation for Step 7/8 comments
- **Files modified:** src/clawrium/core/install.py
- **Commit:** (part of GREEN phase, linter fixed it)
- **Reason:** Blocking issue preventing test execution (Deviation Rule 3)

**2. [Refactor - REFACTOR phase] Removed dead code**
- **Found during:** Code review after GREEN phase
- **Issue:** `current_stage` variable and `on_event` callback defined but never used
- **Fix:** Removed unused variables, simplified to use `update_progress` directly
- **Files modified:** src/clawrium/cli/install.py
- **Commit:** c36d3f3
- **Reason:** Code cleanup during TDD REFACTOR phase

## Verification

### Automated Tests
```bash
.venv/bin/pytest tests/test_cli_install.py -v
# Result: 8/8 passed
```

### Manual Verification
```bash
# Help display
.venv/bin/clm install --help
# Shows: --claw, --host, --yes options

# Interactive flow (requires actual hosts/keys, not run)
# .venv/bin/clm install
# Expected: Prompts for claw, then host, shows confirmation

# Direct invocation (requires actual hosts/keys, not run)
# .venv/bin/clm install --claw openclaw --host myhost
# Expected: Shows confirmation, installs on acceptance
```

## Success Criteria

- ✓ Users can complete installation interactively or via flags (D-01)
- ✓ Step-by-step progress shown during install (D-02)
- ✓ Confirmation with summary displayed before install (D-03)
- ✓ Tests cover success, error, and cancellation paths
- ✓ All 8 CLI install tests pass
- ✓ Install command registered in main CLI
- ✓ Help text shows all options

## Files Modified

### Created
- `src/clawrium/cli/install.py` (171 lines) - Install CLI command implementation
- `tests/test_cli_install.py` (254 lines) - Comprehensive CLI tests

### Modified
- `src/clawrium/cli/main.py` - Added install command registration and import

## Commits

| Hash | Type | Message |
|------|------|---------|
| 0b05173 | test | Add failing tests for install CLI command (RED phase) |
| b64b56d | feat | Implement install CLI command with interactive flow (GREEN phase) |
| c36d3f3 | refactor | Remove unused callback variable in install command (REFACTOR phase) |

## Known Limitations

None identified. Command follows existing CLI patterns and integrates cleanly with core install module.

## Next Steps

Per roadmap, next plans are:
- 04-03: Fleet status command for viewing installed claws
- 04-04: E2E installation test for OpenClaw on real/mock host

The install command is now ready for integration testing in 04-04.

## Self-Check: PASSED

All files created and commits verified:
- ✓ src/clawrium/cli/install.py exists
- ✓ tests/test_cli_install.py exists
- ✓ Commit 0b05173 (test) exists
- ✓ Commit b64b56d (feat) exists
- ✓ Commit c36d3f3 (refactor) exists

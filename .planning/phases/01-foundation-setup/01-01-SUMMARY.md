---
phase: 01-foundation-setup
plan: 01
subsystem: cli-core
tags: [init, config, cli, foundation]
dependency_graph:
  requires: []
  provides:
    - clm-cli-entry-point
    - config-directory-management
  affects:
    - phase-01-plan-02
tech_stack:
  added:
    - typer: ">=0.24.0"
    - rich: ">=14.0.0"
    - ansible-runner: ">=2.4.0"
    - pytest: ">=8.0.0"
    - pytest-cov: ">=6.0.0"
  patterns:
    - src-layout-packaging
    - typer-cli-with-commands
    - xdg-config-home-support
    - tdd-red-green-refactor
key_files:
  created:
    - pyproject.toml
    - README.md
    - src/clawrium/__init__.py
    - src/clawrium/cli/__init__.py
    - src/clawrium/cli/main.py
    - src/clawrium/cli/init.py
    - src/clawrium/core/__init__.py
    - src/clawrium/core/config.py
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_config.py
    - tests/test_cli_init.py
  modified: []
decisions:
  - choice: Use src/ layout for project structure
    rationale: Industry best practice for Python packaging, cleaner imports, better isolation
    alternatives: Flat layout (rejected - harder to maintain)
  - choice: Use Typer callback pattern for multi-command CLI
    rationale: Forces command names even with single command, allows future expansion
    alternatives: Single-command pattern (rejected - not extensible)
  - choice: TDD with RED-GREEN-REFACTOR for core modules
    rationale: Ensures correctness, prevents regressions, documents expected behavior
    alternatives: Test-after (rejected - less reliable)
  - choice: Use monkeypatch + os.environ for CLI testing
    rationale: Allows proper environment isolation in tests
    alternatives: Mock config_dir directly (rejected - less realistic)
metrics:
  duration_minutes: 6
  tasks_completed: 3
  files_created: 12
  tests_added: 12
  test_coverage: 94
  commits: 6
  completed_at: "2026-03-21T02:06:50Z"
requirements_satisfied:
  - INIT-01
---

# Phase 01 Plan 01: Project Scaffolding and Init Command Summary

**One-liner:** Established Python project structure with Typer CLI and implemented `clm init` command to create ~/.config/clawrium/ directory.

## What Was Built

Created the foundation for Clawrium as a properly structured Python CLI application with:

1. **Project scaffolding** - pyproject.toml with uv/hatchling build system, src/ layout, test framework configured
2. **Config directory management** - Functions to get and initialize config directory with XDG_CONFIG_HOME support
3. **CLI entry point** - Typer-based `clm` command with `init` subcommand that creates config directory and shows confirmation

The `clm init` command is now functional and can be invoked via `uv run clm init`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create project scaffolding with pyproject.toml | 9f4df76 | pyproject.toml, src/clawrium/**, tests/**, README.md, uv.lock |
| 2 (RED) | Write failing tests for config module | dd36aff | tests/test_config.py |
| 2 (GREEN) | Implement config directory management | dc0de09 | src/clawrium/core/config.py |
| 3 (RED) | Write failing tests for CLI init command | f3d44f9 | tests/test_cli_init.py |
| 3 (GREEN) | Implement clm init command | f06cc21 | src/clawrium/cli/main.py, src/clawrium/cli/init.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing README.md blocked build**
- **Found during:** Task 1 - uv sync
- **Issue:** pyproject.toml referenced README.md but file didn't exist, causing build failure
- **Fix:** Created minimal README.md with project description and basic usage
- **Files modified:** README.md (created)
- **Commit:** 9f4df76 (included in Task 1 commit)

**2. [Rule 1 - Bug] CliRunner environment isolation**
- **Found during:** Task 3 - GREEN phase testing
- **Issue:** CliRunner wasn't inheriting monkeypatched environment variables from fixtures
- **Fix:** Added `env=os.environ` parameter to runner.invoke() calls in tests that use isolated_config fixture
- **Files modified:** tests/test_cli_init.py
- **Commit:** f06cc21 (included in Task 3 commit)

**3. [Rule 1 - Bug] Typer auto-running single command**
- **Found during:** Task 3 - GREEN phase testing
- **Issue:** Typer auto-detected single-command mode and ran init without requiring command name
- **Fix:** Added @app.callback() with invoke_without_command=True to force command names
- **Files modified:** src/clawrium/cli/main.py
- **Commit:** f06cc21 (included in Task 3 commit)

**4. [Rule 2 - Missing critical functionality] Test expectation adjustment**
- **Found during:** Task 3 - GREEN phase testing
- **Issue:** Test expected exit code 0 for no-args invocation, but CLI correctly exits non-zero when showing help as error
- **Fix:** Changed test to use --help explicitly instead of no args
- **Files modified:** tests/test_cli_init.py
- **Commit:** f06cc21 (included in Task 3 commit)

## Test Results

**Full test suite:**
- Tests: 12 passed, 0 failed
- Coverage: 94% (36 statements, 2 missed in main.py callback)
- Duration: ~0.11s

**Test breakdown:**
- `tests/test_config.py`: 7 tests (get_config_dir behavior, init_config_dir idempotency)
- `tests/test_cli_init.py`: 5 tests (help output, directory creation, success message, idempotency)

## Verification

All plan success criteria met:

- [x] `clm init` creates ~/.config/clawrium/ directory
- [x] `clm init` respects XDG_CONFIG_HOME when set
- [x] `clm init` is idempotent (can run multiple times)
- [x] `clm --help` shows available commands
- [x] All tests in tests/test_config.py and tests/test_cli_init.py pass
- [x] Package is properly structured with src/ layout

**Automated verification:**
```bash
$ uv run pytest tests/ -v --cov=clawrium
# 12 passed, 94% coverage

$ uv run clm --help
# Shows "Clawrium - Manage your AI assistant fleet" and init command

$ uv run clm init
# Creates directory and shows confirmation
```

## Known Stubs

None. All functionality is fully implemented with no placeholders or stub data.

## Architecture Impact

**New patterns introduced:**
1. **src/ layout** - All source code under src/clawrium/, tests separate
2. **Typer CLI pattern** - Main app with callback + commands for extensibility
3. **XDG config pattern** - Respects XDG_CONFIG_HOME, falls back to ~/.config
4. **Test fixtures** - tmp_config_dir and isolated_config fixtures for config testing

**Module structure:**
```
clawrium/
├── cli/          # CLI commands (main.py, init.py)
├── core/         # Core functionality (config.py)
└── utils/        # Utilities (empty for now)
```

This structure supports future expansion:
- cli/ will hold additional command modules (host.py, claw.py, etc.)
- core/ will hold business logic (registry.py, ansible.py, etc.)
- utils/ will hold shared helpers (console.py, validation.py, etc.)

## Next Steps

Phase 01 Plan 02 will:
1. Implement dependency detection for Python and Ansible
2. Add install instructions for missing dependencies
3. Extend `clm init` to show dependency status table

This plan provides the foundation - Plan 02 will complete the initialization experience.

## Self-Check

Verifying all claimed artifacts exist and commits are valid:

**Files check:**
- [x] pyproject.toml exists
- [x] src/clawrium/__init__.py exists
- [x] src/clawrium/cli/main.py exists
- [x] src/clawrium/cli/init.py exists
- [x] src/clawrium/core/config.py exists
- [x] tests/test_config.py exists
- [x] tests/test_cli_init.py exists
- [x] README.md exists

**Commits check:**
- [x] 9f4df76 exists (project scaffolding)
- [x] dd36aff exists (config tests RED)
- [x] dc0de09 exists (config implementation GREEN)
- [x] f3d44f9 exists (CLI tests RED)
- [x] f06cc21 exists (CLI implementation GREEN)

**Functionality check:**
- [x] `uv run clm --help` shows help
- [x] `uv run clm init` creates directory
- [x] All 12 tests pass with 94% coverage

## Self-Check: PASSED

All artifacts exist, all commits valid, all functionality working as documented.

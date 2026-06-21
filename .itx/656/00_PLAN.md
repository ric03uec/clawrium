# Plan: Issue #656 — User can see version and git commit SHA from clawctl version

## Context

Issue #656 requests that `clawctl version` and `clawctl --version` display the git
commit SHA alongside the release version string, e.g.:

    clawctl 26.6.1 (git: a3f9c12)

The SHA must be embedded at package build time so it is available at runtime
without requiring a `.git` directory.

## Current State

- `clawrium/__init__.py` reads `__version__` from `importlib.metadata`.
- `clawrium/cli/meta.py` defines `version_cmd()` which prints
  `f"clawctl {__version__}"`.
- `clawrium/cli/__init__.py` (clawctl entry) uses `f"clawctl {__version__}"` in
  the root `--version` callback.
- `clawrium/cli/main.py` (legacy clm entry) uses `f"clm {__version__}"`.
- Build system is **hatchling** (no setuptools-scm).
- No existing `_version.py` or git-SHA embedding mechanism.

## Approach: Hatchling build hook generates `_version.py`

Hatchling supports custom build hooks that run at wheel/sdist build time. We
will create a `hatch_build.py` at the project root that:

1. Reads the short git SHA via `git rev-parse --short HEAD`.
2. Falls back to `"unknown"` when `.git` is absent (e.g. sdist builds, CI
   checkout without git history).
3. Writes `src/clawrium/_version.py` with two constants:
   `__version__` and `__git_sha__`.

This is the standard hatchling pattern — the build hook generates code that
ships inside the wheel. At runtime, `clawrium/__init__.py` imports from
`_version.py` when available (i.e. installed package) and falls back to
`importlib.metadata` for editable installs.

## Tasks

### Task 1: Create `hatch_build.py` build hook

**File**: `hatch_build.py` (project root)

- Implement a `CustomBuildHook` class inheriting from
  `hatchling.builders.hooks.plugin.interface.BuildHookInterface`.
- In `initialize()` (runs before build), compute:
  - `version`: read from `importlib.metadata.version("clawrium")`, falling back
    to parsing `pyproject.toml` `[project].version`.
  - `git_sha`: run `git rev-parse --short HEAD`, falling back to `"unknown"`.
- Write `src/clawrium/_version.py` with:
  ```python
  __version__ = "26.6.1"
  __git_sha__ = "a3f9c12"
  ```
- Register the hook in `pyproject.toml`:
  ```toml
  [tool.hatch.build.hooks.custom]
  path = "hatch_build.py"
  ```

**Pitfalls**:
- The hook must not fail when `.git` is absent (sdist builds, Docker). Always
  fall back to `"unknown"`.
- Hatchling invokes `initialize()` even for editable installs — the generated
  file must be importable from the source tree too.

### Task 2: Update `clawrium/__init__.py` to import git SHA

**File**: `src/clawrium/__init__.py`

- Add `__git_sha__` alongside `__version__`.
- Try importing from `_version.py` first (installed package). If that fails,
  fall back to `importlib.metadata` for `__version__` and set `__git_sha__` to
  `"unknown"` (editable install without build hook).

```python
try:
    from clawrium._version import __version__, __git_sha__
except ImportError:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("clawrium")
    except PackageNotFoundError:
        __version__ = "0.0.0"
    __git_sha__ = "unknown"
```

### Task 3: Update `clawrium/cli/meta.py` version output

**File**: `src/clawrium/cli/meta.py`

- Import `__git_sha__` alongside `__version__`.
- Change `version_cmd()` output to:
  ```python
  typer.echo(f"clawctl {__version__} (git: {__git_sha__})")
  ```

### Task 4: Update `clawrium/cli/__init__.py` root callback

**File**: `src/clawrium/cli/__init__.py`

- Import `__git_sha__` alongside `__version__`.
- Update the `--version` callback to:
  ```python
  typer.echo(f"clawctl {__version__} (git: {__git_sha__})")
  ```

### Task 5: Update legacy `clm --version` output

**File**: `src/clawrium/cli/main.py`

- Import `__git_sha__` alongside `__version__`.
- Update the `--version` callback to:
  ```python
  console.print(f"clm {__version__} (git: {__git_sha__})")
  ```

### Task 6: Update tests

**File**: `tests/test_cli_version.py`

- Update `test_version_output_format` to expect the new format
  `clm <version> (git: <sha>)`.
- Add a test that `__git_sha__` is a non-empty string.
- Add a test for `clawctl version` subcommand output (via the clawctl app).
- Update `test_version_works_without_config` to accept the new format.
- Keep `test_short_v_flag_not_version` and `test_ps_verbose_still_works`
  unchanged (they don't depend on the SHA format).

### Task 7: Add `.gitignore` entry for generated `_version.py`

**File**: `.gitignore`

- Add `src/clawrium/_version.py` to `.gitignore` since it is a build artifact.

### Task 8: Update CHANGELOG.md

**File**: `CHANGELOG.md`

- Add under `## [Unreleased]` / `### Added`:
  ```
  - `clawctl version` and `clawctl --version` now show the git commit SHA alongside the release version (#656).
  ```

## Files Changed (summary)

| File | Change |
|------|--------|
| `hatch_build.py` | NEW — custom hatchling build hook |
| `pyproject.toml` | Register custom build hook |
| `src/clawrium/__init__.py` | Add `__git_sha__`, import from `_version` |
| `src/clawrium/_version.py` | GENERATED — not committed |
| `src/clawrium/cli/meta.py` | Include git SHA in `version_cmd` output |
| `src/clawrium/cli/__init__.py` | Include git SHA in root `--version` |
| `src/clawrium/cli/main.py` | Include git SHA in legacy `clm --version` |
| `.gitignore` | Ignore generated `_version.py` |
| `tests/test_cli_version.py` | Update assertions for new format |
| `CHANGELOG.md` | Document feature |

## Risks

| Risk | Mitigation |
|------|------------|
| Build hook fails without `.git` | Fallback to `"unknown"` SHA |
| Editable installs don't run build hook | `__init__.py` fallback sets `__git_sha__ = "unknown"` |
| Tests break due to format change | Task 6 updates all version assertions |

## DoD Mapping (from issue #656)

| Acceptance Criterion | Task |
|----------------------|------|
| `clawctl version` prints version + short git SHA | Task 3 |
| `clawctl --version` prints same info | Task 4 |
| SHA embedded at build time, no `.git` at runtime | Task 1 + Task 2 |
| Existing tests updated / new tests added | Task 6 |

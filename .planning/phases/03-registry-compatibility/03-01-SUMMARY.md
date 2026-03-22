---
phase: 03-registry-compatibility
plan: 01
subsystem: registry
tags: [manifest, registry, openclaw, yaml]
dependency_graph:
  requires: []
  provides: [registry-loading, openclaw-manifest]
  affects: []
tech_stack:
  added: [pyyaml, packaging]
  patterns: [importlib.resources, TypedDict, yaml.safe_load]
key_files:
  created:
    - src/clawrium/platform/registry/openclaw/manifest.yaml
    - src/clawrium/core/registry.py
    - src/clawrium/platform/__init__.py
    - src/clawrium/platform/registry/__init__.py
    - tests/test_registry.py
  modified:
    - pyproject.toml
decisions: []
metrics:
  duration_seconds: 96
  completed_at: "2026-03-21T22:31:37Z"
  tasks_completed: 1
  files_created: 5
  files_modified: 1
  tests_added: 6
---

# Phase 03 Plan 01: Registry Manifest Loading Summary

**One-liner:** Registry loading system with OpenClaw manifest using importlib.resources and YAML parsing

## Overview

Created the foundational registry system that loads claw manifests from bundled YAML files. The system supports discovering available claw types, loading their platform requirements, and extracting summary information. OpenClaw manifest includes entries for Ubuntu 24.04 and 22.04 on x86_64 architecture.

## What Was Built

### Core Functionality

**Registry Loading Module** (`src/clawrium/core/registry.py`):
- `load_manifest(claw_name)` - Loads and parses YAML manifest from bundled package
- `list_claws()` - Discovers all available claw types in registry
- `get_claw_info(claw_name)` - Extracts summary with latest version and supported platforms
- TypedDict schemas: `Requirements`, `ManifestEntry`, `ClawManifest`
- Exception types: `ManifestNotFoundError`, `ManifestParseError`

**OpenClaw Manifest** (`src/clawrium/platform/registry/openclaw/manifest.yaml`):
- Name: openclaw
- Description: "Open-source AI assistant framework"
- Entries for Ubuntu 24.04 (Node.js >=20.0.0) and Ubuntu 22.04 (Node.js >=18.0.0)
- Both require 2GB RAM, x86_64 architecture, no GPU

**Package Structure**:
- `src/clawrium/platform/` - Platform-specific definitions
- `src/clawrium/platform/registry/` - Registry root package
- `src/clawrium/platform/registry/openclaw/` - OpenClaw claw directory

**Dependencies Added**:
- `pyyaml>=6.0.0` - YAML parsing
- `packaging>=24.0` - Semver comparison for version handling

### Testing

**Test Coverage** (`tests/test_registry.py` - 6 tests):
1. `test_load_manifest_openclaw` - Validates OpenClaw manifest structure
2. `test_load_manifest_nonexistent` - Verifies error handling for missing claws
3. `test_load_manifest_malformed` - Tests ManifestParseError exception
4. `test_list_claws` - Confirms openclaw appears in registry listing
5. `test_get_claw_info_openclaw` - Validates summary extraction with version and platforms
6. `test_get_claw_info_nonexistent` - Error handling for unknown claws

All tests pass with 100% success rate.

## Implementation Approach

### TDD Execution

**RED Phase** (commit 6bfbf2c):
- Created 6 failing tests in `tests/test_registry.py`
- Tests initially failed with `ModuleNotFoundError`

**GREEN Phase** (commit 0ac205b):
- Added PyYAML and packaging dependencies
- Created package structure (`platform/`, `platform/registry/`)
- Implemented registry loading module with importlib.resources
- Created OpenClaw manifest with two platform entries
- All tests pass

### Technical Decisions

1. **importlib.resources over file paths**: Used `importlib.resources.files()` for reading bundled manifests, ensuring compatibility with zip-deployed packages

2. **TypedDict for schemas**: Followed existing `hardware.py` pattern for type definitions without runtime overhead

3. **Sparse manifest matrix**: Each entry explicitly defines supported platform combination - no wildcards or inheritance

4. **Semver latest version**: Used `packaging.version.Version` to find highest semantic version across entries

5. **Graceful discovery**: `list_claws()` only returns directories with valid `manifest.yaml` files

## Verification Results

✅ All acceptance criteria met:
- `pyproject.toml` contains "pyyaml>=6.0.0"
- `pyproject.toml` contains "packaging>=24.0"
- OpenClaw manifest exists and contains "name: openclaw"
- registry.py exports all required functions and types
- 6+ test functions in test_registry.py
- `uv run pytest tests/test_registry.py` exits 0

✅ Additional verification:
- Manifest is valid YAML (verified with yaml.safe_load)
- All exports available and importable
- `list_claws()` returns ["openclaw"]

## Files Changed

### Created
- `src/clawrium/platform/__init__.py` (package marker)
- `src/clawrium/platform/registry/__init__.py` (registry package marker)
- `src/clawrium/platform/registry/openclaw/manifest.yaml` (23 lines)
- `src/clawrium/core/registry.py` (172 lines)
- `tests/test_registry.py` (86 lines)

### Modified
- `pyproject.toml` (added 2 dependencies)

**Total**: 5 files created, 1 modified

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. All functionality is fully implemented and operational.

## Integration Points

**Provides for downstream plans:**
- Registry loading functions for CLI commands (03-02)
- Manifest schema for compatibility checking (03-03)
- Foundation for future claw type additions (zeroclaw, nemoclaw)

**Dependencies:**
- None (standalone module)

## Self-Check: PASSED

✅ Created files exist:
```
FOUND: src/clawrium/platform/__init__.py
FOUND: src/clawrium/platform/registry/__init__.py
FOUND: src/clawrium/platform/registry/openclaw/manifest.yaml
FOUND: src/clawrium/core/registry.py
FOUND: tests/test_registry.py
```

✅ Modified files contain expected content:
```
FOUND: pyproject.toml contains "pyyaml>=6.0.0"
FOUND: pyproject.toml contains "packaging>=24.0"
```

✅ Commits exist:
```
FOUND: 6bfbf2c (test phase)
FOUND: 0ac205b (implementation phase)
```

✅ All tests pass:
```
6 passed in 0.03s
```

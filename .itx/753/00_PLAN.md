# Implementation Plan: #753 — Validate agent_name before path interpolation in sync_agent_canonical

**Issue**: https://github.com/ric03uec/clawrium/issues/753
**Labels**: type:bug, complexity:s, type:security

## Problem Statement

`sync_agent_canonical` and its helpers (`_get_host_openclaw_version`, `_restart_unit`) interpolate `agent_name` directly into filesystem paths (e.g., `/home/{agent_name}/.openclaw/bin/openclaw`) and systemd unit names (e.g., `{agent_type}-{agent_name}.service`). While `shlex.quote()` prevents shell command injection, it does NOT prevent path traversal — an `agent_name` like `..` or `foo/../bar` escapes the `/home/` prefix.

`agent_name` originates from `hosts.json` (operator-controlled), but defense-in-depth validation should reject malformed entries at the boundary, before any SSH round-trips.

Many core modules already validate agent names with `_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")` — `lifecycle_canonical.py` is the notable gaps.

## Approach

Add the same regex validator to `lifecycle_canonical.py` that exists in `agent_exec.py`, `launchd.py`, `render.py`, `skills_apply.py`, `skills_state.py`, `agent_shell.py`, and `memory.py`. Call the validator at the top of `sync_agent_canonical`, before any render, SSH, or ansible work.

### Why validate in sync layer (not just render layer)?

The render layer (`render.py:976`) does call `_validate_agent_name`, but it's gated behind per-agent-type branches (`_validate_agent_name(inputs.agent_name)` is called inside `render_hermes`, `render_zeroclaw`, `render_openclaw`). The sync layer is the unified entry point and should validate unconditionally before delegating to any downstream subsystem. The test suite should confirm that invalid names are rejected without triggering render-type-specific paths.

## Files to Modify

| File | Change |
|---|---|
| `src/clawrium/core/lifecycle_canonical.py` | Add `_AGENT_NAME_RE`, `_validate_agent_name()`, call at top of `sync_agent_canonical` |
| `tests/core/test_lifecycle_canonical.py` | Add validation test class (5 tests) |

## Implementation Steps

### Step 1: Add regex and validator to `lifecycle_canonical.py`

After the existing module-level constants (after `_SECRET_KEY_SUFFIXES` around line 108), add:

```python
# Defense-in-depth: agent_name from hosts.json must match the same
# character/length constraints enforced by agent_exec.py, launchd.py,
# render.py, skills_apply.py, skills_state.py, agent_shell.py, and
# memory.py. Reject path traversal (`..`) and uppercase at the sync
# boundary before any SSH round-trip. (Issue #753)
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _validate_agent_name(agent_name: str) -> None:
    """Raise `CanonicalSyncError` if agent_name fails format validation."""
    if not isinstance(agent_name, str) or not _AGENT_NAME_RE.match(agent_name):
        raise CanonicalSyncError(f"invalid agent_name: {agent_name!r}")
```

### Step 2: Call validator at top of `sync_agent_canonical`

Insert `_validate_agent_name(agent_name)` as the first operational line in the function body, after the `emit` helper definition (line ~1756), before `emit("validate", ...)` and `build_render_inputs(agent_name)` at line 1758. This ensures rejection before any render input assembly, SSH connection, or workspace staging.

Placement rationale:
- Before `build_render_inputs(agent_name)` — avoids triggering render-layer side effects on bad input
- Before `_open_ssh` at line 1853 — no network cost for invalid names
- After the `emit` helper definition — can still log the rejection if needed

### Step 3: Add tests to `tests/core/test_lifecycle_canonical.py`

Add a new test class `TestAgentNameValidation` with 5 parameterized tests covering:

| Test ID | Case | Agent Name | Expected |
|---|---|---|---|
| T1 | Path traversal (dotdot) | `".."` | `CanonicalSyncError` with `invalid agent_name` |
| T2 | Path traversal (nested) | `"foo/../bar"` | Same as T1 |
| T3 | Uppercase rejection | `"Wolf"` | Same as T1 |
| T4 | Length exceeded | `"a" * 33` | Same as T1 |
| T5 | Valid name passes | `"wolf-i"` | No validation error (may fail downstream on missing mocks) |

**Test approach**: For T1-T4, the validation happens BEFORE `build_render_inputs`, so no mocking of render inputs or probe is needed — just call `sync_agent_canonical` with the bad name and assert `CanonicalSyncError`. The `_default_probe_present` autouse fixture won't matter since the function exits early.

For T5, minimal mocking of `build_render_inputs` is needed to prevent downstream errors, mirroring the pattern in `test_sync_agent_missing_from_hosts_raises` (line 525). The assertion is that the validation step does NOT raise, and execution proceeds to the existing mocked downstream path.

**Key assertion for all T1-T4**: `_open_ssh` is never called. Verified by monkeypatching `_open_ssh` to raise on invocation and confirming the error is `CanonicalSyncError` from validation, not from the SSH stub.

## Test Strategy

1. **Parameterized rejection tests** (T1-T4): Each invalid name triggers `CanonicalSyncError` with `"invalid agent_name"` in the message. No downstream mocking needed since validation exits before any other work.

2. **Positive acceptance test** (T5): Valid name `"wolf-i"` passes validation. Mock `build_render_inputs` and `_open_ssh` to let execution proceed past validation. Assert no `CanonicalSyncError` from name validation specifically.

3. **SSH-not-called assertion**: For rejection tests, monkeypatch `_open_ssh` to raise `RuntimeError("SSH opened")`. The `CanonicalSyncError` should be raised first, proving no SSH connection was attempted.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Name validation breaks legitimate agent names | Regex matches existing agent_exec.py pattern (in use, proven). All current agent names in tests use lowercase alphanumeric. |
| Validator called too late (after SSH) | Code review + tests asserting `_open_ssh` not called on invalid names |
| Regex duplication across modules | Accepted pattern — every module that reads `agent_name` independently validates. Precedent: 7+ modules already have this constant. |

## Verification

- `make test` passes, including new validation tests
- Manual: edit `hosts.json` with `agent_name: ".."`, run `clawctl agent sync`, observe fast failure with error message
- `make lint` passes (ruff/flake8)

## Subtasks

None — single task execution. This is a focused, single-file change with co-located tests.

---

## Prompt Log

### Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-04T07:28:00Z
**Model**: qwen3.6-27b

```prompt
Create an implementation plan for GitHub issue #753 in the Clawrium repository at /home/devashish/workspace/ric03uec/clawrium.
```

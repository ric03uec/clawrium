# Issue #712 — GUI lifecycle endpoints return 200 with success:false on failure (ATX B1)

## Overview

Three lifecycle endpoints in `src/clawrium/gui/routes/fleet.py` — `start_agent_endpoint`,
`stop_agent_endpoint`, `restart_agent_endpoint` — return **HTTP 200** with a payload of
`{"success": false, "error": "..."}` when the underlying `start_agent` / `stop_agent` /
`restart_agent` core call returns a result dict whose `success` key is falsy (no exception
raised). Any consumer that gates on the HTTP status code proceeds as if the operation
succeeded. This is the ATX B1 finding from release PR #711 (v26.6.3); the bug is
pre-existing (present in v26.6.0 → v26.6.3).

Fix: after each core call, when `result.get("success")` is falsy, raise
`HTTPException(status_code=502, detail=_sanitize_health_error(...))`. This matches the
existing behavior for the `LifecycleError` and generic-`Exception` catch-arms (both
already 5xx), so the change makes the "success:false without exception" path consistent
with sibling failure paths in the same three handlers.

Frontend: the shared `request()` helper in `gui/src/lib/api.ts` already throws on
`!res.ok`, so react-query's mutation `error` state will populate correctly once the
backend switches from 200 to 502. Today `agent-header.tsx` binds only `isPending` on the
Start/Stop/Restart buttons — nothing surfaces `mutation.error`. Add a minimal inline
error notice so the operator sees the failure rather than silently seeing the button
re-enable with no visible outcome (matches the acceptance-criteria bullet about the
frontend handling 5xx gracefully).

## Root Cause

In `fleet.py:324-408` each handler does:

```python
result = await asyncio.to_thread(start_agent, ...)   # (or stop / restart)
return {
    "success": result["success"],
    "operation": "start",
    "agent": agent_key,
    "error": result.get("error"),
}
```

`core.lifecycle.start_agent` returns `{"success": False, "error": "..."}` on some
recoverable-failure paths (e.g. the ansible-runner run finishes but the target daemon
didn't come up). Those paths don't raise `LifecycleError`, so the `except`-arms below
never fire and the fall-through path returns HTTP 200 with a body whose truthiness the
caller must inspect. The other two handlers repeat the same pattern verbatim.

## Files to Modify

| File | Change |
|---|---|
| `src/clawrium/gui/routes/fleet.py` | After each of the 3 `result = await asyncio.to_thread(...)` calls (start / stop / restart), check `if not result.get("success"): raise HTTPException(status_code=502, detail=_sanitize_health_error(result.get("error")) or _LIFECYCLE_GENERIC_ERROR)`. Sanitize before use so filesystem paths inside the core-returned error string don't leak to the browser, mirroring the existing `LifecycleError` arm. |
| `tests/test_gui_fleet_lifecycle.py` | Rewrite the three `test_*_returns_success_false_with_error_field` tests to assert `HTTPException(status_code=502)` with `"SSH key not found"` in `exc.value.detail`. Also assert path sanitization on the returned error (add one dedicated case per verb using an error string containing an absolute filesystem path, mirroring `test_start_agent_lifecycle_error_sanitized`). |
| `tests/test_gui_routes_fleet.py` | Add three integration-level cases (`TestClient`) — `test_{start,stop,restart}_agent_returns_502_when_result_success_false` — that patch the core call to return `{"success": False, "error": "boom"}` and assert `resp.status_code == 502` and `resp.json()["detail"] == "boom"` (or the sanitized form when the error contains a path). |
| `gui/src/components/agent-detail/agent-header.tsx` | Surface `start.error` / `stop.error` / `restart.error` as an inline alert below the button row when any of the three mutations is in `isError` state. Use the existing text-status-error styling (already used at line 187 for the install-missing hint). Keep it small — one line, dismissable-on-next-mutation. |
| `CHANGELOG.md` | Add an entry under `## [Unreleased]` → `### Fixed` referencing #712. |

## Steps

1. **Backend fix (`fleet.py`)** — in each of the three lifecycle handlers, insert the
   `if not result.get("success")` guard between the `result = await asyncio.to_thread(...)`
   line and the current `return {...}` line. Compose the 502 detail as
   `_sanitize_health_error(result.get("error")) or _LIFECYCLE_GENERIC_ERROR` so a missing
   or None error field still produces a non-empty detail. Log at ERROR level with the
   same `logger.error("<verb>_agent returned success=false for %s: %s", ...)` pattern
   for symmetry with the exception arms; do not pass `exc_info=True` since there's no
   live exception.

2. **Rewrite the three `success_false` unit tests** in `tests/test_gui_fleet_lifecycle.py`
   to expect `HTTPException(502)`, and add a path-sanitization assertion in the same
   verb group so the sanitize call is covered independent of the LifecycleError arm.

3. **Add three `TestClient` integration cases** in `tests/test_gui_routes_fleet.py`
   (following the `test_start_agent_lifecycle_error_sanitized` pattern in the same file)
   asserting `502` on the `result["success"] == False` return path.

4. **Frontend error surface** — in `agent-header.tsx`, after the button row, render:
   ```tsx
   {(start.isError || stop.isError || restart.isError) && (
     <div className="mt-2 text-xs text-status-error" role="alert">
       {(start.error || stop.error || restart.error)?.message}
     </div>
   )}
   ```
   Verify no existing test asserts the absence of this element; if any does, update it.

5. **Changelog** — under `## [Unreleased]` → `### Fixed`, one line: fixed GUI lifecycle
   endpoints returning HTTP 200 with `success:false` on failure (#712).

6. **Verify** — `make lint && make test`. Follow with a real-host UAT: on wolf-i or any
   host with an agent, take the daemon down manually (`sudo systemctl stop <unit>` or
   invalidate a config file), hit the GUI's Restart button, confirm the button re-enables
   AND the inline error surfaces. Screenshot the 502 in the browser devtools Network tab
   for the PR body.

## Test Strategy

- **Unit** — `tests/test_gui_fleet_lifecycle.py::TestStartAgentEndpoint::test_start_agent_returns_success_false_with_error_field` (rewritten) covers the 502-instead-of-200 assertion at the handler level. Same for stop / restart. New sanitization cases cover the branch where the returned error string contains a filesystem path.
- **Integration** — `tests/test_gui_routes_fleet.py::test_{start,stop,restart}_agent_returns_502_when_result_success_false` exercise the full FastAPI wire path (TestClient) to make sure the raise propagates as a 502 response and the sanitized `detail` shows up in the JSON body.
- **Real-host UAT** — required per the "no PR without real-host UAT" project rule. Verify against a running fleet that the button UX degrades gracefully (see step 6).
- **Non-regression** — the existing `test_*_success` and `test_*_lifecycle_error_sanitized` and `test_*_generic_exception_uses_safe_message` cases must continue to pass unchanged.

## Risks / Trade-offs

- **API surface change.** The endpoints now return 5xx where they returned 2xx. Any external SDK consumer that reads the JSON body regardless of status code keeps working. Anyone gating on the status code was already broken by this bug; the fix is what they expected. Log this in the changelog under `### Fixed` (not `### BREAKING`) — the pre-fix behavior was a bug, not a contract.
- **Status-code choice.** Issue body proposes 502. That matches "upstream lifecycle system reported failure" semantics — the GUI is a gateway in front of the ansible-runner subprocess. 500 would be defensible too (matches the two existing except-arms), but 502 more accurately reflects "we succeeded; the thing we called reported it failed" and is what the ATX reviewer suggested. Go with 502 as issued; note the inconsistency vs. 500 for other arms in the PR body (a follow-up could unify them, but scope-creep out of this fix).
- **Frontend touch is minimal.** No new component, no new state, no toast library. Just one conditional `<div>` bound to react-query's built-in `isError` / `error`. If any snapshot test in `agent-header.test.tsx` matches the current DOM structure exactly it will need a refresh — check during execution.

## Definition of Done

- [ ] Backend: all three endpoints return 502 when `result["success"]` is false; sanitized detail; no path leakage.
- [ ] Tests: three rewritten unit tests + three new integration tests pass; existing tests still pass.
- [ ] Frontend: inline error surface renders on mutation.isError for all three verbs.
- [ ] `make lint && make test` clean.
- [ ] Real-host UAT recorded in PR body (host name + observed 502 + observed UI).
- [ ] `CHANGELOG.md` entry under `[Unreleased]` → `### Fixed` referencing #712.
- [ ] `.itx/712/` committed with the change.

## Subtasks

None — single-file backend fix + adjacent test updates + minimal frontend touch. Scope
is small enough for one branch / one PR.

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-05T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 712.
```

**Output**: high-level implementation plan for #712 saved to `.itx/712/00_PLAN.md`

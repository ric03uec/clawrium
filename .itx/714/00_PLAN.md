# Issue #714 — Execution Plan

## Title
[security] Pairing/tunnel error responses leak internal hostnames+ports (ATX W2)

## Problem
`_ABS_PATH_RE` in `src/clawrium/gui/routes/fleet.py:78` only strips POSIX absolute paths. SSH stderr fragments (e.g. `ssh: connect to host 192.168.1.42 port 22: Connection refused`) and hostnames/ports pass through verbatim into the HTTP response body, leaking internal network topology.

## Affected Code — Two Leak Points

Both are `TunnelError` handlers in `fleet.py` that use `_ABS_PATH_RE.sub("<path>", str(e))`:

1. **`agent_web_ui` (line ~483-488)** — `/fleet/agents/{key}/web-ui` endpoint
   - Returns `"reason": _ABS_PATH_RE.sub("<path>", str(e))`
   - The regex `(?:/[\w.\-]+)+` matches POSIX paths but misses IP addresses, hostnames, port numbers

2. **`agent_pairing_code` (line ~600-602)** — `/fleet/agents/{key}/pairing-code` endpoint
   - Raises `HTTPException(status_code=502, detail=_ABS_PATH_RE.sub("<path>", str(e)))`
   - Same regex weakness

## Existing Pattern to Follow
The generic `Exception` handlers at lines 493 and 611 already do this correctly — they log the full error server-side and return a constant string. The `TunnelError` handlers should match this pattern.

## Fix

Replace the `_ABS_PATH_RE.sub()` calls in both `TunnelError` handlers with constant error messages:

### Leak Point 1: `agent_web_ui` (web-ui tunnel)
```python
except web_ui_tunnel.TunnelError as e:
    logger.warning("web-ui tunnel failed for %s: %s", agent_key, e)
    return {
        "available": False,
        "local_url": None,
        "reason": "Tunnel could not be established. Check server logs for details.",
    }
```

### Leak Point 2: `agent_pairing_code` (pairing-code tunnel)
```python
except web_ui_tunnel.TunnelError as e:
    logger.warning("pairing-code tunnel failed for %s: %s", agent_key, e)
    raise HTTPException(
        status_code=502,
        detail="Tunnel could not be established. Check server logs for details.",
    ) from e
```

## Test Changes

### Existing tests that ASSERT the raw error appears (must be updated):

1. **`test_web_ui_reports_tunnel_failure_as_unavailable`** (line ~160 in test file)
   - Currently asserts `"ssh failed" in body["reason"]` — **this is the bug**
   - Must change to assert the constant string and that raw error is NOT present

2. **`test_pairing_code_502_on_tunnel_failure`** (line ~340 in test file)
   - Currently asserts `"ssh refused" in resp.json()["detail"]` — **this is the bug**
   - Must change to assert the constant string and that raw error is NOT present

### New tests to add:
- Test with realistic SSH stderr (IP addresses, hostnames, ports) to confirm none of it leaks

## Files to Change

| File | Changes |
|------|---------|
| `src/clawrium/gui/routes/fleet.py` | Two `TunnelError` handler edits (lines ~483-488, ~600-602) |
| `tests/test_gui_routes_fleet.py` | Update 2 existing tests + add 1-2 new tests for realistic SSH stderr |
| `CHANGELOG.md` | Add entry under `### Fixed` |

## Acceptance Criteria (from issue)

- [ ] No SSH stderr / raw exception text reaches the HTTP response body for pairing/tunnel/lifecycle routes
- [ ] Server-side log retains the full detail for operator debugging
- [ ] Tests assert the response detail is a constant string, not interpolated from server-side state

## Scope
Small, focused change — two error handler edits + test updates. No architectural risk. Low severity bug but security-adjacent.

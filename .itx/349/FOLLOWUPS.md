# Issue #349 — Follow-up Items

The `gui-feat` PR (#350) lands B1–B12 and W1–W26 from the ATX iterations. Items below are intentionally *not* in that PR and want their own follow-up — either because they exceed the GUI scope or are non-blocking nice-to-haves.

## Test coverage

### B9 — API-layer integration tests for fleet.py / agents.py routes

Unit-level enforcement of the security fixes (`_AGENT_TOKEN_RE`, `_HOSTNAME_RE`, the constant generic error message, `resolve_agent` exception paths, async offloading) is fully covered in this PR by:
- `tests/test_gui_logs_security.py`
- `tests/test_gui_resolve_agent.py`
- `tests/test_gui_async_offload.py`
- `tests/test_gui_openclaw_secrets.py`

The route-level (FastAPI `TestClient`) layer is still uncovered. A refactor of any handler that drops `asyncio.to_thread`, mis-maps `_LogsFetchError` to a non-503, or otherwise breaks the HTTP contract would slip through the current suite.

**Minimum tests required when this lands:**
- `GET /api/fleet/agents/{key}` with unknown key → 404
- `GET /api/fleet/agents/{key}` filtered by host alias → 200
- `GET /api/agents/{key}/logs` with control chars in `agent_type` → 503
- `POST /api/agents/{key}/start` when `start_agent` raises `LifecycleError` → 500
- `GET /api/agents/{key}/logs` when SSH fails → 503 (B8 contract)
- `GET /api/fleet` response does not contain a `gateway_auth` key for any agent (B1 contract)

## Suggestions

These are reviewer suggestions worth considering but not warnings against shipping.

- **S7** — `StrictHostKeyChecking=accept-new` plus a per-host `UserKnownHostsFile` populated at `clm host init` gives MITM protection while gracefully handling first-contact. Current implementation uses `StrictHostKeyChecking=yes` (safe but breaks on a brand-new host until the user's known_hosts is primed).
- **S9** — Call `_validate_address(hostname)` in `core/hosts.py:add_host` so hostname injection is closed at the data-entry point as well as the SSH-call site (defense in depth).
- **S11** — Replace the fixed 1.0 s browser-open delay in `cli/gui.py` with a readiness poll on `/api/health` every 100 ms until 200. Cleaner than a fixed delay; never opens against a non-serving URL.
- **S12** — Assert `console.error` is not called during the AbortError-suppression test in `sidebar.test.tsx` to catch error-boundary regressions.
- **S13** — `routes/agents.py` log fetch error path could use `_LOGS_FETCH_GENERIC_ERROR` constant directly in `HTTPException(detail=...)` (currently the value is identical but routed through the exception instance — eliminates a latent leakage path if a future call site adds diagnostic text).
- **S14** — Split SSH error HTTP status: `TimeoutExpired` → 504, other failures → 502; 503 implies "this server is overloaded," not "upstream dependency failed."
- **S15** — On port-in-use, print a Rich-formatted error with a `clm gui --port <other>` hint before re-raising.
- **S16** — Move `open_timer.cancel()` into a `finally` block (currently only runs on `BaseException`).
- **S17** — Add a `# patch target:` comment above the `_resolve_agent = resolve_agent` alias in `routes/agents.py` so test authors know the correct monkeypatch path.
- **S18** — Verify `proOptions={{ hideAttribution: true }}` matches our React Flow license entitlement.
- **S19** — Surface `missing_secrets` as a warning banner on the Agent Detail page (parity with the TUI).
- **S21** — Once B9 lands, expand its minimum test list with the items called out in `FOLLOWUPS.md` history.

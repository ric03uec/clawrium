# Issue #483 — Execution Log

Phase 3 of issue #478. Branch: `issue-483-agent-open-cli`. PR base:
`issue-482-hermes-dashboard` (stacked).

## What landed

- `src/clawrium/core/web_ui_tunnel.py` (new) — idempotent SSH local-port-forward manager. State at `~/.config/clawrium/tunnels/<agent_key>.json` (PID + local port + cmdline signature). Per-key threading lock around the check→spawn→write sequence. Cmdline-guarded SIGTERM/SIGKILL with a pre-SIGKILL re-check. Atomic `O_CREAT|O_EXCL` state write with mode 0o600. `atexit` hook closes process-owned tunnels.
- `src/clawrium/cli/agent.py` — new `@agent_app.command("open")` (`clm agent open <name>`) — hermes-only hard error, optional `--print` (machine-readable URL, bypasses Rich), local-agent shortcut, otherwise spawns tunnel, opens default browser, blocks on `threading.Event` waiting for SIGINT/SIGTERM, cleans up.
- `src/clawrium/gui/routes/fleet.py` — `GET /api/fleet/agents/{key}/web-ui` returns `{ available, local_url, reason }`. Per-agent last-access map; reaper helper `reap_idle_tunnels()`.
- `src/clawrium/gui/server.py` — FastAPI lifespan task that calls the reaper every 5 minutes (threshold 30 minutes); drains tunnels on shutdown via `asyncio.to_thread`.
- `gui/src/lib/types.ts`, `gui/src/lib/api.ts`, `gui/src/hooks/use-agent.ts`, `gui/src/components/agent-detail/agent-header.tsx` — `WebUIResponse` type, `getAgentWebUI()` client, `useAgentWebUI()` hook (hermes-only, 30s refetch on failure), "Open Agent UI" button (`aria-label`, `title`, disabled-state tooltip).
- `docs/agent-support/hermes.md` — new "Native dashboard" section.
- `AGENTS.md` — new "Hermes Native Dashboard" subsection.
- `tests/test_web_ui_tunnel.py`, `tests/test_cli_agent_open.py`, `tests/test_gui_routes_fleet.py` — 24 new tests.

## Verification

- `make test` — 2493 passed, 6 skipped.
- `make lint` — clean (`ruff`, ESLint).
- `npx tsc --noEmit` in `gui/` — clean.

## ATX review summary

Three iterations. Final: rating 3 (no blockers in PR code). Iteration 3 re-flagged
pre-existing repo-wide concerns (Rich-markup-escape sweep across
~24 unrelated exception handlers, `ActionResponse.error` missing on
lifecycle endpoints, `LifecycleError` detail forwarding) as blockers;
these are explicitly **out of scope** for this PR and recorded as
PR Callouts.

See `.itx/483/atx-session.json` for per-iteration cost / blockers /
fixes.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-05-22T15:45:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 483 --pr-base=issue-482-hermes-dashboard
```

**Output**: Phase 3 of #478 implemented and reviewed via 3 ATX rounds; PR opened against `issue-482-hermes-dashboard`.

</details>

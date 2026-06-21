# Implementation Plan — Issue #758

Make the agent detail page render its shell instantly and load each
section's data progressively, instead of blocking the entire route on a
single slow remote health probe.

## Diagnosis (the actual blocker)

Tracing the click → render path:

- `gui/src/app/agents/page.tsx:58-69` — `AgentDetailView` is gated
  entirely on `useAgent(agentKey).isLoading`. While that one query is
  in flight, the page shows three pulsing skeleton blocks. **No shell
  content, no header, no name** until `useAgent` resolves.
- `useAgent` → `GET /fleet/agents/:key` →
  `src/clawrium/gui/routes/fleet.py:211 agent_detail()` →
  `src/clawrium/cli/tui/data.py:428 get_agent_detail()`.
- Inside `get_agent_detail`, line 443:
  `check_claw_health_safe(agent_key, h)`. That's a remote SSH-driven
  health probe — seconds on a slow/unreachable host. Compounded by a
  synchronous `latest_supported_version` lookup right after
  (`fleet.py:238`).
- Everything *else* the page needs (`agent_name`, `agent_type`, `host`,
  `version`, `provider`, `gateway_url`, `device_id`) is read straight
  out of `hosts.json` and would resolve in milliseconds if the health
  probe weren't on the critical path.

The other tabs (skills, web-ui, memory, etc.) already own their own
hooks and don't gate the shell — they're not the bug.

## Solution

Split the slow probe off the critical path:

1. One backend endpoint for **static identity + persisted config**
   (cheap, local — reads `hosts.json` only).
2. A second endpoint for **runtime health** (slow, remote — runs
   `check_claw_health_safe` + `latest_supported_version`).
3. Two React Query hooks. The shell renders as soon as the static call
   resolves; status / uptime / version-badge show their own loading
   state.
4. Per-section failure isolation: a health-endpoint error surfaces an
   inline "Status unavailable, retry" in the header instead of blanking
   the page.

No new caching layer (explicitly out of scope per the issue).

## Files to modify

### Backend

- `src/clawrium/cli/tui/data.py`
  - Extract `get_agent_static(agent_key, host_identifier) -> AgentViewModel | None`
    returning the hosts.json-derived fields only — no
    `check_claw_health_safe`, no `latest_supported_version`. Runtime
    fields default to `None` / `UNKNOWN`.
  - Keep `get_agent_detail` as the runtime path (or rename to
    `get_agent_runtime` and have it return just the runtime delta).
    Simpler refactor: keep `get_agent_detail` as-is and add the static
    sibling.

- `src/clawrium/gui/routes/fleet.py`
  - `GET /fleet/agents/{agent_key}` switches to `get_agent_static`.
    Removes the `latest_supported_version` lookup from this handler.
  - Add `GET /fleet/agents/{agent_key}/health` returning
    `{ status, uptime, process_running, missing_secrets,
       onboarding_step, cpu_count, memory_total_mb, health_error,
       latest_supported_version }`. Calls `get_agent_detail` and
    `latest_supported_version` on the executor.

### Frontend

- `gui/src/lib/types.ts` — mark runtime fields optional on
  `AgentDetail` (`status?`, `uptime?`, `cpu_count?`, `memory_total_mb?`,
  `missing_secrets?`, `onboarding_step?`, `health_error?`,
  `process_running?`, `latest_supported_version?`). Optional add: a
  thin `AgentHealth` type for the new hook's payload.

- `gui/src/lib/api.ts` — add `getAgentHealth(key)` next to `getAgent`.

- `gui/src/hooks/use-agent.ts`
  - `useAgent` continues to call `/fleet/agents/:key` (now fast). Drop
    the 10s `refetchInterval` from `useAgent` — static data doesn't
    change between mutations.
  - Add `useAgentHealth(key)` with `refetchInterval: 10_000`.
  - `useAgentActions` `invalidate()` now invalidates both
    `["agent", key]` AND `["agent-health", key]` (plus the existing
    fleet/web-ui keys).

- `gui/src/app/agents/page.tsx`
  - Remove the page-level `isLoading` early-return that gates the shell.
  - Render shell (breadcrumb, `AgentHeader`, `AgentMetrics`, `TabNav`,
    active tab) as soon as `useAgent` resolves. The static call should
    be sub-100ms; keep a minimal skeleton only as a transitional state
    while it loads.
  - Error / not-found state stays the same.

- `gui/src/components/agent-detail/agent-header.tsx`
  - Name / type / host / OS icon from `useAgent` (static).
  - Status dot, uptime, action-button enable-state from
    `useAgentHealth(agent.agent_key)`. While pending: status shows
    "Checking…" placeholder, action buttons disabled with a tooltip.
    On error: inline "Status unavailable, retry" without killing the
    header chrome.

- `gui/src/components/agent-detail/agent-metrics.tsx` — runtime metrics
  (cpu / mem / uptime) consume `useAgentHealth`; skeleton row until
  resolved.

- `gui/src/components/agent-detail/overview-tab.tsx` — the Status and
  Uptime rows in the Agent Identity card read from `useAgentHealth`;
  Version/Name/Type/Host stay on the static payload. `VersionRow`
  consumes `latestSupportedVersion` from health (loading: hide the
  upgrade badge, never show a wrong one).

## Test strategy

### Backend unit (`tests/`)

- `tests/gui/routes/test_fleet.py` (or nearest existing file): mock
  `check_claw_health` to raise / sleep; assert
  `/fleet/agents/:key` returns the static fields fast and does not
  surface the probe error.
- New test: `/fleet/agents/:key/health` returns the runtime fields and
  surfaces the health probe via the existing `_HEALTH_ERROR_LABELS`
  sanitizer.
- `tests/cli/test_tui_data.py` (or nearest): `get_agent_static`
  populates identity but leaves runtime fields at defaults; `check_claw_health`
  is NOT called (mock + `assert_not_called()`).

### Frontend (vitest)

- Update existing `gui/src/components/agent-detail/overview-tab.test.tsx`
  for the hook split (Status / Uptime rows now sourced from
  `useAgentHealth`).
- New page-level test: with `useAgent` resolved and `useAgentHealth`
  pending, assert the shell renders (`agent_name` text,
  `TabNav`, OverviewTab Provider card visible) AND the status pill
  reads "Checking…".

### Manual

On an unreachable host (kevin or any stopped Pi): click into the
agent; chrome + name must appear within ~100ms; status pill stays
"Checking…" until the probe times out, then shows an inline retryable
error in the header only — the rest of the page (provider, skills,
tabs) remains interactive.

## Risks / things to watch

1. **Consumers of `agent.status`** — `agent-header.tsx` uses
   `agent.status === "running"` / `"stopped"` for button gating. After
   the split these read from `useAgentHealth`. Other consumers may
   exist; `grep` pass before implementation.
2. **Polling moves from `useAgent` to `useAgentHealth`.** Lifecycle
   mutations (`start` / `stop` / `restart`) must invalidate both
   queries so the freshly-flipped status shows up without waiting for
   the 10s tick.
3. **`key={agent.agent_key}` reset trick** (`page.tsx:98`) on
   `AgentHeader` still works — `agent.agent_key` is part of the static
   payload.
4. **Fleet list page** (`/agents` no key) also calls a fleet-health
   probe; that is a separate concern and a separate issue. Out of
   scope here.
5. **`AgentDetail` type churn** — making fields optional means every
   render site needs a `?? "—"` fallback or a guard. Keep changes
   mechanical and grep-driven.

## Subtasks

None — `complexity:s`, single concern (split one endpoint and its
consumers), ~6–8 files. One PR.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-21T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:plan-create 758. plan only no files creation yet
```

Followed by:

```prompt
ok. update plan and fix this in a worktree. commit the plan file in the
worktree only. create tree off of main. use atx cli for review
```

**Output**: `.itx/758/00_PLAN.md` (this file) — implementation plan
committed in worktree `clawrium-issue-758` on branch
`issue-758-agent-page-progressive`.

</details>

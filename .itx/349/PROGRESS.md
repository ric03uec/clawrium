# GUI Implementation Progress

## Step 1: Branch & Project Scaffold

### Expected Outcome

After this step:

1. **Git branch** `feat/gui` exists and is checked out
2. **CLI command** `clm gui` exists and prints a placeholder message ("GUI server coming soon on port 3100")
3. **Python package** `src/clawrium/gui/__init__.py` exists (empty for now)
4. **Python package** `src/clawrium/gui/server.py` exists (placeholder FastAPI app, not wired yet)
5. **Frontend project** `gui/` exists at repo root with:
   - `package.json` (Next.js 14, Tailwind CSS 3, TanStack Query, React Flow, Recharts)
   - `next.config.js` (static export config)
   - `tailwind.config.ts` (ocean teal theme colors)
   - `tsconfig.json`
   - `postcss.config.js`
   - `src/styles/globals.css` (design tokens as CSS custom properties)
   - `src/app/layout.tsx` (minimal root layout)
   - `src/app/page.tsx` (placeholder "Clawrium GUI" text)
6. **Verification**:
   - `clm gui` command appears in `clm --help`
   - `cd gui && npm install && npm run build` succeeds (static export to `gui/out/`)
   - `python -c "from clawrium.gui.server import app"` imports without error
   - Tests pass: `make test` still green

### Status: COMPLETE

### Verification Results
- `clm gui` shows in `clm --help` ✓
- `npm run build` produces `gui/out/index.html` ✓
- `from clawrium.gui.server import app` imports ✓
- `make test` → 1721 passed ✓
- Default port: 36000

---

## Step 2: Backend API (FastAPI)

### Expected Outcome

After this step:

1. **Route modules** under `src/clawrium/gui/routes/`:
   - `fleet.py` — Fleet overview, agent detail, lifecycle (start/stop/restart)
   - `topology.py` — Network graph data for topology view
   - `providers.py` — Provider CRUD (list, add, update, delete, types)
   - `settings.py` — App settings and version info
   - `usage.py` — Token usage tracking (summary, history, by-agent, clear)
2. **Service modules** under `src/clawrium/gui/services/`:
   - `pricing.py` — Model cost lookup table
   - `usage_tracker.py` — SQLite-backed usage store (~/.config/clawrium/usage.db)
3. **Server** wires all routers and mounts static frontend when built
4. **18 API endpoints** registered and responding
5. **Verification**:
   - All existing tests pass (1721)
   - Lint clean
   - Endpoints respond with correct data from live config

### Status: COMPLETE

### Verification Results
- Server imports cleanly: 23 routes total (18 API + 4 docs + 1 static) ✓
- `/api/health` → {"status":"ok"} ✓
- `/api/settings/version` → v26.5.1, Python 3.13.5, Linux x86_64 ✓
- `/api/providers/types` → 7 types ✓
- `/api/providers` → 2 providers ✓
- `/api/fleet` → 1 agent, 1 host, 1 running ✓
- `/api/fleet/topology` → 1 host, 1 connection ✓
- `/api/usage/summary` → zeroed (fresh db) ✓
- `/api/settings` → config paths ✓
- All 1721 tests pass ✓
- Lint/format clean ✓

---

## Step 3: Frontend Shell

### Expected Outcome

After this step:

1. **AppShell layout** with text-only sidebar (Dashboard, Topology, Providers, Settings)
2. **TanStack Query** provider wrapping the app
3. **API client** (`lib/api.ts`) with typed methods for all endpoints
4. **TypeScript types** (`lib/types.ts`) for all API responses
5. **Custom hooks** for data fetching (fleet, topology, providers, usage, agent)
6. **UI primitives**: Card, Button, StatusDot, Modal
7. **Route pages** (placeholder): `/`, `/topology`, `/providers`, `/settings`, `/agents`
8. **Design tokens** mapped to Tailwind utilities (bg-panel, text-muted, border-default, etc.)
9. **Build produces** 6 static pages with shared JS bundle

### Status: COMPLETE

### Verification Results
- `npm run build` → 6 routes compiled, all static ✓
- HTML title: "Clawrium" ✓
- Sidebar contains: Dashboard, Topology, Providers, Settings ✓
- API health responding alongside frontend ✓
- Agent detail uses query param (`/agents?key=...`) for static export compat ✓
- All 1721 tests pass ✓

### Files Created
- `gui/src/lib/api.ts` — Typed API client
- `gui/src/lib/types.ts` — TypeScript interfaces (Fleet, Agent, Topology, Provider, Usage, Settings)
- `gui/src/components/layout/sidebar.tsx` — Text sidebar with active state
- `gui/src/components/layout/app-shell.tsx` — Sidebar + content wrapper
- `gui/src/components/layout/page-header.tsx` — Title + description + actions
- `gui/src/components/layout/index.ts` — Barrel export
- `gui/src/components/ui/status-dot.tsx` — Status indicator dot
- `gui/src/components/ui/card.tsx` — Card container
- `gui/src/components/ui/button.tsx` — Button with variants
- `gui/src/components/ui/modal.tsx` — Dialog modal
- `gui/src/components/ui/index.ts` — Barrel export
- `gui/src/hooks/use-fleet.ts` — Fleet data hook
- `gui/src/hooks/use-topology.ts` — Topology data hook
- `gui/src/hooks/use-providers.ts` — Provider CRUD hooks
- `gui/src/hooks/use-usage.ts` — Usage data hooks
- `gui/src/hooks/use-agent.ts` — Agent detail + actions hooks
- `gui/src/hooks/index.ts` — Barrel export
- `gui/src/app/providers.tsx` — QueryClientProvider wrapper
- `gui/src/app/topology/page.tsx` — Topology placeholder
- `gui/src/app/providers/page.tsx` — Providers placeholder
- `gui/src/app/settings/page.tsx` — Settings placeholder
- `gui/src/app/agents/page.tsx` — Agent detail (query param based)

---

## Step 4: Dashboard Page

### Expected Outcome

After this step:

1. **MetricsRow** — 5 metric cards (Total Agents, Running, Providers, Tokens/24h, Est. Cost/24h)
2. **UsageChart** — Area chart showing 7-day token usage (Recharts)
3. **StatusChart** — Stacked bar showing agent status distribution with legend
4. **AgentTable** — Fleet agents table with status dots, click navigates to agent detail
5. **Layout** — 2-column grid (chart wider, status narrower) + full-width table below
6. All components fetch live data from existing hooks

### Status: COMPLETE

### Verification Results
- `npx tsc --noEmit` → no type errors ✓
- `npm run build` → 8 static pages, dashboard 108KB first load ✓
- HTML serves at root with `<title>Clawrium</title>` ✓
- `/api/fleet` → live data (1 agent, 1 host, 1 running) ✓
- `/api/usage/summary?days=1` → responds correctly ✓
- "Dashboard" text in rendered HTML ✓
- All 1721 tests pass ✓

### Files Created
- `gui/src/components/dashboard/metric-card.tsx` — Single metric card
- `gui/src/components/dashboard/metrics-row.tsx` — Row of 5 metrics (uses fleet, providers, usage hooks)
- `gui/src/components/dashboard/usage-chart.tsx` — 7-day area chart (Recharts)
- `gui/src/components/dashboard/status-chart.tsx` — Stacked bar + legend
- `gui/src/components/dashboard/agent-table.tsx` — Fleet table with navigation
- `gui/src/components/dashboard/index.ts` — Barrel export
- `gui/src/app/page.tsx` — Updated to compose all dashboard components

---

## Step 5: Topology Page

### Expected Outcome

After this step:

1. **TopologyCanvas** — React Flow canvas with custom nodes and edges
2. **ControlNode** — Custom node representing the local clm control machine
3. **HostNode** — Custom node with host header (clickable) + nested agent cards (clickable)
4. **TopologyLegend** — Status color legend + SSH line indicator
5. **AgentInfoModal** — Read-only modal showing agent details with [View Details →] and [Cancel]
6. **HostInfoModal** — Read-only modal showing host details with [Cancel] only
7. **Summary badge** — Top-right overlay showing Hosts/Agents/Running counts
8. **SPA routing** fixed — FastAPI serves .html files for extension-less paths

### Status: COMPLETE

### Verification Results
- `npx tsc --noEmit` → no type errors ✓
- `npm run build` → 8 pages, topology 165KB first load (includes React Flow) ✓
- Topology page renders at `/topology` (SPA routing fixed) ✓
- Control node: "clm CLI" / "Control Machine" ✓
- SSH edge: animated dashed line with "SSH" label ✓
- Host node: "clawdmin" (xclm@192.168.20.44) with nested agent card ✓
- Agent card: "vand" hermes · zai.glm-5 with running status dot ✓
- Agent click → modal with all fields (Status, Type, Host, Model, Version, Uptime, Provider, Provider Type) ✓
- Host click → modal with (Hostname, User, SSH Key, Addresses, Agents list) ✓
- Zoom/Fit controls rendered ✓
- Legend: Running, Degraded, Stopped, Provisioning + SSH connection line ✓
- Summary badge: Hosts: 1, Agents: 1, Running: 1 ✓
- Zero console errors ✓
- All 1721 tests pass ✓

### Files Created/Modified
- `gui/src/lib/types.ts` — Updated TopologyResponse types to match actual API
- `gui/src/components/topology/control-node.tsx` — Control machine node (React Flow custom node)
- `gui/src/components/topology/host-node.tsx` — Host node with nested agent cards
- `gui/src/components/topology/topology-canvas.tsx` — Main React Flow canvas
- `gui/src/components/topology/topology-legend.tsx` — Status color legend
- `gui/src/components/topology/agent-info-modal.tsx` — Agent read-only modal
- `gui/src/components/topology/host-info-modal.tsx` — Host read-only modal
- `gui/src/components/topology/index.ts` — Barrel export
- `gui/src/app/topology/page.tsx` — Updated with full topology view
- `gui/next.config.js` — Kept without trailingSlash (routing handled by backend)
- `src/clawrium/gui/server.py` — Rewrote frontend serving with SPA routing (path.html lookup)

## Step 6: Agent Detail Page

### Status: COMPLETE

### Verification Results

- TypeScript: zero errors (`npx tsc --noEmit`)
- Build: 8 pages, agents route 105KB first load
- Browser: all 5 tabs render correctly with live data
- Console: zero errors
- Tests: 1721 passed
- Backend: 6 new routes registered via agents.py

### What Was Built

**Backend (`src/clawrium/gui/routes/agents.py`):**
- `GET /api/agents/{key}/memory` — List memory files (SSH via ansible)
- `GET /api/agents/{key}/memory/{filename}` — Read memory file content
- `PUT /api/agents/{key}/memory/{filename}` — Write memory file content
- `POST /api/agents/{key}/chat` — SSE streaming chat proxy (hermes/openclaw)
- `GET /api/agents/{key}/chat/info` — Chat capability check
- `GET /api/agents/{key}/logs` — Fetch journalctl logs via SSH

**Frontend components (`gui/src/components/agent-detail/`):**
- `agent-header.tsx` — Status dot + name + metadata + Start/Restart/Stop buttons
- `agent-metrics.tsx` — 4-col metrics row (Uptime, Status, Tokens, Cost)
- `tab-nav.tsx` — 5-tab navigation (Chat, Configuration, Skills & Tools, Memory, Logs)
- `chat-tab.tsx` — Chat UI with message bubbles, SSE streaming, loading state
- `config-tab.tsx` — Provider/Gateway/Channels/Status info cards
- `skills-tab.tsx` — Placeholder with CLI reference
- `memory-tab.tsx` — File list + content viewer + editor with save
- `logs-tab.tsx` — journalctl viewer with filter, line count, priority colors
- `index.ts` — Barrel export

**Updated files:**
- `gui/src/lib/types.ts` — Added MemoryInfo, MemoryFile, MemoryFileContent, ChatInfo, ChatMessage, LogEntry, LogsResponse
- `gui/src/lib/api.ts` — Added getMemoryFiles, getMemoryFile, updateMemoryFile, getChatInfo, sendChatMessage (SSE), getAgentLogs
- `gui/src/app/agents/page.tsx` — Full page with Suspense, breadcrumb, header, metrics, tabs
- `gui/src/components/ui/status-dot.tsx` — Added "lg" size variant
- `src/clawrium/gui/server.py` — Registered agents router

---

## Step 7: Providers Page

### Status: COMPLETE

### Verification Results
- TypeScript: zero errors
- Build: 8 pages, providers route 113KB first load
- Browser: 2 provider cards (OR/BR badges), Model Catalog table, Add/Edit modals
- Console: zero errors

### What Was Built

**Backend (`src/clawrium/gui/routes/providers.py`):**
- `GET /api/providers/catalog?provider=&search=&limit=100` — Model catalog endpoint with fuzzy search

**Frontend components (`gui/src/components/providers/`):**
- `provider-card.tsx` — Card with type badge, model, endpoint, key status, used-by agents
- `add-provider-modal.tsx` — Form: name, type dropdown, model dropdown, API key, endpoint
- `edit-provider-modal.tsx` — Edit: model, endpoint, API key (type read-only)
- `model-catalog.tsx` — Filterable/searchable table of all available models
- `index.ts` — Barrel export

**Updated files:**
- `gui/src/lib/types.ts` — Added ProviderTypeInfo, ProviderTypesMap, CatalogModel
- `gui/src/lib/api.ts` — Added getModelCatalog, fixed return types
- `gui/src/hooks/use-providers.ts` — Added useModelCatalog hook
- `gui/src/app/providers/page.tsx` — Full page with CRUD modals

---

## Step 8: Settings Page

### Status: COMPLETE

### Verification Results
- TypeScript: zero errors
- Build: 8 pages, settings route 112KB first load
- Browser: all 4 cards render (About, Token Tracking, GUI Preferences, Danger Zone)
- Modals: Clear Usage Data and Reset All Configuration both work
- Console: zero errors
- Tests: 1496 passed (non-SSH tests)
- Lint: clean

### What Was Built

**Backend:**
- `src/clawrium/gui/routes/settings.py` — Added usage_db path to settings response
- `src/clawrium/gui/routes/usage.py` — Added `GET /api/usage/export` (CSV download)
- `src/clawrium/gui/services/usage_tracker.py` — Added `export_all()` and `get_db_path()` methods

**Frontend components (`gui/src/components/settings/`):**
- `about-card.tsx` — Version, Config Dir, Python, Platform
- `token-tracking-card.tsx` — Status, Storage path, Export CSV, Clear Usage Data + confirm modal
- `gui-preferences-card.tsx` — Port, Auto-open, Refresh Rate (read-only, CLI-configured)
- `danger-zone-card.tsx` — Reset All Configuration + confirm modal with warnings
- `index.ts` — Barrel export

**Updated files:**
- `gui/src/lib/types.ts` — Added usage_db to Settings, arch to VersionInfo
- `gui/src/lib/api.ts` — Added clearUsage, exportUsageCsv methods
- `gui/src/hooks/use-settings.ts` — NEW: useSettings, useVersion, useClearUsage hooks
- `gui/src/hooks/index.ts` — Added settings hook exports
- `gui/src/app/settings/page.tsx` — Full settings page with all 4 cards

---

## Step 9: Integration & Build

### Status: COMPLETE

### Verification Results
- Full build: 8 static pages, zero TypeScript errors
- All API routes: 28 registered (27 API + 1 catch-all)
- E2E navigation: Dashboard → Topology → Providers → Settings → Agent Detail all render
- Console: zero errors on all pages
- Tests: 1496 passed
- Lint/Format: clean

### Summary

The complete GUI system is operational:
- `clm gui --port 36000 --no-open` starts FastAPI + serves static Next.js frontend
- 5 screens: Dashboard, Topology, Providers, Settings, Agent Detail (5 tabs)
- Real-time data from live Clawrium configuration
- Token tracking with SQLite, CSV export
- Provider CRUD (Add/Edit/Remove) + Model Catalog
- Network topology with React Flow
- Agent chat (SSE streaming), memory editor, log viewer

# Issue #373 — Implementation Plan

GUI rebrand + topology improvements + integrations page. Five UX deliverables shipped together.

## Source

Implementation plan authored by @ric03uec in issue #373 (see comment IC_kwDORps9Hc8AAAABCmJHnQ).
See https://github.com/ric03uec/clawrium/issues/373 for the canonical spec, wireframes, and acceptance criteria.

## Phases

### Phase 1 — Sidebar branding
**Files:** `gui/src/components/layout/sidebar.tsx`, `gui/src/components/layout/sidebar.test.tsx`

- Keep flex row (logo + wordmark side-by-side).
- Logo `h-7 w-7` → `h-10 w-10`.
- Wordmark `CLM` → `Clawrium` (keep `text-lg font-semibold text-primary`).
- Add nav item `{ label: "Integrations", href: "/integrations" }` between Providers and Settings.

### Phase 2 — Topology: prominent host, agents as columns
**Files:** `gui/src/components/topology/host-node.tsx`, `gui/src/components/topology/topology-graph.ts`, related tests.

- Flip layout: agents in horizontal flex row at top; host header (alias + `user@hostname`) at bottom strip.
- Each agent: fixed-width column card with status dot, name, type, model.
- Each agent's `Handle type="source" position={Position.Bottom} id={agent.agent_key}` at the column's bottom edge.
- Host header keeps `onHostClick` button behaviour.
- `topology-graph.ts`: per-host node width = `AGENT_COL_WIDTH × agents.length`, no cap. Cumulative-width layout (no fixed `HOST_SPACING`). Edges keep `sourceHandle: agentKey`. Edge label includes model name (small, low opacity).

### Phase 3 — Topology hardware badges

**Backend:**
- `src/clawrium/core/hardware.py`: extend `HardwareInfo` with `product_name: str | None`, `system_vendor: str | None`. `extract_hardware_from_facts` reads `ansible_product_name`, `ansible_system_vendor` (lowercase normalize `system_vendor`).
- `src/clawrium/gui/routes/topology.py`: add `hardware` block to host dict (`architecture`, `cores`, `memtotal_mb`, `gpu`, `product_name`, `system_vendor`).
- Tests: extend `tests/test_hardware.py`; extend `tests/test_gui_topology_providers.py` (or add a new test) to assert host dict carries hardware.

**Frontend:**
- `gui/src/lib/types.ts`: `HostHardware`, attach to `TopologyHost`.
- New `gui/src/components/icons/{nvidia,amd,intel}.tsx` — inline SVG marks (~14px height).
- `host-node.tsx`: render badges in host strip:
  - architecture text badge when `architecture` present and not `"unknown"`
  - GPU badge: vendor logo + text per `vendor` (`nvidia`/`amd`/`intel`/`unknown` → generic GPU)
  - `gpu.present === false` → render nothing
  - `system_vendor === "nvidia"` (regardless of GPU detection) → NVIDIA mark + `product_name` sub-line
  - `product_name` known but `system_vendor !== "nvidia"` → show `product_name` sub-line, no logo
  - No `hardware` field at all → render nothing, no error

### Phase 4 — Integrations backend
**Files:** new `src/clawrium/gui/routes/integrations.py`; edit `src/clawrium/gui/server.py`; new `tests/test_gui_integrations.py`.

| Endpoint | Maps to |
|----------|---------|
| `GET /api/integrations` | `load_integrations()` (mask credentials) |
| `GET /api/integrations/types` | `INTEGRATION_TYPES` |
| `GET /api/integrations/{name}` | `get_integration(name)` + `find_agents_using_integration(name)` |
| `POST /api/integrations` | `add_integration(...)`, then `set_integration_credential(...)` per key |
| `PATCH /api/integrations/{name}/credentials` | `set_integration_credential` per key |
| `DELETE /api/integrations/{name}` | `remove_integration(name)`; 409 on `IntegrationInUseError` with `agents_using` |

Error mappings:
- `InvalidIntegrationTypeError`, `InvalidIntegrationNameError`, `DuplicateIntegrationError` → 400
- Not found → 404
- `IntegrationInUseError` → 409
- `IntegrationsFileCorruptedError` → 500 with clear message

### Phase 5 — Integrations frontend

**New files:**
- `gui/src/app/integrations/page.tsx`
- `gui/src/components/integrations/integration-card.tsx`
- `gui/src/components/integrations/add-integration-modal.tsx`
- `gui/src/components/integrations/edit-credentials-modal.tsx`
- `gui/src/components/integrations/index.ts`
- `gui/src/hooks/use-integrations.ts`

**Edits:**
- `gui/src/lib/types.ts` — add `Integration`, `IntegrationType`, `IntegrationCredentialDef`, `IntegrationDetail`.
- `gui/src/lib/api.ts` — CRUD methods.
- `gui/src/hooks/index.ts` — re-export new hooks.

**Dynamic credential field rules:**
- Password input when key matches `/token|key|secret|password|api/i`, text otherwise.
- Honor `required` flag from `IntegrationCredentialDef`.

**Empty state copy:**
> No integrations configured. Use `clm integration add <name> --type <type>` or click **Add Integration** to connect GitHub, GitLab, Atlassian, Linear, or Notion.

## Tests

Per phase above plus:
- `host-node.test.tsx`: new layout, agent handle presence, architecture/GPU badges, NVIDIA + `product_name` sub-line, missing-hardware no-render.
- `topology-graph.test.ts`: variable-width host layout, agent→provider edges originate from `sourceHandle: agentKey`.
- New component tests for `integration-card`, `add-integration-modal`, `edit-credentials-modal`.

## Verification

- `make test` (Python)
- `make lint`
- GUI tests via gui-side test runner (inspect `gui/package.json`)

## Out of scope (per issue)

- Fast initial metric counts on the Dashboard.
- Per-agent integration assignment UI.
- New integration types beyond `INTEGRATION_TYPES`.
- OAuth flows.

## Review

ATX enabled per `.claude/itx-config.json`. Iterate until Rating > 3/5 with no blockers per AGENTS.md `commit-format-atx` / `pr-format-atx`.

## Decisions

- **One PR for all 5 phases** ("shipped together" per issue summary). Confirmed by user 2026-05-16.
- **GUI + Python tests both gated.** Confirmed by user 2026-05-16.
- **Worktree:** `/home/devashish/workspace/ric03uec/clawrium-issue-373/`, branch `issue-373-gui-ux-rebrand-topology-integrations`.

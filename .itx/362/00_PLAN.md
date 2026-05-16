# Issue #362 — Plan

**Title**: User can see which provider each agent uses on the topology map
**URL**: https://github.com/ric03uec/clawrium/issues/362

**Customer outcome:** User can see which provider each agent uses on the topology map.

## Overview

The topology view today renders a `Control → Host(→ nested agents)` graph. Provider information already exists on each `TopologyAgent` (`provider`, `provider_type`) but is only surfaced inside the agent-info modal — never as a visual node/edge on the canvas.

This change introduces a **Provider** node type, places a row of provider nodes below the host row, and draws edges from each agent row to its configured provider. Providers are deduplicated by `(provider_name, provider_type, endpoint)` so a shared Ollama host fans in from multiple agents to a single node.

Agents are not first-class React Flow nodes today — they are rendered as buttons inside a `HostNode`. To draw an edge that visually originates from a specific agent row without rewriting the host card, we add **per-agent source `Handle`s** to `HostNode` and target them by `handle id = agent_key`.

## Files to Modify

### Backend

- `src/clawrium/gui/routes/topology.py` — include `provider_endpoint` in each agent dict so providers can be deduped by endpoint and the endpoint can be shown on the provider node.
- `src/clawrium/cli/tui/data.py` — if `provider_endpoint` is not already exposed by `get_fleet_data`, plumb it through alongside `provider`/`provider_type` from `provider_cfg.get("endpoint")` (see lines 134–138 and 269–273). Verify before adding.

### Frontend types

- `gui/src/lib/types.ts` — add `provider_endpoint: string | null` to `TopologyAgent`.

### Frontend topology UI

- `gui/src/components/topology/provider-node.tsx` *(new)* — visually distinct card (different border / icon glyph per `provider_type`: Ollama / OpenCode / Cloud AI / unknown). Top `Handle type="target"`. Displays type label, name, and truncated endpoint when set.
- `gui/src/components/topology/host-node.tsx` — add a per-agent right-side source `Handle` with `id={agent.agent_key}` on each agent row. Keep the existing top target handle for SSH edges.
- `gui/src/components/topology/topology-canvas.tsx` — compute deduped provider list from `data.hosts[].agents[]` using key `${type}::${name}::${endpoint ?? ""}`. Add an `unconfigured` synthetic provider node only if at least one agent has no provider, styled muted/dashed. Lay providers out in a row at `y ≈ 420`. For each agent, push an edge: `source = host-${hostname}`, `sourceHandle = agent.agent_key`, `target = provider-${providerKey}`. Register `provider` in `nodeTypes`.
- `gui/src/components/topology/topology-legend.tsx` — add a "Provider" swatch row and a solid-line "Agent → Provider" entry beneath the SSH line.

### Tests

- `gui/src/components/topology/topology-graph.ts` *(new)* + `.test.ts` — extract pure layout logic `computeTopology(data) → { nodes, edges }` from canvas so it is unit-testable without rendering React Flow.
  - Two agents on different hosts sharing one provider → one provider node, two edges.
  - Two agents sharing a provider *name* but different endpoints → two provider nodes.
  - Agent with no provider → one `unconfigured` node, edge points to it.
  - All currently supported agent types (`zeroclaw`, `openclaw`, `nemoclaw`) appear with correct edges.
- `tests/...test_topology.py` (find existing route test home with `grep`) — `provider_endpoint` is present when configured, `null` otherwise.

## Implementation Steps

1. **Backend**: confirm `provider_endpoint` source in `cli/tui/data.py`; add it to the agent row and include it in the topology route response.
2. **Types**: extend `TopologyAgent` with `provider_endpoint`.
3. **Extract layout logic** from `topology-canvas.tsx` into a pure `computeTopology(data)` function for testability.
4. **Add `ProviderNode` component** with `provider_type` glyph/styling.
5. **Update `HostNode`** to expose per-agent source handles keyed by `agent_key`.
6. **Update `TopologyCanvas`**: dedupe providers, position them in a row below hosts, render agent→provider edges, register the new node type.
7. **Update legend** to document the new visual elements.
8. **Tests**: unit test `computeTopology`; backend test for `provider_endpoint` field.
9. **Manual verify**: `cd gui && npm run dev`, open `/topology` with a fleet containing mixed providers (one shared Ollama, one Cloud AI, one unconfigured agent). Confirm acceptance criteria visually.

## Test Strategy

- `make test` and `make lint` for the Python side.
- `cd gui && npm test` (vitest) covers `computeTopology`.
- Manual smoke via `clm gui` against a fleet with at least two agents sharing a provider and one agent without a provider.
- Type check via the project's existing `tsc`/lint step (confirm exact command from `gui/package.json`).

## Risks & Open Questions

- **Per-agent handles**: React Flow handles must exist at render time for edges to connect. Edges referencing `sourceHandle = <agent_key>` will silently fail to render if the handle is missing — verify visually after wiring.
- **Layout under load**: Many agents × many shared providers can produce edge crossings. Initial implementation uses a simple centered row; if tangled in practice, consider `dagre` or grouping providers by type. Out of scope here.
- **`provider_endpoint` plumbing**: If the data path doesn't currently surface endpoint, the backend change is the largest unknown. The agent config already has `provider_cfg.get("endpoint")` available; it just isn't returned today.
- **Provider name vs. type**: The modal shows both `provider` (name) and `provider_type`. The acceptance criterion specifies the *type* display, so always render the type label, with the name as a sub-line when set.

## Subtasks

None — single task execution. All changes are within the topology view's vertical slice (one backend route + the topology components) and are tightly coupled by the same data contract.

---

<details>
<summary>Prompt Log</summary>

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-15
**Model**: claude-opus-4-7

```prompt
Add a new issue. This is a feature for the UI dashboard. In the UI, also show — or in the UI map / topology map — also show the providers. So if agents are connected to OpenCode or local Ollama or Cloud AI or something else, that should also be shown as a connection in the UI so that users can visualize which providers are being used by their respective agents.

Customer outcome (selected): See which provider each agent uses on the topology map.
```

</details>

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-05-15
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 362
```

</details>

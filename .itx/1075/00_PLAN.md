# Issue #1075 — GUI design-system completion plan

## Original maintainer outcome

Issue #1075 requires Clawrium's GUI to adopt a CSS-grid shell with a 248 px
sidebar and aligned 72 px brand/header regions, use a copied-once set of i7n/ui
design-system primitives pinned to commit
`6fa5f42a9892c15e4ef41bee9e67dd5826d1ae7f`, and expose the approved primary
navigation hierarchy:

- Main: Dashboard, Agents, Hosts
- Configuration: Providers, Integrations, MCP servers
- Footer: Settings, GitHub, collapse/expand, version

The MCP route is a no-CRUD follow-up placeholder. Surviving pages must remain
reachable during the transition. Fleet inventories should converge on the one
`DataTable` primitive. The issue also records later D-step outcomes for real
Hosts content and resource descriptions/context injection; those backend/D7
outcomes were not silently added to this GUI completion branch.

## Delivery strategy

1. Copy and adapt the exact authorized design-system snapshot locally without
   adding an i7n package dependency.
2. Activate its tokens and shell structure while retaining existing routes and
   behavior.
3. Migrate shared headers, controls, status, metrics, tabs, and accessibility
   contracts.
4. Standardize Agents, Providers, Model Catalog, and Integrations inventories on
   `DataTable`, preserving all existing actions and states.
5. Correct navigation to the issue-approved hierarchy while keeping Skills and
   Topology as explicitly transitional links.
6. Add static migration enforcement, production-export browser acceptance,
   deterministic evidence, CI wiring, and final review hardening.

## Acceptance and risk controls

- Preserve upstream attribution, source headers, pinned SHA, and private-source
  ownership; assert no new license or broader redistribution right.
- Preserve existing backend/API contracts and mutation payloads.
- Require unit, lint, production build, Chromium acceptance, Python suite, and
  whitespace validation.
- Do not modify unrelated `.itx/1033`, `.itx/1049`, or `.itx/1069` artifacts.

## Planning Prompt Log

**Stage**: plan
**Skill**: direct execution (no skill invoked)
**Timestamp**: 2026-11-26T01:32:30Z
**Model**: gpt-5.6-sol

```prompt
the latest merge pr did not implement the design system :( figure out whats missing and give me aplan to fix it.check the original issue for the expected outcomes
```

**Output**: Recorded the original #1075 outcomes, bounded scope, six-phase delivery strategy, and validation gates.

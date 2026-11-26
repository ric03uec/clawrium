# Issue #1075 — execution scaffold

## Phase 1 — copied design-system foundation

**Work:** Copy the exact pinned primitives/assets, preserve tracking/source
contracts, adapt React 18/Next 14/Tailwind 3 compatibility, activate scoped
tokens, and document provenance.

**Validation:** focused foundation tests, GUI unit suite, lint, build, and diff
check.

## Phase 2 — shell activation

**Work:** Introduce the grid app shell, aligned brand/header/page/footer regions,
grid backdrop, and responsive sidebar without changing backend APIs.

**Validation:** layout/app-shell tests plus full GUI unit, lint, and build gates.

## Phase 3 — shared component migration and accessibility

**Work:** Migrate page headers, controls, status surfaces, metrics, modal behavior,
and tabs; preserve tracking IDs and production behavior.

**Validation:** focused component/page tests, keyboard and ARIA assertions, full
GUI unit, lint, and build gates.

## Phase 4 — inventory standardization

**Work:** Migrate Agents (4A), Providers/Model Catalog (4B), and Integrations
(4C) to `DataTable`; preserve loading, empty, search, paging, details, mutation,
and error states. Remove obsolete card implementations when unused.

**Validation:** table-specific tests, static no-raw-table guard, full GUI unit,
lint, build, and diff checks. Recorded checkpoints included 401 tests after 4A,
407 after 4B, and 404 after Phase 4 closure as the concurrent test tree evolved.

## Phase 5 — navigation correction

**Work:** Match the exact approved primary hierarchy, retain MCP and Hosts
follow-up pages, remove unapproved primary entries/dead coming-soon code, and
leave Skills/Topology addressable only by direct route, outside the sidebar.

**Validation:** sidebar order/active-state/collapse/focus/version tests, full GUI
unit, lint, build, and diff checks.

## Phase 6 — enforcement and browser evidence

**Work:** Add migration contracts, Chromium acceptance against the static
production export, deterministic API fixtures, evidence screenshots/metadata,
and bounded CI enforcement.

**Validation:** 397 GUI tests, 7 Chromium tests, 5,694 Python tests (2 skipped),
GUI/Python lint, build, and diff checks passed in the original phase run.

## Final review passes

- **Pass A:** stable table identities, real link/button actions, ARIA tab
  keyboard behavior, AA foreground tokens, skip link, mobile sidebar reachability,
  canonical Claude logo mapping, obsolete provider-card removal, and app-footer
  version restoration. Independently validated with 400 GUI tests, lint, build,
  and Chromium evidence.
- **Pass B:** export-server security/error hardening and focused Node tests;
  fresh/local versus already-built/CI e2e scripts; AST-aware migration checks;
  required ITX artifacts; provenance authorization wording; final evidence and
  metadata regeneration.

## Review transport

Repository review is enabled. The ATX MCP transport was unavailable in the
worker harness. The required CLI fallback was checked, but `atx server status`
reported `Running: false`; manual/independent review therefore remained the
active gate. This is an unavailable transport record, not a successful ATX
review.

## Scaffold Prompt Log

**Stage**: scaffold
**Skill**: direct execution (no skill invoked)
**Timestamp**: 2026-11-26T01:32:30Z
**Model**: gpt-5.6-sol

```prompt
do all phases. validate after each phase. usesubagets as muchas possible to keep context here clean and to drive this successfully without losing original outcomes. all changes in a branch. go
```

**Output**: Documented phased work, validation checkpoints, review passes, and ATX fallback state.

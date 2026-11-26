# Issue #1075 — execution record

## Implemented outcome

The branch completes the local design-system activation, accessible app shell,
approved navigation, shared inventory tables, browser acceptance, and review
hardening described by the plan/scaffold. It does not widen into the later
backend description/context-injection work recorded in the parent issue.

## Verified review findings and resolutions

- Added stable `DataTable` row IDs and replaced focusable row activation with
  named links/buttons.
- Implemented roving ARIA tabs and connected tabpanels.
- Added AA foreground tokens, skip navigation, reachable mobile collapse,
  official marks for all seven supported agent types, footer version, and
  removed dead ProviderCard code.
- Hardened the static export server against malformed URL escapes, traversal,
  untrusted Host input, symlink escape, and stat/read errors; added focused Node
  tests.
- Split e2e scripts into fresh local (`test:e2e`), already-built CI
  (`test:e2e:ci`), and fresh evidence (`test:e2e:evidence`) flows; documented
  Node 20+ and one-time Chromium installation.
- Replaced brittle migration source scans with TypeScript AST import/JSX checks,
  exact design-system exclusion, explicit expected PageHeader files, and
  AST-checked raw table/input contracts.
- Added `00_PLAN.md`, `01_SCAFFOLD.md`, and this execution log.
- Added a provenance NOTICE stating the exact private snapshot was explicitly
  required and authorized for this Clawrium change, while preserving i7n
  ownership/attribution and asserting neither a new license nor an npm
  dependency.
- Regenerated browser evidence and metadata after all fixes. Metadata describes
  the uncommitted working tree and does not claim a commit SHA.

## Review transport

ATX review is configured. MCP review was unavailable in the worker harness,
and the final parent review attempt failed because the Node Supervisor at
`127.0.0.1:30000` was not running. The CLI fallback also could not run because
`atx server status` reported `Running: false`. Pass A was independently
reviewed; Pass B and the official-logo correction were manually reviewed and
validated with focused and full test suites.

## Final validation

- `cd gui && npm test` — passed: 43 files, 406 tests.
- `cd gui && npm run lint` — passed with no warnings/errors.
- `cd gui && npm run test:export-server` — passed: 4 Node tests.
- `cd gui && npm run test:e2e` — built a fresh 12-page static export and passed
  all 7 Chromium tests.
- `cd gui && npm run test:e2e:evidence` — rebuilt, passed 7 Chromium tests, and
  regenerated the eight screenshots plus metadata.
- `make test` — passed: 5,694 Python tests, 2 skipped, and 406 GUI tests.
- `make lint` — Ruff and Next lint passed.
- `git diff --check` — passed.
- `git diff --name-only --cached` — empty; no staged files.

## Execution Prompt Log

**Stage**: execute
**Skill**: direct execution (no skill invoked)
**Timestamp**: 2026-11-26T01:32:30Z
**Model**: gpt-5.6-sol

```prompt
do all phases. validate after each phase. usesubagets as muchas possible to keep context here clean and to drive this successfully without losing original outcomes. all changes in a branch. go
```

**Output**: Implemented all six phases, resolved verified review findings, regenerated evidence, and recorded final validation without changing backend scope.

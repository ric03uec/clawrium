# Issue #491 — Execution Log

## Execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-22T22:35:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute https://github.com/ric03uec/clawrium/issues/491 in a worktree. use atx cli for review test with existing zeroclaw agent intalled on local
```

**Output**: Branch `issue-491-zeroclaw-open` in worktree
`~/workspace/ric03uec/clawrium-issue-491/` with the following changes:

- `src/clawrium/core/registry.py`: added `wildcard` to
  `_ALLOWED_WEB_UI_BINDS`; widened `WebUIFeatureConfig.bind` Literal.
- `src/clawrium/core/web_ui.py`: added `wildcard → 127.0.0.1` entry to
  `BIND_ADDRESS_MAP`; widened `ResolvedUI.bind` Literal; updated module
  docstring to describe both bind modes.
- `src/clawrium/platform/registry/zeroclaw/manifest.yaml`: added
  `features.web_ui` block (`enabled: true`, `bind: wildcard`,
  `default_port: 40000`, `port_field: gateway.port`).
- `src/clawrium/cli/agent.py`: dropped the `claw_type != "hermes"` gate
  in `clm agent open` and updated the docstring; resolver-None branch
  is now the only gate.
- `gui/src/hooks/use-agent.ts`: replaced the hermes-only `enabled`
  gate with an allowlist `WEB_UI_AGENT_TYPES = {hermes, zeroclaw}` and
  exported it so the render decision shares one source of truth with
  the fetch decision.
- `gui/src/hooks/index.ts`, `gui/src/components/agent-detail/agent-header.tsx`:
  re-exported and consumed the allowlist so the "Open Agent UI" button
  shows for zeroclaw too.
- `tests/test_web_ui_resolver.py`: flipped the previous
  `test_resolve_zeroclaw_returns_none` to assert zeroclaw resolves to
  its persisted `gateway.port`; added a `gateway.port`-missing fallback
  test and a `BIND_ADDRESS_MAP["wildcard"]` coverage test.
- `tests/test_registry.py`: flipped
  `test_zeroclaw_manifest_does_not_declare_web_ui` to assert the new
  manifest block.
- `tests/test_cli_agent_open.py`: renamed
  `test_open_rejects_non_hermes_agent` →
  `test_open_rejects_agent_without_web_ui_feature` and updated the
  expected error string.

### Verification

- `make test` — 2552 passed (`pytest`), 213 passed (`vitest`).
- `make lint` — ruff + eslint clean.
- Manual e2e against a live `clm`-managed zeroclaw on `wolf-i`:
  - `clm agent open clawrium-d01 --print` →
    `http://wolf.tailf7742d.ts.net:41429/` ✓
  - `clm agent open clawrium-d01` → tunnel established on local port
    39211; `curl http://127.0.0.1:39211/` returned `HTTP 200` (524 B);
    tunnel closed cleanly on Ctrl-C. ✓
  - Negative: `clm agent open wolf-i --print` (openclaw) →
    `Error: Agent 'wolf-i' does not declare a native web UI in its
    manifest.` ✓
  - Regression: `clm agent open espresso --print` (hermes) →
    `http://wolf.tailf7742d.ts.net:9119/` ✓

### ATX

Run via `atx review --worktree clawrium-issue-491 --format json
--timeout 10m`. Task `5c55522e-e8ac-4287-b0f4-18896b8bcd4e` was
created on project `30011` but the daemon poll timed out after 10m
without returning a rating. Session metadata persisted to
`.itx/491/atx-session.json`. Documented in PR Callouts as an
`[ENVIRONMENT]` note; the PR is opened anyway with the manual
verification evidence above.

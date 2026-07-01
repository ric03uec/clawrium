# Issue #834 — Execution Log

GitHub: https://github.com/ric03uec/clawrium/issues/834
Parent: #499 (Slack integration plan)
Branch: `issue-834-hermes-slack`
PR base: `main`

## Scope

Phase 1 (driver slice) of the Slack integration plan — hermes end-to-end:

- `slack-user` + `slack-cookie` in `INTEGRATION_TYPES`
- `_HERMES_SUPPORTED_INTEGRATIONS` extended
- Attach-time agent-type gate (B8)
- `_stub.py` exit-1 fix (B10)
- `hermes-config.canonical.yaml.j2` slack branch
- `configure.yaml` + `configure_macos.yaml` slack-mcp-server install
- GUI Slack card
- Tests (goldens, gate rejection, asset map, stub exit, integration e2e)
- CHANGELOG entry

## Key deviations from plan (captured as PR Callouts)

- **korotovsky asset shape**: v1.3.0 ships single Go binaries, not tarballs.
  No `unarchive` step needed — use `get_url` directly to
  `~/.local/bin/slack-mcp-server`. Plan assumed tarballs.
- **armv7l coverage gap**: v1.3.0 has **no armv7l asset** (linux amd64/arm64
  + darwin amd64/arm64 only). Plan called for 5-entry sha256_map; we ship
  4-entry map. armv7l is not a hermes target on wolf-i (maurice is amd64),
  and Phase 3 zeroclaw pre-checks armv7l support anyway. Documented in
  Callouts.
- **Real-host UAT deferred**: PR opened with tests green; maurice UAT
  captured as follow-up Callout per resilient chain policy.

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-07-01T23:20:02Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 834 --pr-base=main
Review-tool override: use the atx CLI. Persist state in .itx/834/atx-session.json
with transport: cli. Skip ATX and record a Callout if the CLI fails. Iteration
ceiling 3, then open PR with [ITX-STUCK] marker. Stage and commit
.itx/499/00_PLAN.md and 01_EXECUTION.md in the FIRST commit. Branch already
checked out.
```

**Output**: Phase 1 code + tests + CHANGELOG + PR against main.

# Issue #499 — Execution Scaffolding

GitHub: https://github.com/ric03uec/clawrium/issues/499

## Mode

Multi-phase (5 phases, strictly sequential per operator instruction #1 — agent-order).

## Ordering rationale

- Phase 1 introduces the attach gate (B8), `INTEGRATION_TYPES` entries, and `_stub.py` exit-1 fix (B10) that Phases 2 + 3 rely on for the "coming-soon" contract.
- Phase 2 factors the inline slack-mcp-server install (landed inline in Phase 1) into `core/playbook_resolver.py` extravars; Phase 3 depends on that resolver work.
- Phase 4 (docs) requires Phases 1–3 to describe what's shipped.
- Phase 5 (stub deletion) requires Phase 4 docs to redirect users before removal.

Lifecycle-core specialist noted phases 1–3 could parallelize technically; operator instruction #1 pins agent-order sequential.

## Phases

### Phase 1 — Hermes end-to-end (driver slice)

**Complexity**: complex (10+ files, cross-cutting foundation: attach gate, stub fix, `INTEGRATION_TYPES` additions).

**Entry Criteria**:
- Plan Revision 2 merged on main (bafee7e)
- korotovsky/slack-mcp-server latest release inspected via `gh api repos/korotovsky/slack-mcp-server/releases/latest` → 3 Linux + 2 Darwin assets present, SHA256 hashes recorded
- Slack workspace + test user token (xoxp) provisioned for UAT
- Branch `issue-499-hermes-slack` (or subtask-numbered equivalent) created from main

**Exit Criteria**:
- `slack-user` + `slack-cookie` entries in `INTEGRATION_TYPES` (`core/integrations.py`) with correct credential-key sets
- `_HERMES_SUPPORTED_INTEGRATIONS` (`core/render.py`) includes both types
- `agent/integration.py:attach()` **rejects** `attach <openclaw-agent|zeroclaw-agent> <slack-*>` at CLI time with `emit_error(exit_code=2)` (B8 gate)
- `_stub.py:echo_not_implemented()` exits 1 with redirect message pointing at `clawctl integration registry create` (B10)
- `mcp_slack_version` + `mcp_slack_sha256_map` (5 entries: linux x86_64/aarch64/armv7l, darwin arm64/amd64) declared at top of `hermes/playbooks/configure.yaml`
- `configure_macos.yaml` variant also installs slack-mcp-server (W11 — Slack is the first MCP on Darwin hermes)
- Rendered `.hermes/config.yaml` verified as mode 0600 (W6)
- GUI Slack card visible in Integrations tab; hermes attach row live; openclaw/zeroclaw rows show "coming soon"
- All tests green (unit + integration + arch matrix)
- Real-host UAT on maurice (wolf-i) documented in PR body
- `make lint && make test` green
- CHANGELOG.md `[Unreleased] ### Added` entry landed

**Dependencies**: None (foundation slice).

**Files Affected**:
- `src/clawrium/core/integrations.py`
- `src/clawrium/core/render.py`
- `src/clawrium/platform/registry/hermes/templates/hermes-config.canonical.yaml.j2`
- `src/clawrium/platform/registry/hermes/playbooks/configure.yaml` (+ `_macos`)
- `src/clawrium/cli/clawctl/agent/integration.py`
- `src/clawrium/cli/clawctl/_stub.py`
- `src/clawrium/gui/frontend/integrations.html`
- `src/clawrium/gui/routes/integrations.py`
- `tests/core/test_render.py`
- `tests/cli/clawctl/agent/test_integration_gate.py` (new)
- `tests/cli/clawctl/integration/test_slack.py` (new)
- `tests/platform/test_slack_asset_map.py` (new)
- `CHANGELOG.md`

---

### Phase 2 — Openclaw end-to-end

**Complexity**: complex (renderer signature change, playbook-resolver extravar extraction, macOS matrix).

**Entry Criteria**:
- Phase 1 merged on main
- Openclaw agent available on wolf-i for UAT
- Branch created from main

**Exit Criteria**:
- `_OPENCLAW_SUPPORTED_INTEGRATIONS` frozenset exists in `render.py` (create if missing) and includes both slack types
- `_render_openclaw_json()` at `render.py:1610` accepts an `integrations` parameter; emits `mcp.servers.slack` **only when** a slack-typed integration is attached (W10 conditional emit, zero diff for existing agents)
- `openclaw/playbooks/configure.yaml` still uses `ansible.builtin.copy` of `prerendered_openclaw_config_json` — **no Ansible deep-update introduced** (B1 invariant preserved)
- `core/playbook_resolver.py` computes `mcp_slack_asset_url`, `mcp_slack_asset_sha256`, `mcp_slack_dest`, `mcp_slack_group` per OS; hermes + openclaw playbooks consume these extravars (B9 fix)
- Phase 1's inline install refactored to consume the same extravars (retrospective in this phase)
- `configure_macos.yaml` variant covered (openclaw macOS is GA per #770)
- Byte-lock test proves zero diff for openclaw agents without slack attached
- Real-host UAT on wolf-i openclaw documented in PR body
- `make lint && make test` green
- GUI Slack card: openclaw attach row live; zeroclaw still "coming soon"
- CHANGELOG.md `[Unreleased] ### Added` entry landed

**Dependencies**: Phase 1.

**Files Affected**:
- `src/clawrium/core/render.py`
- `src/clawrium/core/playbook_resolver.py`
- `src/clawrium/platform/registry/openclaw/playbooks/configure.yaml` (+ `_macos`)
- `src/clawrium/platform/registry/hermes/playbooks/configure.yaml` (+ `_macos`) — refactor inline install
- `src/clawrium/gui/frontend/integrations.html`
- `tests/core/test_render.py`
- `CHANGELOG.md`

---

### Phase 3 — Zeroclaw end-to-end

**Complexity**: complex (TOML shape fix + gateway-bearer sync-order test + armv7l UAT precheck).

**Entry Criteria**:
- Phase 2 merged on main
- Precheck 1 (S7): `gh api repos/korotovsky/slack-mcp-server/releases/latest --jq '.assets[].name'` confirms an armv7 asset. If none, log the gap, plan wolf-i fallback UAT before starting.
- Precheck 2: verify kevin's outstanding zeroclaw bind bug does not block `clawctl agent sync`. If it does, drop to wolf-i UAT + open a tracking issue for armv7l coverage.
- Branch created from main

**Exit Criteria**:
- `_ZEROCLAW_SUPPORTED_INTEGRATIONS` includes both slack types
- `zeroclaw-config.toml.j2`: `servers = []` **removed** from `[mcp]` baseline (B2 TOML spec violation fix); `[[mcp.servers]]` array-of-tables emitted conditionally per attached slack integration; `enabled` flipped conditionally
- Byte-lock test proves zero-slack case renders byte-identical to pre-fix output
- `zeroclaw/playbooks/configure.yaml` consumes the same install extravars from `playbook_resolver.py` (Phase 2 pattern)
- Integration test asserts exactly one `gateway_token_rotated` event per successful sync (W2), AND `hosts.json.gateway.auth` untouched on simulated Slack-hydration failure (S9)
- Real-host UAT on kevin (armv7l) OR wolf-i fallback (with documented coverage gap) — either way documented in PR body with rationale
- `make lint && make test` green
- GUI Slack card: zeroclaw attach row live; all "coming soon" ribbons removed
- CHANGELOG.md `[Unreleased] ### Added` entry landed

**Dependencies**: Phase 2.

**Files Affected**:
- `src/clawrium/core/render.py`
- `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`
- `src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml`
- `src/clawrium/gui/frontend/integrations.html`
- `tests/core/test_render.py`
- `tests/…` — new test for gateway_token_rotated count + stale-bearer safety
- `CHANGELOG.md`

---

### Phase 4 — Docs

**Complexity**: simple (documentation-only, no code changes).

**Entry Criteria**:
- Phases 1–3 all merged on main
- Real-host UAT evidence collected in Phase 1/2/3 PR bodies

**Exit Criteria**:
- `docs/integrations/slack.md` (new) — token acquisition (xoxp and xoxc/xoxd flows), security warning for cookie mode, tool list, composite blast-radius note (S5), `--credential-stdin` recommendation (S6)
- `docs/agent-support/hermes.md` — Slack integration subsection
- `docs/agent-support/openclaw.md` — Slack integration subsection
- `docs/agent-support/zeroclaw.md` — Slack integration subsection
- `CHANGELOG.md`: docs entries under `[Unreleased] ### Documentation`; `_stub.py` exit-code shift documented under `### BREAKING` if any tooling depends on old exit-0 (low probability, still called out)
- `make lint` green (markdown lint)
- No real-host UAT (docs only)

**Dependencies**: Phases 1, 2, 3.

**Files Affected**:
- `docs/integrations/slack.md` (new)
- `docs/agent-support/{hermes,openclaw,zeroclaw}.md`
- `CHANGELOG.md`

---

### Phase 5 — Follow-up: successor MCP issue + stub deletion

**Complexity**: simple (one CLI group removal + one new tracking issue).

**Entry Criteria**:
- Phase 4 merged; docs published referencing `clawctl integration registry create --type slack-user` as canonical
- Follow-up GitHub issue opened for **generic MCP-server support** (arbitrary MCP servers, not just Slack) — successor to the removed stub group

**Exit Criteria**:
- `src/clawrium/cli/clawctl/mcp.py` deleted along with `mcp_app` wiring in the parent Typer surface
- `tests/cli/clawctl/mcp/test_placeholder.py` deleted
- If `mcp` was the only remaining stub group, prune `_stub.py` entirely; otherwise leave in place
- `clawctl mcp` returns Typer's default unknown-command message (exit 2), not stub's exit-1 — covered by test
- CHANGELOG.md `[Unreleased] ### BREAKING`: `clawctl mcp` group removed; migration = use `clawctl integration registry create --type slack-user|slack-cookie` for Slack; successor issue #N referenced for arbitrary MCP servers
- `make lint && make test` green
- No real-host UAT (CLI removal only; rejection path already covered by Phase 1)

**Dependencies**: Phases 1–4.

**Files Affected**:
- `src/clawrium/cli/clawctl/mcp.py` (deleted)
- Parent Typer wiring wherever `mcp_app` is registered
- `tests/cli/clawctl/mcp/test_placeholder.py` (deleted)
- `CHANGELOG.md`

## Cross-phase notes

- **Version + SHA256 pin drift (W7)**: Phases 1–3 all touch `mcp_slack_version` / `mcp_slack_sha256_map`. Recommend adding a CI assertion or single-source-of-truth Python constant imported into both `render.py` and `playbook_resolver.py` extravars in Phase 2.
- **Composite blast-radius defense-in-depth (S5)**: consider adding a `clawctl doctor`-level warning when both a Slack channel and a Slack integration are attached to the same agent. Not on critical path — Phase 5 or separate follow-up.
- **PR review**: every PR follows the ATX round + re-review cycle per `.claude/itx-config.json`. No PR opens without real-host UAT evidence in the body (Phases 4 + 5 exempt as docs-only / removal-only).

## Scaffolding

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-07-01T00:00:00Z
**Model**: claude-opus-4-7

```prompt
499. give me plan first, dont create any issue
[then, after review:]
ok. create issues for these with clear exit criteria, tsting guidlines and live testing scenarios.
```

**Output**: 5-phase execution scaffolding for #499 (hermes → openclaw → zeroclaw → docs → stub-deletion follow-up), strictly sequential per operator agent-order instruction. Each phase has entry/exit criteria + testing guidelines + live-testing scenarios. Subtask issues created and linked as children of #499.

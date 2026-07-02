# Issue #851 — Tech debt: harmonize zeroclaw slack install to runbook pattern

GitHub: https://github.com/ric03uec/clawrium/issues/851

## Implementation Plan

Replace zeroclaw's **inline slack-mcp-server install** (currently in `zeroclaw/playbooks/configure.yaml`) with the **sync-time runbook pattern** already used by hermes (Phase 1) and openclaw (Phase 2). Makes main's actual code match what main's Phase 3 CHANGELOG entry claims. #849's `issue-836-zeroclaw-slack` branch is the reference for file shapes but must NOT be merged (61 test failures against evolved `lifecycle.py`).

**Behavioral shift:** binary install moves from `configure` time to `sync` time. Mirrors hermes+openclaw behavior on main today. First `clawctl agent sync` after attach still installs the binary; `clawctl agent configure` alone no longer does. This is the intentional pattern per the "Integration Binary Install" section in AGENTS.md.

### Locked design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Helper shape | Structural mirror of `_openclaw_install_slack_mcp` in `lifecycle_canonical.py`. Signature: `(agent_name, hostname, host, inputs, *, on_event, timeout=180)`. Gated on `_ZEROCLAW_SLACK_TYPES` frozenset membership in `inputs.integrations`. | One-runbook-per-(agent_type, binary) resolver contract (AGENTS.md Rule 1). |
| macOS behavior | **Loud refusal** — raise `CanonicalSyncError` when `os_family == "darwin"`. Do NOT silently route to Linux runbook. | The `install_slack_mcp_macos.yaml` sibling is a deferred follow-up per #836 exit criteria. |
| Runbook file | Byte-parallel to `openclaw/playbooks/install_slack_mcp.yaml` (89 lines on main). Copy structure from #849's `zeroclaw/playbooks/install_slack_mcp.yaml`. | Preserves the pin-lockstep contract (`mcp_slack_version` must equal `_HERMES_MCP_SLACK_VERSION` in `render.py`). |
| Inline install removal | Delete the slack install block from `configure.yaml` + `slack_integration_assigned` var. | Two install paths for the same binary is the tech debt this issue closes. |
| Extravar cleanup | Only if `mcp_slack_extravars` zeroclaw branch becomes unreferenced after configure.yaml surgery. | Dead-code hygiene, conditional on grep result. |
| lifecycle.py refactor from #849 | **Out of scope.** Do NOT touch `lifecycle.py`'s render_zeroclaw exception narrowing. | Explicitly deferred per #851 body. Aborted rebase's 61 test failures came from that refactor. |

### Files touched

**New**
- `src/clawrium/platform/registry/zeroclaw/playbooks/install_slack_mcp.yaml` (~89 lines)
- `tests/core/test_lifecycle_zeroclaw_prerender.py` (~186 lines — adapted from openclaw prerender test template)

**Modified**
- `src/clawrium/core/lifecycle_canonical.py` — additive only: `_ZEROCLAW_SLACK_TYPES` + `_zeroclaw_install_slack_mcp` helper (~70 lines) + `if inputs.agent_type == "zeroclaw":` branch in `sync_agent_canonical`
- `src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml` — delete inline slack install tasks + `slack_integration_assigned` var
- `src/clawrium/core/playbook_resolver.py` — conditional zeroclaw extravar cleanup
- `tests/test_zeroclaw_slack_sync_order.py` — update assertions for helper-based path
- `tests/test_configure_claw.py` — remove configure-time-install assertions
- `CHANGELOG.md` — `[Unreleased] ### Changed` entry
- `AGENTS.md` — if "hermes and openclaw" phrasing needs updating to include zeroclaw

### Test strategy

**Unit**
- Byte-lock: zero-slack zeroclaw agents render `config.toml` byte-identical to pre-change output
- Helper gating: `_zeroclaw_install_slack_mcp` is a no-op when no slack integration is attached
- Helper darwin refusal: raises `CanonicalSyncError` with operator-friendly message on darwin
- Helper failure surfacing: mocked `_run_lifecycle_playbook` returning `(False, "err")` → helper raises `CanonicalSyncError`, sync short-circuits before restart

**Integration**
- Attach → sync → assert `install_slack_mcp.yaml` invoked via event stream capture
- Detach → sync → assert next sync does NOT invoke runbook (fast no-op gate works)
- Sync-order invariant: slack install failure → zero `gateway_token_rotated` events

**Real-host UAT** — blocking per `no_pr_without_real_host_uat`
- Target: wolf-i zeroclaw agent (Linux x86_64)
- Pre-existing zeroclaw with slack integration attached
- Verify: sync succeeds → sha256sum matches → chat still lists Slack channels → detach + sync no-op

### Rollback plan

Single-file rollback: restore inline install in `configure.yaml`, revert helper call site. Runbook + helper become dead code but harmless in place.

### Risks

- `test_configure_claw.py` may have assertions that inline install runs at configure time — needs updating
- `mcp_slack_extravars` may still be consumed by non-configure.yaml callers for zeroclaw — grep first
- `slack_integration_assigned` var may be referenced elsewhere in `configure.yaml` — verify before deletion
- AGENTS.md may need textual update if it lists runbook-pattern agents exhaustively

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-02T00:00:00Z
**Model**: claude-opus-4-7

```prompt
ok now plan 851 in a worktree (use same session as other sbutasks). use /itx-plan-create but dont create any files
```

**Output**: Plan for zeroclaw slack runbook harmonization. Uses openclaw runbook as byte-parallel template; helper is structural mirror of `_openclaw_install_slack_mcp` with darwin refusal added. #849's implementation is the file-shape reference; #849's lifecycle.py refactor is explicitly out of scope. Single PR — no subtask breakdown.

# Issue #835 — Execution Log

GitHub: https://github.com/ric03uec/clawrium/issues/835

Phase 2 of the #499 orchestrated chain. Depends on #834 (Phase 1 —
hermes) via stacked-PR chain: base branch is `issue-834-hermes-slack`.

## Execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-07-01T17:32:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 835 --pr-base=issue-834-hermes-slack.

This is Phase 2 of the #499 orchestrated chain. Your PR MUST target
issue-834-hermes-slack (not main). Include "Stacked on top of
issue-834-hermes-slack" in the PR body.

Review-tool override: use the atx CLI (`atx review request --prompt
"..."`) for all code review iterations. Do NOT use
mcp__atx__request_review. The repo config (.claude/itx-config.json)
has MCP review enabled but the orchestrator is overriding it for this
run. Persist review state in .itx/835/atx-session.json with transport:
cli. Follow the skill resilient chain: if atx CLI fails, skip ATX and
record a Callout — never block on ATX. Iteration ceiling 3, then open
PR with [ITX-STUCK] marker if unresolved blockers remain.

Branch is issue-835-openclaw-slack (already checked out). Do not
create a new branch.

Real-host UAT target for Phase 2 openclaw: wolf-i (per the plan).
```

**Output**: Openclaw Slack MCP integration end-to-end:

- `_OPENCLAW_SUPPORTED_INTEGRATIONS` extended to include `slack-user` /
  `slack-cookie` — attach gate at
  `cli/clawctl/agent/integration.py:attach` now accepts openclaw+slack.
- `_render_openclaw_json` takes new `slack_integrations`, `agent_name`,
  `home_root` parameters; emits `mcp.servers.<slug>` block conditionally.
  W10 byte-lock guaranteed via unit tests: openclaw agents without slack
  render byte-identical to pre-#835 output.
- `render_openclaw` takes `os_family` for per-OS binary path selection
  (`/home` vs `/Users`).
- `core/playbook_resolver.py` gains `_MCP_SLACK_VERSION` / arch maps /
  sha256 maps + `mcp_slack_extravars(os_family)` — single Python source
  of truth (B9 fix). Both hermes and openclaw configure playbooks (Linux
  + macOS) removed their inline `vars:` pins.
- `core/playbook_resolver.normalize_os_family(host)` — single seam for
  the `os_family` alias normalization (previously triplicated in
  `configure_agent`).
- `lifecycle.configure_agent` threads `mcp_slack_extravars` for hermes
  + openclaw; wraps in `try/ValueError → (False, msg)` so exotic
  os_family surfaces as a clean assembly-time failure.
- `lifecycle_canonical.sync_agent_canonical` threads `os_family` into
  hermes + openclaw renderer calls (closes the darwin+slack silent
  wrong-path bug ATX iter-1 W1 flagged).
- openclaw `configure.yaml` / `configure_macos.yaml` install
  `slack-mcp-server` when a slack integration is attached; `no_log:
  true` on install tasks matches openclaw.json copy posture.
- Tests: openclaw slack render goldens, W10 byte-lock, unknown-auth
  defensive raise, slack-user + slack-cookie coexistence, agent_name
  validation, `os_family` typo rejection, playbook_resolver extravar
  matrix, `normalize_os_family` alias parametrize, `mcp_slack_extravars`
  ValueError → `(False, msg)` lifecycle path, attach-gate acceptance
  with hosts.json persistence assertion.

## ATX Review Iterations

Three iterations via the atx CLI (`atx review request --prompt ...`)
per the orchestrator override — MCP review path skipped per Task
instruction. State persisted at `.itx/835/atx-session.json`.

| Iter | Rating | Cost   | Duration | Blockers | Resolution                                    |
|------|--------|--------|----------|----------|-----------------------------------------------|
| 1    | 3.5/5  | $3.63  | 8m22s    | 0 B, 7 W | All 7 warnings fixed in iter-2                |
| 2    | 4.0/5  | $5.53  | 9m10s    | 3 B, 3 W | 3 blockers + 3 warnings fixed in iter-3       |
| 3    | 4.0/5  | $6.56  | 10m19s   | 0 B      | Threshold `>3/5` met; iteration ceiling (3)   |

Total review cost: **$15.72**.

## Real-Host UAT

**Target per plan**: wolf-i openclaw. `clawctl agent get` shows the
only openclaw agent on wolf-i (`wolf-i` itself) is in `failed` state
(age 0s) and cannot serve as a UAT target. `esper-mac-oc` is a `ready`
darwin openclaw on `esper-macmini` (not wolf-i) — usable for macOS UAT
if the operator elects to use it.

**Blocked by pre-existing openclaw install state on wolf-i.** UAT
recorded in the PR Callouts section for the operator to run manually
or after remediating the failed install with `clawctl agent create
<name> --type openclaw --host wolf-i --cleanup-failed`.

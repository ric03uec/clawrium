# Execution — Phase 3: Slack integration for zeroclaw agents (#836)

**Parent**: #499
**Depends on**: #835 (Phase 2 — openclaw)
**Branch**: `issue-836-zeroclaw-slack`
**PR base**: `issue-835-openclaw-slack` (stacked)

## Prechecks

**Precheck 1 (S7, armv7 asset)**:
`gh api repos/korotovsky/slack-mcp-server/releases/latest --jq '.assets[].name'`
returns linux-{amd64,arm64} + darwin-{amd64,arm64} + windows only. **No armv7
asset published at v1.3.0.** Kevin (armv7l Raspberry Pi) cannot be the UAT
target regardless of bind-bug status. Falling back to wolf-i x86_64 zeroclaw
per the plan's documented fallback.

**Precheck 2 (kevin bind bug)**: Moot — Precheck 1 already blocked kevin. Not
tested.

## Implementation Summary

- `src/clawrium/core/render.py`:
  - `_ZEROCLAW_SUPPORTED_INTEGRATIONS` now includes `slack-user` and
    `slack-cookie`.
  - `render_zeroclaw` signature adds `*, os_family="linux"` with strict
    validation (mirrors hermes/openclaw). Home-root resolved via
    `home_root_for` seam. `[[mcp.servers]]` view builder added inside
    `render_zeroclaw` (mirrors `render_openclaw`'s slack view builder
    line-for-line: slug tracker, empty-slug + collision guards, per-auth-mode
    credential checks).
  - `_render_zeroclaw_config_template` signature extended with
    `slack_integrations` + `slack_mcp_binary`.

- `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`:
  - **B2 TOML shape fix**: `servers = []` (inline array) DELETED from `[mcp]`
    baseline. `enabled` and `[[mcp.servers]]` blocks now conditional on
    `slack_integrations`. Zero-slack case emits only `[mcp]` +
    `deferred_loading = true` + `enabled = false` (no `servers` key at
    all — TOML treats absent as empty).

- `src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml`:
  - `slack_integration_assigned` convenience flag added.
  - slack-mcp-server install task block added (arch-guard fail-fast,
    `~/.local/bin` ensure, `get_url` with SHA256 checksum). Consumes the
    `mcp_slack_*` extravars from `playbook_resolver.mcp_slack_extravars`.
  - Positioned BEFORE the gateway pair handshake so a slack install failure
    short-circuits the sync before `_zeroclaw_repair_after_start` rotates the
    bearer (W2/S9 sync-ordering invariant).

- `src/clawrium/core/lifecycle.py`:
  - `resolved_type in ("hermes", "openclaw", "zeroclaw")` — zeroclaw now
    receives `mcp_slack_extravars`.
  - Zeroclaw pre-render call site threads `os_family=normalize_os_family(host)`.

- `src/clawrium/core/lifecycle_canonical.py`:
  - `sync_agent_canonical` threads `os_family` into the zeroclaw renderer too.

- Tests:
  - `tests/core/test_render.py` — added 10 zeroclaw slack tests
    (byte-lock for zero-slack, slack-user + slack-cookie golden, two-slack
    stable order, darwin home-root, slug collision, empty slug, missing
    credentials, unsupported os_family, TOML parseability for all four
    variants). Updated `test_supported_integrations_for_agent_type` (zeroclaw
    now supports slack).
  - `tests/cli/clawctl/agent/test_integration_gate.py` — flipped
    `test_attach_slack_*_to_zeroclaw_rejected` → `_succeeds`.
  - `tests/test_zeroclaw_slack_sync_order.py` (new) — S9/W2 sync-ordering
    tests: slack-hydration failure short-circuits before bearer rotation
    (repair mock never called, no `gateway_token_rotated` events); positive
    control exercises the exact-argument repair call.

- `CHANGELOG.md`:
  - `### Added` entry for Phase 3 zeroclaw slack integration + os_family
    signature extension.
  - `### Fixed` entry for B2 TOML shape bug.

## Test Results

- `make lint-py` — clean, `All checks passed!`
- `make test-py` — **4279 passed, 8 skipped in 36s**.

## Real-Host UAT — wolf-i (x86_64) fallback

Kevin (armv7l) unreachable — Precheck 1 revealed no upstream armv7 asset.
UAT ran against `clawrium-d01` (zeroclaw, wolf-i x86_64) via `uv run clawctl`
from this workspace.

### Verified via `--dry-run --diff`

1. **Attach gate acceptance**:
   ```
   uv run clawctl agent integration attach slack-uat836 --agent clawrium-d01
   → agent/clawrium-d01: attached integration 'slack-uat836'
   ```
   Previously (Phase 2) would have exited 2. Verifies the
   `_ZEROCLAW_SUPPORTED_INTEGRATIONS` frozenset update landed correctly.

2. **B2 TOML shape fix on real host** — dry-run diff on the rendered
   `config.toml` for `clawrium-d01`:
   ```diff
    [mcp]
    deferred_loading = true
   -enabled = false
   -servers = []
   +enabled = true
   +
   +[[mcp.servers]]
   +name = "slack-slack_uat836"
   +command = "/home/clawrium-d01/.local/bin/slack-mcp-server"
   +args = ["--transport", "stdio"]
   +[mcp.servers.env]
   +SLACK_MCP_XOXP_TOKEN = "xoxp-placeholder-uat-836"
   ```
   Exactly the expected shape — inline `servers = []` replaced by
   array-of-tables blocks.

3. **Byte-lock at rest** — after detach + dry-run diff:
   ```diff
    [mcp]
    deferred_loading = true
    enabled = false
   -servers = []
   +
   ```
   Zero-slack shape stable; `servers = []` correctly removed.

4. **Cleanup**: `integration registry delete slack-uat836 --yes` succeeded.
   Agent has no residual attachment.

### Not exercised on real host (see Callouts)

- **Full apply-phase sync** blocked by pre-existing incomplete zeroclaw
  install on `clawrium-d01` (`AgentInstallMissingError: missing service unit
  /etc/systemd/system/zeroclaw-clawrium-d01.service`). This is fleet state,
  not a #836 regression — the on-host install was removed out-of-band
  before this PR started.
- SHA256 checksum verification of downloaded slack-mcp-server binary.
- Actual `gateway_token_rotated` NDJSON event count on a live sync.
- Chat verification (placeholder token would 401 anyway).
- armv7l coverage — upstream ships no asset.

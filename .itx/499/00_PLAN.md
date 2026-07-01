# Issue #499 — User can configure MCP servers once and attach them to any agent

GitHub: https://github.com/ric03uec/clawrium/issues/499

## Implementation Plan — Slack integration for hermes, openclaw, zeroclaw (stdio MCP)

**Revision 2** — post ATX review (2/5, 10 blockers). This revision closes the 7 valid blockers (B1, B2, B6, B7, B8, B9, B10) and demotes cookie auth per B4. B3 (uvx-vs-binary discriminator) rejected as inflated — a Jinja `{% if %}` branch suffices for two entries. B5 (multi-secret schema) rejected as fabricated — the credential store is already multi-secret (see `set_integration_credential(name, key, value)` in `core/integrations.py:285`; atlassian already stores 3 secrets). Full disposition table in "ATX review response" section below.

### Reframe

**Slack is a new integration type**, not a new MCP framework. It slots in alongside `atlassian`, `github`, `linear`, `notion`, `gitlab`, `git`, `brave` in the existing `clawctl integration` surface. Its **implementation detail** happens to be an stdio-spawned MCP server subprocess — the same shape that atlassian uses today.

Concretely:

- No new `clawctl mcp` CLI. The existing stub group in `src/clawrium/cli/clawctl/mcp.py` is deleted in a follow-up subtask.
- No new registry file. Slack lives in `~/.config/clawrium/integrations.json`.
- No new hosts.json shape. Uses the existing `agent["integrations"]` list.
- Each agent type learns to render an MCP subprocess declaration when `integration.type == "slack-user"` or `"slack-cookie"`, exactly like atlassian.

Why this reframe: `_HERMES_SUPPORTED_INTEGRATIONS` already includes atlassian, and the hermes canonical template already emits an `mcp_servers:` block. The zeroclaw TOML template already has an empty `[mcp] servers = []` section (which we replace, not append to — see Slice 3). Openclaw's `openclaw.json` supports `mcp.servers` upstream. Every substrate we need already exists — Slack is a mirror, not a new abstraction.

### Locked design decisions

| Decision | Choice | Rationale |
|---|---|---|
| MCP server implementation | **korotovsky/slack-mcp-server** | Community leader (~9k users, ~30k monthly visits). Single Go binary — no Node/Python/uv runtime on the host. Matches the "install once in configure.yaml" shape used by mcp-atlassian. |
| Transport | stdio only | Per issue scope. |
| Registry | Existing `integrations.json` (shared) | Slack is an integration, not a new attachable. |
| Per-agent attachment | Existing `agent["integrations"]` list | Same as atlassian. |
| Token flow (B4 fix) | `slack-user` (xoxp) is the **default and recommended path**. `slack-cookie` (xoxc+xoxd) is an **explicit opt-in** requiring `--type slack-cookie`; emits a warning on `add` and every `sync` about fragility (Slack abuse detection targets this pattern; xoxd rotates unpredictably). Documented in `docs/integrations/slack.md`. | Cookie mode is TOS-adjacent per Slack's abuse-detection posture. Discouraged fallback, not co-equal. |
| CLI type entries (B7 fix) | Two entries in `INTEGRATION_TYPES`: `slack-user` (one required credential: `SLACK_MCP_XOXP_TOKEN`) and `slack-cookie` (two required credentials: `SLACK_MCP_XOXC_TOKEN`, `SLACK_MCP_XOXD_TOKEN`). No new type-specific flags. Auth mode implicit from `--type`. | Preserves `--credential KEY=VALUE` convention from `_parse_credential_pairs` in `cli/clawctl/integration.py`. |
| Binary distribution (B6 fix) | Prebuilt korotovsky release tarball per (os, arch), **SHA256-pinned via `mcp_slack_sha256_map` (5 entries: linux x86_64/aarch64/armv7l, darwin arm64/amd64)**. Unpacked to `~/.local/bin/slack-mcp-server`. | Mirrors existing `uv_sha256_map` at `hermes/playbooks/configure.yaml:19-22`. Version-only pinning on a third-party GitHub release is retag-vulnerable. |
| Attach-time agent-type gate (B8 fix) | New agent-type ↔ integration-type check added to `agent/integration.py:attach()` in Slice 1. Uses the currently-discarded `_atype` return from `safe_resolve_agent()`. Membership check against the per-agent-type frozenset (e.g. `_HERMES_SUPPORTED_INTEGRATIONS`). Rejects with `emit_error(hint=..., exit_code=2)` referencing #499 when the target agent type doesn't support the integration. | Today `agent/integration.py:59-69` calls `add_agent_integration` unconditionally — the render layer is the only guard, which is exactly the #555-class regression pattern the coming-soon contract is meant to prevent. The gate benefits every future integration, not just Slack. |
| Stub exit code (B10 fix) | `_stub.py:echo_not_implemented()` changes from print-and-return (exit 0) to print + `raise typer.Exit(code=1)`. Landed in Slice 1 since we extend the stub group's lifetime through Slices 1–3. | Pre-existing bug — `clawctl mcp registry get && next_cmd` silently succeeds in scripts today. One-line fix. |
| Shared install task shape (B9 fix) | **No `_shared/tasks/install-slack-mcp-server.yaml`.** Slice 1 inlines the install block in `hermes/playbooks/configure.yaml`. Slice 2 factors out using the **extravar-driven pattern**: `core/playbook_resolver.py` computes `mcp_slack_asset_url`, `mcp_slack_asset_sha256`, `mcp_slack_dest`, `mcp_slack_group` per OS and passes them as extravars. Playbooks are dumb consumers. | Preserves `dispatcher-only OS fork` project invariant. Alternative (separate `_macos.yaml` variant of the install task) also acceptable but produces two files that drift. |
| Docs | Deferred to trailing slice | Per operator instruction #3. |
| GUI | Part of each agent slice | Per operator instruction #4. Coming-soon ribbons for unwired agent types. |

### Fallback if korotovsky is unacceptable

The Zencoder-maintained fork of the archived `modelcontextprotocol/servers/slack` is the "official-lineage" alternative. Requires workspace-admin bot approval; not recommended.

### Slack ≠ Slack channel — do not confuse

The repo already has a Slack **channel** type (`_HERMES_SUPPORTED_CHANNELS = {"discord", "slack"}`, emits `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` env vars). That is the **inbound chat** surface — users message the agent through Slack. This work adds the **outbound tool** surface — the agent queries Slack via MCP tool calls. Two distinct concepts, both can attach to the same agent independently.

---

### Slice structure (agent-scoped, end-to-end)

Each slice ships end-to-end for one agent type: CLI + render + playbook + GUI + unit tests + integration tests + real-host UAT. Docs deferred to Slice 4.

#### Slice 1 — Hermes end-to-end (driver slice)

- Add `slack-user` and `slack-cookie` entries to `INTEGRATION_TYPES` in `src/clawrium/core/integrations.py` with the required credential-key lists.
- Add `slack-user` and `slack-cookie` to `_HERMES_SUPPORTED_INTEGRATIONS` in `src/clawrium/core/render.py`.
- **Attach-time gate (B8)**: extend `agent/integration.py:attach()` to consume `_atype` from `safe_resolve_agent()` and validate agent-type/integration-type compatibility against per-agent-type frozensets. Reject with `emit_error(hint="run `clawctl integration registry get --type slack-user` for supported agent types", exit_code=2)`. Cover the rejection path with a unit test (W1).
- **Stub exit fix (B10)**: change `_stub.py:echo_not_implemented()` to `raise typer.Exit(code=1)` after the echo. Update stub message to redirect: `"Not implemented: use `clawctl integration registry create --type slack-user` — see #499"`.
- Extend `hermes-config.canonical.yaml.j2`'s existing `mcp_servers:` block with a slack branch. Emit `slack: {command: /home/{{agent_name}}/.local/bin/slack-mcp-server, args: [--transport, stdio], env: {SLACK_MCP_XOXP_TOKEN: ..., SLACK_MCP_XOXC_TOKEN: ..., SLACK_MCP_XOXD_TOKEN: ...}}` — key set depends on integration type. Adjacent to the atlassian branch, no shared abstraction (B3 rejected).
- Extend `hermes/playbooks/configure.yaml` (+ `_macos` variant — see W11 note) with an inline slack-mcp-server install block. Add both `mcp_slack_version:` AND `mcp_slack_sha256_map:` pinned vars at the top of the playbook (5 entries — B6). Use `get_url` + `unarchive` with explicit `checksum: "sha256:{{ mcp_slack_sha256_map[ansible_architecture] }}"`. Mirror the `uv` install pattern.
- **hermes macOS scope (W11 acknowledgment)**: Slice 1 makes Slack the **first** MCP subprocess on Darwin hermes (atlassian macOS was deferred). Explicitly in scope for Slice 1 — the `configure_macos.yaml` variant gets the same install block. If bandwidth-constrained mid-slice, split into "hermes Linux Slack" + "hermes macOS Slack" as separate sub-slices; do not silently skip Darwin.
- **Verify config.yaml file mode (W6)**: assert rendered `.hermes/config.yaml` has mode `0600` (rendered plaintext SLACK_MCP_XOXP_TOKEN). Verify atlassian precedent first; state as invariant if already true.
- GUI: Slack integration card added to Integrations tab; per-agent integration picker shows Slack as attachable for hermes agents. Openclaw and zeroclaw rows show "Slack MCP for openclaw / zeroclaw — coming soon".
- Tests:
  - Unit: golden test — hermes `config.yaml` with each of `slack-user` and `slack-cookie` attached vs baseline.
  - Unit (W1): CLI attach rejection when target agent type does not support the integration.
  - Unit (W3): parametrized arch → tarball URL + SHA256 for all 5 (os, arch) targets.
  - Integration: CLI end-to-end via the existing `test_cli_clawctl` fixture pattern — add → attach → sync → assert render output. Include the detach→sync round-trip (W13).
  - **Real-host UAT on maurice (wolf-i)** — mandatory per `no_pr_without_real_host_uat`. Add `slack-user` integration, attach, sync, open a chat, verify the agent can list Slack channels via MCP tool call. Second UAT with `slack-cookie` if a test workspace is available (optional).

#### Slice 2 — Openclaw end-to-end

- Add `slack-user` and `slack-cookie` to openclaw's supported-integrations set (create `_OPENCLAW_SUPPORTED_INTEGRATIONS` frozenset in `render.py` if it doesn't exist yet — the pattern-parity gap is worth closing now).
- **B1 fix**: extend `_render_openclaw_json()` at `render.py:1610` to accept an `integrations` parameter and populate `mcp.servers.slack` in the returned JSON when a slack-typed integration is attached. **Do NOT introduce an Ansible-side deep-update.** The playbook keeps its existing `ansible.builtin.copy` of `prerendered_openclaw_config_json` at `openclaw/playbooks/configure.yaml:150`. This preserves the #622 single-renderer invariant.
- **W10 fix**: the baseline `mcp: {servers: {}}` block is added to `openclaw.json` **conditionally** — only when at least one MCP-emitting integration is attached. `_render_openclaw_json()` drops the key entirely when the map is empty, keeping the byte diff for existing agents at zero. Alternative: unconditional baseline, documented under CHANGELOG `### Changed`. Prefer conditional-emit.
- Extract the slack-mcp-server install block from `hermes/playbooks/configure.yaml` into the extravar-driven pattern (B9 fix): add `mcp_slack_asset_url`, `mcp_slack_asset_sha256`, `mcp_slack_dest`, `mcp_slack_group` to `core/playbook_resolver.py`'s per-OS computation. Both hermes and openclaw playbooks consume these extravars via a common install task snippet (which may live in a shared file OR be duplicated with a byte-lock test — implementer's call). Cover openclaw macOS variant (macOS is GA per #770).
- GUI: Slack card now shows openclaw as attachable. Zeroclaw stays "coming soon".
- Tests:
  - Unit: `openclaw.json` golden with slack attached; byte-lock guard (no diff for existing openclaw agents without slack).
  - Integration: CLI e2e via the openclaw fixture path, add → attach → sync → detach round-trip.
  - **Real-host UAT on a wolf-i openclaw** (Linux matrix stays consistent with hermes slice). mac-test UAT as a follow-up if bandwidth allows within the slice.

#### Slice 3 — Zeroclaw end-to-end

- Add `slack-user` and `slack-cookie` to zeroclaw's supported-integrations set.
- **B2 fix (TOML shape)**: the current `zeroclaw-config.toml.j2:422-425` declares:
  ```toml
  [mcp]
  deferred_loading = true
  enabled = false
  servers = []
  ```
  This inline-array `servers = []` is **incompatible** with appending `[[mcp.servers]]` array-of-tables (TOML spec forbids defining the same key twice with different forms — parser rejects, daemon crashes at start). The fix:
  - Delete the `servers = []` line from the baseline.
  - Conditionally emit `[[mcp.servers]]` array-of-tables blocks when slack integrations are attached, one per integration instance.
  - Flip `enabled = true` in the same conditional.
  - When zero MCP-emitting integrations are attached, emit only the `[mcp]` header + `deferred_loading = true` + `enabled = false` (no `servers` key at all — TOML treats absent = empty).
  - Alternative (simpler but less TOML-idiomatic): `servers = [{name="slack", command="...", args=[...], env={...}}, ...]` inline-table-in-array; only viable if all slack integrations fit in one line reasonably.
  - Byte-lock test: assert existing zeroclaw agents (no slack) render **byte-identical** to pre-fix output.
- Extend `zeroclaw/playbooks/configure.yaml` to consume the same extravar-driven slack-mcp-server install (per B9 fix in Slice 2). No new shared file.
- **W2**: verify Slack render + hydration completes **before** `_zeroclaw_repair_after_start` rotates the gateway bearer. If Slack hydration fails after bearer rotation, `hosts.json.gateway.auth` has a fresh bearer but daemon holds the old one — reintroduces #437 stale-bearer failure. Assert exactly one `gateway_token_rotated` event per successful sync.
- GUI: Slack card now shows zeroclaw as attachable. All coming-soon ribbons removed.
- Tests:
  - Unit: `config.toml` golden with slack attached; byte-lock guard for the no-slack case.
  - Integration: CLI e2e via zeroclaw fixture path, add → attach → sync → detach round-trip.
  - **Real-host UAT** — first choice is kevin (armv7l, exercises the arch matrix — **critical regression signal**). Precheck at slice start: (1) run `curl -s https://api.github.com/repos/korotovsky/slack-mcp-server/releases/latest | jq '.assets[].name'` to confirm an armv7 asset ships; (2) verify kevin's outstanding zeroclaw bind bug (per operator memory) does not block the sync path. If korotovsky ships no armv7 asset OR kevin is blocked, fall back to a fresh zeroclaw on wolf-i AND document armv7l as a known coverage gap with a tracking issue. Wolf-i fallback is x86_64 — losing the armv7l signal is real risk (W4).

#### Slice 4 — Docs + changelog

- `docs/integrations/slack.md` *(new)* — token acquisition (`slack-user` xoxp: how to create a Slack app + install token; `slack-cookie` xoxc/xoxd: browser extraction steps + security warning), tool list, security posture. **Composite blast-radius note (S5)**: attaching both the Slack **channel** (inbound) and Slack **integration** (outbound) to the same agent enables a prompt-injection tool-call exfiltration path — a message sent to the agent via Slack can drive Slack MCP tool calls back out. Document + recommend separate agents per direction for high-sensitivity workspaces.
- `docs/agent-support/{hermes,openclaw,zeroclaw}.md` — Slack integration subsection each.
- Root `CHANGELOG.md` under `[Unreleased] ### Added` — Slices 1–3 each add their own bullet as they land; Slice 4 adds the docs entries. `### BREAKING` entry (or `### Changed`) for the `_stub.py` exit-code shift if any user tooling depends on the old exit-0 behavior — low probability, worth calling out.

### Coming-soon contract

| Surface | After Slice 1 | After Slice 2 | After Slice 3 |
|---|---|---|---|
| `clawctl integration registry create --type slack-user` | works globally (registry is shared) | works | works |
| `clawctl agent integration attach <hermes-agent> slack-user-instance` | works, syncs render + restart | works | works |
| `clawctl agent integration attach <openclaw-agent> slack-user-instance` | CLI rejects at attach time (B8 gate) with hint referencing #499 | works | works |
| `clawctl agent integration attach <zeroclaw-agent> slack-user-instance` | CLI rejects at attach time | CLI rejects at attach time | works |
| GUI Slack card — hermes row | attach button live | attach button live | attach button live |
| GUI Slack card — openclaw row | "coming soon" ribbon | attach button live | attach button live |
| GUI Slack card — zeroclaw row | "coming soon" ribbon | "coming soon" ribbon | attach button live |

### Files touched (headline map)

**Slice 1 (hermes)**
- `src/clawrium/core/integrations.py` — `slack-user` + `slack-cookie` entries in `INTEGRATION_TYPES`
- `src/clawrium/core/render.py` — `_HERMES_SUPPORTED_INTEGRATIONS` add, slack view builder, `_HERMES_MCP_SLACK_VERSION` pin
- `src/clawrium/platform/registry/hermes/templates/hermes-config.canonical.yaml.j2` — slack branch adjacent to atlassian branch in mcp_servers loop
- `src/clawrium/platform/registry/hermes/playbooks/configure.yaml` (+ `_macos`) — inline slack-mcp-server install with `mcp_slack_version` + `mcp_slack_sha256_map`
- `src/clawrium/cli/clawctl/agent/integration.py` — attach-time agent-type gate (B8)
- `src/clawrium/cli/clawctl/_stub.py` — exit-1 fix (B10) + redirect message
- `src/clawrium/gui/frontend/integrations.html` + `src/clawrium/gui/routes/integrations.py` — slack card
- `tests/core/test_render.py` — hermes golden (`slack-user`, `slack-cookie`)
- `tests/cli/clawctl/agent/test_integration_gate.py` *(new)* — attach rejection tests
- `tests/cli/clawctl/integration/test_slack.py` *(new)* — registry create for both types
- `tests/platform/test_slack_asset_map.py` *(new)* — parametrized 5 (os, arch) mapping

**Slice 2 (openclaw)**
- `src/clawrium/core/render.py` — `_OPENCLAW_SUPPORTED_INTEGRATIONS` frozenset (create if missing), openclaw slack branch, extend `_render_openclaw_json()` signature to accept integrations
- `src/clawrium/platform/registry/openclaw/templates/openclaw.json` — no change (baseline stays lean; `mcp` key conditionally emitted by Python)
- `src/clawrium/platform/registry/openclaw/playbooks/configure.yaml` (+ `_macos`) — install task via extravars from `playbook_resolver.py`
- `src/clawrium/core/playbook_resolver.py` — new `mcp_slack_*` extravar computation per OS
- GUI wiring for openclaw slack row
- Tests + real-host UAT

**Slice 3 (zeroclaw)**
- `src/clawrium/core/render.py` — `_ZEROCLAW_SUPPORTED_INTEGRATIONS` add, zeroclaw slack branch
- `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2` — **delete `servers = []` from baseline**; conditional `[[mcp.servers]]` emission; flip `enabled` conditionally
- `src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml` — install task via extravars
- GUI wiring for zeroclaw slack row
- Tests + real-host UAT (kevin armv7l or wolf-i fallback)

**Slice 4 (docs)**
- `docs/integrations/slack.md` *(new)*, `docs/agent-support/{hermes,openclaw,zeroclaw}.md`, `CHANGELOG.md`

### Recommended subtasks (children of #499)

1. **[Parent #499] Slack integration for hermes agents (end-to-end)** — includes attach-time agent-type gate (B8) and `_stub.py` exit-1 fix (B10) as cross-cutting foundation.
2. **[Parent #499] Slack integration for openclaw agents (end-to-end)** — depends on 1; extracts install-task extravars via `playbook_resolver.py`.
3. **[Parent #499] Slack integration for zeroclaw agents (end-to-end)** — depends on 2; fixes zeroclaw TOML shape (B2).
4. **[Parent #499] Docs + changelog for Slack integration across hermes / openclaw / zeroclaw** — depends on 3; includes composite blast-radius note (S5).
5. **[Parent #499] Follow-up: generic MCP support parent issue + delete stubbed `clawctl mcp` command group** — depends on 1. Opens the successor issue for arbitrary MCP-server support before deleting the stub group.

### Risks and open questions

- **Binary distribution across arches**: korotovsky ships GitHub releases per (os, arch). Playbook must resolve tarball URL by `(ansible_system, ansible_architecture)` — **two axes, not one**. Confirm at Slice 3 start that korotovsky publishes an armv7 asset via `curl … | jq '.assets[].name'`; if not, drop kevin from UAT and open a tracking issue for armv7l coverage.
- **kevin's zeroclaw bind bug** (per operator memory): may block Slice 3 real-host UAT. Verify at slice start; fall back to wolf-i zeroclaw with an explicit armv7l coverage gap documented.
- **`ansible_user_dir` ban** (per AGENTS.md project-wide invariant): use `/home/{{ agent_name }}/.local/bin/slack-mcp-server` literally on Linux, `/Users/{{ agent_name }}/.local/bin/slack-mcp-server` on macOS. Never `ansible_user_dir`.
- **Openclaw macOS matrix**: Slice 2 must include the `configure_macos.yaml` variant — openclaw macOS is GA per #770.
- **Hermes macOS is first MCP on Darwin (W11)**: atlassian macOS was deferred; Slack is the first MCP subprocess on Darwin hermes. Explicit Slice 1 scope; do not silently skip.
- **Backward compat of the stub `clawctl mcp` group**: stubs stay through Slices 1–3 with exit-1 + redirect message. Deleted in follow-up subtask #5 alongside the generic-MCP-support successor issue.
- **Secrets hydration**: `SLACK_MCP_XOXP_TOKEN` (or the cookie pair) flows through `set_integration_credential(name, key, value)` (multi-secret store, already used by atlassian's 3-credential setup) and hermes's existing per-integration credentials path. No new hydration mechanism.
- **Version + SHA256 pin drift (W7)**: `_HERMES_MCP_SLACK_VERSION` (render.py) + `mcp_slack_version` (playbook) + `mcp_slack_sha256_map` (playbook) can drift. Add a CI assertion or single-source-of-truth constant imported into both surfaces.
- **CLI credential leakage via ps auxww / shell history (S6)**: `--credential SLACK_MCP_XOXP_TOKEN=<value>` shows in process listing. `integration registry create` should support `--credential-stdin` (already exists per the read of `_parse_credential_pairs`) and `docs/integrations/slack.md` must recommend it for xoxp tokens.

### Test strategy summary

| Layer | Slice 1 | Slice 2 | Slice 3 |
|---|---|---|---|
| Unit (Jinja / JSON golden) | hermes `config.yaml` (both types) | `openclaw.json` (with byte-lock for no-slack) | zeroclaw `config.toml` (with byte-lock for no-slack) |
| Unit (CLI gate) | attach rejection for unsupported (agent, integration) pairs | attach acceptance for openclaw | attach acceptance for zeroclaw |
| Unit (asset map) | parametrized 5 (os, arch) → URL + SHA256 | (reuse) | (reuse) |
| Integration (CLI e2e) | attach → sync → detach → sync round-trip on hermes | same on openclaw | same on zeroclaw (incl. gateway_token_rotated assertion) |
| Real-host UAT | maurice on wolf-i (both `slack-user` and, if available, `slack-cookie`) | wolf-i openclaw | kevin (armv7l) — precheck asset availability + bind bug; fallback wolf-i with documented gap |

Real-host UAT is blocking per operator standing rule; PR body must record host + observed behavior for the UAT step, including a checklist for host-side file checks (config.yaml mode, install binary present, checksum verified) before the chat test.

### ATX review response (revision 2)

Full ATX review saved to `/home/devashish/.claude/projects/-home-devashish-workspace-ric03uec-clawrium/.../mcp-atx-request_review-1782884071401.txt`. Review rating: 2/5, 10 blockers. Disposition:

| Blocker | Disposition | Where addressed |
|---|---|---|
| B1 — Ansible deep-update on openclaw.json violates #622 | **Accepted, fixed** | Slice 2: extend `_render_openclaw_json()` at `render.py:1610`; playbook stays dumb copy |
| B2 — Invalid TOML: `servers = []` + `[[mcp.servers]]` | **Accepted, fixed** | Slice 3: delete `servers = []` from baseline; conditional array-of-tables emission |
| B3 — uvx vs direct-binary shape discriminator | **Rejected — inflated** | Two entries need a Jinja `{% if %}` branch, not a `launch_style` abstraction. Adjacent branches in `mcp_servers` block, no shared shape needed. |
| B4 — Cookie auth risk framing | **Accepted, demoted** | `slack-cookie` requires explicit `--type`, warns on add + every sync. `slack-user` is the recommended default. |
| B5 — Two-secret schema unverified | **Rejected — fabricated** | ATX specialist did not read the code. `set_integration_credential(name, key, value)` at `core/integrations.py:285` is per-key; `get_integration_credentials()` returns `dict[str, str]`. Atlassian already stores 3 secrets per integration. Store is multi-secret today. |
| B6 — Version-only pinning missing SHA256 | **Accepted, fixed** | `mcp_slack_sha256_map` mirroring `uv_sha256_map`. 5 entries. `checksum: sha256:...` in `get_url`. |
| B7 — Type-specific flags break `--credential` convention | **Accepted, fixed** | Two entries in `INTEGRATION_TYPES` (`slack-user`, `slack-cookie`), operators use existing `--credential KEY=VALUE`. |
| B8 — Attach gate unimplemented; writes hosts.json unconditionally | **Accepted, fixed** | Slice 1 wires the gate in `agent/integration.py:attach()` using the currently-discarded `_atype`. Applies to every future integration too. |
| B9 — Shared install task violates dispatcher-only OS fork | **Accepted, fixed** | No `_shared/tasks/…` file. Slice 1 inlines. Slice 2 extracts via `playbook_resolver.py` extravars — playbooks stay dumb consumers. |
| B10 — `echo_not_implemented()` exits 0 | **Accepted, fixed** | Slice 1 changes to `raise typer.Exit(code=1)` + redirect message pointing at `clawctl integration registry create`. |

Warnings W1, W2, W3, W4, W6, W7, W10, W11, W13 folded into the slice checklists explicitly. W5 (arch two-axis) captured in Risks. W12 (terminology `add` vs `registry create`) — plan text now uses `registry create` throughout. Suggestions S5 (composite blast radius), S6 (`--credential-stdin`), S7 (asset precheck), S9 (zeroclaw sync ordering) folded in.

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-30T00:00:00Z
**Model**: claude-opus-4-7

```prompt
499. dont create files, just give me a plan

[iterated in-conversation with the following direction:]
1. subtask breakdown must be based on agents not technical tasks. so first add suport for hermes and then openclaw and then zeroclaw
2. for openclaw and zeroclaw do a research and find the right approach to add this support
3. docs wil be done after all agents are added
4. gui will be part of each agent, not a seprate task. each agent slice needs end to end fuctionality. missing functionality will be marked as coming soon.
5. thsi will be an stdio support only. do a reserahc on the mcp server for slack which is most used and stable and use that for all agents.
6. test strategy wil be iterleaved with each agent as well. end to end test for each agent on a live host is a must alongwith unit and integration tests.
7. this shoudl follow similar pattern as atlassian so its basially an integration, not an mcp i suppose. update plan
```

**Output**: Agent-sliced plan (hermes → openclaw → zeroclaw → docs) reframing #499 as a Slack integration mirroring atlassian, using korotovsky/slack-mcp-server over stdio. GUI, tests, and real-host UAT interleaved per slice; docs deferred to trailing slice. Subtask issues not yet opened.

## Revision 2 — ATX Review Response

**Stage**: planning-revision
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-30T00:00:00Z
**Model**: claude-opus-4-7

```prompt
are these valid blockers?
[after verifying each ATX blocker against actual code]
yes review 7 blcokers and update plan
```

**Output**: Closed the 7 valid ATX blockers (B1 openclaw single-renderer, B2 zeroclaw TOML shape, B6 SHA256 pin, B7 flag convention, B8 attach gate, B9 dispatcher OS-fork invariant, B10 stub exit code) and demoted cookie auth per B4. Rejected B3 (Jinja branch, not an abstraction) and B5 (fabricated — multi-secret store already exists via `set_integration_credential(name, key, value)`; atlassian proves it with 3 keys). Warnings W1/W2/W3/W4/W6/W7/W10/W11/W13 folded into slice checklists. Full disposition table in "ATX review response" section.

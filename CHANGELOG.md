# Changelog

All notable changes to this project are documented here. Per-release frozen
archives live under [`docs/releases/`](docs/releases/) — that directory is
the single place to read the full history of what shipped in each version.

The project follows a `YY.M.PATCH` calendar versioning convention; the
`## [Unreleased]` section below is the working log for the next release
cut. The `itx-release` skill archives this section into a new
`docs/releases/<version>/CHANGELOG.md` and resets this file to an empty
`[Unreleased]` template on every release.

## [Unreleased]

### BREAKING

- **zeroclaw upstream pin bumped to v0.8.5** (previously v0.8.2). Three config sections were retired upstream between v0.8.3 and v0.8.5; the clawrium renderer no longer emits any of them, and operators MUST NOT hand-add them via the workspace overlay at `~/.config/clawrium/agents/zeroclaw/<name>/workspace/config.toml`:
  - **`[node_transport]`** — removed in v0.8.5 (upstream #10289). Retired legacy HMAC node transport. `[nodes]` remains the supported peer-discovery surface.
  - **`[providers]` root with inline `fallback = "..."`** — no longer accepted. The daemon silently resets the entire `[providers]` section to defaults when the malformed inline key is present, **which wipes the LLM provider binding and breaks chat**. Provider selection now lives entirely on `[agents.<alias>].model_provider = "<type>.<alias>"`.
  - **root-level `[cron]` block** (`catch_up_on_startup`, `enabled`, `jobs`, `max_run_history`) — restructured to a map of named `[cron.<name>]` sub-tables shaped as `CronJobDecl` structs. Clawrium ships no built-in cron jobs, so no `[cron.*]` sub-tables are rendered; operators add jobs via the workspace overlay.

  **Recommended upgrade order: `clawctl agent upgrade <name>` first (which bumps binary + re-renders config in one step), NOT `clawctl agent sync` before upgrade** — running sync against a still-0.8.2 binary will render the new v0.8.5-shaped config against the old daemon. Clawrium never populated `[node_transport].shared_secret` (it always rendered `""`), so no secret rotation is required unless an operator hand-patched the file outside the renderer. If you were relying on the retired legacy node transport (anything talking to `NodeTransport` / `sign_request` / `verify_request` from external Rust code), switch to `[nodes]` before upgrading (#985).
- **`/itx:<verb>` skills renamed to `/itx-<verb>`** to comply with Anthropic's documented `SKILL.md` `name:` charset (`[a-z0-9-]{1,64}`). All thirteen skills under `.claude/skills/itx-*/` now use hyphens instead of colons in their `name:` frontmatter and in every documented invocation. There is no compat shim — the Claude Code harness has no skill-alias mechanism. **Migration**: update any saved prompts, scripts, cron jobs, or muscle-memory invocations from `/itx:foo` to `/itx-foo` (e.g. `/itx-execute`, `/itx-plan-create`, `/itx-review-pr`). Directory names were already hyphenated, so no filesystem paths change. Historical records under `.itx/<n>/` are preserved verbatim — they document invocations that actually used the colon form at the time (#970).
- **zeroclaw agents whose clawctl name contains a hyphen or uppercase letter require a one-time on-host state migration.** The renderer now sanitizes the in-TOML alias keys `[agents.<alias>]` and `[providers.models.<type>.<alias>]` to match zeroclaw 0.8.2's schema-v3 charset requirement (`[a-z0-9_]+`), mirroring the `[channels.discord.<alias>]` fix from #974. Chat continued to work with the hyphenated aliases because the TOML boot loader is lenient, but the dashboard's per-request alias resolver rejected them with `[path_not_found]` on any agent-scoped operation. There is no automated migration — the per-alias state directory at `~/.zeroclaw/agents/<name>/` must be renamed on each affected host so session history and per-alias memory carry over. `clawctl`-visible `agent_name` and every on-host filesystem path (systemd unit, `/home/<name>/`) stay unchanged. Agents whose name is already `[a-z0-9_]+` need no action. Manual procedure per affected agent (substitute `<NAME>` and derive `<NEW_ALIAS>` as `echo <NAME> | tr 'A-Z-' 'a-z_'`):

  ```bash
  clawctl agent stop <NAME>
  clawctl agent shell <NAME> -- \
    "mv ~/.zeroclaw/agents/<NAME> ~/.zeroclaw/agents/<NEW_ALIAS>"
  clawctl agent configure <NAME>
  clawctl agent start <NAME>
  # Verify — all four alias headers underscored:
  clawctl agent shell <NAME> -- \
    "grep -E '^\\[(agents|providers\\.models|channels\\.discord)\\.' \
       ~/.zeroclaw/config.toml"
  ```

  Shared SQLite (`data/memory/brain.db`, `data/sessions/sessions.db`) is not alias-keyed — session history and memory carry over untouched regardless (#980).

### Added

- Make all thirteen `/itx-*` workflow skills available from Claude Code,
  OpenCode, and Pi from one canonical `.claude/skills/` source. Pi also exposes
  native `/skill:itx-*` commands, with project aliases preserving the shared
  `/itx-*` names.
- Add the mirrored `clawctl-lmwork` orchestration skill for safely dispatching human-approved small issues to a local model, gating rebased commits through an independent judge and ATX review, and recording runtime telemetry outside the repository (#955).
- `clawctl host edit --description <text>` sets or updates a free-form description on a host record; passing an empty string clears it (#122).
- **zeroclaw**: accept the `litellm` provider type so a zeroclaw agent can front a LiteLLM proxy (or any OpenAI-compatible gateway) directly. The renderer emits `uri` + `api_key` under `[providers.models.litellm.<alias>]` in `~/.zeroclaw/config.toml` (zeroclaw's litellm schema uses `uri`, not `base_url`) and normalizes the endpoint the same way as opencode (strip trailing `/`, append `/v1` if missing). Matches the existing openclaw (#723) and hermes (#705) litellm paths. Use with `clawctl provider registry create <name> --type litellm --litellm-url <proxy> --model <id> --api-key <bearer>` + `clawctl agent provider attach <name> --agent <zeroclaw-agent>` (#976).
- **gui**: The per-agent Chat tab input is now a multi-line textarea that grows
  from 1 to 8 rows as you type. Enter sends, Shift+Enter inserts a newline, and
  Cmd/Ctrl+Enter is an alias for Enter (#788).
- **gui**: A Stop button cancels an in-flight chat response, and the typing
  indicator now counts elapsed seconds instead of showing a static
  "Thinking..." (#788).

### Changed

- **zeroclaw**: manifest pins bumped from v0.8.2 → v0.8.5 across all five shipped arch rows (armv7l Debian 13, aarch64 Ubuntu 22.04/24.04, x86_64 Ubuntu 22.04/24.04). SHA256s sourced from the upstream `SHA256SUMS` for `v0.8.5`. `latest_version` resolves to `0.8.5` for fresh installs and `clawctl agent upgrade` on existing agents (#985).
- ITX review workflows now select an ATX transport by capability instead of a
  Claude-specific MCP tool name, with stateless CLI and documented manual
  fallbacks when automated review is unavailable.
- Agent-authored pull requests now include execution metrics in the PR template, and the `itx-execute` guidance documents stateless ATX review requests for changes authored outside Claude Code sessions (#955).
- `clawctl channel registry create/edit --home-channel <id>` now accepts Discord channels in addition to Slack; the Jinja `hermes-env.canonical.j2` template already emitted `DISCORD_HOME_CHANNEL` when the field was set, only the CLI guards blocked it (#642).

### Fixed

- **gui**: Harden static-file handler against path traversal — all candidate
  paths in the catch-all frontend route are now resolved and verified to
  stay inside the frontend directory via `Path.resolve()` +
  `is_relative_to()` (issue #418).
- **gui**: Add `TrustedHostMiddleware` to reject requests with foreign
  `Host` headers, closing a DNS rebinding exposure (issue #418).
- **gui**: Remove `secrets_file`, `hosts_file`, and `providers_file` from
  the `/api/settings` response; replace with `secrets_configured` (bool)
  to avoid leaking absolute filesystem paths (issue #418).
- `clawctl agent upgrade` now probes the live openclaw version on the host instead of trusting the hosts.json snapshot, closing the false-no-op trap when snapshot and live binary diverge (#754)
- **zeroclaw**: rendered `config.toml` now emits `[channels.discord.<alias>]` sub-tables with a per-agent `channels = ["channels.discord.<alias>"]` binding under `[agents.<name>]`, matching zeroclaw ≥0.8.2's schema v3. The previous pre-0.8.2 flat `[channels.discord]` block was silently ignored by the daemon — every clawctl-managed zeroclaw agent with an attached discord channel reported `no channels configured` and refused inbound messages with `The operator needs to run Quickstart before I can reply`. `schema_version` also bumped `2 → 3` to eliminate any risk of a future daemon picking the v2 parser code path (#974).
- **zeroclaw renderer**: `[agents.<alias>]` and `[providers.models.<type>.<alias>]` sub-table keys are now sanitized via `_sanitize_zeroclaw_alias(agent_name)`, matching the `[channels.discord.<alias>]` fix from #974. Zeroclaw 0.8.2's dashboard alias resolver enforces `[a-z0-9_]+` strictly and returned `[path_not_found]` on any agent-scoped operation for agents whose clawctl name contained a hyphen or uppercase letter (e.g. `clawrium-d01`). On-host filesystem paths and systemd unit names continue to use the raw `agent_name` (#980).
- **zeroclaw renderer**: emit `[heartbeat] agent = "<alias>"` so the heartbeat worker can bind to the agent alias and start. Without this, every clawctl-managed zeroclaw agent's heartbeat worker was error-looping on startup with `heartbeat worker requires [heartbeat] agent = "<alias>"` and `restart_count` climbing indefinitely in `~/.zeroclaw/state/daemon_state.json`; no operator-visible symptoms until the daemon-state file was inspected. Runs off the sanitized `agent_alias` already threaded into the render context by #980 (#982).
- **gui**: The Chat tab input is no longer disabled while a response is in
  flight — you can keep typing, and focus returns to the input after each send
  and after each response arrives (#788).
- **gui**: The Chat tab now fills the available pane height instead of a fixed
  500px, so long conversations scroll inside the message list rather than
  growing the page (#788).
- **gui**: Chat SSE error messages redact common absolute server paths,
  credential-shaped values, and terminal-control characters before rendering
  in the browser. The SSE reader also buffers partial lines and split UTF-8
  code points across chunk boundaries so payloads are not dropped or mangled
  (#788).

### Documentation

- Correct the ZeroClaw Discord documentation for schema-v3 aliased channel tables, agent bindings, and the registry/attach/sync workflow (#979).
- Align the ZeroClaw support matrix and rendered `config.toml` examples with schema v3, current v0.8.2 installs, aliased provider/agent/channel tables, and heartbeat binding (#984).
- **website**: Restore the missing summary blockquote in `website/docs/guides/local-skills.md` mirror so its body matches `docs/local-skills.md` verbatim (#965).
- Document `clawctl host validate`, the `RUNTIME` column on `clawctl agent get`,
  and openclaw's mandatory `--provider` flag; correct the `clawctl agent create`
  and `clawctl agent get` reference sections, whose documented signatures and
  options had drifted from the real CLI (#947-#950, #754).
- Add a "Pin the host's IP address" step to host preparation covering router
  DHCP reservation, OS-level static IP fallbacks (netplan, NetworkManager,
  macOS), and recovery via `clawctl host edit --hostname` when a host's
  address has already changed (#973).

### Internal

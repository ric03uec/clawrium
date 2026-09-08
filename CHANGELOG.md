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

- Add the mirrored `clawctl-lmwork` orchestration skill for safely dispatching human-approved small issues to a local model, gating rebased commits through an independent judge and ATX review, and recording runtime telemetry outside the repository (#955).
- `clawctl host edit --description <text>` sets or updates a free-form description on a host record; passing an empty string clears it (#122).
- **zeroclaw**: accept the `litellm` provider type so a zeroclaw agent can front a LiteLLM proxy (or any OpenAI-compatible gateway) directly. The renderer emits `uri` + `api_key` under `[providers.models.litellm.<alias>]` in `~/.zeroclaw/config.toml` (zeroclaw's litellm schema uses `uri`, not `base_url`) and normalizes the endpoint the same way as opencode (strip trailing `/`, append `/v1` if missing). Matches the existing openclaw (#723) and hermes (#705) litellm paths. Use with `clawctl provider registry create <name> --type litellm --litellm-url <proxy> --model <id> --api-key <bearer>` + `clawctl agent provider attach <name> --agent <zeroclaw-agent>` (#976).

### Changed

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

### Documentation

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

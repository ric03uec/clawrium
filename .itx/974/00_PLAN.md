# #974 — zeroclaw 0.8.2 aliased channels + agent binding

## Problem

Every clawctl-managed zeroclaw agent (0.8.2) with a discord channel
attached silently fails to route inbound Discord messages. Discord
users see `This agent isn't fully set up yet. The operator needs to
run Quickstart before I can reply`; `zeroclaw doctor` reports
`no channels configured — run zeroclaw quickstart to set one up`.

Root cause: `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`
still emits the pre-0.8.2 flat `[channels.discord]` block. Zeroclaw
0.8.2 (config schema v3) keys channels by alias under
`[channels.discord.<alias>]` and requires a per-agent binding
`[agents.<agent>].channels = ["channels.discord.<alias>"]`. The
flat block is silently dropped and the binding is empty, so the
daemon has no channel routing to any agent.

Same class of drift called out in the `[zeroclaw 0.8.2 /ws/chat BC
break]` note — a partial 0.8.2 migration.

## Fix

Two coordinated changes in `src/clawrium/`:

1. **`platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`**
   - Change `[channels.discord]` → `[channels.discord.{{ discord_alias }}]`,
     rendered only when a discord channel is attached.
   - Add `channels = ["channels.discord.{{ discord_alias }}"]` under
     `[agents.{{ agent_name }}]` (empty list when no channel).
   - Bump `schema_version = 2 → 3` (auto-migration works, but the
     bump prevents any future daemon version from selecting a v2
     code path).

2. **`core/render.py`**
   - Add `_sanitize_zeroclaw_alias(name)` — collapses `[^a-z0-9_]`
     to underscore; raises `AgentConfigError` on empty input.
   - Compute `discord_alias = _sanitize_zeroclaw_alias(agent_name)`
     in `render_zeroclaw`; thread through to the template.
   - `_render_zeroclaw_config_template` guards
     `discord_channel != None with empty discord_alias` — raise
     rather than render invalid TOML `[channels.discord.]`.

## Test Plan

- Unit (`tests/core/test_render.py`):
  - Sanitizer parametrize covers hyphen, uppercase, dot, all-special.
  - Sanitizer rejects empty input.
  - `_render_zeroclaw_config_template` rejects channel-without-alias.
  - Renderer emits `[channels.discord.<alias>]` + agent binding.
  - No-discord path emits `channels = []` and no aliased section.
  - Escape-roundtrip test looks up via `_sanitize_zeroclaw_alias`.

- Real-host UAT #1: `clawrium-d01` (existing, broken). `clawctl agent
  sync` heals; doctor `✅ at least one channel configured`; chat via
  `/ws/chat` protocol works end-to-end.

- Real-host UAT #2: `zc-974-uat` (fresh, alias `zc_974_uat`). Fresh
  install + sync produces correct v3 config; deleted after
  verification.

## Rollout

No migration needed. Next `clawctl agent sync` on each zeroclaw agent
re-renders `~/.zeroclaw/config.toml` in the new shape. Daemon restart
picks up the config; the systemd unit `Restart=on-failure` continues
to work as-is.

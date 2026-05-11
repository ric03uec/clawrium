# Issue #324 — Implementation Plan

User can `clm agent configure <hermes-name>` and pick Discord as a channel, providing the bot token + allowed users + (optional) home channel. Agent connects to Discord on next restart and routes messages through the configured LLM provider, with no hand-rolled `.env` edits.

Source of truth: GitHub issue #324 plus this file. Phase 6 of the broader #68 effort (Phases 1-5 already shipped).

## Key discovery from codebase exploration

The Discord wiring **already exists in clm** for openclaw/zeroclaw via `_run_channels_stage` in `src/clawrium/cli/agent.py:693-820`. Specifically:

- The function offers `["cli", "discord", "slack"]` for non-hermes claw types.
- The discord branch prompts for bot token / guild ID / channel ID / user ID, validates formats, stores the token via `set_instance_secret(instance_key, "DISCORD_BOT_TOKEN", ...)` — the canonical B3 pattern.
- The non-sensitive Discord config (guild/channel/user IDs) is persisted to `hosts.json` under `agents.<name>.config.channels.discord`.
- An explicit `if claw_type == "hermes": channels = ["cli"]` guard at line 716 **restricts hermes to cli-only**.

So Phase 6 is mostly:

1. Drop the hermes guard at line 716.
2. Translate the existing `channels.discord` config into hermes' env-var contract (different shape than openclaw's runtime which reads from a config service).
3. Render those env vars into `.env.j2`.
4. Hydrate the bot token from `secrets.json` in `lifecycle.configure_agent()` (mirror the `HERMES_API_SERVER_KEY` pattern).
5. Strip the bot token from `hosts.json` persistence in `install.py`'s updater closure (mirror the `api_server.key` stripping).
6. Verify in `configure.yaml`.
7. Add `DISCORD_HOME_CHANNEL` to the CLI prompts (hermes nags without it — user hit this on espresso).
8. Tests + docs + E2E migration of espresso on wolf-i from hand-rolled to clm-managed.

Total estimated diff: 400-600 LOC including tests. **Single PR — no subtasks needed.**

## Hermes Discord env-var contract (already researched, pinned at v2026.5.7)

| Env var | Source | Required | Notes |
|---|---|---|---|
| `DISCORD_BOT_TOKEN` | `secrets.json` via `set_instance_secret(instance_key, "DISCORD_BOT_TOKEN", ...)` | yes | Bearer for discord.py gateway. Validate format: `^[A-Za-z0-9._+/=-]{50,120}$` (matches the existing openclaw validator). |
| `DISCORD_ALLOWED_USERS` | `hosts.json` `config.channels.discord.allowed_users` (list[str], joined `,`) | yes (or set `DISCORD_ALLOW_ALL_USERS=true`) | Without one of these, hermes denies every message. User IDs are PII-ish but not secret — fine in hosts.json. |
| `DISCORD_HOME_CHANNEL` | `hosts.json` `config.channels.discord.home_channel` (str) | optional, but hermes nags every cold start without it | This is what the user just hit on espresso. |
| `DISCORD_HOME_CHANNEL_NAME` | `hosts.json` `config.channels.discord.home_channel_name` (str) | optional, defaults to "Home" | Display name only. |
| `DISCORD_HOME_CHANNEL_THREAD_ID` | `hosts.json` `config.channels.discord.home_channel_thread_id` (str) | optional | If posting to a thread instead of channel root. |
| `DISCORD_ALLOWED_CHANNELS` | `hosts.json` `config.channels.discord.allowed_channels` (list[str], joined `,`) | optional | Restrict bot to specific channels. If omitted, bot responds in any channel it's invited to. |
| `DISCORD_REQUIRE_MENTION` | `hosts.json` `config.channels.discord.require_mention` (bool, lowercased) | optional, hermes default `true` | If false, bot replies to any message in allowed channels (DMs always work either way). |
| `DISCORD_ALLOW_ALL_USERS` | `hosts.json` `config.channels.discord.allow_all_users` (bool, lowercased) | optional (only if `allowed_users` empty) | Open-access shorthand. CLI should print a security warning before accepting. |

Out of scope for v1 (env vars hermes reads but we don't surface):
- `DISCORD_AUTO_THREAD`, `DISCORD_REACTIONS`, `DISCORD_IGNORED_CHANNELS`, `DISCORD_NO_THREAD_CHANNELS`, `DISCORD_REPLY_TO_MODE`, `DISCORD_ALLOW_MENTION_*`, `DISCORD_FREE_RESPONSE_CHANNELS`

These can land in follow-ups; v1 covers the four-key Hot Path (token / allowed_users / home_channel / allowed_channels).

## Schema (hosts.json shape)

After this phase, a configured hermes agent record in `hosts.json` looks like:

```json
{
  "type": "hermes",
  "agent_name": "espresso",
  "config": {
    "api_server": { "enabled": true, "host": "127.0.0.1", "port": 8642 },
    "provider": { "name": "local-inx", "type": "ollama", "default_model": "qwen3-coder:30b-128k", "endpoint": "http://192.168.1.17:11434" },
    "channels": {
      "selected": "discord",
      "discord": {
        "enabled": true,
        "allowed_users": ["740723459344302120"],
        "home_channel": "<channel_id>",
        "home_channel_name": "Home",
        "allowed_channels": [],
        "require_mention": true,
        "allow_all_users": false
      }
    }
  }
}
```

`secrets.json` carries the bearer-equivalent secrets:

```json
{
  "192.168.1.36:hermes:espresso": {
    "HERMES_API_SERVER_KEY": {...},
    "DISCORD_BOT_TOKEN": {"value": "<token>", "description": "Discord bot token", ...}
  }
}
```

**B3 invariant**: `DISCORD_BOT_TOKEN` must never appear in `hosts.json` post-configure. Regression test required (mirror `test_configure_strips_api_server_key_from_persisted_hosts_json`).

## File changes

### Manifest

`src/clawrium/platform/registry/hermes/manifest.yaml` — `onboarding.stages.channels` block:

```yaml
channels:
  required: true
  description: "Configure communication channels (cli always on; discord optional)"
  tasks:
    - id: confirm_cli
      name: "Confirm CLI channel"
      type: confirm
      message: "Hermes will use the loopback api_server platform on 127.0.0.1:8642 as its CLI-equivalent endpoint."
      default: true
    - id: select_discord
      name: "Configure Discord channel (optional)"
      type: confirm
      message: "Enable Discord messaging for this agent?"
      default: false
    # If select_discord=yes, the CLI prompts for token/users/home_channel
    # interactively. The manifest doesn't list each prompt — the CLI handles
    # them based on the discord-enabled flag from this stage's result.
```

(May also need to update the "channels" stage description in `00_PLAN.md`'s acceptance criteria for #316 if we want docs symmetry.)

### Core logic

`src/clawrium/cli/agent.py` (`_run_channels_stage` at line 693):

1. Remove the hermes-restriction guard at lines 715-720; let hermes follow the same channels list `["cli", "discord", "slack"]`. (Slack stays out of scope for hermes — TODO: filter to `["cli", "discord"]` for hermes specifically, since hermes doesn't have slack wiring yet.)
2. After channel selection, branch on `claw_type` for the per-claw config shape:
   - openclaw: existing behavior preserved (the rich `guilds: {<id>: {...}}` shape)
   - hermes: simpler env-var-mapped shape (per the hosts.json schema above)
3. For hermes specifically, add prompts after the existing token / user-id prompts:
   - **home channel ID** (optional; press Enter to skip with a "you'll see a one-time nudge" warning)
   - **home channel name** (optional; defaults to "Home")
   - **allowed channel IDs** (optional, comma-separated; press Enter for "any channel")
   - **require mention** (default `true`)
4. Keep the `set_instance_secret(instance_key, "DISCORD_BOT_TOKEN", bot_token, ...)` call unchanged — the storage path is already correct.
5. Build the `channels_config["discord"]` dict in the hermes shape (NOT the openclaw `guilds: {}` shape).

`src/clawrium/core/lifecycle.py` (`configure_agent` hermes hydration around line 733):

After the existing `api_server.key` hydration block, add a parallel block for Discord:

```python
# Hermes Discord: hydrate the bot token from secrets.json IF the user
# enabled Discord via the channels stage. Mirrors the api_server.key
# hydration pattern. If channels.discord.enabled is false/missing, this
# block is a no-op — no token is hydrated, .env.j2 emits no DISCORD_*.
channels_cfg = config_data.get("channels") or {}
discord_cfg = (channels_cfg.get("discord") or {}) if isinstance(channels_cfg, dict) else {}
if isinstance(discord_cfg, dict) and discord_cfg.get("enabled"):
    discord_secret = get_instance_secrets(instance_key).get("DISCORD_BOT_TOKEN")
    discord_token = discord_secret["value"] if discord_secret else None
    if not isinstance(discord_token, str) or len(discord_token) < 50:
        return (
            False,
            "Discord enabled for this agent but DISCORD_BOT_TOKEN is missing or invalid "
            "in secrets.json. Re-run 'clm agent configure <name> --stage channels' "
            "to set the bot token.",
        )
    discord_cfg["bot_token"] = discord_token
    channels_cfg["discord"] = discord_cfg
    config_data["channels"] = channels_cfg
```

`src/clawrium/core/install.py` — updater closure at the end (around line 995-1020):

Extend the existing `dict(config_data)` strip to also handle Discord:

```python
persisted_config = dict(config_data)
if resolved_type == "hermes":
    if "api_server" in persisted_config:
        api_server_persisted = dict(persisted_config["api_server"])
        api_server_persisted.pop("key", None)
        persisted_config["api_server"] = api_server_persisted
    # B3 invariant for Discord: bot_token lives in secrets.json only.
    channels_persisted = persisted_config.get("channels")
    if isinstance(channels_persisted, dict) and "discord" in channels_persisted:
        channels_persisted = dict(channels_persisted)
        discord_persisted = dict(channels_persisted["discord"])
        discord_persisted.pop("bot_token", None)
        channels_persisted["discord"] = discord_persisted
        persisted_config["channels"] = channels_persisted
```

### Template

`src/clawrium/platform/registry/hermes/templates/.env.j2` — append:

```jinja
# Discord platform (only emitted when channels.discord.enabled).
{% set channels = config.channels | default({}) %}
{% set discord = channels.discord | default({}) if channels else {} %}
{% if discord.enabled and discord.bot_token %}
DISCORD_BOT_TOKEN={{ discord.bot_token }}
{% if discord.allowed_users %}
DISCORD_ALLOWED_USERS={{ discord.allowed_users | join(',') }}
{% endif %}
{% if discord.allow_all_users %}
DISCORD_ALLOW_ALL_USERS=true
{% endif %}
{% if discord.home_channel %}
DISCORD_HOME_CHANNEL={{ discord.home_channel }}
{% endif %}
{% if discord.home_channel_name %}
DISCORD_HOME_CHANNEL_NAME={{ discord.home_channel_name }}
{% endif %}
{% if discord.home_channel_thread_id %}
DISCORD_HOME_CHANNEL_THREAD_ID={{ discord.home_channel_thread_id }}
{% endif %}
{% if discord.allowed_channels %}
DISCORD_ALLOWED_CHANNELS={{ discord.allowed_channels | join(',') }}
{% endif %}
{% if discord.require_mention is defined %}
DISCORD_REQUIRE_MENTION={{ discord.require_mention | lower }}
{% endif %}
{% endif %}
```

Block guarded on `discord.enabled AND discord.bot_token` so a partial config (enabled-but-no-token, after a corrupted hydration) does NOT emit empty `DISCORD_BOT_TOKEN=` to `.env` — that would crash discord.py on startup.

### Playbook

`src/clawrium/platform/registry/hermes/playbooks/configure.yaml` — add after the existing provider verification blocks:

```yaml
- name: Verify .env contains DISCORD_BOT_TOKEN when Discord enabled
  ansible.builtin.command:
    cmd: grep -q '^DISCORD_BOT_TOKEN=' "/home/{{ agent_name }}/.hermes/.env"
  register: discord_token_check
  changed_when: false
  failed_when: discord_token_check.rc != 0
  no_log: true
  when:
    - config.channels is defined
    - config.channels.discord is defined
    - config.channels.discord.enabled | default(false)

- name: Verify .env contains DISCORD_ALLOWED_USERS or DISCORD_ALLOW_ALL_USERS when Discord enabled
  ansible.builtin.shell: |
    grep -qE '^(DISCORD_ALLOWED_USERS=.+|DISCORD_ALLOW_ALL_USERS=true)' "/home/{{ agent_name }}/.hermes/.env"
  register: discord_allowlist_check
  changed_when: false
  failed_when: discord_allowlist_check.rc != 0
  when:
    - config.channels is defined
    - config.channels.discord is defined
    - config.channels.discord.enabled | default(false)
```

(The second one needs `shell:` because of the alternation.) The restart handler + `/health` probe + service active-state check from Phase 2/4 cover the rest — if hermes can't log into Discord with a bad token, the service either logs an error (visible in journalctl) or `/health` returns non-200 once initialization completes.

**Open question** (research during scaffold): does hermes expose `/health/platforms` listing connected platforms? If yes, add a probe step like `curl /health/platforms | jq '.platforms[] | select(.name=="discord") | .status == "connected"'`. Today we know `/health` returns 200 even if Discord platform init silently fails — that's a coverage gap, but matches the current escape hatch (journalctl grep).

### CLI prompts (hermes-specific home-channel addition)

Reuse the existing token / allowed-user prompts; add 3 more after them when claw_type == "hermes":

```
Discord home channel ID (Enter to skip; you'll see a nudge on every cold start until set): 
Discord home channel name [Home]: 
Allowed channel IDs (comma-separated, Enter for "any channel"): 
Require @mention to respond? [Y/n]: 
```

All except `home_channel` are skippable. Print a warning if home_channel is empty: "Without DISCORD_HOME_CHANNEL, hermes will prompt the user to run /sethome in Discord on each cold start. You can set it later via `clm agent configure <name> --stage channels`."

Non-interactive flags (for automation):

```
--channel-discord                          # implies enabling Discord, requires the next three
--discord-token <token>                    # OR read from --discord-token-file
--discord-allowed-users <id,id,id|all>
--discord-home-channel <id>
--discord-allowed-channels <id,id>         # optional
--discord-require-mention / --no-discord-require-mention
```

## Sequencing (suggested order within the single PR)

1. Update manifest channels stage schema (small, no behavior change yet).
2. Add the hermes branch in `_run_channels_stage` config-building (data only — schema is now in place but `.env.j2` doesn't read it yet, so this commits without runtime effect).
3. Add `lifecycle.configure_agent` hydration block (token comes through; template still doesn't render).
4. Add `install.py` updater-closure strip (B3 invariant guard).
5. Extend `.env.j2` with the Discord block.
6. Add `configure.yaml` verification block.
7. CLI prompts: home channel, allowed channels, require_mention, etc.
8. Tests (parameterized + regression guards).
9. Docs update (`docs/agent-support/hermes.md` — replace deferred section with real walkthrough).
10. E2E on wolf-i: migrate espresso.

Land each step as its own commit if reasonable for review; merge in one PR.

## Tests

### Existing patterns to mirror

- `tests/test_hermes_configure.py::TestHermesApiServerKeySecretsHygiene::test_configure_strips_api_server_key_from_persisted_hosts_json` — copy this shape exactly for Discord:
  - `test_configure_strips_discord_bot_token_from_persisted_hosts_json`
- `tests/test_hermes_configure.py::TestHermesApiServerKeySecretsHygiene::test_is_valid_hermes_api_server_key_*` — add a `_is_valid_discord_bot_token` helper + tests if we centralize validation.
- `test_hermes_with_persisted_key_passes_to_ansible` — copy for Discord (token reaches inventory unchanged).
- `test_hermes_reconfigure_does_not_rotate_persisted_key` — copy for Discord (idempotency: token byte-identical across reconfigures).

### New tests

- `test_channels_stage_hermes_can_select_discord` — assert hermes is no longer restricted to cli-only.
- `test_channels_stage_hermes_discord_writes_secrets_json` — assert `set_instance_secret(... DISCORD_BOT_TOKEN ...)` is called.
- `test_channels_stage_hermes_discord_persists_non_sensitive_to_hosts_json` — assert allowed_users / home_channel / etc. land in `hosts.json` `channels.discord.*`.
- `test_env_j2_renders_all_discord_envvars_when_enabled` — Jinja unit test: render `.env.j2` against a complete hermes Discord config; assert all 7 vars present.
- `test_env_j2_omits_discord_block_when_disabled` — Jinja unit test: no `DISCORD_*` lines when `channels.discord.enabled` is false/missing.
- `test_env_j2_omits_optional_discord_envvars_when_unset` — Jinja unit test: missing `home_channel` / `allowed_channels` / etc. don't render as empty lines.
- `test_configure_rejects_discord_enabled_without_token` — `lifecycle.configure_agent` returns `(False, error)` if `channels.discord.enabled=true` but `secrets.json` has no `DISCORD_BOT_TOKEN`.
- `test_configure_yaml_discord_verify_tasks_gated_on_enabled` — playbook lint / shape test: the new verification tasks have `when: ... discord.enabled` conditions.

Total new test count: ~12-15. Mirrors Phase 2's test density.

## Documentation update

`docs/agent-support/hermes.md` — the Discord section that currently says "deferred":

- Replace with a full walkthrough: interactive `clm agent configure` flow, the four Hot Path prompts, what `DISCORD_HOME_CHANNEL` gets you (no nudge on cold start), the non-interactive flag set.
- Add a Troubleshooting subsection: bot doesn't respond → check allowed_users includes your Discord user ID; bot can't see channel → check Discord permissions + `DISCORD_ALLOWED_CHANNELS` includes the channel; rate-limit errors → backoff.
- Reference the deferred-features list: Slack/Telegram/WhatsApp/etc. still pending separate phases.

`docs/agent-support/index.md` — update the hermes row in the Quick Comparison table: "Discord ✅" replaces "Discord 🚧 (deferred)".

## E2E plan (wolf-i)

Pre-condition: `espresso` agent currently has hand-rolled Discord lines in `~/.hermes/.env`. Goal: replace with clm-managed wiring without service downtime in the test channel.

1. **Snapshot current state**: `ssh xclm@wolf-i 'sudo cat /home/espresso/.hermes/.env' > /tmp/espresso-current.env`. Confirm `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`, `DISCORD_HOME_CHANNEL` lines are present.
2. **Run `clm agent configure espresso --stage channels`** with the new code. Select discord, paste the same token / user ID / home channel ID from the snapshot. Expect:
   - `secrets.json` instance entry gains `DISCORD_BOT_TOKEN`.
   - `hosts.json` `agents.espresso.config.channels.discord` is populated (no `bot_token` field).
   - `~/.hermes/.env` is re-rendered; diff against snapshot should show only:
     - Manual comment "# --- manual Discord wiring ---" removed
     - Same `DISCORD_*` lines present (possibly re-ordered)
3. **Restart hermes-espresso**. Watch `/health` and `journalctl` for Discord init. Verify ESTAB sockets to Cloudflare IPs.
4. **Send a Discord message** from the allowed user. Bot should respond via local-inx Ollama, same as before — no behavioral change.
5. **Test idempotency**: run `clm agent configure espresso --stage channels` again (or any stage). Verify `DISCORD_BOT_TOKEN` in `secrets.json` is byte-identical to before. `.env` is byte-identical (modulo ordering).
6. **Test removal**: `clm agent remove espresso --force`. Verify `secrets.json` instance entry purged (including Discord). Re-install + re-configure; expect to be prompted for a fresh bot token (no leftover from previous instance).

Cleanup: don't actually remove espresso after the test; leave it running with the new clm-managed wiring.

## Risks / unknowns

1. **`/sethome` from Discord side**: If a user uses hermes' built-in slash command to set the home channel, hermes writes to `~/.hermes/config.yaml` under a `discord:` block. clm's `config.yaml.j2` is `force: yes`, so a subsequent `clm agent configure` would WIPE that. Mitigation: when rendering `config.yaml.j2`, either (a) ensure the template includes a `discord:` block with the channels-stage values, OR (b) switch to a non-force rendering strategy that preserves sections. Recommend (a) — extend `config.yaml.j2` to also emit `discord:` settings, sourced from `hosts.json`. This makes clm authoritative.

2. **Discord-init failures are silent**: hermes default log level is WARNING, so successful Discord init produces zero log output. A failed login (bad token) MIGHT log at WARNING (need to verify). The `/health` endpoint may not reflect Discord platform status. Mitigation: during E2E, set `LOG_LEVEL=INFO` temporarily and confirm Discord init log line; add to plan if found.

3. **`DISCORD_ALLOW_ALL_USERS=true` is dangerous**: open bot to any Discord user. CLI must print a security warning and require an explicit confirm. Don't silently accept "all" as a shorthand without a second prompt.

4. **Channels stage state machine**: today the channels stage is `confirm_cli` only. Allowing discord changes the stage's run semantics — needs to complete with one of {cli, cli+discord} and update the onboarding state. Verify the stage transitions to `validate` correctly for both shapes (test_onboarding.py coverage).

5. **Multi-bot per host**: Two hermes agents on the same host with different Discord bots is allowed by design (each `~/.hermes/.env` is isolated). Verify no port conflicts at api_server level (they run on different default ports? Or do they collide on 8642?). Phase 2's manifest pins `port: 8642` — multi-instance MUST use different ports. Out of scope for v1; flag if it bites during E2E.

6. **Pre-existing openclaw shape mismatch**: `_run_channels_stage` today builds the openclaw `guilds: {<id>: {users: [...], channels: {...}}}` shape. The hermes branch will build a flatter shape. CLI code must branch cleanly — a single `else: build_openclaw_shape()` after `if claw_type == "hermes": build_hermes_shape()` is fine.

## Out of scope (track follow-ups)

- Slack, Telegram, WhatsApp, Signal, Teams, Google Chat, Matrix, Mattermost, QQBot, Feishu, DingTalk, etc. — each its own phase.
- Advanced Discord features: auto-threading (`DISCORD_AUTO_THREAD`), reactions (`DISCORD_REACTIONS`), ignored channels, no-thread channels, reply-to-mode, mention permissions, free-response channels. Add knobs incrementally as users request.
- Discord OAuth flow for bot installation. clm assumes the user already has an installed Discord bot with a token.
- Multi-instance hermes Discord (two espresso-like agents on the same host with different bots). Probably works due to per-agent `.env` isolation but untested.
- `clm chat <hermes-name>` over the local OpenAI gateway — that's #322, separate work.

## Acceptance criteria

(Mirrors #324 issue body acceptance section.)

- [ ] `clm agent configure <hermes-name>` with channels=cli,discord renders `.env` with all selected `DISCORD_*` vars; agent connects to Discord on restart.
- [ ] `DISCORD_BOT_TOKEN` in `secrets.json`, NOT `hosts.json` (regression test required).
- [ ] Re-configure preserves the bot token byte-identical across runs (idempotency).
- [ ] `clm agent remove <name>` purges Discord secrets via existing `remove_instance_secrets()` (regression test).
- [ ] Non-interactive flags `--discord-token`, `--discord-allowed-users`, `--discord-home-channel`, etc. work for automation.
- [ ] `configure.yaml` verification block confirms `DISCORD_BOT_TOKEN` + an allowlist landed in `.env`.
- [ ] `docs/agent-support/hermes.md` Discord section is a real walkthrough (no "deferred" callout).
- [ ] Migrate the `espresso` agent on wolf-i from hand-rolled to clm-managed; manual `.env` lines deleted; clm-rendered output equivalent; service stays connected to Discord; existing Discord channel still works end-to-end.
- [ ] `make test` green (1566 baseline + ~12-15 new).
- [ ] `make lint` clean.
- [ ] ATX review > 3/5 with no blocking issues.

## Subtasks

**None — single-task execution.**

Single PR is appropriate given:
- Scope is bounded (one platform — Discord).
- All file changes are mechanically related (manifest → CLI → core → template → playbook → tests → docs).
- Phase 2 (PR #318) was similar size and shipped as one PR.

If implementation surfaces a chunk that wants to land separately (e.g. the `config.yaml.j2` discord-section extension from Risk #1), open a follow-up rather than splitting Phase 6.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-10T20:35:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 324
```

Context: triggered after #324 was filed by the orchestrator. Plan-create explores the codebase (which already has Discord wiring for openclaw/zeroclaw) and narrows the scope significantly — Phase 6 is mostly removing the hermes guard + translating the existing config shape into hermes' env-var contract + a B3-pattern token persistence path.

</details>

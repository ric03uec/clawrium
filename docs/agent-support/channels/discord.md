# Discord

**Status:** ✅ Supported on OpenClaw, Hermes, and ZeroClaw (each uses a different on-disk shape — see the agent-specific sections below).

Discord channel allows your agent to operate as a bot in Discord servers.

## Features

- **Server bot:** Responds to messages in Discord channels
- **Allowlisting:** Control which users can interact
- **Channel restrictions:** Limit to specific channels
- **Thread support:** Conversations in threads
- **Rich formatting:** Markdown, embeds, reactions

## Setup

### 1. Create Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**
3. Name it (e.g., "My Claw Agent")
4. Go to **Bot** section
5. Click **Add Bot**
6. Enable **Message Content Intent** (required for reading messages)
7. Copy the **Token** (starts with `MTA...` or similar)

### 2. Invite Bot to Server

1. Go to **OAuth2** → **URL Generator**
2. Select scopes:
   - `bot`
   - `applications.commands` (optional, for slash commands)
3. Select bot permissions:
   - **Send Messages**
   - **Read Message History**
   - **Embed Links**
   - **Add Reactions**
   - **Use External Emojis**
   - **Read Messages/View Channels**
4. Copy the generated URL
5. Open URL in browser and select your server

### 3. Configure Channel in Clawrium

During agent onboarding:

```bash
clawctl agent configure my-agent
```

When prompted for channels:
1. Select **Discord**
2. Enter bot token (from step 1)
3. Enter your Discord server (guild) ID:
   - Enable Developer Mode in Discord (Settings → Advanced)
   - Right-click server name → **Copy Server ID**
4. Enter channel ID:
   - Right-click channel → **Copy Channel ID**
5. Enter your user ID (for auto-approve):
   - Right-click your username → **Copy User ID**

### 4. Start Agent

```bash
clawctl agent start my-agent
```

The bot will come online in your Discord server.

## Configuration Details

The Discord configuration includes:

```json
{
  "discord": {
    "enabled": true,
    "token": {
      "source": "env",
      "id": "DISCORD_BOT_TOKEN"
    },
    "allowFrom": ["USER_ID_1", "USER_ID_2"],
    "groupPolicy": "allowlist",
    "guilds": {
      "GUILD_ID": {
        "users": ["USER_ID_1"],
        "channels": {
          "CHANNEL_ID": {
            "allow": true
          }
        }
      }
    }
  }
}
```

## Security

- Bot token is stored securely (not in plain text)
- Allowlist controls who can trigger the agent
- Channel restrictions limit where it responds
- Consider creating a dedicated channel for the bot

## Usage

Once running, interact with the bot by:
- Mentioning it: `@MyBot analyze this code`
- Sending messages in allowed channels
- The bot will respond in the same channel

## Troubleshooting

**"Bot not responding"**
- Check bot is online in Discord
- Verify bot token is correct
- Check allowlist includes your user ID
- Ensure channel is in allowed channels list

**"Token invalid"**
- Regenerate token in Discord Developer Portal
- Re-register the channel: `clawctl channel registry create <channel-name> --type discord --token-stdin <<<"$NEW_TOKEN"` then `clawctl agent sync <agent-name>` (the existing attachment picks up the new token)

**"Missing permissions"**
- Re-invite bot with correct permissions
- Check bot role has required permissions in server

**"Message intent required"**
- Enable **Message Content Intent** in Bot settings
- This is required for the bot to read message content

---

## Hermes Configuration

Hermes uses a simpler configuration model than OpenClaw — env vars rendered directly into `~/.hermes/.env`. There are no SecretRef objects; the bot token is written as a plain value in the env file (mode 0600 on the agent host).

### Env vars rendered by clawctl

| Variable | Required | Description |
|----------|:--------:|-------------|
| `DISCORD_BOT_TOKEN` | yes | Bot token from the Discord developer portal |
| `DISCORD_ALLOWED_USERS` | yes (or `DISCORD_ALLOW_ALL_USERS=true`) | Comma-separated Discord user IDs (17–19 digits) |
| `DISCORD_ALLOW_ALL_USERS` | no | `true` to allow any user (asks for confirmation in the wizard) |
| `DISCORD_HOME_CHANNEL` | no | Channel ID for cron/scheduled messages |
| `DISCORD_HOME_CHANNEL_NAME` | no | Display name (defaults to `Home`) |
| `DISCORD_HOME_CHANNEL_THREAD_ID` | no | Specific thread ID for scheduled messages |
| `DISCORD_ALLOWED_CHANNELS` | no | Restrict bot to specific channel IDs (empty = any channel the bot was invited to) |
| `DISCORD_REQUIRE_MENTION` | no | `true` (default): require `@mention` in guild channels; DMs always work |

### Setup (Hermes)

```bash
# 1. Register the channel in the registry (one record, reusable across agents)
clawctl channel registry create <channel-name> --type discord \
  --token-stdin <<<"$BOT_TOKEN" \
  --allowed-user 740723459344302120 \
  --home-channel 1503238729962356777 \
  --require-mention

# 2. Attach the channel to the agent
clawctl agent channel attach <channel-name> --agent <hermes-name>

# 3. Sync the agent (renders ~/.hermes/.env and restarts the unit)
clawctl agent sync <hermes-name>
```

Flags accepted by `clawctl channel registry create` (canonical fields, persisted in `~/.config/clawrium/channels.json`):

| Flag | Required | Notes |
|------|:--------:|-------|
| `--type discord` | yes | Channel type. |
| `--token` / `--token-stdin` | yes | Bot token. Stored in `secrets.json` under `channel:<channel-name>`, never in `channels.json`. |
| `--allowed-user <id>` | yes (repeatable) | Discord user IDs (17–19 digits). Hermes silently drops messages from non-allowlisted users. |
| `--home-channel <id>` | optional | Default channel ID. Without this, hermes nudges users to run `/sethome` on every cold start. |
| `--allowed-channel <id>` | optional (repeatable) | Restrict the bot to specific channels. Empty = any channel the bot is invited to. |
| `--require-mention` / `--no-require-mention` | optional | Defaults to true. DMs always work regardless. |

`clawctl agent sync` re-renders `~/.hermes/.env` with the `DISCORD_*` block from the attached channel's registry record and restarts `hermes-<name>.service`. Verification confirms the token + allowlist landed in the env file before sync reports success.

### Resulting on-disk shape (Hermes)

`channels.json` (non-sensitive only — one record per chat surface, reusable across agents):

```json
{
  "<channel-name>": {
    "name": "<channel-name>",
    "type": "discord",
    "config": {
      "allowed_users": ["740723459344302120"],
      "home_channel": "1503238729962356777",
      "require_mention": true
    },
    "created_at": "..."
  }
}
```

`hosts.json` carries only the attachment list:

```json
"agents": {
  "<hermes-name>": {
    "channels": ["<channel-name>"]
  }
}
```

`secrets.json` carries the bot token, keyed by channel name (B3 invariant):

```json
"channel:<channel-name>": {
  "DISCORD_BOT_TOKEN": {"value": "<token>", "description": "Discord bot token"}
}
```

The bot token **never** lands in `channels.json` or `hosts.json` — `clawctl channel registry create` strips it into `secrets.json` before persisting.

### Removal (Hermes)

`clawctl agent channel detach <channel-name> --agent <hermes-name>` removes the attachment. `clawctl agent sync <hermes-name>` then re-renders `~/.hermes/.env` without the `DISCORD_*` block. To delete the channel from the registry (and its secret): `clawctl channel registry delete <channel-name> --yes --force`.

### Hermes-specific troubleshooting

<details>
<summary><strong>Bot is online but doesn't respond in the test channel</strong></summary>

1. Confirm your Discord user ID is in the channel registry's `allowed_users` (run `clawctl channel registry describe <channel-name>`). Hermes silently drops messages from non-allowlisted users.
2. If `require_mention` is true (default), the bot only responds to messages that `@mention` it directly in a guild channel. DMs always work.
3. Confirm the bot has the right Discord permissions in the guild: Send Messages, Read Message History, Use Slash Commands.
4. If `allowed_channels` is non-empty, the bot only responds in those channel IDs.

</details>

<details>
<summary><strong>Service is active but Discord init silently fails</strong></summary>

Hermes' default log level is WARNING, and Discord-init success/failure logs at INFO. The `/health` endpoint returns 200 even if the Discord platform failed to register. To check:

```bash
ssh <agent-host> "sudo journalctl -u hermes-<name>.service -n 200 --no-pager | grep -iE 'discord|platform'"
```

If you see nothing, temporarily bump `LOG_LEVEL=INFO` in `~/.hermes/.env` (manual edit — note the override will be wiped on next `clawctl agent configure`) and restart the service. The Discord init line will read `INFO  hermes.platforms.discord: connected as <bot-name>#<discriminator>`.

</details>

<details>
<summary><strong><code>DISCORD_ALLOW_ALL_USERS=true</code> is set and I want to lock it down</strong></summary>

Re-create the channel record with specific user IDs: `clawctl channel registry delete <channel-name> --yes --force` then `clawctl channel registry create <channel-name> --type discord --token-stdin <<<"$BOT_TOKEN" --allowed-user <id1> --allowed-user <id2>`. Re-attach with `clawctl agent channel attach <channel-name> --agent <name>` and `clawctl agent sync <name>` — the next `~/.hermes/.env` render drops `DISCORD_ALLOW_ALL_USERS` entirely.

</details>

### Non-interactive flags (Hermes)

The `clawctl channel registry create` flags listed in [Setup (Hermes)](#setup-hermes) accept all values non-interactively, including `--token-stdin` for the bot token. Compose with `clawctl agent channel attach` and `clawctl agent sync` for fully scripted setup.

---

## ZeroClaw Configuration

ZeroClaw consumes Discord credentials via **inline TOML**, not env vars. The bot token lives directly in `~/.zeroclaw/config.toml` under `[channels.discord]`, mode 0600. This differs from Hermes (env-based) and OpenClaw (env-based). Source of truth: zeroclaw upstream `docs/book/src/channels/chat-others.md` (v0.7.5).

### Schema rendered by clawctl

The clawctl-managed `[channels.discord]` block uses **only** the keys documented in zeroclaw v0.7.5:

| TOML key | Source field in `hosts.json` `channels.discord.*` | Notes |
|---|---|---|
| `enabled = true` | always emitted when `enabled` is true and the bot token is hydrated | gating |
| `bot_token = "..."` | hydrated from `secrets.json` `DISCORD_BOT_TOKEN` by `lifecycle.configure_agent` | inline TOML, never persisted in `hosts.json` |
| `allowed_users = [...]` | `allowed_users` | empty array if unset |
| `allowed_guilds = [...]` | `allowed_guilds` | empty array if unset; zeroclaw-specific (no hermes equivalent) |
| `reply_to_mentions_only` | `require_mention` | renamed to match the upstream key |
| `draft_update_interval_ms` | `draft_update_interval_ms` | optional — defaults handled by the daemon when omitted |
| `stream_mode` | `stream_mode` | `"off"` / `"partial"` / `"multi_message"`. Wizard default is `"partial"` so long turns surface mid-turn progress to Discord instead of going silent until done. Upstream default is `"off"`. |
| `multi_message_delay_ms` | `multi_message_delay_ms` | optional — only consulted when `stream_mode = "multi_message"`. Wizard prompts in the 10000–60000 ms range (10–60 s) so multi-paragraph responses stay under Discord's ~5 messages / 5 s per-channel rate limit; the daemon's compiled-in default applies when omitted. |

### Hermes-side fields with no ZeroClaw equivalent

These wizard inputs land in `hosts.json` but are **not** rendered into `~/.zeroclaw/config.toml`:

- `home_channel`, `home_channel_name`, `home_channel_thread_id` — no upstream zeroclaw concept of a "home" channel.
- `allow_all_users` — zeroclaw uses an empty `allowed_users = []` array to mean "allow everyone"; the boolean has no direct upstream representation.
- `allowed_channels` — zeroclaw's upstream `allowed_destinations` is the nearest concept but is documented only generically (`channels/overview.md`), not under the Discord-specific schema; clawctl does not emit it pending a confirmed mapping.

If you set any of these via the wizard for a zeroclaw agent, they persist to `hosts.json` for forward compatibility but have no runtime effect.

### Setup (ZeroClaw)

```bash
# 1. Register the channel in the registry
clawctl channel registry create <channel-name> --type discord \
  --token-stdin <<<"$BOT_TOKEN" \
  --allowed-guild 987654321098765432 \
  --allowed-user 740723459344302120 \
  --require-mention \
  --stream-mode partial

# 2. Attach to the zeroclaw agent
clawctl agent channel attach <channel-name> --agent <zeroclaw-name>

# 3. Sync (renders ~/.zeroclaw/config.toml with [channels.discord] and restarts the unit)
clawctl agent sync <zeroclaw-name>
```

Flags accepted (zeroclaw schema, per v0.7.5 upstream):

| Flag | Renders to TOML |
|------|-----------------|
| `--type discord` | gating |
| `--token` / `--token-stdin` | `bot_token` (inline TOML; never in `channels.json`) |
| `--allowed-user <id>` (repeatable) | `allowed_users = [...]` |
| `--allowed-guild <id>` (repeatable) | `allowed_guilds = [...]` |
| `--require-mention` / `--no-require-mention` | `mention_only = true/false` (default true) |
| `--stream-mode <off\|partial\|multi_message>` | `stream_mode = "..."` |
| `--stream-delay <ms>` | `draft_update_interval_ms` (partial) or `multi_message_delay_ms` (multi_message) |

`clawctl agent sync` re-renders `~/.zeroclaw/config.toml` with the `[channels.discord]` block from the attached channel's registry record, restarts `zeroclaw-<name>.service`, and verifies the block landed by grepping for `^bot_token =`.

### Streaming progress on long-running turns

Without `stream_mode`, zeroclaw buffers the whole turn before posting — agents working through long tool sequences (e.g. building a PR) appear silent in Discord until they finish. `stream_mode` controls this:

| Value | Behaviour |
|---|---|
| `off` | Upstream default. Single message posted when the turn completes. |
| `partial` (wizard default) | Edits a single draft message in place as the agent runs tools, then finalizes with the full response. Companion knob: `draft_update_interval_ms` (default 500 ms; bump to 750–1000 if you hit Discord rate limits). |
| `multi_message` | Splits the final reply into multiple messages at paragraph boundaries with `multi_message_delay_ms` between bubbles. Doesn't surface tool progress — only paces the final. |

### Resulting on-disk shape (ZeroClaw)

```toml
[channels.discord]
enabled = true
bot_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4Cg.G..."
allowed_guilds = ["987654321098765432"]
allowed_users = ["740723459344302120"]
reply_to_mentions_only = true
draft_update_interval_ms = 750
stream_mode = "partial"
```

In `channels.json` (one record per chat surface):

```json
{
  "<channel-name>": {
    "name": "<channel-name>",
    "type": "discord",
    "config": {
      "allowed_users": ["740723459344302120"],
      "allowed_guilds": ["987654321098765432"],
      "require_mention": true,
      "stream_mode": "partial"
    }
  }
}
```

`hosts.json` carries only the attachment list under `agents.<name>.channels[]`. `bot_token` lives **only** in `secrets.json` under `channel:<channel-name>:DISCORD_BOT_TOKEN` (mode 0600).

### Removal (ZeroClaw)

`clawctl agent channel detach <channel-name> --agent <name>` then `clawctl agent sync <name>`. On the next render, the `[channels.discord]` block disappears from `config.toml` and the daemon stops listening on Discord on restart. To also wipe the channel from the registry (and its token): `clawctl channel registry delete <channel-name> --yes --force`.

### ZeroClaw-specific troubleshooting

<details>
<summary><strong>Bot connects but doesn't reply to my messages</strong></summary>

1. Confirm your Discord user ID is in the channel registry's `allowed_users` (run `clawctl channel registry describe <channel-name>`). The rendered `~/.zeroclaw/config.toml` under `[channels.discord]` `allowed_users` must contain your ID — empty array means **allow all users** (zeroclaw upstream convention).
2. If `reply_to_mentions_only = true`, the bot only responds when @-mentioned.
3. Check the Discord Developer Portal: the bot must have `Message Content Intent` and `Server Members Intent` enabled (zeroclaw upstream requirement).

</details>

<details>
<summary><strong>Bot didn't connect after configure</strong></summary>

```bash
ssh <agent-host> "sudo journalctl -u zeroclaw-<name>.service -n 200 --no-pager | grep -iE 'discord|channel'"
```

If the daemon logged a token error, rotate the bot token in the Discord Developer Portal, re-create the channel record (`clawctl channel registry delete` then `clawctl channel registry create` with the new token), re-attach if needed, and `clawctl agent sync <name>` to push the new value.

</details>

---

[Back to Channels](index.md)

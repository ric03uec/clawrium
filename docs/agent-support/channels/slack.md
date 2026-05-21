# Slack

**Status:** ✅ Supported (OpenClaw, Hermes)

**Mode:** Socket Mode (default) — outbound WebSocket, no public endpoint needed.

Slack channel allows your agent to operate as a bot in Slack workspaces, responding to mentions, DMs, and thread messages.

---

## Token Model

Socket Mode requires **two tokens**:

| Token | Prefix | Secret Name | Purpose |
|-------|--------|-------------|---------|
| **Bot Token** | `xoxb-` | `SLACK_BOT_TOKEN` | Authenticates bot actions (send messages, read channels) |
| **App Token** | `xapp-` | `SLACK_APP_TOKEN` | Authenticates the WebSocket connection to Slack |

Both tokens use SecretRef objects in config and fall back to environment variables.

### Env Fallback

For the default account, tokens resolve from environment if not in config:

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

---

## ⚠️ Critical Prerequisites for DMs

**Before creating your Slack app**, understand that these permissions are **non-negotiable** for direct messages to work:

### Required OAuth Scopes
Without these, you **cannot DM the bot**:
- ✅ `im:history` - Bot MUST be able to read DM history
- ✅ `im:read` - Bot MUST be able to access DM metadata  
- ✅ `im:write` - Bot MUST be able to write to DMs (⚠️ see security note below — applies to both OpenClaw and Hermes)
- ✅ `chat:write` - Bot MUST be able to send messages

> **⚠️ Security note on `im:write` (applies to OpenClaw *and* Hermes):** This scope lets the bot *initiate* unsolicited DMs to **any** workspace member — neither OpenClaw's `allowFrom` nor Hermes' `SLACK_ALLOWED_USERS` gate outbound messages. A compromised agent host or leaked `xoxb-` token can DM-spam or phish the entire workspace. Mitigations: keep the host hardened; treat the bot token as a high-value secret; rotate the token immediately on suspicion (Slack API → **OAuth & Permissions** → **Rotate Tokens** → re-run `clm agent configure <name> --stage channels` with the new bearer); audit `users:read` calls in your workspace's Slack audit log if you suspect abuse.

### Required Event Subscriptions
Without these, the bot **will not receive your DMs**:
- ✅ `message.im` - Fires when you send a DM to the bot (**CRITICAL**)
- ✅ `app_mention` - Fires when you @-mention the bot in channels

### What Happens Without These?
- **Missing `im:*` scopes:** Slack UI won't let you message the bot (Message button disabled/missing in Slack app directory)
- **Missing `message.im` event:** Bot receives no notification when you DM it (messages sent but bot never sees them)
- **Missing `chat:write` scope:** Bot can receive messages but cannot respond

**Verification After Setup:** 
1. Go to https://api.slack.com/apps → Select your app
2. Navigate to **Event Subscriptions** → **Subscribe to bot events**
3. Confirm `message.im` is listed
4. If not, add it and **reinstall the app to your workspace** (required for changes to take effect)

---

## Setup

### Step 1: Create a Slack App

1. Go to **[https://api.slack.com/apps/new](https://api.slack.com/apps/new)**
2. Choose **From a manifest**
3. Select your workspace
4. Paste this manifest (includes all required scopes and events for DM support):

```json
{
  "display_information": {
    "name": "OpenClaw",
    "description": "Slack connector for OpenClaw"
  },
  "features": {
    "bot_user": {
      "display_name": "OpenClaw",
      "always_online": true
    },
    "app_home": {
      "messages_tab_enabled": true,
      "messages_tab_read_only_enabled": false
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "app_mentions:read",
        "channels:history",
        "channels:read",
        "chat:write",
        "im:history",
        "im:read",
        "im:write",
        "mpim:history",
        "mpim:read",
        "mpim:write",
        "reactions:read",
        "reactions:write",
        "users:read",
        "pins:read"
      ]
    }
  },
  "settings": {
    "socket_mode_enabled": true,
    "event_subscriptions": {
      "bot_events": [
        "app_mention",
        "message.channels",
        "message.im",
        "message.mpim",
        "reaction_added",
        "member_joined_channel"
      ]
    }
  }
}
```

> **Note:** The manifest includes `im:history`, `im:read`, `im:write` (DM scopes) and `message.im` (DM event) which are **required** for direct messaging. Without these, users cannot send DMs to your bot.

5. Click **Create**

### Step 2: Generate App-Level Token

This is the `xapp-` token required for Socket Mode.

1. Go to **Basic Information** (sidebar) > **App-Level Tokens**
2. Click **Generate Token and Scopes**
3. Name it: `socket-mode`
4. Add scope: **`connections:write`**
5. Click **Generate**
6. **Copy the token** — it starts with `xapp-`
7. Save this — you'll enter it as `SLACK_APP_TOKEN` during configuration

### Step 3: Verify Event Subscriptions (Critical for DMs)

Before installing, verify the event subscriptions are correct:

1. Go to **Event Subscriptions** (sidebar)
2. Confirm **Enable Events** is ON
3. Scroll to **Subscribe to bot events**
4. **Verify `message.im` is in the list** (required for DMs)
5. If `message.im` is missing:
   - Click **Add Bot User Event**
   - Select `message.im`
   - Click **Save Changes**

> **Why this matters:** Without `message.im`, your bot will never receive direct messages. This is the #1 reason DMs don't work.

### Step 4: Install App to Workspace

1. Go to **OAuth & Permissions** (sidebar)
2. Click **Install to Workspace**
3. Authorize the app
4. **Copy the Bot User OAuth Token** — it starts with `xoxb-`
5. Save this — you'll enter it as `SLACK_BOT_TOKEN` during configuration

### Step 5: Invite Bot to a Channel

In Slack, go to the channel where you want the bot and type:

```
@OpenClaw
```

Slack will prompt you to invite the bot to the channel.

### Step 6: Get Your User ID

1. In Slack, click your profile picture (top right)
2. Click **⋯** (three dots) > **Copy Member ID**
3. The ID starts with `U` (e.g., `U01ABC2DEF`)
4. This goes in the `allowFrom` list during configuration

### Step 7: Configure in Clawrium

```bash
clm agent configure <agent-name>
# Select "slack" when prompted for channel
# Enter your Bot Token, App Token, and User ID
```

Or reconfigure just the channels stage:

```bash
clm agent configure <agent-name> --stage channels
```

---

## Configuration Structure

After setup, the Slack config in your agent's `openclaw.json` looks like:

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "mode": "socket",
      "botToken": {
        "source": "env",
        "provider": "default",
        "id": "SLACK_BOT_TOKEN"
      },
      "appToken": {
        "source": "env",
        "provider": "default",
        "id": "SLACK_APP_TOKEN"
      },
      "allowFrom": ["U01ABC2DEF"],
      "groupPolicy": "allowlist",
      "dmPolicy": "pairing"
    }
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable Slack channel |
| `mode` | string | `"socket"` | Connection mode (Socket Mode) |
| `botToken` | SecretRef | — | Bot token reference (`xoxb-...`) |
| `appToken` | SecretRef | — | App-level token reference (`xapp-...`) |
| `allowFrom` | string[] | `[]` | User IDs allowed to interact with the bot |
| `groupPolicy` | string | `"allowlist"` | Group access policy: `open`, `allowlist`, `disabled` |
| `dmPolicy` | string | `"pairing"` | DM access policy: `pairing`, `allowlist`, `open`, `disabled` |

### SecretRef Object

Tokens use SecretRef objects instead of plaintext values. The secret value is stored in Clawrium's encrypted secrets storage, not in config files.

```json
{
  "source": "env",
  "provider": "default",
  "id": "SLACK_BOT_TOKEN"
}
```

At runtime, OpenClaw resolves the token from the environment file written by Clawrium.

---

## Hermes Configuration

Hermes uses a simpler configuration model — env vars rendered directly into `~/.hermes/.env`. There are no SecretRef objects; tokens are written as plain values in the env file (mode 0600 on the agent host).

### Env vars rendered by clm

| Variable | Required | Description |
|----------|:--------:|-------------|
| `SLACK_BOT_TOKEN` | yes | Bot User OAuth Token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | yes | App-Level Token for Socket Mode (`xapp-...`) |
| `SLACK_ALLOWED_USERS` | yes | Comma-separated Slack Member IDs (e.g., `U01ABC2DEF3,U04XYZ7GHI8`) |
| `SLACK_HOME_CHANNEL` | no | Channel ID for cron/scheduled messages (e.g., `C01234567890`) |
| `SLACK_HOME_CHANNEL_NAME` | no | Display name for the home channel |

### Required scopes (minimal set for Hermes)

> **⚠️ Critical for DMs:** The three `im:*` scopes below are **required** for direct messaging. Without them, users cannot DM the bot in Slack.

| Scope | Required For | What Breaks Without It |
|-------|--------------|------------------------|
| `app_mentions:read` | Channels | Bot won't see @-mentions in channels |
| `chat:write` | All | Bot cannot send any messages (DMs or channels) |
| `channels:read` | Channels | Bot cannot list/join public channels |
| `groups:read` | Private Channels | Bot cannot list private channels it's in |
| `im:history` | **DMs** | **Bot cannot read DM history (DMs fail)** |
| `im:read` | **DMs** | **Bot cannot access DM metadata (DMs fail)** |
| `im:write` | **DMs** | **Slack won't allow users to message the bot** |
| `users:read` | All | Bot cannot look up user info for allowlist checks |

> **⚠️ Security note on `im:write`:** This scope also permits the bot to *initiate* unsolicited DMs to **any** workspace member — the `SLACK_ALLOWED_USERS` allowlist only gates inbound commands, not outbound messages. A compromised agent host or leaked bot token could DM-spam or phish the entire workspace. Keep the agent host hardened and the `xoxb-` bot token in `secrets.json` only. **On suspicion of leakage:** rotate via Slack API → **OAuth & Permissions** → **Rotate Tokens**, then re-run `clm agent configure <name> --stage channels` with the new bearer.

### Required event subscriptions

> **⚠️ Critical for DMs:** Without `message.im`, the bot will never receive your direct messages even if you can send them.

| Event | Required For | What Breaks Without It |
|-------|--------------|------------------------|
| `app_mention` | Channels | Bot won't respond to @-mentions |
| `message.im` | **DMs** | **Bot receives no notification when you DM it** |

### Access control differences from OpenClaw

| Aspect | OpenClaw | Hermes |
|--------|----------|--------|
| **Config location** | `openclaw.json` (SecretRef objects) | `~/.hermes/.env` (plain env vars) |
| **DM policy** | Configurable (`pairing`, `allowlist`, `open`, `disabled`) | `SLACK_ALLOWED_USERS` allowlist only |
| **Group policy** | Configurable (`open`, `allowlist`, `disabled`) | Channel membership controls access (invite-only) |
| **Token storage** | `secrets.json` → rendered to env at runtime | `secrets.json` → rendered to `.env` at configure time |

Hermes uses **Socket Mode** — the bot maintains an outbound WebSocket to Slack, so no public endpoint or ingress is required on the agent host.

### Interactive setup (Hermes)

```bash
clm agent configure <hermes-name> --stage channels
```

The wizard offers `cli`, `discord`, and `slack`. Pick `slack` and the CLI prompts for:

| Prompt | Stored where | Required | Notes |
|--------|--------------|:--------:|-------|
| Slack Bot Token | `secrets.json` as `SLACK_BOT_TOKEN` | yes | Masked input. Must start with `xoxb-`. |
| Slack App Token | `secrets.json` as `SLACK_APP_TOKEN` | yes | Masked input. Must start with `xapp-`. |
| Allowed Slack user IDs | `hosts.json` `channels.slack.allowed_users` | yes | Comma-separated Member IDs (format: `U` + 8+ alphanumeric chars). |
| Slack home channel ID | `hosts.json` `channels.slack.home_channel` | optional | Channel for cron/scheduled messages. Format: `C` + alphanumeric. |
| Slack home channel name | `hosts.json` `channels.slack.home_channel_name` | optional | Display name for the home channel. |

`clm` then runs the configure playbook which re-renders `~/.hermes/.env` with the `SLACK_*` block and restarts `hermes-<name>.service`.

### Resulting on-disk shape (Hermes)

`hosts.json` (non-sensitive only):

```json
"config": {
  "api_server": {"enabled": true, "host": "127.0.0.1", "port": 8642},
  "provider": {...},
  "channels": {
    "slack": {
      "enabled": true,
      "allowed_users": ["U01ABC2DEF3"],
      "home_channel": "C01234567890",
      "home_channel_name": "general"
    }
  }
}
```

`secrets.json`:

```json
"192.168.1.36:hermes:<name>": {
  "HERMES_API_SERVER_KEY": {...},
  "SLACK_BOT_TOKEN": {"value": "xoxb-...", "description": "Slack bot token", ...},
  "SLACK_APP_TOKEN": {"value": "xapp-...", "description": "Slack app token", ...}
}
```

Both tokens **never** land in `hosts.json` — the configure flow stores them exclusively in `secrets.json` (B3 invariant). Re-running `clm agent configure --stage channels` with the same tokens reuses them byte-identical.

### Rendered `.env` (Slack block, Hermes)

After configure, the relevant section of `~/.hermes/.env` on the agent host looks like:

```env
# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_ALLOWED_USERS=U01ABC2DEF3
SLACK_HOME_CHANNEL=C01234567890
SLACK_HOME_CHANNEL_NAME=general
```

### Removal (Hermes)

`clm agent remove <name> --force` purges the entire instance entry from `secrets.json`, including both Slack tokens. There is no separate "rotate Slack token" command — re-run the channels stage with new tokens to overwrite.

### Hermes-specific troubleshooting

<details>
<summary><strong>Bot connects but gets `missing_scope` errors</strong></summary>

Hermes logs will show errors like `slack_bolt: missing_scope: channels:read`. Go to your Slack app's **OAuth & Permissions** > **Scopes** and add the missing scope. Then **reinstall the app** to your workspace (Slack requires reinstall after scope changes). You do NOT need to re-run `clm agent configure` — the tokens remain valid after reinstall.

</details>

<details>
<summary><strong>Bot gets `not_in_channel` error for home channel</strong></summary>

The bot must be a member of the home channel. In Slack, go to that channel and type `/invite @Hermes`. The `SLACK_HOME_CHANNEL` setting only tells hermes where to post scheduled/cron messages — it doesn't auto-join.

</details>

<details>
<summary><strong>❌ CRITICAL: Bot doesn't respond to DMs</strong></summary>

**This is the most common issue.** Follow these steps in order:

### 1. Can you even send a DM to the bot?
- In Slack, go to **Apps** in the sidebar
- Find your bot
- Try to click **Message**

**If you can't click Message or it's grayed out:**
→ Your Slack app is missing the `im:write` scope. Go to Slack API → OAuth & Permissions → Add `im:write` → Reinstall app to workspace.

**If you can send a DM but bot doesn't respond:**
→ Continue to step 2.

### 2. Verify Event Subscription
- Go to https://api.slack.com/apps
- Select your app
- Go to **Event Subscriptions**
- Scroll to **Subscribe to bot events**
- **Confirm `message.im` is in the list**

**If `message.im` is missing:**
→ Click **Add Bot User Event** → Select `message.im` → **Save Changes** → **Reinstall app to workspace** (required!)

### 3. Verify OAuth Scopes
Go to **OAuth & Permissions** → **Scopes** → **Bot Token Scopes** and confirm:
- ✅ `im:history`
- ✅ `im:read`  
- ✅ `im:write`
- ✅ `chat:write`

**If any are missing:** Add them → Reinstall app to workspace.

### 4. Verify User Allowlist (Hermes only)
Your Slack Member ID must be in the allowed users list. Replace `<name>` with your hermes agent name:
```bash
AGENT=<name>
cat ~/.config/clawrium/hosts.json | jq --arg n "$AGENT" '.[] | select(.agents[$n]) | .agents[$n].config.channels.slack.allowed_users'
```

**Find your Member ID:** Slack profile → ⋯ (three dots) → Copy Member ID

**If your ID is missing:** Run `clm agent configure <name> --stage channels` and add your ID.

### 5. Check Agent Logs
```bash
ssh <agent-host> "sudo journalctl -u hermes-<name> -f"
```

Send a test DM and watch for errors. Common errors:
- `missing_scope: im:history` → Add scope and reinstall app
- `not_authed` → Token expired, regenerate and reconfigure
- Silent (no logs) → Event subscription `message.im` is missing

</details>

<details>
<summary><strong>Bot doesn't respond in channels</strong></summary>

1. The bot only listens for `app_mention` events in channels — you must @-mention it.
2. Confirm the bot has been invited to the channel (`/invite @Hermes`).
3. Verify `app_mentions:read` and `channels:read` scopes are enabled.

</details>

<details>
<summary><strong>Socket Mode not connecting</strong></summary>

1. Verify Socket Mode is enabled in the Slack app settings.
2. Confirm `SLACK_APP_TOKEN` starts with `xapp-` and has the `connections:write` scope.
3. Check the journal: `ssh <agent-host> "sudo journalctl -u hermes-<name>.service -n 200 --no-pager | grep -iE 'slack|socket'"`.

</details>

---

## Access Control

### DM Policy (`dmPolicy`)

| Policy | Behavior |
|--------|----------|
| `pairing` (default) | New DM users must approve via `clm pairing approve slack <code>` |
| `allowlist` | Only users in `allowFrom` can DM |
| `open` | Anyone can DM (requires `allowFrom: ["*"]`) |
| `disabled` | No DMs allowed |

### Group Policy (`groupPolicy`)

| Policy | Behavior |
|--------|----------|
| `allowlist` (default) | Bot only responds in explicitly allowed channels |
| `open` | Bot responds in all channels it's invited to |
| `disabled` | No channel responses |

---

## Troubleshooting

### Bot not responding in channels

- Verify `groupPolicy` is not `disabled`
- Check bot is invited to the channel (`@OpenClaw` in channel)
- Verify `app_mentions:read` and `channels:history` scopes are enabled

### Bot not responding to DMs

- Check `dmPolicy` — default is `pairing`, new users must be approved first
- Run `clm pairing list slack` to see pending approvals

### Socket Mode not connecting

- Verify both `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set
- Check that Socket Mode is enabled in Slack app settings
- Verify the App-Level Token has `connections:write` scope

### "Invalid bot token format" error

- Bot token must start with `xoxb-` and contain only alphanumeric characters and hyphens
- Copy the full token from **OAuth & Permissions** in Slack app settings

### "Invalid app token format" error

- App token must start with `xapp-1-` followed by alphanumeric and hex characters
- Copy the full token from **Basic Information > App-Level Tokens**

---

[Back to Channels](index.md)
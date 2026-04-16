# Discord

**Status:** ✅ Supported (OpenClaw only)

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
clm agent configure my-agent
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
clm agent start my-agent
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
- Re-run: `clm agent configure <name> --stage channels`

**"Missing permissions"**
- Re-invite bot with correct permissions
- Check bot role has required permissions in server

**"Message intent required"**
- Enable **Message Content Intent** in Bot settings
- This is required for the bot to read message content

---

[Back to Channels](index.md)

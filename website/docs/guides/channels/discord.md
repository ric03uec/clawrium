---
sidebar_position: 2
description: Set up Discord channel credentials and permissions for agent onboarding.
keywords: [discord, channels, onboarding, bot token, guild id, channel id]
---

# Discord Channel Setup

Use this guide when selecting Discord as your default channel during onboarding.

## Example - Discord channel

```bash
Select default communication channel:
  1. cli (recommended)
  2. discord

Select [1-2]: 2
✓ Default channel: discord

Discord Configuration
Discord bot token: [hidden input]
Discord server (guild) ID: 123456789012345678
Discord channel ID: 987654321098765432

✓ Discord bot token stored securely
Syncing channel config to agent... ✓
```

## Discord Setup Requirements

Before configuring Discord as your channel, you need:

1. **Create a Discord Bot:**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Navigate to "Bot" section and create a bot
   - Copy the bot token (keep it secret!)

2. **Get Server (Guild) ID:**
   - Enable Developer Mode in Discord (User Settings > Advanced > Developer Mode)
   - Right-click your server name and select "Copy Server ID"
   - IDs are 17-19 digit numbers (e.g., `123456789012345678`)

3. **Get Channel ID:**
   - Right-click the channel where your agent should respond
   - Select "Copy Channel ID"
   - IDs are 17-19 digit numbers (e.g., `987654321098765432`)

4. **Invite Bot to Server:**
   - In Developer Portal, go to OAuth2 > URL Generator
   - Select scopes: `bot`, `applications.commands`
   - Select permissions: `Send Messages`, `Read Message History`, `View Channels`
   - Use generated URL to invite bot to your server

:::tip
The Discord bot token is stored securely as a per-instance secret and synced to the agent's environment as `DISCORD_BOT_TOKEN`.
:::

# Slack Channel

**Status:** 🚧 In Development

Slack channel will allow your agent to operate as a bot in Slack workspaces.

---

## Planned Features

- **Workspace bot:** Responds to messages in Slack channels
- **Direct messages:** One-on-one conversations
- **Slash commands:** `/ask` style commands
- **App Home:** Persistent interface for the bot
- **Thread support:** Conversations in threads
- **Rich formatting:** Slack blocks, attachments

## Timeline

**Target:** Q2 2026

**Milestone:** [SEA](https://github.com/ric03uec/clawrium/milestone/2)

Track progress: [GitHub Issue #229](https://github.com/ric03uec/clawrium/issues/229)

---

## Preliminary Setup (Subject to Change)

### 1. Create Slack App

1. Go to [Slack API](https://api.slack.com/apps)
2. Click **Create New App**
3. Choose **From scratch**
4. Name it and select your workspace

### 2. Configure Bot Token Scopes

Under **OAuth & Permissions**, add scopes:
- `app_mentions:read`
- `channels:history`
- `chat:write`
- `im:history`
- `im:write`
- `users:read`

### 3. Install to Workspace

1. Click **Install to Workspace**
2. Authorize the app
3. Copy the **Bot User OAuth Token**

### 4. Configure in Clawrium (When Available)

```bash
clm agent configure my-agent
# Select Slack when prompted
```

---

## Differences from Discord

| Feature | Discord | Slack |
|---------|---------|-------|
| **Scope** | Server (guild) | Workspace |
| **Permissions** | Role-based | Scope-based |
| **DMs** | Not supported | Supported |
| **Slash commands** | Not planned | Planned |
| **Threads** | Supported | Supported |
| **Rich UI** | Embeds | Blocks |

---

## Vote for Priority

Add a 👍 reaction to [the Slack channel issue](../../issues) to help prioritize.

---

[Back to Channels](index.md)

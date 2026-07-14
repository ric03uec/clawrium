# Channels

Channels define how users interact with your agents. Different agents support different channels based on their design goals.

## Available Channels

| Channel | Agents | Use Case |
|---------|--------|----------|
| **[CLI](cli.md)** | All | Terminal-based interaction |
| **[Discord](discord.md)** | OpenClaw | Discord server bot |
| **[Slack](slack.md)** | OpenClaw | Slack workspace bot |
| **[Web](web.md)** | OpenClaw (planned) | Browser-based chat |
| **[WhatsApp](whatsapp.md)** | Not planned | Mobile messaging |

## Channel Comparison

| Feature | CLI | Discord | Slack | Web |
|---------|-----|---------|-------|-----|
| **Setup Complexity** | Low | Medium | Medium | High |
| **Multi-user** | No | Yes | Yes | Yes |
| **Access Control** | OS-level | Roles | Policies | Auth |
| **Rich Media** | Limited | Yes | Yes | Yes |
| **Mobile Support** | SSH app | Discord app | Slack app | Browser |
| **Connection** | Local | Gateway | Socket Mode | HTTP |
| **Required Tokens** | None | 1 (bot) | 2 (bot + app) | Varies |

## Channel vs Provider

- **Provider** = The AI model (OpenAI, Anthropic, etc.)
- **Channel** = How users talk to the agent (CLI, Discord, etc.)

An agent uses:
- 1 provider (the LLM backend)
- 1+ channels (how users interact)

## Configuration

Channels are managed in two steps:

1. **Register the channel** in the channel registry (one record per chat surface, reusable across agents):

   ```bash
   clawctl channel registry create <channel-name> --type discord --token-stdin <<<"$BOT_TOKEN"
   # or for slack:
   clawctl channel registry create <channel-name> --type slack \
     --token-stdin <<<"$BOT_TOKEN" --app-token "$APP_TOKEN"
   ```

2. **Attach the channel to an agent**:

   ```bash
   clawctl agent channel attach <channel-name> --agent <agent-name>
   clawctl agent sync <agent-name>
   ```

To detach: `clawctl agent channel detach <channel-name> --agent <agent-name>` followed by `clawctl agent sync <agent-name>`.

> **Deprecated:** `clawctl agent configure --stage channels` and writes to `hosts.json.agents.<name>.config.channels.*` are no longer supported. The canonical attachment list is `hosts.json.agents.<name>.channels[]` (see #555).

Note: Some agents (like ZeroClaw) only support CLI and cannot attach chat channels.

---

See individual channel pages for detailed setup instructions.

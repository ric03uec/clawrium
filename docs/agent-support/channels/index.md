# Channels

Channels define how users interact with your agents. Different agents support different channels based on their design goals.

## Available Channels

| Channel | Agents | Use Case |
|---------|--------|----------|
| **[CLI](cli.md)** | All | Terminal-based interaction |
| **[Discord](discord.md)** | OpenClaw | Discord server bot |
| **[Slack](slack.md)** | OpenClaw (planned) | Slack workspace bot |
| **[Web](web.md)** | OpenClaw (planned) | Browser-based chat |
| **[WhatsApp](whatsapp.md)** | Not planned | Mobile messaging |

## Channel Comparison

| Feature | CLI | Discord | Slack | Web |
|---------|-----|---------|-------|-----|
| **Setup Complexity** | Low | Medium | Medium | High |
| **Multi-user** | No | Yes | Yes | Yes |
| **Access Control** | OS-level | Roles | Permissions | Auth |
| **Rich Media** | Limited | Yes | Yes | Yes |
| **Mobile Support** | SSH app | Discord app | Slack app | Browser |

## Channel vs Provider

- **Provider** = The AI model (OpenAI, Anthropic, etc.)
- **Channel** = How users talk to the agent (CLI, Discord, etc.)

An agent uses:
- 1 provider (the LLM backend)
- 1+ channels (how users interact)

## Configuration

Channels are configured during agent onboarding:

```bash
clm agent configure <agent-name>
# Select channel during the channels stage
```

## Switching Channels

To change an agent's channel:

```bash
clm agent configure <agent-name> --stage channels
```

Note: Some agents (like ZeroClaw) only support CLI and cannot switch channels.

---

See individual channel pages for detailed setup instructions.

# OpenClaw Support Matrix

OpenClaw is a full-featured agent supporting multiple LLM providers, communication channels, and third-party integrations.

**Status:** ✅ Production Ready

**Best for:** Discord bots, multi-channel assistants, complex workflows

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully supported and tested |
| 🚧 | In development / Planned |
| ❌ | Not supported |
| 📋 | Not planned (PRs welcome) |

---

## Provider Support

OpenClaw supports all major LLM providers:

| Provider | Status | Configuration | Models |
|----------|:------:|---------------|--------|
| **[OpenAI](providers/openai.md)** | ✅ | [Setup Guide](providers/openai.md) | GPT-4o, GPT-4, GPT-3.5, o1 |
| **[Anthropic](providers/anthropic.md)** | ✅ | [Setup Guide](providers/anthropic.md) | Claude Opus, Sonnet, Haiku |
| **[OpenRouter](providers/openrouter.md)** | ✅ | [Setup Guide](providers/openrouter.md) | Multi-provider gateway |
| **[AWS Bedrock](providers/bedrock.md)** | ✅ | [Setup Guide](providers/bedrock.md) | Claude, Llama, Titan |
| **[Google Vertex](providers/vertex.md)** | ✅ | [Setup Guide](providers/vertex.md) | Gemini series |
| **[ZAI / BigModel](providers/zai.md)** | ✅ | [Setup Guide](providers/zai.md) | GLM series |
| **[Ollama](providers/ollama.md)** | ✅ | [Setup Guide](providers/ollama.md) | Self-hosted models |
| **[Azure OpenAI](providers/azure-openai.md)** | 📋 | [Not Planned](providers/azure-openai.md) | — |

**Quick Setup:**
```bash
clm provider add <name> --type <provider-type>
```

---

## Channel Support

Channels define how users interact with the agent:

| Channel | Status | Configuration | Notes |
|---------|:------:|---------------|-------|
| **[CLI](channels/cli.md)** | ✅ | [Setup Guide](channels/cli.md) | Interactive terminal chat |
| **[Discord](channels/discord.md)** | ✅ | [Setup Guide](channels/discord.md) | Bot with allowlisting |
| **[Slack](channels/slack.md)** | 🚧 | [Milestone SEA](channels/slack.md) | Coming Q2 2026 |
| **[Web Interface](channels/web.md)** | 🚧 | [Milestone SEA](channels/web.md) | Browser-based chat |
| **[WhatsApp](channels/whatsapp.md)** | 📋 | [Not Planned](channels/whatsapp.md) | PRs welcome |

**During Onboarding:**
```bash
clm agent configure <agent-name>
# Select channel during the channels stage
```

---

## Integration Support

Integrations allow the agent to interact with external tools and services:

| Integration | Status | Configuration | Use Case |
|-------------|:------:|---------------|----------|
| **[GitHub](integrations/github.md)** | 🚧 | [Milestone SEA](integrations/github.md) | PR reviews, issues |
| **[Jira](integrations/jira.md)** | 🚧 | [Milestone SEA](integrations/jira.md) | Issue tracking |
| **[GitLab](integrations/gitlab.md)** | 📋 | [Not Planned](integrations/gitlab.md) | PRs welcome |
| **[Confluence](integrations/confluence.md)** | 📋 | [Not Planned](integrations/confluence.md) | PRs welcome |
| **[Linear](integrations/linear.md)** | 📋 | [Not Planned](integrations/linear.md) | PRs welcome |
| **[Notion](integrations/notion.md)** | 📋 | [Not Planned](integrations/notion.md) | PRs welcome |

---

## Additional Features

| Feature | Status | Notes |
|---------|:------:|-------|
| **Custom Identity** | ✅ | SOUL.md + IDENTITY.md |
| **Multi-Provider** | ✅ | Switch providers per request |
| **Secrets Management** | ✅ | Per-instance secret storage |
| **Token Tracking** | 🚧 | Coming Q2 2026 |
| **MCP Tools** | 🚧 | Coming Q2 2026 |
| **Auto-Restart** | ✅ | Supervisor-managed |
| **Log Streaming** | ✅ | Real-time log access |
| **Onboarding Wizard** | ✅ | Guided 4-stage setup |

---

## Getting Started

### 1. Install OpenClaw

```bash
clm agent install --type openclaw --host <host-alias> --name my-assistant
```

### 2. Configure the Agent

```bash
clm agent configure my-assistant
```

The wizard will guide you through:
- Provider selection
- Identity configuration (SOUL.md, IDENTITY.md)
- Channel setup (CLI, Discord, etc.)
- Validation

### 3. Start the Agent

```bash
clm agent start my-assistant
```

### 4. Chat with the Agent

```bash
clm chat my-assistant
```

---

## Troubleshooting

<details>
<summary><strong>"Discord bot token invalid"</strong></summary>

1. Verify the bot token in Discord Developer Portal
2. Re-run: `clm agent configure <name> --stage channels`
3. Ensure the bot has proper server permissions
</details>

<details>
<summary><strong>"Provider connectivity failed"</strong></summary>

1. Check provider status: `clm provider status <provider-name>`
2. Verify API key is set: `clm provider list`
3. Test network connectivity from the host
</details>

<details>
<summary><strong>"Onboarding incomplete"</strong></summary>

Run the full onboarding wizard:
```bash
clm agent configure <agent-name>
```

Or configure a specific stage:
```bash
clm agent configure <agent-name> --stage <stage-name>
```
</details>

---

## Next Steps

- [Agent Onboarding](/docs/guides/agent-onboarding) - Detailed onboarding guide
- [CLI Reference](/docs/reference/cli/agent) - Full command documentation
- [Provider Configuration](/docs/guides/host-setup) - Setting up inference providers

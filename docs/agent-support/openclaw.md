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
| **LiteLLM / vLLM / custom OpenAI-compatible proxy** | ✅ | `clawctl provider registry create <name> --type litellm --litellm-url <proxy> --model <id> --api-key <bearer>` | Any model exposed by the proxy (rendered into `models.providers.<name>` in `openclaw.json` with `api: "openai-completions"`) |
| **[Azure OpenAI](providers/azure-openai.md)** | 📋 | [Not Planned](providers/azure-openai.md) | — |

**Quick Setup:**
```bash
clawctl provider registry create <name> --type <provider-type>
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
clawctl agent configure <agent-name>
# Select channel during the channels stage
```

---

## Integration Support

Integrations allow the agent to interact with external tools and services:

| Integration | Status | Configuration | Use Case |
|-------------|:------:|---------------|----------|
| **[Atlassian (Jira + Confluence)](integrations/atlassian.md)** | ✅ | Single API token covers both Jira and Confluence | Issue tracking, docs / knowledge base |
| **[Slack (MCP tool integration)](integrations/slack.md)** | ✅ | `slack-user` (xoxp; recommended) or `slack-cookie` (xoxc + xoxd; fragile fallback) | Outbound Slack tool calls via [`korotovsky/slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server) stdio subprocess |
| **[GitHub](integrations/github.md)** | 🚧 | [Milestone SEA](integrations/github.md) | PR reviews, issues |
| **[GitLab](integrations/gitlab.md)** | 📋 | [Not Planned](integrations/gitlab.md) | PRs welcome |
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
| **MCP Tools** | ✅ | Slack MCP tools are supported via the [Slack integration](integrations/slack.md); additional MCP-backed integrations remain incremental. |
| **Auto-Restart** | ✅ | Supervisor-managed |
| **Log Streaming** | ✅ | Real-time log access |
| **Onboarding Wizard** | ✅ | Guided 4-stage setup |

---

## Getting Started

### 1. Install OpenClaw

```bash
clawctl agent create --type openclaw --host <host-alias> --name my-assistant
```

### 2. Configure the Agent

```bash
clawctl agent configure my-assistant
```

The wizard will guide you through:
- Provider selection
- Identity configuration (SOUL.md, IDENTITY.md)
- Channel setup (CLI, Discord, etc.)
- Validation

### 3. Start the Agent

```bash
clawctl agent start my-assistant
```

### 4. Chat with the Agent

```bash
clawctl agent chat my-assistant
```

---

## Slack integration

OpenClaw agents can attach the [Slack integration](integrations/slack.md) (`--type slack-user` recommended, `--type slack-cookie` discouraged fallback) — the outbound Slack tool surface backed by [`korotovsky/slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server). See the [Slack integration doc](integrations/slack.md) for token acquisition, security posture, and the full walkthrough.

OpenClaw-specific details:

- **Config surface:** the Slack MCP subprocess is rendered into `mcp.servers.<slug>` of `~/.openclaw/openclaw.json` on the agent host. Renderer: [`_render_openclaw_json`](https://github.com/ric03uec/clawrium/blob/main/src/clawrium/core/render.py) in `src/clawrium/core/render.py`.
- **Conditional emission (byte-lock guarantee):** the top-level `mcp` key is emitted **only** when at least one MCP-emitting integration is attached. OpenClaw agents with no Slack integration render byte-identical to the pre-#835 output — upgrading to this release does **not** touch `openclaw.json` on existing agents.
- **Binary install location:** `~/<agent-name>/.local/bin/slack-mcp-server` — single-binary Go install, SHA256-pinned per (os, arch). Same source of truth (`playbook_resolver._MCP_SLACK_VERSION` + SHA256 maps) as the hermes install.
- **macOS support (GA):** `clawctl agent sync` installs the darwin arm64 / x86_64 tarball via the dedicated `install_slack_mcp_macos.yaml` runbook. OpenClaw macOS is GA per #770, so Slack on darwin is a first-class combination.
- **Attach gate:** attaching a `slack-user` or `slack-cookie` integration to an openclaw agent is accepted by the CLI's attach-time gate (Phase 2 of #499); attempts to attach to unsupported agent types exit 2 with a hint.
- **Composite blast-radius warning applies** if you attach a future Slack channel + this Slack integration to the same agent. See [integrations/slack.md → Composite blast-radius warning](integrations/slack.md#composite-blast-radius-warning). (Slack **channel** on openclaw is on the SEA milestone; today only the Slack **integration** is attachable on openclaw, so the composite risk is future-only for openclaw.)

Quick attach + sync:

```bash
printf 'SLACK_MCP_XOXP_TOKEN=xoxp-...' | \
  clawctl integration registry create slack --type slack-user --credential-stdin
  clawctl agent integration attach <openclaw-name> --integration slack
clawctl agent sync <openclaw-name>
```

---

## Troubleshooting

<details>
<summary><strong>"Discord bot token invalid"</strong></summary>

1. Verify the bot token in Discord Developer Portal
2. Re-create the channel record (`clawctl channel registry delete <channel-name> --yes --force` then `clawctl channel registry create <channel-name> --type discord --token-stdin <<<"$BOT_TOKEN" ...`), re-attach if needed (`clawctl agent channel attach <channel-name> --agent <name>`), and `clawctl agent sync <name>`
3. Ensure the bot has proper server permissions
</details>

<details>
<summary><strong>"Provider connectivity failed"</strong></summary>

1. Check provider status: `clawctl provider status <provider-name>`
2. Verify API key is set: `clawctl provider registry get`
3. Test network connectivity from the host
</details>

<details>
<summary><strong>"Onboarding incomplete"</strong></summary>

Run the full onboarding wizard:
```bash
clawctl agent configure <agent-name>
```

Or configure a specific stage:
```bash
clawctl agent configure <agent-name> --stage <stage-name>
```
</details>

---

## Next Steps

- [Agent Onboarding](../agent-onboarding.md) - Detailed onboarding guide
- [CLI Reference](../reference/cli/agent.md) - Full command documentation
- [Provider Configuration](../host-preparation.md) - Setting up inference providers

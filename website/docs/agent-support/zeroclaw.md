# ZeroClaw Support Matrix

ZeroClaw is a minimal CLI-only agent designed for simple automation tasks and quick scripts.

**Status:** 🚧 In Development

**Best for:** CLI automation, minimal resource usage, quick tasks

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

ZeroClaw will support a limited set of providers focused on efficiency:

| Provider | Status | Configuration | Models |
|----------|:------:|---------------|--------|
| **[OpenAI](providers/openai.md)** | 🚧 | [In Development](providers/openai.md) | GPT-4o-mini, GPT-3.5 |
| **[Anthropic](providers/anthropic.md)** | 🚧 | [In Development](providers/anthropic.md) | Claude Haiku |
| **[Ollama](providers/ollama.md)** | 🚧 | [In Development](providers/ollama.md) | Local models |
| **[OpenRouter](providers/openrouter.md)** | ❌ | — | Not planned |
| **[AWS Bedrock](providers/bedrock.md)** | ❌ | — | Not planned |
| **[Google Vertex](providers/vertex.md)** | ❌ | — | Not planned |
| **[ZAI / BigModel](providers/zai.md)** | ❌ | — | Not planned |
| **[Azure OpenAI](providers/azure-openai.md)** | ❌ | — | Not planned |

**Notes:**
- ZeroClaw focuses on lightweight providers
- Self-hosted (Ollama) is prioritized for cost efficiency
- Complex providers (Bedrock, Vertex) are excluded by design

---

## Channel Support

ZeroClaw is CLI-only by design:

| Channel | Status | Configuration | Notes |
|---------|:------:|---------------|-------|
| **[CLI](channels/cli.md)** | 🚧 | [In Development](channels/cli.md) | Terminal-only |
| **Discord** | ❌ | — | Not supported (use OpenClaw) |
| **[Slack](channels/slack.md)** | ❌ | — | Not supported |
| **[Web Interface](channels/web.md)** | ❌ | — | Not supported |
| **[WhatsApp](channels/whatsapp.md)** | ❌ | — | Not supported |

**Philosophy:**
ZeroClaw intentionally excludes multi-channel support to maintain simplicity. For Discord or web interfaces, use [OpenClaw](openclaw.md).

---

## Integration Support

ZeroClaw does not support external integrations by design:

| Integration | Status | Configuration | Notes |
|-------------|:------:|---------------|-------|
| **GitHub** | ❌ | — | Not supported |
| **Jira** | ❌ | — | Not supported |
| **GitLab** | ❌ | — | Not supported |
| **Confluence** | ❌ | — | Not supported |
| **Linear** | ❌ | — | Not supported |
| **Notion** | ❌ | — | Not supported |

**Philosophy:**
ZeroClaw is designed for simple, self-contained automation. It focuses on:
- Quick CLI tasks
- Local file operations
- Simple API calls via curl/httpie
- Scripting and piping

For integrations with GitHub, Jira, etc., use [OpenClaw](openclaw.md).

---

## Feature Support

| Feature | Status | Notes |
|---------|:------:|-------|
| **Custom Identity** | ❌ | Minimal identity only (no SOUL.md) |
| **Multi-Provider** | 🚧 | Basic switching planned |
| **Secrets Management** | 🚧 | Per-instance storage planned |
| **Token Tracking** | ❌ | Not planned |
| **MCP Tools** | ❌ | Not planned |
| **Auto-Restart** | 🚧 | Supervisor-managed planned |
| **Log Streaming** | 🚧 | Planned |
| **Onboarding Wizard** | 🚧 | Simplified 2-stage setup |

---

## Comparison with OpenClaw

| Aspect | ZeroClaw | OpenClaw |
|--------|----------|----------|
| **Setup Time** | 1-2 minutes | 3-5 minutes |
| **Channels** | CLI only | CLI, Discord, Web |
| **Identity** | Minimal | Fully customizable |
| **Providers** | 3 (lightweight) | 7+ (all major) |
| **Integrations** | None | GitHub, Jira, etc. |
| **Resource Usage** | Low | Moderate |
| **Use Case** | Automation | Assistants |

---

## Getting Started (When Available)

### 1. Install ZeroClaw

```bash
clm agent install --type zeroclaw --host <host-alias> --name my-script
```

### 2. Configure (Minimal)

```bash
clm agent configure my-script
# Auto-skips identity, configures CLI channel only
```

### 3. Start and Chat

```bash
clm agent start my-script
clm chat my-script
```

---

## Development Status

ZeroClaw is currently in development. Expected features:

- **v0.1.0** (Target: Q2 2026)
  - CLI channel support
  - OpenAI and Anthropic providers
  - Basic onboarding
  - Start/stop lifecycle

- **v0.2.0** (Target: Q3 2026)
  - Ollama support
  - Log streaming
  - Secrets management

Track progress: [GitHub Milestone SEA](https://github.com/ric03uec/clawrium/milestones)

---

## When to Use ZeroClaw vs OpenClaw

**Choose ZeroClaw when:**
- ✅ You only need CLI interaction
- ✅ You want minimal resource usage
- ✅ You need quick automation scripts
- ✅ You don't need custom identity
- ✅ You don't need Discord or web interface
- ✅ You want fast setup (1-2 minutes)

**Choose OpenClaw when:**
- ✅ You need Discord or web interface
- ✅ You want customizable personality
- ✅ You need external integrations (GitHub, Jira)
- ✅ You need full feature set
- ✅ You want multi-provider flexibility

---

## Next Steps

- [OpenClaw Support Matrix](openclaw.md) - Full-featured alternative
- [Agent Onboarding](/docs/guides/agent-onboarding) - Onboarding process overview
- [CLI Reference](/docs/reference/cli/agent) - Command documentation

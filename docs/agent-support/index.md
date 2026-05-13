# Agent Support

Clawrium supports multiple agent types, each designed for different use cases. This section provides detailed support matrices for each agent.

## Available Agents

### Production Ready

| Agent | Description | Status |
|-------|-------------|--------|
| **[OpenClaw](openclaw.md)** | Full-featured agent with multi-channel support | ✅ Production Ready |

### In Development

| Agent | Description | Status |
|-------|-------------|--------|
| **[Hermes](hermes.md)** | Nous Research self-improving agent — local OpenAI-compatible HTTP API, file-based memory | 🚧 In Development |
| **[ZeroClaw](zeroclaw.md)** | Minimal CLI-only agent for simple automation | 🚧 In Development |

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully supported and tested |
| 🚧 | In development / Planned |
| ❌ | Not supported |
| 📋 | Not planned / Deferred (PRs welcome) |

## Quick Comparison

| Aspect | OpenClaw | Hermes | ZeroClaw |
|--------|:--------:|:------:|:--------:|
| **Status** | ✅ Production Ready | 🚧 In Development | 🚧 In Development |
| **Transport** | Native daemon | Local OpenAI-compatible HTTP API (`127.0.0.1:8642`) | CLI process |
| **`clm chat <name>` support** | ✅ | ✅ (OpenAI-compatible HTTP backend) | 🚧 |
| **Multi-Provider** | ✅ (OpenAI, Anthropic, OpenRouter, Bedrock, Vertex, ZAI, Ollama) | ✅ (OpenRouter, Anthropic, OpenAI, Ollama / custom) | 🚧 (OpenAI, Anthropic, Ollama planned) |
| **Memory model** | Daily files + identity files | Two fixed files: `MEMORY.md` (≤ 2200 chars), `USER.md` (≤ 1375 chars) | ❌ |
| **Identity management** | clm-managed `SOUL.md` / `IDENTITY.md` | Hermes-managed `SOUL.md` / `AGENTS.md` inside `~/.hermes/` (accessible via `clm agent memory`) | ❌ |
| **Messaging gateways** | Discord ✅, Slack 🚧, Web 🚧 | Discord ✅, Slack/Telegram/WhatsApp/Signal/email/... 📋 deferred | ❌ |
| **External integrations** | GitHub 🚧, Jira 🚧 | 📋 Deferred | ❌ |
| **Onboarding wizard** | ✅ 4-stage | ✅ 4-stage (identity auto-skipped) | 🚧 2-stage |
| **Resource usage** | Moderate | Moderate-to-high (uv venv + npm + playwright) | Low |

## Choosing an Agent

**Use OpenClaw when:**

- You need Slack or multi-channel (Discord + Slack + Web) support
- You want clm-managed customizable identity/personality
- You need integrations with external tools
- You want a fully production-ready experience today

**Use Hermes when:**

- You want a local OpenAI-compatible HTTP API in front of your model
- You want Discord support backed by a local inference endpoint
- You want a self-managed-identity agent (hermes manages its own `SOUL.md` / `AGENTS.md`)
- You're driving a local inference endpoint (Ollama, vLLM, llama.cpp) and want hermes to wrap it

**Use ZeroClaw when:**

- You only need CLI interaction
- You want minimal resource usage
- You need quick automation scripts
- You prefer simple, no-frills setup

## Adding New Agents

To request support for a new agent type or feature:

1. Check the existing agent matrices for current capabilities
2. Open an issue describing your use case
3. Reference the relevant agent matrix in your request

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for contribution guidelines.

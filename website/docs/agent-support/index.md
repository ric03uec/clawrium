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

### Install-only CLI

| Agent | Description | Status |
|-------|-------------|--------|
| **[Claude Code](claude.md)** | Isolated per-agent Claude Code environment with on-demand CLI and GUI chat; no daemon or native web UI | ✅ Supported contract |
| **[Codex](codex.md)** | Isolated per-agent Codex environment with OAuth and on-demand CLI and GUI chat; no daemon or native web UI | ✅ Supported contract |

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully supported and tested |
| 🚧 | In development / Planned |
| ❌ | Not supported |
| 📋 | Not planned / Deferred (PRs welcome) |

## Quick Comparison

| Aspect | OpenClaw | Hermes | ZeroClaw | Claude Code | Codex |
|--------|:--------:|:------:|:--------:|:-----------:|:-----:|
| **Status** | ✅ Production Ready | 🚧 In Development | 🚧 In Development | ✅ Install-only | ✅ Install-only |
| **Transport** | Native daemon | Local OpenAI-compatible HTTP API (`127.0.0.1:8642`) | CLI process | Per-agent CLI environment | Per-agent CLI environment |
| **`clawctl agent chat <name>` support** | ✅ | ✅ (OpenAI-compatible HTTP backend) | 🚧 | ✅ (finite CLI backend) | ✅ (finite CLI backend) |
| **Multi-Provider** | ✅ (OpenAI, Anthropic, OpenRouter, Bedrock, Vertex, ZAI, Ollama) | ✅ (OpenRouter, Anthropic, OpenAI, Ollama / custom) | 🚧 (OpenAI, Anthropic, Ollama planned) | ❌ — one OAuth or Anthropic API-key credential |
| **Memory model** | Daily files + identity files | Two fixed files: `MEMORY.md` (≤ 2200 chars), `USER.md` (≤ 1375 chars) | ❌ | ❌ |
| **Identity management** | clawctl-managed `SOUL.md` / `IDENTITY.md` | Hermes-managed `SOUL.md` / `AGENTS.md` inside `~/.hermes/` (accessible via `clawctl agent memory`) | ❌ | Project-owned `.claude` settings untouched |
| **Messaging gateways** | Discord ✅, Slack 🚧, Web 🚧 | Discord ✅, Slack/Telegram/WhatsApp/Signal/email/... 📋 deferred | ❌ | ❌ |
| **External integrations** | GitHub 🚧, Jira 🚧 | 📋 Deferred | ❌ | ❌ |
| **Onboarding wizard** | ✅ 4-stage | ✅ 4-stage (identity auto-skipped) | 🚧 2-stage | ❌ — bounded configure/sync only |
| **Resource usage** | Moderate | Moderate-to-high (uv venv + npm + playwright) | Low | Low until an operator runs a command |

## Choosing an Agent

**Use OpenClaw when:**

- You need Slack or multi-channel (Discord + Slack + Web) support
- You want clawctl-managed customizable identity/personality
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

**Use Codex when:**

- You need an isolated, pinned Codex CLI installation with local OAuth import
- You want finite native commands or on-demand CLI/GUI chat without a daemon
- You do not need a Clawrium-managed gateway or native web UI

**Use Claude Code when:**

- You need an isolated, pinned Claude Code installation on a fleet host
- You will run finite native commands through `clawctl agent exec <name> -- <args...>` (or a shell expression through `agent shell`) or chat on demand through `clawctl agent chat <name>` or the GUI Chat tab
- You do not need a Clawrium-managed gateway, daemon, or native web UI
- You need Clawrium to own only the per-agent account, bounded global settings,
  selected credential environment, and installation prefix

## Adding New Agents

To request support for a new agent type or feature:

1. Check the existing agent matrices for current capabilities
2. Open an issue describing your use case
3. Reference the relevant agent matrix in your request

See [CONTRIBUTING.md](/docs/contributing) for contribution guidelines.

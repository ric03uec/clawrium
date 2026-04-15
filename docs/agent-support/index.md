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
| **[ZeroClaw](zeroclaw.md)** | Minimal CLI-only agent for simple automation | 🚧 In Development |

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully supported and tested |
| 🚧 | In development / Planned |
| ❌ | Not supported |
| 📋 | Not planned (PRs welcome) |

## Quick Comparison

| Feature | OpenClaw | ZeroClaw |
|---------|:--------:|:--------:|
| **Multi-Provider** | ✅ | 🚧 |
| **CLI Channel** | ✅ | 🚧 |
| **Discord** | ✅ | ❌ |
| **Custom Identity** | ✅ (SOUL.md) | ❌ |
| **Integrations** | 🚧 | ❌ |
| **Onboarding Wizard** | ✅ | 🚧 |

## Choosing an Agent

**Use OpenClaw when:**
- You need Discord or multi-channel support
- You want customizable identity/personality
- You need integrations with external tools
- You want a full-featured assistant

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

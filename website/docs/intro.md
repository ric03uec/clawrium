---
sidebar_position: 1
slug: /
description: Clawrium is a CLI to manage all your AI assistants. Deploy agents like OpenClaw across your network from a single command center.
keywords: [clawrium, AI assistant, fleet management, CLI tool, multi-host, agent, openclaw]
---

# Introduction

**Clawrium is a CLI to manage all your AI assistants.** Point it at any machine on your network and deploy agents like [OpenClaw](https://github.com/openclaw/openclaw) with a single command.

[Documentation](https://ric03uec.github.io/clawrium/) · [Issues](https://github.com/ric03uec/clawrium/issues) · [Roadmap](https://github.com/users/ric03uec/projects/1) · [Discord](https://discord.gg/KzPuSxgQ98)

## Watch: 3-minute quickstart

<div style={{position: 'relative', paddingBottom: '56.25%', height: 0, overflow: 'hidden', maxWidth: '100%', marginBottom: '2rem'}}>
  <iframe
    style={{position: 'absolute', top: 0, left: 0, width: '100%', height: '100%'}}
    src="https://www.youtube.com/embed/qEqDnzJBaig"
    title="Clawrium Quickstart — Install + Chat With Your First Agent (3 min)"
    frameBorder="0"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
    allowFullScreen>
  </iframe>
</div>

End-to-end walkthrough: install `clawctl`, register a host, deploy a [Hermes](https://github.com/NousResearch/hermes-agent) agent, attach a model provider, and chat with it. Full step-by-step write-up in the [Quickstart guide](./guides/quickstart.md).

## Watch: GUI walkthrough

<div style={{position: 'relative', paddingBottom: '56.25%', height: 0, overflow: 'hidden', maxWidth: '100%', marginBottom: '2rem'}}>
  <iframe
    style={{position: 'absolute', top: 0, left: 0, width: '100%', height: '100%'}}
    src="https://www.youtube.com/embed/F8AVpxsZTOA"
    title="Clawrium GUI walkthrough — every tab in the clawctl dashboard"
    frameBorder="0"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
    allowFullScreen>
  </iframe>
</div>

75-second narrated tour of every tab in `clawctl gui` — Dashboard, Agents, Topology, Providers, Skills, Integrations, Settings. Full reference in the [Web Dashboard guide](./web-dashboard.md).

## What is an Agent?

A Clawrium **agent** is a general-purpose AI assistant that runs on a machine in your network. Unlike coding-specific tools, these agents are versatile assistants that can:

- Answer questions via Discord, Slack, or CLI
- Research topics and summarize findings
- Help with writing, brainstorming, and planning
- Connect to external services (GitHub, Jira, etc.)

**Fully supported today:**
- [**OpenClaw**](https://github.com/openclaw/openclaw) ✅ - Full-featured assistant with multi-provider and multi-channel support
- [**Hermes**](https://github.com/NousResearch/hermes-agent) ✅ (Nous Research) - Install, configure, and OpenAI-compatible API
- [**ZeroClaw**](https://github.com/zeroclaw-labs/zeroclaw) ✅ - Lightweight assistant for resource-constrained devices

**Planned:**
- **IronClaw** - High-performance assistant for demanding workloads

## Why Clawrium?

You're running multiple AI agents across machines on your network. Without Clawrium, you SSH into each box, manage configs individually, and have no unified view of what's running where.

Clawrium gives you `kubectl`-style fleet control for AI agents:

- **One CLI, all hosts.** Add machines to your fleet and deploy any agent type to any host.
- **Specialized agents.** Run a fleet of purpose-built agents - a research agent, a support agent, an internal assistant - each with its own context and configuration.
- **Model flexibility.** Use any provider: OpenAI, Anthropic, local Ollama, or self-hosted inference.
- **Lifecycle management.** Upgrades, rollbacks, secrets rotation - handled from one place.
- **Local web dashboard.** `clawctl gui` opens a visual fleet view on `127.0.0.1` — chat with agents, browse topology, manage providers. See the [Web Dashboard guide](./web-dashboard.md).

## How It Works

```
Your Machine (clawctl CLI)
    │
    ├── Host A ──> openclaw instance (Discord bot)
    ├── Host B ──> openclaw instance (internal assistant)
    └── Host C ──> zeroclaw instance (lightweight helper)
```

Clawrium runs from your control machine and uses SSH + Ansible to manage remote hosts.

## Quick Reference

```bash
# Initialize Clawrium (check dependencies)
clawctl service init
```
```
✓ Configuration directory created at ~/.config/clawrium/
✓ Dependencies validated
```

```bash
# Register a host (the xclm management user must already exist on the host —
# see the Host Setup guide for one-time host preparation).
clawctl host create 192.168.1.100 --user xclm --alias homelab
```
```
Connecting to 192.168.1.100 as xclm...
✓ Connection successful
Detecting hardware capabilities...
  CPU: 4 cores (ARM64)
  Memory: 8 GB
  GPU: None
✓ Host 'homelab' added to fleet
```

```bash
# See your fleet status
clawctl agent get
```
```
HOST        AGENT          TYPE       PROVIDER   STATUS    UPTIME
──────────────────────────────────────────────────────────────────
homelab     oc-discord     openclaw   openai     running   3d 4h
nuc-01      oc-work        openclaw   anthropic  running   12h
```

```bash
# Install an agent on a host (name is positional)
clawctl agent create my-assistant --type openclaw --host homelab
```
```
Installing openclaw on homelab...
✓ Dependencies installed
✓ Agent user created
✓ Configuration deployed
✓ Agent 'my-assistant' installed successfully
```

```bash
# Open the local web dashboard
clawctl gui
```
```
Clawrium GUI starting on http://127.0.0.1:36000 — press Ctrl+C to stop
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Host** | A machine in your network that runs one or more agents |
| **Agent** | An installed AI assistant instance managed by Clawrium (e.g. OpenClaw, Hermes) |
| **Agent Type** | The implementation/runtime class of an agent |
| **Registry** | Available agent types with versions, dependencies, and templates |

## What You'll Need

Before you start, make sure you have:

| Requirement | Details |
|-------------|---------|
| **Control machine** | Ubuntu or macOS with Python 3.10+ |
| **Target host** | Ubuntu 22.04/24.04 or macOS with SSH access |
| **Network** | Direct connectivity between control machine and hosts |
| **API keys** | At least one LLM provider (OpenAI, Anthropic, etc.) |

## Architecture

![Clawrium architecture](/img/clawrium-architecture.png)

Clawrium runs from your control machine and uses SSH + Ansible to manage remote hosts from one CLI.

## FAQ

### What operating systems are supported?

Clawrium is tested end-to-end on **Ubuntu** and **macOS** — both as the control machine and as target hosts. On macOS hosts, enable Remote Login before registering them; see the [Host Setup](./guides/host-setup.md) guide. Other Linux distributions may work but are not in the test matrix.

### Which agents are supported today?

[OpenClaw](https://github.com/openclaw/openclaw), [Hermes](https://github.com/NousResearch/hermes-agent), and [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw) are fully supported end-to-end. IronClaw is planned. See the [Support Matrix](https://github.com/ric03uec/clawrium#support-matrix) on the GitHub README for the canonical status table.

### Is Claude subscription supported?

No. API keys are required by design - Clawrium manages API credentials, not subscription accounts.

### Which communication channels are supported?

Discord, Slack, and CLI are supported today. Web interface is planned.

### Do I need to be online?

Yes. The agents connect to LLM providers via API. Local inference with Ollama reduces external dependencies but still requires the model to be served.

### Why doesn't it support my favorite agent?

Clawrium is built in spare time, so features are prioritized by maintainer use cases. Want support for a specific agent? [Open an issue](https://github.com/ric03uec/clawrium/issues) or send a PR.

## User Data

Clawrium stores configuration in `~/.config/clawrium/`:

| Path | Description |
|------|-------------|
| `hosts.json` | Registered hosts and metadata |
| `keys/<hostname>/` | SSH keypairs for each host |
| `secrets/<agent-name>/` | Encrypted secrets for agent instances |

## Next Steps

- **[Quickstart](./guides/quickstart.md)** - Deploy your first agent in 5 minutes
- [Installation](./installation.md) - Install Clawrium
- [Host Setup](./guides/host-setup.md) - Detailed host preparation guide
- [Architecture](./architecture.md) - Understand how Clawrium works

---
sidebar_position: 1
slug: /
description: Clawrium is a CLI to manage all your AI assistants. Deploy agents like OpenClaw across your network from a single command center.
keywords: [clawrium, AI assistant, fleet management, CLI tool, multi-host, agent, openclaw]
---

# Introduction

**Clawrium is a CLI to manage all your AI assistants.** Point it at any machine on your network and deploy agents like [OpenClaw](https://github.com/openclaw/openclaw) with a single command.

[Documentation](https://ric03uec.github.io/clawrium/) · [Issues](https://github.com/ric03uec/clawrium/issues) · [Roadmap](https://github.com/users/ric03uec/projects/1) · [Discord](https://discord.gg/KzPuSxgQ98)

## What is a Claw?

A **claw** is a general-purpose AI assistant that runs on a machine in your network. Unlike coding-specific tools, claws are versatile assistants that can:

- Answer questions via Discord, Slack, or CLI
- Research topics and summarize findings
- Help with writing, brainstorming, and planning
- Connect to external services (GitHub, Jira, etc.)

**Currently supported:**
- [**OpenClaw**](https://github.com/openclaw/openclaw) - Full-featured assistant with multi-provider and multi-channel support

**Planned:**
- **ZeroClaw** - Lightweight assistant for resource-constrained devices
- **IronClaw** - High-performance assistant for demanding workloads

## Why Clawrium?

You're running multiple AI agents across machines on your network. Without Clawrium, you SSH into each box, manage configs individually, and have no unified view of what's running where.

Clawrium gives you `kubectl`-style fleet control for AI agents:

- **One CLI, all hosts.** Add machines to your fleet and deploy any agent type to any host.
- **Specialized agents.** Run a fleet of purpose-built agents - a research agent, a support agent, an internal assistant - each with its own context and configuration.
- **Model flexibility.** Use any provider: OpenAI, Anthropic, local Ollama, or self-hosted inference.
- **Lifecycle management.** Upgrades, rollbacks, secrets rotation - handled from one place.

## How It Works

```
Your Machine (clm CLI)
    │
    ├── Host A ──> openclaw instance (Discord bot)
    ├── Host B ──> openclaw instance (internal assistant)
    └── Host C ──> zeroclaw instance (lightweight helper)
```

Clawrium runs from your control machine and uses SSH + Ansible to manage remote hosts.

## Quick Reference

```bash
# Initialize Clawrium (check dependencies)
clm init
```
```
✓ Configuration directory created at ~/.config/clawrium/
✓ Dependencies validated
```

```bash
# Initialize a host (generates keypair, sets up management user)
clm host init 192.168.1.100 --user myuser
```
```
Generating SSH keypair for 192.168.1.100...
✓ Keypair created: ~/.config/clawrium/keys/192.168.1.100/
Configuring xclm user on remote host...
✓ Host initialized successfully
```

```bash
# Add an initialized host to the fleet
clm host add 192.168.1.100 --alias homelab
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
clm ps
```
```
HOST        AGENT          TYPE       STATUS    UPTIME
─────────────────────────────────────────────────────────
homelab     oc-discord     openclaw   running   3d 4h
nuc-01      oc-work        openclaw   running   12h
```

```bash
# Install an agent on a host
clm agent install --type openclaw --host homelab --name my-assistant
```
```
Installing openclaw on homelab...
✓ Dependencies installed
✓ Agent user created
✓ Configuration deployed
✓ Agent 'my-assistant' installed successfully
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Host** | A machine in your network that runs one or more agents |
| **Claw** | An AI assistant instance (like OpenClaw or ZeroClaw) |
| **Agent** | An installed claw instance managed by Clawrium |
| **Registry** | Available claw types with versions, dependencies, and templates |

## What You'll Need

Before you start, make sure you have:

| Requirement | Details |
|-------------|---------|
| **Control machine** | macOS or Linux with Python 3.10+ |
| **Target host** | Ubuntu 22.04/24.04 with SSH access |
| **Network** | Direct connectivity between control machine and hosts |
| **API keys** | At least one LLM provider (OpenAI, Anthropic, etc.) |

## Architecture

![Clawrium architecture](/img/clawrium-architecture.png)

Clawrium runs from your control machine and uses SSH + Ansible to manage remote hosts from one CLI.

## FAQ

### What operating systems are supported?

Clawrium is currently tested on Ubuntu control machines and Ubuntu 22.04/24.04 target hosts.

### Which agents are supported today?

[OpenClaw](https://github.com/openclaw/openclaw) is supported with full lifecycle management. ZeroClaw support is planned.

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

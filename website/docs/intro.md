---
sidebar_position: 1
slug: /
description: Clawrium is a CLI tool for managing AI assistant fleets on local networks. Deploy and manage agent instances across hosts from a single command center.
keywords: [clawrium, AI assistant, fleet management, CLI tool, multi-host, agent]
---

# Introduction

Clawrium is a CLI tool for managing AI assistant fleets on local networks. Deploy and manage multiple agent instances across hosts from a single command center.

## Why Clawrium?

You're running multiple AI agents - coding assistants, internal tools, experiment harnesses - across machines on your network. Without Clawrium, you SSH into each box, manage configs individually, lose track of token spend, and have no unified view of what's running where.

Clawrium gives you `kubectl`-style fleet control for AI agents:

- **One CLI, all hosts.** Add machines to your fleet and deploy any agent type to any host.
- **Specialized agents.** Each agent does one job and does it well. Instead of one overloaded assistant, run a fleet of purpose-built agents - a coding agent, a review agent, a research agent - each with its own context, data, and configuration isolated from the rest.
- **Local inference.** Use hardware you already have - Mac Minis, [NVIDIA DGX Spark](https://www.nvidia.com/en-us/products/workstations/dgx-spark/), spare servers - as inference providers. Run smaller open models like Gemma, GPT-4o-mini, Kimi, or Llama locally and point multiple agents at them.
- **Model experimentation.** Swap models across agents to compare performance without touching individual configs.
- **Lifecycle management.** Upgrades, rollbacks, secrets rotation, backups - handled.
- **Token tracking & guardrails.** See spend across your fleet. Set limits before someone's experiment burns through your API budget.

## Features

### 🌐 Agent Support (Current)

Today, Clawrium supports one agent type for end-to-end install, onboarding, and lifecycle management.

Support for additional agent types is planned.

### ⚙️ Normalized Configuration

One config format, every agent. Define your preferences once and Clawrium translates them for each agent runtime's native format.

### 🔓 Multi-Model Freedom

Run any model across your fleet:
- **Open models**: NVIDIA Nemotron, GLM-4, MiniMax
- **Big labs**: OpenAI, Anthropic, Google, Mistral
- **Local**: Ollama, llama.cpp, vLLM

## Quick Reference

```bash
# Initialize Clawrium (check dependencies)
clm init

# Initialize a host (generates keypair, sets up management user)
clm host init 192.168.1.100 --user myuser

# Add an initialized host to the fleet
clm host add 192.168.1.100 --alias myhost

# List all hosts
clm host list

# Check host status
clm host ps myhost

# Browse available agent types
clm agent registry list

# Add inference provider
clm provider add anthropic --type anthropic

# Install an agent on a host
clm agent install --type <agent-type> --host myhost --name my-agent

# Set a secret for an agent
clm agent secret set my-agent OPENAI_API_KEY

# Configure and start the agent
clm agent configure my-agent
clm agent start my-agent
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Host** | A machine in your network that runs one or more agents |
| **Agent** | An installed AI assistant instance managed by Clawrium |
| **Agent Type** | The implementation/runtime class of an agent |
| **Agent Name** | The unique identifier for an installed agent instance |
| **Registry** | Platform-defined agent types with versions, dependencies, and templates |

## Architecture

![Clawrium architecture](/img/clawrium-architecture.png)

Clawrium runs from your control machine and uses SSH + Ansible to manage remote hosts from one CLI.

## FAQ

### 1. What operating systems are supported?

Clawrium is currently tested on Ubuntu control machines and Ubuntu target hosts only.

### 2. Which agents are supported today?

One agent type is supported right now.

Additional agent types are planned.

### 3. Is Claude subscription supported?

No. API keys are required by design.

### 4. Which channels are supported?

Discord is supported right now. Additional channels are planned.

### 5. Why doesn't it support x-agent and y-feature?

I'm building Clawrium in my spare time, so I prioritize my own use cases first.

If you want support for a specific agent type or feature, please open an issue and send a PR. See the [Contributing Guidelines](https://github.com/ric03uec/clawrium/blob/main/CONTRIBUTING.md).

## User Data

Clawrium stores configuration in `~/.config/clawrium/` (or `$XDG_CONFIG_HOME/clawrium/`):

| Path | Description |
|------|-------------|
| `hosts.json` | Registered hosts and metadata (0600 permissions) |
| `keys/<hostname>/xclm_ed25519` | Private key for SSH to host |
| `keys/<hostname>/xclm_ed25519.pub` | Public key added to host's authorized_keys |
| `secrets/<agent-name>/<key>` | Encrypted secrets for agent instances |

## Next Steps

- [Installation](./installation.md) - Install Clawrium
- [Quickstart](./guides/quickstart.md) - Deploy your first agent
- [Host Setup](./guides/host-setup.md) - Detailed host preparation guide
- [Architecture](./architecture.md) - Understand how Clawrium works

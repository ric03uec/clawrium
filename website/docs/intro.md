---
sidebar_position: 1
slug: /
description: Clawrium is a CLI tool for managing AI assistant fleets on local networks. Deploy and manage multiple claw instances across hosts from a single command center.
keywords: [clawrium, AI assistant, fleet management, CLI tool, multi-host, zeroclaw, openclaw]
---

# Introduction

Clawrium is a CLI tool for managing AI assistant fleets on local networks. Deploy and manage multiple claw instances across hosts from a single command center.

## Why Clawrium?

Running AI assistants across multiple machines means dealing with:
- Different configuration formats for each claw type
- Manual SSH access to each host
- Scattered secrets and credentials
- No unified view of your fleet

Clawrium solves this by providing a single interface to manage any number of claws across any number of hosts.

## Features

### 🌐 Universal Claw Support

Manage any claw from a single command center:
- [ZeroClaw](https://github.com/zeroclaw/zeroclaw)
- [OpenClaw](https://github.com/openclaw/openclaw)
- [NemoClaw](https://github.com/nemoclaw/nemoclaw)
- [NanoClaw](https://github.com/nanoclaw/nanoclaw)
- [IronClaw](https://github.com/ironclaw/ironclaw)

### ⚙️ Normalized Configuration

One config format, every claw. Define your preferences once and Clawrium translates them for each claw's native format.

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
clm host status myhost

# Browse available claw types
clm registry list

# Install a claw on a host
clm install --claw zeroclaw --host myhost

# Set a secret for a claw
clm secret set zc-myhost OPENAI_API_KEY
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Host** | A machine in your network that runs one or more claws |
| **Claw** | An AI assistant instance (zeroclaw, openclaw, etc.) |
| **Registry** | Platform-defined claw types with versions, dependencies, and requirements |

## User Data

Clawrium stores configuration in `~/.config/clawrium/` (or `$XDG_CONFIG_HOME/clawrium/`):

| Path | Description |
|------|-------------|
| `hosts.json` | Registered hosts and metadata (0600 permissions) |
| `keys/<hostname>/xclm_ed25519` | Private key for SSH to host |
| `keys/<hostname>/xclm_ed25519.pub` | Public key added to host's authorized_keys |
| `secrets/<claw-name>/<key>` | Encrypted secrets for claw instances |

## Next Steps

- [Installation](./installation.md) - Install Clawrium
- [Quickstart](./guides/quickstart.md) - Deploy your first claw
- [Host Setup](./guides/host-setup.md) - Detailed host preparation guide
- [Architecture](./architecture.md) - Understand how Clawrium works

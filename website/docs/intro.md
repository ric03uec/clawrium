---
sidebar_position: 1
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

### Universal Claw Support

Manage any claw from a single command center:
- [ZeroClaw](https://github.com/zeroclaw/zeroclaw)
- [OpenClaw](https://github.com/openclaw/openclaw)
- [NemoClaw](https://github.com/nemoclaw/nemoclaw)
- [NanoClaw](https://github.com/nanoclaw/nanoclaw)
- [IronClaw](https://github.com/ironclaw/ironclaw)

### Normalized Configuration

One config format, every claw. Define your preferences once and Clawrium translates them for each claw's native format.

### Multi-Model Freedom

Run any model across your fleet:
- **Open models**: NVIDIA Nemotron, GLM-4, MiniMax
- **Big labs**: OpenAI, Anthropic, Google, Mistral
- **Local**: Ollama, llama.cpp, vLLM

## Quick Start

```bash
# Install Clawrium
git clone https://github.com/ric03uec/clawrium.git
cd clawrium && uv sync && uv pip install -e .

# Initialize Clawrium
clm init

# Prepare and add a host
clm host init 192.168.1.100 --user myuser
clm host add 192.168.1.100 --alias myhost

# Check your fleet
clm host list
clm host status myhost
```

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- SSH access to target hosts

## Next Steps

- [Architecture](./architecture.md) - Understand how Clawrium works
- [Host Preparation](./guides/host-setup.md) - Detailed host setup guide

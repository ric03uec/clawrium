# Clawrium

**An aquarium for your claws.**

<p align="center">
  <img src="docs/assets/clawrium-logo.png" alt="Clawrium Logo" width="600">
</p>

CLI tool for managing AI assistant fleets on local networks. Deploy and manage multiple claw instances across hosts from a single command center.

## Features

### Universal Claw Support

Manage any claw from a single command center:
- [OpenClaw](https://github.com/openclaw/openclaw)
- [ZeroClaw](https://github.com/zeroclaw/zeroclaw)
- [NemoClaw](https://github.com/nemoclaw/nemoclaw)
- [NanoClaw](https://github.com/nanoclaw/nanoclaw)
- [IronClaw](https://github.com/ironclaw/ironclaw)

### Normalized Configuration

One config format, every claw. Clawrium standardizes settings across different claw types - define your preferences once and Clawrium translates them for each claw's native format.

### Multi-Model Freedom

Don't get locked into one provider. Run any model across your fleet:
- **Open models**: NVIDIA Nemotron, GLM-4, MiniMax
- **Big labs**: OpenAI, Anthropic, Google, Mistral
- **Local**: Ollama, llama.cpp, vLLM

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

```bash
# Clone the repository
git clone https://github.com/ric03uec/clawrium.git
cd clawrium

# Install dependencies
uv sync

# Install in development mode
uv pip install -e .
```

## Initial Setup

```bash
# Initialize Clawrium configuration
clm init

# Add a host to manage
clm host add <hostname> --ip <ip-address>

# Check host status
clm host status
```

## Usage

```bash
# List available commands
clm --help

# Manage hosts
clm host list
clm host add <name> --ip <address>
clm host remove <name>
clm host status [name]
```

## License

Apache 2.0

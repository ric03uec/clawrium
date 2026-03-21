# Clawrium

<p align="center">
  <img src="docs/assets/clawrium-logo.png" alt="Clawrium Logo" width="300">
</p>

**An aquarium for your claws.**

CLI tool for managing AI assistant fleets on local networks. Deploy and manage multiple claw instances (ZeroClaw, NemoClaw, OpenClaw) across hosts from a single command center.

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

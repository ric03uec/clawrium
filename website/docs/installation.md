---
sidebar_position: 2
---

# Installation

This guide covers installing Clawrium on your management machine (the computer you'll use to control your claw fleet).

## Prerequisites

- **Python 3.10 or higher**
- **uvx** (recommended) or pip

### Check Python Version

```bash
python3 --version
# Should be 3.10 or higher
```

### Install uvx

If you don't have uvx, install it via pipx or brew:

```bash
# Using pipx (recommended)
pipx install uv

# Or using Homebrew on macOS
brew install uv
```

## Install Clawrium

### Using uvx (Recommended)

```bash
uvx clawrium
```

This runs the latest version of Clawrium without permanent installation. To install permanently:

```bash
uv tool install clawrium
```

### Using pip

```bash
pip install clawrium
```

## Verify Installation

Run the `clm` command to verify installation:

```bash
clm --help
```

You should see:

```
 Usage: clm [OPTIONS] COMMAND [ARGS]...

 Clawrium - Manage your AI assistant fleet

╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init      Initialize Clawrium and check dependencies.                        │
│ install   Install a claw on a host.                                          │
│ status    Show fleet status across all hosts.                                │
│ host      Manage hosts in your fleet                                         │
│ registry  Browse available claw types                                        │
│ secret    Manage secrets for claw instances                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## Initialize Clawrium

Run `clm init` to create the configuration directory and check dependencies:

```bash
clm init
```

This creates:
- `~/.config/clawrium/` directory
- Validates that required dependencies are available

## Next Steps

- [Quickstart: Deploy your first claw](./guides/quickstart.md)
- [Host Setup Guide](./guides/host-setup.md)

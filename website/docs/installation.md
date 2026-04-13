---
sidebar_position: 2
description: Install Clawrium CLI on your management machine. Requirements, installation methods, and initial setup.
keywords: [install, setup, requirements, uv, uvx, python]
---

# Installation

This guide covers installing Clawrium on your management machine (the computer you'll use to control your agent fleet).

## Prerequisites

- **Python 3.10 or higher**
- **uv** ([install guide](https://docs.astral.sh/uv/getting-started/installation/))

### Check Python Version

```bash
python3 --version
# Should be 3.10 or higher
```

### Install uv

If you don't have uv, install it:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using Homebrew on macOS
brew install uv
```

## Install Clawrium

### Install Permanently (Recommended)

```bash
uv tool install clawrium
```

### Run Without Installing

```bash
uvx --from clawrium clm --help
```

This runs the latest version without permanent installation.

## Verify Installation

Run the `clm` command to verify installation:

```bash
clm --help
```

You should see output similar to:

```
 Usage: clm [OPTIONS] COMMAND [ARGS]...

 Clawrium - Manage your AI assistant fleet

╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init      Initialize Clawrium and check dependencies                         │
│ host      Manage hosts in your fleet                                         │
│ provider  Manage inference providers (LLM APIs)                              │
│ agent     Manage agents in your fleet                                        │
│ ps        Show fleet status across all hosts                                 │
│ chat      Chat with a deployed agent                                         │
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

- [Quickstart: Deploy your first agent](./guides/quickstart.md)
- [Host Setup Guide](./guides/host-setup.md)

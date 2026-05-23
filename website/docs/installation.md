---
sidebar_position: 2
description: Install Clawrium CLI on your management machine. Requirements, installation methods, and initial setup.
keywords: [install, setup, requirements, uv, uvx, python]
---

<!-- Mirror of docs/installation.md. Do not edit here directly — edit docs/installation.md and copy the body verbatim. The Docusaurus frontmatter above and this comment are the only website-specific additions. -->

# Installation

This guide covers installing Clawrium on your management machine (the computer you'll use to control your agent fleet).

## What You'll Need

| Requirement | Version | How to Check |
|-------------|---------|--------------|
| **Python** | 3.10 or higher | `python3 --version` |
| **uv** | Any | `uv --version` |

### Check Python Version

```bash
python3 --version
```
```
Python 3.11.4
```

If your version is below 3.10, [upgrade Python](https://www.python.org/downloads/) first.

### Install uv

Clawrium is distributed as a Python package and installed via [uv](https://docs.astral.sh/uv/). If you don't have uv, install it:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```
```
Downloading uv...
Installing to ~/.cargo/bin/uv
✓ uv installed successfully

Run 'source ~/.bashrc' or restart your shell to use uv.
```

Or using Homebrew on macOS:

```bash
brew install uv
```

See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) for other platforms and options.

## Install Clawrium

### Install Permanently (Recommended)

```bash
uv tool install clawrium
```
```
Resolved 1 package in 523ms
Installed 1 package in 12ms
 + clawrium==26.5.4
```

### Run Without Installing

```bash
uvx --from clawrium clm --help
```

This runs the latest version without permanent installation - useful for trying it out.

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
│ init      Initialize Clawrium and check dependencies                         │
│ host      Manage hosts in your fleet                                         │
│ provider  Manage inference providers (LLM APIs)                              │
│ agent     Manage agents in your fleet                                        │
│ ps        Show fleet status across all hosts                                 │
│ chat      Chat with a deployed agent                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Check the version:

```bash
clm --version
```
```
clm, version 26.5.4
```

## Initialize Clawrium

Run `clm init` to create the configuration directory and check dependencies:

```bash
clm init
```
```
✓ Configuration directory created at ~/.config/clawrium/
✓ Ansible found: ansible [core 2.15.0]
✓ SSH client found: OpenSSH_9.0p1
✓ Dependencies validated

Clawrium is ready! Next: clm host init <hostname> --user <user>
```

This creates:
- `~/.config/clawrium/` directory structure
- Validates that Ansible and SSH are available

## Troubleshooting

### "command not found: clm"

The uv tools directory isn't in your PATH. Add it:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"
```

Then restart your shell or run `source ~/.bashrc`.

### "Ansible not found"

Install Ansible:

```bash
# macOS
brew install ansible

# Ubuntu/Debian
sudo apt install ansible

# Using pip
pip install ansible
```

### "Permission denied" during init

The config directory location isn't writable. Check permissions:

```bash
ls -la ~/.config/
# Should show your user owns the directory
```

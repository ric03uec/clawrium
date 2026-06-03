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
 + clawrium==26.6.0
```

### Run Without Installing

```bash
uvx --from clawrium clawctl --help
```

This runs the latest version without permanent installation - useful for trying it out.

## Verify Installation

Run the `clawctl` command to verify installation:

```bash
clawctl --help
```

You should see:

```
 Usage: clawctl [OPTIONS] COMMAND [ARGS]...

 clawctl — manage your AI assistant fleet, kubectl-style.

╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ service     System-level lifecycle ops (init, snapshot, ...)                 │
│ host        Manage hosts in your fleet                                       │
│ provider    Manage inference providers (LLM APIs)                            │
│ integration Manage external service integrations                             │
│ channel     Manage chat-channel attachables (Discord, Slack, ...)            │
│ skill       Browse the skills catalog                                        │
│ agent       Manage agents in your fleet                                      │
│ tui         Launch the interactive TUI dashboard                             │
│ gui         Launch the local web GUI dashboard                               │
│ version     Show clawctl version and exit                                    │
│ completion  Emit a shell-completion script                                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Check the version:

```bash
clawctl --version
```
```
clawctl 26.6.0
```

## Initialize Clawrium

Run `clawctl service init` to create the configuration directory and check dependencies:

```bash
clawctl service init
```
```
✓ Configuration directory created at ~/.config/clawrium/
✓ Ansible found: ansible [core 2.15.0]
✓ SSH client found: OpenSSH_9.0p1
✓ Dependencies validated

Clawrium is ready! Next: clawctl host create <hostname> --user xclm --alias <name>
```

This creates:
- `~/.config/clawrium/` directory structure
- Validates that Ansible and SSH are available

## macOS targets

Clawrium can manage macOS hosts (Apple Silicon, macOS 14+) alongside the
Linux fleet. The control machine (where you run `clawctl`) can be either
Linux or macOS.

### Target prerequisites

On the macOS host you want to manage:

1. **A user with `sudo` access** for the manual `xclm` setup. See
   [Host Preparation](guides/host-setup.md) for the exact commands — macOS
   uses `dscl`, `dseditgroup` (including the critical
   `com.apple.access_ssh` group membership), and `sudoers.d`. Password
   sudo is fine; you only run the commands once, interactively.
2. **Xcode Command Line Tools.** The base playbook installs them
   automatically if missing, but the first install takes 5–15 minutes
   and downloads ~700MB. Pre-installing with `xcode-select --install`
   beforehand is faster if you're rebuilding hosts often.

### Register the host

Follow [Host Preparation](guides/host-setup.md) — the same flow works for
Linux and macOS hosts. In short:

```bash
clawctl host create <mac-ip> --user xclm --alias <name>
```

The first invocation generates a per-host keypair and prints the
macOS-specific manual commands (with the public key inlined). Paste those
on the Mac, then re-run the same `clawctl host create` command to register
the host.

### Install an agent

Both `hermes` and `openclaw` agent types are supported on macOS
(Apple Silicon, macOS 14+). They can coexist on the same host.

```bash
# hermes
clawctl agent create <name> --type hermes --host <alias>

# openclaw
clawctl agent create <name> --type openclaw --host <alias>
```

Behind the scenes, clawrium installs Homebrew (if missing), then
`node`, `ripgrep`, `ffmpeg`, and `uv` via brew, creates a per-agent
macOS user (`/Users/<agent_name>/`), and runs the upstream installer
for the chosen agent type. The openclaw install also registers a
launchd unit at
`/Library/LaunchDaemons/ai.clawrium.openclaw.<agent>.plist` and
performs the loopback pairing handshake to populate
`gateway.auth` + `gateway.device_*` in `hosts.json`.

Configure, start, chat — same commands as Linux:

```bash
clawctl agent provider attach <provider> --agent <name>
clawctl agent configure <name> --stage providers --provider <provider>
clawctl agent start <name>
clawctl agent chat <name>
```

### Lifecycle differences

On macOS the lifecycle backend uses `launchctl` in the **system** domain
(plists land in `/Library/LaunchDaemons/`, not `~/Library/LaunchAgents/`).
This is deliberate — daemons must survive user logout and reboot. See
[`docs/operations/hermes-macos-upstream-quirks.md`](operations/hermes-macos-upstream-quirks.md)
for the upstream hermes defects clawrium routes around.

### Manual cleanup (if you tear a Mac host down by hand)

```bash
# Remove the xclm management user
sudo dscl . -delete /Users/xclm
sudo rm -f /etc/sudoers.d/xclm

# Remove a hermes agent named <agent>
sudo launchctl bootout system/ai.clawrium.hermes.<agent>
sudo launchctl bootout system/ai.clawrium.hermes.<agent>.dashboard
sudo rm -f /Library/LaunchDaemons/ai.clawrium.hermes.<agent>*.plist
sudo dscl . -delete /Users/<agent>
sudo rm -rf /Users/<agent>

# Remove an openclaw agent named <agent>
sudo launchctl bootout system/ai.clawrium.openclaw.<agent>
sudo rm -f /Library/LaunchDaemons/ai.clawrium.openclaw.<agent>.plist
sudo dscl . -delete /Users/<agent>
sudo rm -rf /Users/<agent>
```

## Troubleshooting

### "command not found: clawctl"

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

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
 + clawrium==26.8.1
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
│ server      Manage the local GUI server (loopback-only, port 36000)          │
│ version     Show clawctl version and exit                                    │
│ completion  Emit a shell-completion script                                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Check the version:

```bash
clawctl --version
```
```
clawctl 26.8.1
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

## Start the GUI

Bring up the local web dashboard with `clawctl server start`:

```bash
clawctl server start
```
```
Server started at http://127.0.0.1:36000 (pid 12345)
```

The server binds `127.0.0.1:36000` only. Open the URL in your browser.

- `clawctl server status` — show whether the server is running.
- `clawctl server stop` — stop the running server.
- `clawctl server run` — foreground/blocking mode, for `systemd` or Docker.

If port `36000` is already held by another process, `start` exits `1`
with a clear error and does not touch state. Stop the other process
and re-run.

> **Note**: `clawctl server` is Linux-only in this release. macOS
> support ships in a follow-up.

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

`hermes`, `openclaw`, and install-only `claude` and `pi` agent types are supported on
macOS (Apple Silicon, macOS 14+). Pi is also supported on Ubuntu 24.04 x86_64.
They can coexist on the same host.

```bash
# hermes
clawctl agent create <name> --type hermes --host <alias>

# openclaw (--provider is mandatory since v26.7.3)
clawctl agent create <name> --type openclaw --host <alias> --provider <provider-name>

# Claude Code (install-only; no service is started)
clawctl agent create <name> --type claude --host <alias>

# Pi (install-only; no service or native UI is started)
clawctl agent create <name> --type pi --host <alias>
```

Behind the scenes, clawrium installs Homebrew (if missing) and the
brew packages required for the chosen agent type, creates a per-agent
macOS user (`/Users/<agent_name>/`), and runs the upstream installer:

- **hermes** requires `node`, `ripgrep`, `ffmpeg`, and `uv`. The
  upstream hermes installer also writes a launchd plist (gateway +
  optional dashboard) at `/Library/LaunchDaemons/`.
- **openclaw** requires only `node`. Install registers a launchd unit
  at `/Library/LaunchDaemons/ai.clawrium.openclaw.<agent>.plist` and
  performs the loopback pairing handshake to populate `gateway.auth`
  + `gateway.device_*` in `hosts.json`.
- **claude** requires Node.js 20 or later. Install creates an isolated
  per-agent Claude Code prefix only: it does not invoke Claude Code, log in,
  start a service, allocate a port, create a gateway, pair a device, or expose
  a UI. See [Claude Code Support](agent-support/claude.md) for credential,
  settings, finite-command, and removal boundaries.
- **pi** requires Node.js 20.6 or later. Install creates a dedicated account
  and pinned Pi prefix only: it does not start a service, allocate a port, or
  expose a native UI. To chat, attach one existing OpenRouter provider with an
  unprefixed OpenRouter `default_model`, an AWS Identity Center Bedrock provider
  created with its model, region, and complete `--sso-*` profile metadata, or a
  single `openai-codex` provider with one model from Pi's pinned 0.73.1 catalog.
  Then sync: `clawctl agent provider attach <provider> --agent <name>`;
  `clawctl agent sync <name>`; `clawctl agent chat <name>`. For Bedrock, Clawrium
  writes only an isolated AWS profile/configuration to the Pi account; run
  `aws sso login --profile <profile>` as that account before chat. It never
  copies a controller `~/.aws`, an SSO token cache, or static AWS keys. Pi
  consumes the assigned access on demand and never requests a grant. `agent exec`
  receives the same isolated environment. For `openai-codex`, create the provider
  without an API key, attach and sync it, then run
  `clawctl agent provider login <provider> --agent <name>` from an interactive
  terminal. That command opens Pi under only the dedicated agent account; complete
  Pi's native `/login` → `openai-codex` flow there. Pi owns the resulting private
  OAuth document and refreshes it locally; on expiry or revocation, rerun the same
  command. Never export an OAuth bearer, set `OPENAI_API_KEY`, or copy a controller
  `~/.pi` directory. Pi supports one provider; `agent open` remains unavailable.
  Bedrock chat needs AWS CLI v2 installed on the fleet host and an interactive
  `aws sso login` performed as the dedicated Pi account; an expired login produces
  a recoverable error rather than falling back to another credential source.

  **Bedrock cleanup boundary.** Detaching Bedrock or switching the Pi agent to
  another provider removes Clawrium-managed AWS files and attempts to clear the
  dedicated Pi account's local AWS SSO and CLI caches. This is best-effort local
  file cleanup, not upstream AWS Identity Center session revocation. It cannot
  invalidate credentials already copied or held in memory, or prevent concurrent
  Pi processes running as the same account from recreating cache files. If
  needed, separately expire or revoke the upstream AWS session.

  Pi 0.73.1's [Amazon Bedrock provider documentation](https://github.com/earendil-works/pi/blob/v0.73.1/packages/coding-agent/docs/providers.md#amazon-bedrock)
  consumes `AWS_PROFILE` and `AWS_REGION` through its AWS SDK credential chain;
  on-demand Pi chat and exec do not discover or invoke an `aws` binary.

Configure, start, chat — same commands as Linux for daemon-backed Hermes and
OpenClaw agents:

```bash
# On hermes, --role is required (use `primary` for the first attachment;
# auxiliary slots: vision, web_extract, compression, session_search,
# skills_hub, approval, mcp, title_generation, curator). On openclaw,
# omit --role — only one provider per agent is permitted.
clawctl agent provider attach <provider> --agent <name> [--role primary]
clawctl agent configure <name> --stage providers --provider <provider>
clawctl agent start <name>
clawctl agent chat <name>
```

For the full hermes multi-provider model (1 primary + up to 9 auxiliary
slots), see [Hermes Support Matrix → Multi-provider attachments](agent-support/hermes.md#multi-provider-attachments).

### Herdr support

Installing a `hermes` or install-only `claude` agent also provisions the
pinned, checksum-verified, root-owned Herdr binary at `/usr/local/bin/herdr`.
It is shared by those supported agent accounts on the host and is not removed
when either account is deleted. Hermes alone receives Herdr's native
`herdr-agent-state` plugin; Claude is binary-only. OpenClaw, ZeroClaw, and
Ethos do not provision or integrate Herdr.

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

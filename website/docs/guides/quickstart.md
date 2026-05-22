---
sidebar_position: 1
description: Deploy your first AI assistant in 5 minutes with this step-by-step quickstart guide.
keywords: [quickstart, tutorial, first agent, deploy, get started, 5 minutes]
---

# Quickstart

Deploy your first [OpenClaw](https://github.com/openclaw/openclaw) instance in under 5 minutes. This guide walks through the complete workflow from installation to a running agent.

## What You'll Need

Before you start, verify you have:

| Requirement | How to Check |
|-------------|--------------|
| **Python 3.10+** | `python3 --version` |
| **uv installed** | `uv --version` |
| **Target host ready** | Ubuntu 22.04/24.04 with SSH access |
| **API key** | OpenAI or Anthropic API key |

:::tip No target host yet?
You can still follow along through Step 3 to set up Clawrium locally. You'll need a target host (VM, Raspberry Pi, spare machine) for the agent deployment steps.
:::

## Step 1: Install Clawrium

Install on your control machine:

```bash
uv tool install clawrium
```
```
Resolved 1 package in 523ms
Installed 1 package in 12ms
 + clawrium==26.5.4
```

Verify installation:

```bash
clm --help
```
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

## Step 2: Initialize Clawrium

Create the configuration directory and validate dependencies:

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

## Step 3: Prepare a Host

Initialize the target host. Clawrium generates a unique keypair and sets up the `xclm` management user:

```bash
clm host init 192.168.1.100 --user myuser
```

Replace:
- `192.168.1.100` with your target host's IP or hostname
- `myuser` with a user that has sudo privileges on the target

```
Generating SSH keypair for 192.168.1.100...
✓ Keypair saved to ~/.config/clawrium/keys/192.168.1.100/

Connecting to 192.168.1.100 as myuser...
Password for myuser@192.168.1.100: ********

Configuring xclm user on remote host...
  Creating user 'xclm'...
  Configuring passwordless sudo...
  Adding SSH public key...
✓ Host initialization complete

Next: clm host add 192.168.1.100 --alias <friendly-name>
```

:::note Manual setup required?
If automatic setup fails (e.g., password authentication disabled), Clawrium shows manual setup instructions. Follow them on the target host, then continue to the next step.
:::

## Step 4: Add the Host

Add the initialized host to your fleet:

```bash
clm host add 192.168.1.100 --alias homelab
```
```
Connecting to 192.168.1.100 as xclm...
  Unknown host key for 192.168.1.100
    Fingerprint: SHA256:abc123def456...
  Accept this host key? [y/N]: y
✓ Host key saved

Detecting hardware capabilities...
  CPU: 4 cores (x86_64)
  Memory: 16 GB
  GPU: None detected
✓ Host 'homelab' added to fleet
```

Verify with:

```bash
clm host list
```
```
ALIAS      HOSTNAME         STATUS    CPU    MEMORY  GPU
────────────────────────────────────────────────────────────
homelab    192.168.1.100    online    4      16 GB   -
```

## Step 5: Install the Agent

Install OpenClaw on your host:

```bash
clm agent install --type openclaw --host homelab --name my-assistant
```
```
Fetching openclaw manifest...
✓ Manifest loaded: openclaw v1.2.0

Installing on homelab...
  Installing system dependencies...
  Creating agent user 'oc-my-assistant'...
  Deploying agent files...
  Creating systemd service...
✓ Agent 'my-assistant' installed

Next: clm agent configure my-assistant
```

## Step 6: Configure the Agent

Run the configuration wizard:

```bash
clm agent configure my-assistant
```
```
═══════════════════════════════════════════════════════════
  OpenClaw Configuration: my-assistant
═══════════════════════════════════════════════════════════

Stage 1/4: Provider Setup
─────────────────────────
Select primary LLM provider:
  1. OpenAI
  2. Anthropic
  3. OpenRouter
  > 2

Enter Anthropic API key: ********
Testing connection... ✓ Connected

Stage 2/4: Identity
───────────────────
Agent name [my-assistant]: 
Description [A helpful AI assistant]: My homelab assistant

Stage 3/4: Channels
──────────────────
Enable CLI channel? [Y/n]: y
Enable Discord channel? [y/N]: n

Stage 4/4: Validation
────────────────────
✓ Provider: Anthropic (claude-3-5-sonnet)
✓ Channels: CLI
✓ Configuration valid

Save and start agent? [Y/n]: y
✓ Configuration saved
✓ Agent started
```

## Step 7: Check Fleet Status

Verify your fleet:

```bash
clm ps
```
```
HOST        AGENT          TYPE       PROVIDER   STATUS    UPTIME
──────────────────────────────────────────────────────────────────
homelab     my-assistant   openclaw   anthropic  running   1m
```

## Step 8: Chat with Your Agent

Test your agent:

```bash
clm chat my-assistant
```
```
Connected to my-assistant (openclaw) on homelab
Type 'exit' to quit, 'help' for commands

You: Hello! What can you help me with?

my-assistant: Hello! I'm your homelab assistant running on OpenClaw. 
I can help you with:
- Answering questions and research
- Writing and editing text
- Brainstorming ideas
- General assistance

What would you like to work on today?

You: exit
Disconnected.
```

## What's Next?

- [Host Setup Guide](./host-setup.md) - Detailed host preparation options
- [Agent Onboarding](./agent-onboarding.md) - Deep dive into agent configuration
- [OpenClaw Support Matrix](/docs/agent-support/openclaw) - Providers, channels, integrations
- [Fleet Management](./fleet-management.md) - Managing multiple agents

## Troubleshooting

### Connection refused during host init

SSH isn't running or is blocked by firewall on the target host:

```bash
# On target host
sudo systemctl status sshd
sudo ufw allow ssh
```

### Permission denied during host init

Your SSH user doesn't have sudo privileges. Verify on the target:

```bash
sudo whoami
# Should output: root
```

### Agent won't start

Check the agent logs:

```bash
clm agent logs my-assistant
```

Common issues:
- Invalid API key (re-run `clm agent configure my-assistant --stage providers`)
- Port already in use (check with `clm agent status my-assistant`)

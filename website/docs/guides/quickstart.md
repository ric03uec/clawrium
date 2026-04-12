---
sidebar_position: 1
description: Deploy your first AI assistant claw in under 10 minutes with this step-by-step quickstart guide.
keywords: [quickstart, tutorial, first claw, deploy, get started]
---

# Quickstart

Deploy your first OpenClaw instance in under 10 minutes. This guide walks through the complete workflow from installation to a running claw.

## Prerequisites

- Clawrium installed ([Installation Guide](../installation.md))
- A target machine (physical or VM) with:
  - Ubuntu 22.04/24.04
  - SSH access with sudo privileges
  - Network connectivity from your management machine

## Install Clawrium

Use one of the following commands on your control machine:

```bash
uv tool install clawrium
# or
python -m pip install clawrium
```

## Step 1: Initialize Clawrium

First, initialize Clawrium on your management machine:

```bash
clm init
```

This creates the configuration directory and validates dependencies.

## Step 2: Prepare a Host

Initialize the target host. Clawrium will generate a unique keypair and set up the `xclm` management user:

```bash
clm host init 192.168.1.100 --user myuser
```

Replace:
- `192.168.1.100` with your target host's IP or hostname
- `myuser` with a user that has sudo privileges on the target

If auto-setup succeeds, you'll see a success message. If it fails, follow the manual setup instructions shown in the output.

## Step 3: Add the Host

Add the initialized host to your fleet:

```bash
clm host add 192.168.1.100 --alias homelab
```

The `--alias` flag gives your host a friendly name. Clawrium will:
1. Connect using the keypair from `host init`
2. Prompt you to accept the host key (first connection)
3. Detect hardware capabilities
4. Save the host to your configuration

Verify with:

```bash
clm host list
```

## Step 4: Browse Available Claws

See what claw types are available:

```bash
clm registry list
```

Example output:
```
Available Claws:
  openclaw    Open-source AI assistant framework
```

Get details about OpenClaw:

```bash
clm registry show openclaw
```

## Step 5: Configure Secrets

OpenClaw requires provider credentials. Check what secrets are needed:

```bash
clm secret list oc-homelab
```

Set the required secrets:

```bash
# For openclaw - set provider credentials
clm secret set oc-homelab OPENAI_API_KEY

clm secret set oc-homelab ANTHROPIC_API_KEY
```

The secret value is entered via masked prompt (not visible on screen).

## Step 6: Install the Claw

Install OpenClaw on your host:

```bash
clm install --claw openclaw --host homelab
```

Clawrium will:
1. Check host compatibility
2. Verify required secrets are set
3. Deploy the claw to the host
4. Start the claw service

## Step 7: Check Status

Verify your fleet status:

```bash
clm status
```

You should see your host with the claw running.

## What's Next?

- [Host Setup Guide](./host-setup.md) - Detailed host preparation options
- [Secret Management](./secret-management.md) - Managing claw secrets
- Browse more claws with `clm registry list`

## Troubleshooting

### Permission denied during host init

Your SSH user doesn't have sudo privileges or the password was incorrect. Verify you can run `sudo whoami` on the target host.

### Host not compatible with claw

The claw's manifest doesn't support your host's OS, version, or architecture. Run `clm registry show <claw>` to see supported platforms.

### Missing required secrets

Run `clm secret list <claw-name>` to see which secrets are missing. Set them before running `clm install`.

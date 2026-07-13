---
sidebar_position: 1
description: Deploy your first AI assistant in 5 minutes with this step-by-step quickstart guide.
keywords: [quickstart, tutorial, first agent, deploy, get started, 5 minutes]
---

# Quickstart

Deploy your first [OpenClaw](https://github.com/openclaw/openclaw) instance in under 5 minutes. This guide walks through the complete workflow from installation to a running agent.

## Watch the walkthrough (3 min)

<div style={{position: 'relative', paddingBottom: '56.25%', height: 0, overflow: 'hidden', maxWidth: '100%', marginBottom: '2rem'}}>
  <iframe
    style={{position: 'absolute', top: 0, left: 0, width: '100%', height: '100%'}}
    src="https://www.youtube.com/embed/qEqDnzJBaig"
    title="Clawrium Quickstart — Install + Chat With Your First Agent (3 min)"
    frameBorder="0"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
    allowFullScreen>
  </iframe>
</div>

The video walks through the same steps below end-to-end on a real host. The recording uses a **`hermes` agent** with a **`litellm` provider** (one of several supported agent + provider combinations); the written guide below uses **`openclaw` + `anthropic`** as the canonical example. The CLI surface is identical — only the `--type` flag value and provider name change.

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
 + clawrium==26.7.2
```

Verify installation:

```bash
clawctl --help
```
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

## Step 2: Initialize Clawrium

Create the configuration directory and validate dependencies:

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

## Step 3: Prepare a Host

Clawrium connects to remote hosts as a dedicated unprivileged management user named `xclm`. This user must be created on the target host once before registration. Follow the [Host Setup guide](host-setup.md) for the one-time `xclm` user provisioning on Linux or macOS — it's a single SSH session of `useradd`/`visudo` commands.

## Step 4: Register the Host

With `xclm` provisioned on the target, register the host into your fleet:

```bash
clawctl host create 192.168.1.100 --user xclm --alias homelab
```

Replace `192.168.1.100` with your target host's IP or hostname and `homelab` with a friendly alias.

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
clawctl host get
```
```
Alias      Host            Architecture   Cores   Memory (GB)   Tags
──────────────────────────────────────────────────────────────────────
homelab    192.168.1.100   x86_64         4       16.0          -
```

## Step 5: Install the Agent

Install OpenClaw on your host (the agent name is positional):

```bash
clawctl agent create my-assistant --type openclaw --host homelab
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

Next: clawctl agent configure my-assistant
```

## Step 6: Configure the Agent

`clawctl agent configure` runs one configuration stage per invocation; the
`--stage` flag selects which stage. Pass each stage explicitly — bare
`clawctl agent configure <name>` exits with an error asking you to pick one.

First, attach a provider. You'll need a registered provider — see
`clawctl provider registry create --help` for one-shot provider setup, or
reuse one already in the secret store.

```bash
clawctl agent configure my-assistant --stage providers --provider my-anthropic
```
```
agent/my-assistant: configure stage=providers on homelab
agent/my-assistant: [configure] Loaded provider API key from secrets
agent/my-assistant: [configure] Running Ansible playbook...
agent/my-assistant: [configure] Saving configuration to hosts.json...
agent/my-assistant: stage providers complete
```

Then run the identity stage to set personality / name metadata:

```bash
clawctl agent configure my-assistant --stage identity
```

Finally, validate the resulting configuration is internally consistent:

```bash
clawctl agent configure my-assistant --stage validate
```

:::note Channels
The `channels` stage is deprecated. Manage channels via
`clawctl channel registry create` followed by
`clawctl agent channel attach`. See the [Channel reference](../reference/cli/index.md)
for the full surface.
:::

## Step 7: Start the Agent

`agent create` installs the systemd unit but leaves it stopped; `configure`
provisions it but does not start it. Bring it up explicitly:

```bash
clawctl agent start my-assistant
```
```
agent/my-assistant: [start] Starting systemd unit on homelab...
agent/my-assistant: [start] Service active
agent/my-assistant: running
```

## Step 8: Check Fleet Status

Verify your fleet:

```bash
clawctl agent get
```
```
NAME           TYPE       HOST       PROVIDER       STATUS    AGE
─────────────────────────────────────────────────────────────────
my-assistant   openclaw   homelab    my-anthropic   ready     1m
```

## Step 9: Chat with Your Agent

Test your agent:

```bash
clawctl agent chat my-assistant
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

### Connection refused during `clawctl host create`

SSH isn't running or is blocked by firewall on the target host:

```bash
# On target host
sudo systemctl status sshd
sudo ufw allow ssh
```

### Permission denied during `clawctl host create`

The `xclm` management user hasn't been created on the target, or the
per-host public key hasn't been added to `~xclm/.ssh/authorized_keys`.
See the [Host Setup guide](host-setup.md) for the Linux + macOS setup
steps and run them on the target before retrying.

### Agent won't start

Check the agent logs:

```bash
clawctl agent logs my-assistant
```

Common issues:
- Invalid API key — re-run the provider stage with the right provider name:
  `clawctl agent configure my-assistant --stage providers --provider <name>`
- Port already in use — check with `clawctl agent describe my-assistant`

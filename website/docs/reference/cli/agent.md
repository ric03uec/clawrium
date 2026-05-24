---
sidebar_position: 2
description: Command reference for managing agent lifecycle - install, configure, start, stop, and monitor agents
keywords: [cli, agent, command reference, configure, install, start, stop]
---

# clawctl agent

Manage agent lifecycle: install, configure, start, stop, and monitor agents.

## Synopsis

```bash
clawctl agent <command> [options]
```

## Commands

### install

Install an agent on a host.

```bash
clawctl agent create <agent-type> --host <host> --name <agent-name> [options]
```

**Arguments:**
- `agent-type` - Type of agent to install (e.g., `openclaw`, `zeroclaw`, `nanoclaw`)

**Options:**
- `--host <hostname>` - Target host (required)
- `--name <name>` - Agent instance name (required)
- `--version <version>` - Specific version to install (default: latest)
- `--user <username>` - User to run the agent as (default: from manifest)

**Examples:**

```bash
# Install latest openclaw
clawctl agent create openclaw --host lab1 --name opc-work

# Install specific version
clawctl agent create zeroclaw --host pi4 --name zc-edge --version 2026.3.0

# Install with custom user
clawctl agent create openclaw --host lab2 --name opc-dev --user alice
```

**What happens:**
1. Verifies host compatibility
2. Downloads agent package
3. Deploys to host
4. Initializes onboarding (state: PENDING)
5. Returns installation summary

**Success output:**
```
✓ Installed openclaw v2026.4.2 on lab1
✓ Agent: opc-work
✓ Status: PENDING (onboarding required)

Next step: clawctl agent configure opc-work
```

**Related:**
- [clawctl agent registry describe](#related-commands) - Check agent requirements before install
- [clawctl agent configure](#configure) - Configure the installed agent

---

### configure

Configure an agent through interactive onboarding wizard.

```bash
clawctl agent configure <agent-name> [options]
```

**Arguments:**
- `agent-name` - Name of the agent to configure

**Options:**
- `--stage <stage>` / `-s` - Configure specific stage only (providers, identity, channels, validate)
- `--yes` / `-y` - Accept defaults and skip confirmations
- `--file <path>` / `-f` - Import identity file (SOUL.md, AGENTS.md, TOOLS.md, IDENTITY.md). Repeatable. Only valid with `--stage identity`
- `--skip-health` - Skip OpenClaw gateway health verification during validate stage
- `--edit-config` - Open agent config file in editor for direct editing. Cannot be combined with `--stage`, `--file`, or `--skip-health`
- `--editor <command>` - Editor command for `--edit-config` (e.g., vim, nano). Falls back to VISUAL, then EDITOR, then vi

**Examples:**

```bash
# Full interactive wizard
clawctl agent configure opc-work

# Configure specific stage
clawctl agent configure opc-work --stage providers
clawctl agent configure opc-work --stage identity

# Non-interactive (use defaults)
clawctl agent configure opc-work --yes

# Import identity file
clawctl agent configure opc-work --stage identity --file ~/SOUL.md

# Edit config directly in default editor
clawctl agent configure opc-work --edit-config

# Edit config with specific editor
clawctl agent configure opc-work --edit-config --editor nano
```

**Stages:**

| Stage | Purpose | Skippable? |
|-------|---------|-----------|
| providers | Assign inference provider | No |
| identity | Configure personality/behavior | Depends on agent type |
| channels | Set up communication methods | Depends on agent type |
| validate | Verify configuration | No |

**Interactive wizard flow:**

```bash
$ clawctl agent configure opc-work

Starting onboarding for 'opc-work' (openclaw)
Current state: PENDING

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1/4] PROVIDERS - Select Inference Provider
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Available providers:
  1. openai-prod (OpenAI GPT-4)
  2. local-ollama (Ollama - llama3:latest)

Select provider [1-2]: 1
✓ Provider 'openai-prod' assigned

[... continues through remaining stages ...]

✓ Onboarding complete! 'opc-work' is ready to start.
```

**Related:**
- [Agent Onboarding Guide](../../guides/agent-onboarding.md) - Detailed onboarding walkthrough
- [clawctl agent describe](#status) - Check configuration progress

---

### start

Start a configured agent.

```bash
clawctl agent start <agent-name> [options]
```

**Arguments:**
- `agent-name` - Name of the agent to start

**Options:**
- `--wait` - Wait for agent to be fully running before returning
- `--timeout <seconds>` - Max wait time (default: 30)

**Examples:**

```bash
# Start agent
clawctl agent start opc-work

# Start and wait for confirmation
clawctl agent start opc-work --wait

# Start with custom timeout
clawctl agent start opc-work --wait --timeout 60
```

**Requirements:**
- Agent must be in READY state (onboarding complete)
- Host must be reachable
- Required secrets must be set

**Success output:**
```
✓ Starting 'opc-work' on lab1...
✓ Agent started successfully
```

**Error: Onboarding incomplete:**
```
✗ Cannot start 'opc-work' - onboarding incomplete

Status: ONBOARDING (2/4 stages)

Remaining stages:
  - channels
  - validate

Complete onboarding: clawctl agent configure opc-work
```

**Related:**
- [clawctl agent stop](#stop) - Stop a running agent
- [clawctl agent describe](#status) - Check if agent is running

---

### stop

Stop a running agent.

```bash
clawctl agent stop <agent-name> [options]
```

**Arguments:**
- `agent-name` - Name of the agent to stop

**Options:**
- `--force` - Force stop (send SIGKILL instead of graceful shutdown)
- `--timeout <seconds>` - Wait time before force kill (default: 10)

**Examples:**

```bash
# Graceful stop
clawctl agent stop opc-work

# Force stop immediately
clawctl agent stop opc-work --force

# Graceful with custom timeout
clawctl agent stop opc-work --timeout 30
```

**Success output:**
```
✓ Stopping 'opc-work' on lab1...
✓ Agent stopped successfully
```

**Related:**
- [clawctl agent start](#start) - Start a stopped agent
- [clawctl agent restart](#restart) - Restart a running agent

---

### restart

Restart a running agent (stop + start).

```bash
clawctl agent restart <agent-name> [options]
```

**Arguments:**
- `agent-name` - Name of the agent to restart

**Options:**
- `--wait` - Wait for agent to be fully running after restart
- `--force` - Force stop before restart

**Examples:**

```bash
# Restart agent
clawctl agent restart opc-work

# Force restart
clawctl agent restart opc-work --force

# Restart and wait for confirmation
clawctl agent restart opc-work --wait
```

**Success output:**
```
✓ Stopping 'opc-work' on lab1...
✓ Agent stopped
✓ Starting 'opc-work' on lab1...
✓ Agent started successfully
```

---

### status

Display agent status and health information.

```bash
clawctl agent describe [agent-name] [options]
```

**Arguments:**
- `agent-name` - Specific agent to check (optional - shows all if omitted)

**Options:**
- `--verbose` - Show detailed information including onboarding progress
- `--json` - Output in JSON format

**Examples:**

```bash
# Show all agents
clawctl agent describe

# Show specific agent
clawctl agent describe opc-work

# Detailed view with onboarding progress
clawctl agent describe opc-work --verbose

# JSON output for scripting
clawctl agent describe --json
```

**Output (all agents):**

```
Agent Status:
┌──────────┬──────┬───────┬─────────────┬──────────┐
│ Name     │ Host │ Type  │ Status      │ Progress │
├──────────┼──────┼───────┼─────────────┼──────────┤
│ opc-work │ lab1 │ opc   │ RUNNING     │ 4/4      │
│ zc-edge  │ pi4  │ zc    │ READY       │ 4/4      │
│ opc-home │ lab1 │ opc   │ ONBOARDING  │ 2/4      │
│ nc-test  │ lab2 │ nc    │ PENDING     │ 0/4      │
└──────────┴──────┴───────┴─────────────┴──────────┘
```

**Output (verbose):**

```bash
$ clawctl agent describe opc-work --verbose

Agent: opc-work
Host: lab1 (192.168.1.100)
Type: openclaw v2026.4.2
Status: RUNNING
Process ID: 12345
Uptime: 2d 5h 32m

Onboarding: COMPLETE (4/4 stages)
  ✓ PROVIDERS  (completed 2026-04-05 10:02:00 UTC)
    Provider: openai-prod (OpenAI GPT-4)

  ✓ IDENTITY   (completed 2026-04-05 10:05:00 UTC)
    Files: SOUL.md, IDENTITY.md

  ✓ CHANNELS   (completed 2026-04-05 10:07:00 UTC)
    Default: CLI

  ✓ VALIDATE   (completed 2026-04-05 10:08:00 UTC)

Resource Usage:
  CPU: 2.3%
  Memory: 245 MB
  Disk: 1.2 GB

Health: HEALTHY
  Last check: 2026-04-07 15:30:00 UTC
  Response time: 120ms
```

**Status values:**

| Status | Description | Can Start? |
|--------|-------------|-----------|
| `PENDING` | Installed, onboarding not started | ❌ No |
| `ONBOARDING` | Configuration in progress | ❌ No |
| `READY` | Configured, not running | ✅ Yes |
| `RUNNING` | Active and operational | - |
| `STOPPED` | Previously running, now stopped | ✅ Yes |
| `ERROR` | Configuration or runtime error | ❌ No |

**Related:**
- [clawctl agent logs](#logs) - View agent logs
- [Agent Onboarding Guide](../../guides/agent-onboarding.md) - Understanding onboarding states

---

### logs

View agent logs.

```bash
clawctl agent logs <agent-name> [options]
```

**Arguments:**
- `agent-name` - Name of the agent

**Options:**
- `--follow` / `-f` - Stream logs in real-time
- `--lines <n>` / `-n <n>` - Number of lines to show (default: 50)
- `--since <time>` - Show logs since timestamp (e.g., "2h", "30m", "2024-01-01")
- `--level <level>` - Filter by log level (debug, info, warn, error)

**Examples:**

```bash
# Show last 50 lines
clawctl agent logs opc-work

# Show last 200 lines
clawctl agent logs opc-work --lines 200

# Follow logs in real-time
clawctl agent logs opc-work --follow

# Show logs from last 2 hours
clawctl agent logs opc-work --since 2h

# Show only errors
clawctl agent logs opc-work --level error
```

**Output:**
```
2026-04-07 15:30:15 [INFO] Agent started successfully
2026-04-07 15:30:16 [INFO] Connected to provider: openai-prod
2026-04-07 15:30:17 [INFO] Ready to accept requests
2026-04-07 15:32:45 [INFO] Processing request: "What's the weather?"
2026-04-07 15:32:47 [INFO] Request completed (2.1s)
```

**Related:**
- [clawctl agent describe](#status) - Check agent health
- [Troubleshooting Guide](../../troubleshooting.md) - Debugging common issues

---

### remove

Remove an agent from a host.

```bash
clawctl agent delete <agent-name> [options]
```

**Arguments:**
- `agent-name` - Name of the agent to remove

**Options:**
- `--force` - Skip confirmation prompt
- `--keep-data` - Preserve agent data and configuration files

**Examples:**

```bash
# Remove with confirmation
clawctl agent delete opc-work

# Force remove (no prompt)
clawctl agent delete opc-work --force

# Remove but keep data
clawctl agent delete opc-work --keep-data
```

**Interactive prompt:**
```
Remove agent 'opc-work' from host 'lab1'?
This will:
  - Stop the agent (if running)
  - Remove the installation
  - Delete configuration and data

Are you sure? [y/N]: y

✓ Stopping agent...
✓ Removing installation...
✓ Cleaning up data...
✓ Agent 'opc-work' removed from lab1
```

**Warning:**
By default, removal is permanent and deletes all agent data including:
- Configuration files
- Identity files (SOUL.md, IDENTITY.md)
- Logs and session history
- Cache and temporary files

Use `--keep-data` to preserve these files for later reinstallation.

---

### list

List all installed agents across the fleet.

```bash
clawctl agent list [options]
```

**Options:**
- `--host <hostname>` - Filter by host
- `--type <agent-type>` - Filter by agent type
- `--status <status>` - Filter by status (pending, onboarding, ready, running, stopped, error)
- `--json` - Output in JSON format

**Examples:**

```bash
# List all agents
clawctl agent list

# List agents on specific host
clawctl agent list --host lab1

# List all openclaw instances
clawctl agent list --type openclaw

# List running agents only
clawctl agent list --status running

# JSON output
clawctl agent list --json
```

**Output:**
```
Installed Agents (4):

┌──────────┬──────┬─────────┬─────────────┬────────────┐
│ Name     │ Host │ Type    │ Version     │ Status     │
├──────────┼──────┼─────────┼─────────────┼────────────┤
│ opc-work │ lab1 │ openclaw│ 2026.4.2    │ RUNNING    │
│ opc-home │ lab1 │ openclaw│ 2026.4.2    │ READY      │
│ zc-edge  │ pi4  │ zeroclaw│ 2026.3.1    │ RUNNING    │
│ nc-test  │ lab2 │ nanoclaw│ 2026.2.0    │ ONBOARDING │
└──────────┴──────┴─────────┴─────────────┴────────────┘
```

---

### upgrade

Upgrade an agent to a newer version.

```bash
clawctl agent upgrade <agent-name> [options]
```

**Arguments:**
- `agent-name` - Name of the agent to upgrade

**Options:**
- `--version <version>` - Upgrade to specific version (default: latest)
- `--restart` - Restart agent after upgrade (if it was running)

**Examples:**

```bash
# Upgrade to latest version
clawctl agent upgrade opc-work

# Upgrade to specific version
clawctl agent upgrade opc-work --version 2026.5.0

# Upgrade and restart
clawctl agent upgrade opc-work --restart
```

**Output:**
```
Agent: opc-work
Current version: 2026.4.2
Latest version: 2026.5.1

Upgrading to v2026.5.1...
✓ Downloaded package
✓ Stopped agent
✓ Installed new version
✓ Started agent
✓ Upgrade complete

opc-work is now running v2026.5.1
```

**Note:**
- Onboarding configuration is preserved during upgrades
- Secrets and identity files are not affected
- Agent is stopped during upgrade (use `--restart` to auto-start)

---

## Related Commands

### clawctl provider

Manage inference providers used by agents.

```bash
clawctl provider registry get          # List configured providers
clawctl provider registry create           # Add new provider
clawctl provider registry delete        # Remove provider
```

See [clawctl provider](./provider.md) for full reference.

### clawctl agent secret

Manage agent secrets and API keys.

```bash
clawctl agent secret create <agent> <key>     # Set secret value
clawctl agent secret get --agent <agent>          # List required secrets
clawctl agent secret delete <agent> <key>  # Remove secret
```

See [clawctl agent secret](./secret.md) for full reference.

### clawctl agent registry

Browse available agent types.

```bash
clawctl agent registry get          # List available agents
clawctl agent registry describe <type>   # Show agent details
```

See [clawctl agent registry](./registry.md) for full reference.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Agent not found |
| 4 | Host unreachable |
| 5 | Onboarding incomplete |
| 6 | Permission denied |

**Example usage in scripts:**
```bash
#!/bin/bash
clawctl agent start opc-work
if [ $? -eq 5 ]; then
  echo "Onboarding required"
  clawctl agent configure opc-work --yes
  clawctl agent start opc-work
fi
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CLAWRIUM_CONFIG` | Config directory path | `~/.config/clawrium` |
| `CLAWRIUM_LOG_LEVEL` | Logging verbosity | `info` |
| `CLAWRIUM_TIMEOUT` | Default operation timeout (seconds) | `30` |

---

## See Also

- [Agent Onboarding Guide](../../guides/agent-onboarding.md) - Detailed onboarding walkthrough
- [Fleet Management Guide](../../guides/fleet-management.md) - Managing multiple agents
- [Troubleshooting](../../troubleshooting.md) - Common issues and solutions

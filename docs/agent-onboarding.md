# Agent Onboarding Workflow

## Overview

When you install an agent (claw) on a host, it goes through a structured onboarding workflow before it can be started. This workflow ensures the agent is properly configured with inference providers, identity settings, communication channels, and has passed validation checks.

Think of onboarding as a setup wizard that walks you through all the essential configuration steps for your newly installed agent.

## Why Onboarding?

Without a structured onboarding process:
- It's unclear what configuration steps remain
- Agents might be started with incomplete setup
- Different agent types have inconsistent setup experiences

With onboarding:
- ✅ Clear visibility into configuration progress
- ✅ Agents can only start when fully configured
- ✅ Consistent experience across all agent types
- ✅ Guided configuration with `clawctl agent configure`

## Onboarding States

Every agent goes through the same six states:

```
┌──────────┐
│ PENDING  │  After install, before onboarding starts
└────┬─────┘
     │  clawctl agent configure <name>
     ▼
┌──────────┐
│ PROVIDERS│  Assign inference provider to this agent
└────┬─────┘
     │  complete
     ▼
┌──────────┐
│ IDENTITY │  Configure who this agent is
└────┬─────┘
     │  complete / skip
     ▼
┌──────────┐
│ CHANNELS │  Configure how agent communicates
└────┬─────┘
     │  complete / skip
     ▼
┌──────────┐
│ VALIDATE │  Verify agent is properly configured
└────┬─────┘
     │  pass
     ▼
┌──────────┐
│  READY   │  Agent can be started
└──────────┘
```

### State Descriptions

| State | Description | Can Skip? |
|-------|-------------|-----------|
| **PENDING** | Agent installed but onboarding not started | No |
| **PROVIDERS** | Assigning an inference provider (LLM backend) | No |
| **IDENTITY** | Configuring agent personality and behavior | Yes* |
| **CHANNELS** | Setting up communication methods | Yes* |
| **VALIDATE** | Running verification checks | No |
| **READY** | Onboarding complete, agent can start | - |

*Skippable stages depend on agent type. For example, ZeroClaw has minimal identity requirements and auto-skips this stage.

## Onboarding Stages

### 1. Providers Stage

**What it does:** Assigns an inference provider to the agent.

**Requirements:**
- At least one provider must be configured (use `clawctl provider registry get` to see available providers)
- Provider must be reachable and functional

**Example:**
```bash
$ clawctl agent configure opc-work
Starting onboarding for 'opc-work'...

[PROVIDERS] Select inference provider
Available providers:
  1. openai-prod (OpenAI GPT-4)
  2. local-ollama (Ollama - llama3)

Select provider [1-2]: 1
✓ Provider 'openai-prod' assigned
✓ Connectivity verified
```

### 2. Identity Stage

**What it does:** Configures the agent's personality, behavior, and role.

**Requirements (varies by agent type):**
- **OpenClaw**: Requires SOUL.md and IDENTITY.md files
- **ZeroClaw**: Auto-skipped (workspace MD files are rendered separately by configure; the runtime owns identity through `~/.zeroclaw/workspace/`)
- **IronClaw**: Governance identity configuration

**Example for OpenClaw:**
```bash
[IDENTITY] Configure agent personality

Create SOUL.md? This defines your agent's personality.
[Y/n]: y
✓ Created ~/.openclaw/SOUL.md

Create IDENTITY.md? This defines your agent's role and context.
[Y/n]: y
✓ Created ~/.openclaw/IDENTITY.md

✓ Identity stage complete
```

**Example for ZeroClaw:**
```bash
[IDENTITY] Configure agent personality
✓ Skipped (zeroclaw renders ~/.zeroclaw/workspace/{SOUL,IDENTITY,USER,AGENTS,TOOLS,MEMORY,HEARTBEAT}.md via configure)
```

### 3. Channels Stage

**What it does:** Configures how the agent communicates (CLI, web, messaging platforms).

**Requirements (varies by agent type):**
- **OpenClaw**: Select from CLI, WhatsApp, Slack, Discord, web
- **ZeroClaw**: CLI only (single confirm step; reachable via `clawctl agent chat` over the daemon's WebSocket gateway)

**Example:**
```bash
[CHANNELS] Configure communication channels

Select default channel:
  1. CLI (command line)
  2. WhatsApp
  3. Slack
  4. Discord
  5. Web interface

Select channel [1-5]: 1
✓ CLI channel configured
```

### 4. Validate Stage

**What it does:** Runs verification checks to ensure the agent is properly configured.

**Checks performed:**
- Configuration files exist
- Required secrets are set
- Agent can connect to inference provider
- Agent self-test passes (if supported)

**Example:**
```bash
[VALIDATE] Verifying configuration

✓ Configuration files present
✓ Provider connectivity verified
✓ Running agent self-test...
✓ All checks passed

✓ Onboarding complete! Agent is ready to start.
```

## Using `clawctl agent configure`

The `configure` command provides an interactive wizard for onboarding.

### Full Onboarding Wizard

Run the full wizard to go through all stages:

```bash
clawctl agent configure <agent-name>
```

The wizard will:
1. Show the current onboarding state
2. Walk through each incomplete stage
3. Automatically skip stages that don't apply
4. Validate the configuration
5. Mark the agent as READY when complete

### Configure a Specific Stage

If you need to reconfigure a specific stage:

```bash
clawctl agent configure <agent-name> --stage providers
clawctl agent configure <agent-name> --stage identity
clawctl agent configure <agent-name> --stage channels
```

### Skip Prompts

Use `--yes` to accept defaults and skip confirmations:

```bash
clawctl agent configure <agent-name> --yes
```

This is useful for:
- Automated setups
- CI/CD pipelines
- Bulk configuration

## Checking Onboarding Status

### View All Agents

```bash
$ clawctl agent describe

Agent Status:
┌──────────┬──────┬───────┬─────────────┬──────────┐
│ Name     │ Host │ Type  │ Status      │ Progress │
├──────────┼──────┼───────┼─────────────┼──────────┤
│ opc-work │ lab1 │ opc   │ ONBOARDING  │ 2/4      │
│ zc-edge  │ lab2 │ zc    │ READY       │ 4/4      │
│ opc-home │ lab1 │ opc   │ PENDING     │ 0/4      │
└──────────┴──────┴───────┴─────────────┴──────────┘
```

**Status meanings:**
- `PENDING`: Installed, onboarding not started
- `ONBOARDING`: In progress (shows N/4 stages completed)
- `READY`: Onboarding complete, can be started
- `RUNNING`: Agent is active (already started)

### View Detailed Progress

Use `--verbose` to see stage-level details:

```bash
$ clawctl agent describe opc-work --verbose

Agent: opc-work
Host: lab1
Type: openclaw
Status: ONBOARDING (2/4 stages)

Onboarding Progress:
  ✓ PROVIDERS  (completed 2026-04-07 10:02:00)
    Provider: openai-prod
  ✓ IDENTITY   (completed 2026-04-07 10:05:00)
  ⧗ CHANNELS   (pending)
  ⧗ VALIDATE   (pending)
```

## Starting an Agent

Agents can only be started when onboarding is complete (status: READY).

```bash
$ clawctl agent start opc-work
```

If onboarding is incomplete, you'll get a clear error:

```bash
$ clawctl agent start opc-work
Error: Cannot start 'opc-work' - onboarding incomplete

Remaining stages:
  - channels
  - validate

Run: clawctl agent configure opc-work
```

## Troubleshooting

### "Onboarding not initialized"

**Problem:** The agent was installed before the onboarding system was added.

**Solution:** Reinstall the agent or manually initialize onboarding:
```bash
clawctl agent reinstall <name>
```

### "Cannot transition from X to Y"

**Problem:** Trying to configure a stage out of order.

**Solution:** Use `clawctl agent configure <name>` (without --stage) to follow the proper workflow.

### Provider Verification Failed

**Problem:** The selected provider is unreachable or not responding.

**Solution:**
1. Check provider status: `clawctl provider status <provider-id>`
2. Verify network connectivity
3. Check provider API keys/secrets
4. Try a different provider

### Stage Marked as Skipped

**Problem:** A stage was auto-skipped but you want to configure it.

**Solution:** Re-run the stage configuration:
```bash
clawctl agent configure <name> --stage <stage-name>
```

## Agent-Specific Behavior

Different agent types have different onboarding requirements:

### OpenClaw
- **Identity**: Required - SOUL.md and IDENTITY.md files
- **Channels**: Required - Must select communication channel
- **Typical time**: 3-5 minutes

### ZeroClaw
- **Identity**: Auto-skipped (workspace MD files rendered by configure; see [ZeroClaw → Workspace files](agent-support/zeroclaw.md#2-configure-the-agent))
- **Channels**: CLI only — confirms the WebSocket gateway, no other channels supported
- **Pairing**: Automated during configure (`GET /pair/code` → `POST /pair`); bearer token persisted to `hosts.json`
- **Typical time**: 2-3 minutes (binary download dominates)

### IronClaw
- **Identity**: Required - Governance and compliance settings
- **Channels**: Required - Audit logging configuration
- **Typical time**: 5-10 minutes

## Next Steps

- [Agent Management](./index.md) - Managing installed agents
- [Provider Configuration](./host-preparation.md) - Setting up inference providers
- [CLI Reference](../website/docs/reference/cli/agent.md) - Full command documentation

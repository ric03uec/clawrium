---
sidebar_position: 4
description: Learn how to configure newly installed agents through the guided onboarding workflow
keywords: [onboarding, configuration, agent setup, configure, providers, identity, channels]
---

# Agent Onboarding

Every newly installed agent goes through a structured onboarding workflow before it can be started. This guide explains the onboarding process and how to use `clm agent configure` to set up your agents.

## What is Onboarding?

Onboarding is a step-by-step configuration process that ensures your agent has everything it needs to run:

- ✅ **Inference Provider**: The LLM backend the agent will use
- ✅ **Identity**: The agent's personality and behavior (for applicable agent types)
- ✅ **Communication**: How the agent interacts with users
- ✅ **Validation**: Verification that everything is configured correctly

Think of it as a setup wizard that prevents you from starting an incomplete or misconfigured agent.

## The Onboarding Workflow

All agents follow the same six-state workflow:

```
PENDING → PROVIDERS → IDENTITY → CHANNELS → VALIDATE → READY
```

### State Descriptions

| State | What Happens | Can Skip? |
|-------|--------------|-----------|
| **PENDING** | Waiting for onboarding to start | - |
| **PROVIDERS** | Select and verify inference provider | ❌ Required |
| **IDENTITY** | Configure agent personality | ✅ Depends on agent type |
| **CHANNELS** | Set up communication methods | ✅ Depends on agent type |
| **VALIDATE** | Run verification checks | ❌ Required |
| **READY** | Configuration complete, agent can start | - |

:::info
Some stages can be auto-skipped depending on the agent type. For example, ZeroClaw has minimal identity requirements and auto-skips the identity stage.
:::

## Quick Start

After installing an agent, run the onboarding wizard:

```bash
clm agent configure <agent-name>
```

The wizard will guide you through each required stage. Here's what a typical session looks like:

```bash
$ clm agent configure opc-work
Starting onboarding for 'opc-work' (openclaw)
Current state: PENDING

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1/4] PROVIDERS - Select Inference Provider
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Available providers:
  1. openai-prod (OpenAI GPT-4)
  2. local-ollama (Ollama - llama3:latest)
  3. anthropic-claude (Anthropic Claude 3)

Select provider [1-3]: 1
✓ Provider 'openai-prod' assigned
✓ Connectivity verified

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2/4] IDENTITY - Configure Agent Personality
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OpenClaw requires identity files to define behavior.

Create SOUL.md? (defines personality) [Y/n]: y
✓ Created ~/.openclaw/SOUL.md

Create IDENTITY.md? (defines role and context) [Y/n]: y
✓ Created ~/.openclaw/IDENTITY.md

✓ Identity configured

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[3/4] CHANNELS - Configure Communication
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Select default communication channel:
  1. cli (recommended)
  2. discord
  3. slack

Select [1-3]: 1
✓ Default channel: cli

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[4/4] VALIDATE - Verify Configuration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Running verification checks...
✓ Configuration files present
✓ Provider connectivity verified
✓ Agent self-test passed

✓ Onboarding complete! 'opc-work' is ready to start.

Run: clm agent start opc-work
```

## Onboarding Stages in Detail

### 1. Providers Stage

**Purpose:** Connect your agent to an LLM backend.

**What you need:**
- At least one configured provider (see [Providers](../agent-support/providers/index.md))
- Network connectivity to the provider

**Example:**
```bash
Available providers:
  1. openai-prod (OpenAI GPT-4)
  2. local-ollama (Ollama - llama3:latest)

Select provider [1-2]: 2
✓ Provider 'local-ollama' assigned
✓ Testing connection to http://192.168.1.50:11434...
✓ Connectivity verified
```

:::tip
Use `clm provider list` to see all configured providers before starting onboarding.
:::

### 2. Identity Stage

**Purpose:** Define the agent's personality, behavior, and role.

**Requirements vary by agent type:**

#### OpenClaw
Requires two files:
- **SOUL.md**: Personality traits, communication style, expertise areas
- **IDENTITY.md**: Role, background context, capabilities

```bash
Create SOUL.md? (defines personality) [Y/n]: y
✓ Created ~/.openclaw/SOUL.md

Edit the file to customize your agent's personality, then continue.
```

#### ZeroClaw
Auto-skipped - minimal identity:
```bash
[IDENTITY] Configure agent personality
✓ Skipped (minimal identity for zeroclaw)
```

#### IronClaw
Governance-focused identity:
```bash
Configure governance identity:
  - Compliance role: [Auditor/Reviewer/Monitor]
  - Policy framework: [SOC2/GDPR/HIPAA/Custom]
```

### 3. Channels Stage

**Purpose:** Set up how the agent communicates with users.

For channel-specific setup and credential requirements, see [Agent Support: Channels](../agent-support/channels/index.md).

:::info
For ZeroClaw, only CLI is supported and auto-configured.
:::

### 4. Validate Stage

**Purpose:** Verify the agent is properly configured and ready to run.

**Checks performed:**
1. ✓ Configuration files exist
2. ✓ Required secrets are set
3. ✓ Provider connectivity works
4. ✓ Agent self-test passes (if supported)

**Example output:**
```bash
Running verification checks...

✓ SOUL.md found
✓ IDENTITY.md found
✓ Provider 'openai-prod' reachable
✓ API key valid
✓ Running agent self-test...
  → Model: gpt-4
  → Response time: 1.2s
  → Test query successful

✓ All checks passed
```

If any check fails, you'll get specific instructions on how to fix it:

```bash
✗ Provider connectivity check failed

Error: Cannot reach provider 'local-ollama' at http://192.168.1.50:11434
Connection refused

Troubleshooting steps:
  1. Check if Ollama is running: curl http://192.168.1.50:11434/api/tags
  2. Verify network connectivity: ping 192.168.1.50
  3. Check firewall rules

Would you like to select a different provider? [Y/n]:
```

## Advanced Usage

### Configure Specific Stages

Reconfigure a specific stage without going through the full wizard:

```bash
# Change the inference provider
clm agent configure opc-work --stage providers

# Update identity files
clm agent configure opc-work --stage identity

# Reconfigure communication channels
clm agent configure opc-work --stage channels
```

### Skip Confirmations

Use `--yes` to accept defaults and skip interactive prompts:

```bash
clm agent configure opc-work --yes
```

This is useful for:
- Automated deployments
- CI/CD pipelines
- Bulk agent configuration

### Edit Config Directly

For advanced users, edit the agent's config file directly:

```bash
# Open in default editor (uses VISUAL, EDITOR, or vi)
clm agent configure opc-work --edit-config

# Use a specific editor
clm agent configure opc-work --edit-config --editor nano
```

After saving, Clawrium validates the config and offers to restart the agent if it's running.

:::warning
Direct editing bypasses the wizard's validation. Make sure you understand the config format before making changes.
:::

### Resume Onboarding

If onboarding was interrupted, just run configure again:

```bash
clm agent configure opc-work
```

It will resume from where you left off:
```bash
Starting onboarding for 'opc-work'
Current state: IDENTITY (2/4 complete)

Resuming from IDENTITY stage...
```

## Checking Status

### View All Agents

```bash
$ clm agent status

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
- **PENDING**: Installed, onboarding not started
- **ONBOARDING**: In progress (Progress shows N/4 stages complete)
- **READY**: Fully configured, can be started
- **RUNNING**: Active and running

### Detailed Progress

Use `--verbose` for stage-level details:

```bash
$ clm agent status opc-work --verbose

Agent: opc-work
Host: lab1 (192.168.1.100)
Type: openclaw v2026.4.2
Status: ONBOARDING (2/4 stages)

Onboarding Progress:
  ✓ PROVIDERS  (completed 2026-04-07 10:02:00 UTC)
    Provider: openai-prod (OpenAI GPT-4)

  ✓ IDENTITY   (completed 2026-04-07 10:05:00 UTC)
    Files: SOUL.md, IDENTITY.md

  ⧗ CHANNELS   (pending)

  ⧗ VALIDATE   (pending)

Next step: clm agent configure opc-work --stage channels
```

## Starting an Agent

Agents can only be started when status is **READY**:

```bash
$ clm agent start opc-work
✓ Starting 'opc-work' on lab1...
✓ Agent started successfully
```

If onboarding is incomplete:

```bash
$ clm agent start opc-work
✗ Cannot start 'opc-work' - onboarding incomplete

Status: ONBOARDING (2/4 stages)

Remaining stages:
  - channels
  - validate

Complete onboarding: clm agent configure opc-work
```

## Troubleshooting

### Error: "Onboarding not initialized"

**Cause:** Agent was installed before onboarding system existed.

**Fix:** Reinstall the agent:
```bash
clm agent remove opc-work
clm agent install openclaw --host lab1 --name opc-work
clm agent configure opc-work
```

### Error: "Cannot transition from X to Y"

**Cause:** Trying to configure stages out of order.

**Fix:** Use the full wizard:
```bash
clm agent configure opc-work
# (without --stage flag)
```

### Provider Verification Fails

**Common causes:**
1. **Provider unreachable:** Check network connectivity
2. **Invalid API key:** Update secrets with `clm secret set`
3. **Provider down:** Try a different provider

**Fix:**
```bash
# Check provider status
clm provider status openai-prod

# Update API key if needed
clm secret set opc-work OPENAI_API_KEY

# Retry provider configuration
clm agent configure opc-work --stage providers
```

### Stage Auto-Skipped When You Want to Configure It

**Cause:** Agent type doesn't require that stage by default.

**Fix:** Explicitly configure the stage:
```bash
clm agent configure opc-work --stage identity
```

The wizard will respect your intent even if the stage is normally skippable.

## Agent Type Differences

| Agent Type | Identity | Channels | Typical Time |
|------------|----------|----------|--------------|
| OpenClaw | Required (SOUL.md, IDENTITY.md) | Required (select from multiple) | 3-5 min |
| ZeroClaw | Auto-skip (minimal) | Auto-configure (CLI only) | 1-2 min |
| IronClaw | Required (governance config) | Required (audit logging) | 5-10 min |
| NemoClaw | Required (persona config) | Required (select from multiple) | 3-5 min |

## Next Steps

- [Fleet Management](./fleet-management.md) - Operating multiple agents
- [CLI Reference: agent](../reference/cli/agent.md) - Full command documentation
- [Troubleshooting](../troubleshooting.md) - Common issues and solutions

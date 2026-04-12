<p align="center">
  <img src="docs/assets/clawrium-logo.png" alt="Clawrium Logo" width="400">
</p>

<p align="center">
  <h1 align="center">Clawrium</h1>
  <p align="center">
    <strong>Fleet management for AI agents on your local network.</strong>
  </p>
  <p align="center">
    Deploy, upgrade, and monitor dozens of AI assistant instances across hosts - from one terminal.
  </p>
  <p align="center">
    <a href="https://ric03uec.github.io/clawrium/">Documentation</a> · <a href="https://github.com/ric03uec/clawrium/issues">Issues</a> · <a href="https://github.com/users/ric03uec/projects/1">Roadmap</a>
  </p>
</p>

---

## How it works

<p align="center">
  <img src="docs/assets/clawrium-architecture.png" alt="Clawrium architecture - control node managing agents across hosts" width="100%" />
</p>

Clawrium uses Ansible under the hood for SSH-based orchestration. You run `clm` from your control machine, which talks to target hosts over SSH. No agents, no containers, no Kubernetes complexity - just processes running on hosts with a unified management layer.

## Commands

```bash
# Initialize Clawrium
clm init

# Host management
clm host init worker-1              # Generate SSH keys and configure remote host
clm host add worker-1               # Add initialized host to fleet
clm host list                       # List all hosts
clm host status worker-1            # Check host connectivity
clm host remove worker-1            # Remove host from fleet

# Agent management
clm agent registry list             # Browse available agents
clm agent install -t openclaw -H worker-1 -n assistant-1
clm agent ps                        # View all agents across fleet
clm agent onboard assistant-1       # Configure agent interactively
clm ps                              # Quick fleet overview

# Provider management
clm provider add anthropic          # Add API keys for inference providers
clm provider list                   # View configured providers

# Chat with agents
clm chat assistant-1                # Start interactive session
```

## Why Clawrium

You're running multiple AI agents - coding assistants, internal tools, experiment harnesses - across machines on your network. Without Clawrium, you SSH into each box, manage configs individually, lose track of token spend, and have no unified view of what's running where.

Clawrium gives you `kubectl`-style fleet control for AI agents:

- **One CLI, all hosts.** Add machines to your fleet and deploy any claw type to any host.
- **Lifecycle management.** Upgrades, rollbacks, secrets rotation, backups - handled.
- **Token tracking & guardrails.** See spend across your fleet. Set limits before someone's experiment burns through your API budget.
- **Model experimentation.** Swap models across agents to compare performance without touching individual configs.

## Quickstart

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
# Install
uvx clawrium

# Initialize config
clm init

# Set up a host
clm host init 192.168.1.100 --user your-username
clm host add worker-1

# Add inference provider (e.g., Anthropic for Claude models)
clm provider add anthropic

# Install an agent
clm agent install --type openclaw --host worker-1 --name my-assistant

# Configure the agent
clm agent onboard my-assistant

# Check fleet status
clm ps

# Chat with your agent
clm chat my-assistant
```

**→ Full setup guide, claw types, and configuration reference: [ric03uec.github.io/clawrium](https://ric03uec.github.io/clawrium/)**

## Who this is for

Clawrium is for **engineers running AI agents in non-trivial setups** - home labs, dev teams, research groups. If you have more than one agent running on more than one machine, this tool exists for you.

It is _not_ a hosted platform. There's no dashboard, no SaaS, no account signup. It's a Python CLI that talks to your machines via Ansible. You own everything.

## Key Concepts

| Concept | What it is |
|---------|-----------|
| **Host** | A machine in your network running one or more claws |
| **Claw** | An AI assistant instance (OpenClaw, NemoClaw, ZeroClaw, or custom) |
| **Registry** | Platform-defined claw types with versions, deps, and templates |

## FAQ

### Why not Kubernetes?

**Two reasons:**

1. **Most AI agents don't support it.** OpenClaw, NemoClaw, ZeroClaw - these run as local processes, not containerized services. They expect a home directory, local config files, and direct access to the host. Wrapping them in containers adds friction with no payoff.

2. **K8s is overkill for local fleets.** You're managing 3-10 machines on a LAN, not orchestrating microservices across cloud regions. Kubernetes brings etcd, control planes, networking overlays, RBAC, and a learning curve that dwarfs the problem. You don't need a container scheduler - you need to SSH into a box and run a process.

**Clawrium uses Ansible under the hood instead.** Ansible gives you idempotent host management, secrets handling, and multi-machine orchestration without requiring anything on the target machines beyond SSH. Clawrium sits on top of Ansible and adds the agent-specific layer: lifecycle management, token tracking, model swapping, and fleet-wide visibility.

## Tech Stack

Python · [Typer](https://typer.tiangolo.com/) · [ansible-runner](https://ansible-runner.readthedocs.io/) · [uv](https://docs.astral.sh/uv/)

## Contributing

```bash
git clone https://github.com/ric03uec/clawrium && cd clawrium
make test       # Run tests
make lint       # Check style
make format     # Auto-format
```

Issues are the source of truth. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

## License

Apache 2.0

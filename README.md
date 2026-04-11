<p align="center">
  <img src="docs/assets/clawrium-logo.png" alt="Clawrium Logo" width="400">
</p>

<p align="center">
  <h1 align="center">Clawrium</h1>
  <p align="center">
    <strong>Fleet management for AI agents on your local network.</strong>
  </p>
  <p align="center">
    Deploy, upgrade, and monitor dozens of AI assistant instances across hosts — from one terminal.
  </p>
  <p align="center">
    <a href="https://ric03uec.github.io/clawrium/">Documentation</a> · <a href="https://github.com/ric03uec/clawrium/issues">Issues</a> · <a href="https://github.com/users/ric03uec/projects/1">Roadmap</a>
  </p>
</p>

---

```
$ uvx clawrium init
$ clm host add worker-1 --ip 192.168.1.50
$ clm claw deploy openclaw --host worker-1
$ clm fleet status

HOST        CLAW        MODEL           STATUS    TOKENS (24h)
worker-1    openclaw    claude-sonnet   running   12,847
worker-2    nemoclaw    gpt-4o          running   8,231
worker-3    zeroclaw    claude-opus     idle      0
```

## How it works

<p align="center">
  <img src="docs/assets/clawrium-architecture.png" alt="Clawrium architecture — control node managing agents across hosts" width="100%" />
</p>

## Why Clawrium

You're running multiple AI agents — coding assistants, internal tools, experiment harnesses — across machines on your network. Without Clawrium, you SSH into each box, manage configs individually, lose track of token spend, and have no unified view of what's running where.

Clawrium gives you `kubectl`-style fleet control for AI agents:

- **One CLI, all hosts.** Add machines to your fleet and deploy any claw type to any host.
- **Lifecycle management.** Upgrades, rollbacks, secrets rotation, backups — handled.
- **Token tracking & guardrails.** See spend across your fleet. Set limits before someone's experiment burns through your API budget.
- **Model experimentation.** Swap models across agents to compare performance without touching individual configs.

## Quickstart

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
# Install
uvx clawrium

# Initialize config
clm init

# Add a host
clm host add my-server --ip 192.168.1.100

# Deploy an agent
clm claw deploy openclaw --host my-server

# Check fleet status
clm fleet status
```

**→ Full setup guide, claw types, and configuration reference: [ric03uec.github.io/clawrium](https://ric03uec.github.io/clawrium/)**

## Who this is for

Clawrium is for **engineers running AI agents in non-trivial setups** — home labs, dev teams, research groups. If you have more than one agent running on more than one machine, this tool exists for you.

It is _not_ a hosted platform. There's no dashboard, no SaaS, no account signup. It's a Python CLI that talks to your machines via Ansible. You own everything.

## Key Concepts

| Concept | What it is |
|---------|-----------|
| **Host** | A machine in your network running one or more claws |
| **Claw** | An AI assistant instance (OpenClaw, NemoClaw, ZeroClaw, or custom) |
| **Registry** | Platform-defined claw types with versions, deps, and templates |

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

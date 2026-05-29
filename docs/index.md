# Clawrium - An aquarium for agents

Clawrium is a CLI tool for managing AI agent fleets on local networks.

## Getting Started

1. [Installation](installation.md) - Install Clawrium on your management machine
2. [Host Preparation](host-preparation.md) - Prepare hosts for management (create xclm user, setup SSH)
3. Host Management - Add, list, and manage hosts with `clawctl host`
4. Agent Deployment - Deploy AI assistants to your fleet with `clawctl agent`
5. [Agent Onboarding](agent-onboarding.md) - Configure newly installed agents through guided workflow

## Quick Reference

```bash
# Initialize config
clawctl service init

# Register a host (first run generates keypair and prints the manual
# xclm setup commands you need to run on the host; re-run after pasting
# them to actually register it). See docs/host-preparation.md.
clawctl host create <hostname> --user xclm --alias <host-alias>

# List all hosts
clawctl host get

# Check host status (exits with code 1 if unreachable - useful for scripting)
clawctl host describe <host-alias>

# Add inference provider
clawctl provider registry create anthropic --type anthropic

# Install, configure, and start an agent
clawctl agent create --type <agent-type> --host <host-alias> --name <agent-name>
clawctl agent configure <agent-name>
clawctl agent start <agent-name>

# Remove a host and its keypair
clawctl host delete <hostname>
clawctl host delete <hostname> --force
```

## User Data

Current files stored in `~/.config/clawrium/` (or `$XDG_CONFIG_HOME/clawrium/` if set):

| Path | Description |
|------|-------------|
| `hosts.json` | Registered hosts and their metadata. Written with `0600` permissions. Do not edit manually. |
| `keys/<hostname>/xclm_ed25519` | Private key for SSH to `<hostname>`. `0600` permissions. |
| `keys/<hostname>/xclm_ed25519.pub` | Public key added to host's `authorized_keys`. |

**Note:** Clawrium also modifies `~/.ssh/known_hosts` when accepting host keys on first connection (TOFU - Trust On First Use).

When a host is removed with `clawctl host delete`, both the host entry in `hosts.json` and the per-host keypair in `keys/<hostname>/` are deleted.

## Key Concepts

| Concept | What it is |
|---------|-----------|
| **Host** | A machine in your network running one or more agents |
| **Agent** | An installed AI assistant instance managed by Clawrium |
| **Agent Type** | The implementation/runtime class of an agent |
| **Agent Name** | The unique identifier for an installed agent instance |
| **Registry** | Platform-defined agent types with versions, dependencies, and templates |

## Design Decisions

- [aichat investigation](research/aichat.md) — why `clawctl agent chat` will be a pure-Python REPL on `httpx` instead of shelling out to [aichat](https://github.com/sigoden/aichat) (in progress — see [#322](https://github.com/ric03uec/clawrium/issues/322)).

## FAQ

### 1. Why not Kubernetes?

**Two reasons:**

1. **Most AI agent runtimes don't support it.** These run as local processes, not containerized services. They expect a home directory, local config files, and direct access to the host. Wrapping them in containers adds friction with no payoff.

2. **K8s is overkill for local fleets.** You're managing 3-10 machines on a LAN, not orchestrating microservices across cloud regions. Kubernetes brings etcd, control planes, networking overlays, RBAC, and a learning curve that dwarfs the problem. You don't need a container scheduler - you need to SSH into a box and run a process.

**Clawrium uses Ansible under the hood instead.** Ansible gives you idempotent host management, secrets handling, and multi-machine orchestration without requiring anything on the target machines beyond SSH. Clawrium sits on top of Ansible and adds the agent-specific layer: lifecycle management, token tracking, model swapping, and fleet-wide visibility.

### 2. Why doesn't it support x-agent and y-feature?

I'm building Clawrium in my spare time, so I prioritize my own use cases first.

If you want support for a specific agent type or feature, please open an issue and send a PR. See [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines.

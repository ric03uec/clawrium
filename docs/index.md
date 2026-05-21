# Clawrium - An aquarium for agents

Clawrium is a CLI tool for managing AI agent fleets on local networks.

## Getting Started

1. [Installation](installation.md) - Install Clawrium on your management machine
2. [Host Preparation](host-preparation.md) - Prepare hosts for management (create xclm user, setup SSH)
3. Host Management - Add, list, and manage hosts with `clm host`
4. Agent Deployment - Deploy AI assistants to your fleet with `clm agent`
5. [Agent Onboarding](agent-onboarding.md) - Configure newly installed agents through guided workflow

## Quick Reference

```bash
# Initialize config
clm init

# Initialize a host (generates keypair, attempts auto-setup of xclm user)
clm host init <hostname> --user <your-ssh-user>

# Add an initialized host to the fleet
clm host add <hostname> --alias <host-alias>

# List all hosts
clm host list

# Check host status (exits with code 1 if unreachable - useful for scripting)
clm host ps <host-alias>

# Add inference provider
clm provider add anthropic --type anthropic

# Install, configure, and start an agent
clm agent install --type <agent-type> --host <host-alias> --name <agent-name>
clm agent configure <agent-name>
clm agent start <agent-name>

# Remove a host and its keypair
clm host remove <hostname>
clm host remove <hostname> --force
```

## User Data

Current files stored in `~/.config/clawrium/` (or `$XDG_CONFIG_HOME/clawrium/` if set):

| Path | Description |
|------|-------------|
| `hosts.json` | Registered hosts and their metadata. Written with `0600` permissions. Do not edit manually. |
| `keys/<hostname>/xclm_ed25519` | Private key for SSH to `<hostname>`. `0600` permissions. |
| `keys/<hostname>/xclm_ed25519.pub` | Public key added to host's `authorized_keys`. |

**Note:** Clawrium also modifies `~/.ssh/known_hosts` when accepting host keys on first connection (TOFU - Trust On First Use).

When a host is removed with `clm host remove`, both the host entry in `hosts.json` and the per-host keypair in `keys/<hostname>/` are deleted.

## Key Concepts

| Concept | What it is |
|---------|-----------|
| **Host** | A machine in your network running one or more agents |
| **Agent** | An installed AI assistant instance managed by Clawrium |
| **Agent Type** | The implementation/runtime class of an agent |
| **Agent Name** | The unique identifier for an installed agent instance |
| **Registry** | Platform-defined agent types with versions, dependencies, and templates |

## Design Decisions

- [aichat investigation](research/aichat.md) — why `clm chat` will be a pure-Python REPL on `httpx` instead of shelling out to [aichat](https://github.com/sigoden/aichat) (in progress — see [#322](https://github.com/ric03uec/clawrium/issues/322)).

## FAQ

### 1. Why not Kubernetes?

**Two reasons:**

1. **Most AI agent runtimes don't support it.** These run as local processes, not containerized services. They expect a home directory, local config files, and direct access to the host. Wrapping them in containers adds friction with no payoff.

2. **K8s is overkill for local fleets.** You're managing 3-10 machines on a LAN, not orchestrating microservices across cloud regions. Kubernetes brings etcd, control planes, networking overlays, RBAC, and a learning curve that dwarfs the problem. You don't need a container scheduler - you need to SSH into a box and run a process.

**Clawrium uses Ansible under the hood instead.** Ansible gives you idempotent host management, secrets handling, and multi-machine orchestration without requiring anything on the target machines beyond SSH. Clawrium sits on top of Ansible and adds the agent-specific layer: lifecycle management, token tracking, model swapping, and fleet-wide visibility.

### 2. Why doesn't it support x-agent and y-feature?

I'm building Clawrium in my spare time, so I prioritize my own use cases first.

If you want support for a specific agent type or feature, please open an issue and send a PR. See [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines.

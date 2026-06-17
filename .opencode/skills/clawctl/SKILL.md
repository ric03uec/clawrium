---
name: clawctl
description: Know the clawctl CLI and manage your Clawrium fleet (hosts, agents, providers, channels, integrations, skills, secrets)
argument-hint: "<task or question about fleet management>"
---

# clawctl — Fleet Management CLI

Use this skill whenever the user asks to manage their Clawrium fleet: creating or configuring agents, working with hosts, attaching providers or channels, managing skills, secrets, or memory. All fleet operations use `clawctl` — never `clm`.

## Architecture

```
Your Machine (clawctl CLI)
    │
    ├── Host A ──> zeroclaw instance
    ├── Host B ──> openclaw instance
    └── Host C ──> nemoclaw instance, zeroclaw instance
```

- **Config root**: `~/.config/clawrium/`
- **Agent state**: `~/.config/clawrium/agents/<agent>/`
- **SSH user on every host**: `xclm`
- **Agent types**: `hermes`, `openclaw`, `zeroclaw`, `nemoclaw`

---

## Top-Level Commands

```
clawctl version           # Show version and exit
clawctl completion        # Emit shell-completion script
clawctl tui               # Launch interactive TUI dashboard
clawctl gui               # Launch local web GUI dashboard
clawctl apply <manifest>  # Apply fleet manifest (declarative reconciliation)
clawctl diff <manifest>   # Preview changes without applying
clawctl delete <manifest> # Delete resources declared in a manifest
clawctl service …         # System-level lifecycle ops
clawctl host …            # Manage fleet machines
clawctl agent …           # Manage AI assistant instances
clawctl provider …        # Inference backend providers
clawctl channel …         # Chat surfaces (Discord, Slack)
clawctl integration …     # External service integrations
clawctl skill …           # Skills catalog and user overlay
clawctl mcp …             # MCP servers (placeholder)
```

---

## `clawctl service`

System-level lifecycle for the control plane itself.

```bash
clawctl service init      # Init config dir, check deps (ansible, ssh, python)
clawctl service start     # Start Clawrium daemon (placeholder)
clawctl service stop      # Stop Clawrium daemon (placeholder)
clawctl service snapshot  # Snapshot fleet state (placeholder)
```

**First-time setup**:
```bash
clawctl service init
```

---

## `clawctl host`

Manage fleet machines. Every host must have an `xclm` SSH user — see `docs/host-preparation.md`.

```bash
clawctl host create <hostname-or-ip> --user xclm --alias <name>
clawctl host get                         # List all hosts
clawctl host describe <name>             # Show full host details
clawctl host delete <name>               # Remove host record
clawctl host delete <name> --force       # Also wipe remote xclm state
clawctl host edit <name>                 # Edit host record in $EDITOR
clawctl host reset <name>                # Wipe remote xclm state on host

# Aliases (multi-value)
clawctl host alias <name> --add <alias>
clawctl host alias <name> --remove <alias>
clawctl host alias <name> --list

# Labels (KEY=VALUE / KEY-)
clawctl host label <name> env=prod tier=gpu-a100
clawctl host label <name> env-          # Remove label

# Addresses (multi-value)
clawctl host address add <name> --address <ip-or-dns>
clawctl host address delete <name> --address <ip-or-dns>
clawctl host address get <name>
clawctl host address set-primary <name> --address <ip-or-dns>

# Registry (read-only catalog of host profiles)
clawctl host registry get
clawctl host registry describe <profile>
```

**Quickstart**:
```bash
clawctl host create 192.168.1.100 --user xclm --alias mybox
```

---

## `clawctl agent`

Manage AI assistant instances across the fleet.

### Lifecycle

```bash
clawctl agent create <name> --type <type> --host <host>
clawctl agent get                    # List all agents (status table)
clawctl agent describe <name>        # Full details for one agent
clawctl agent delete <name>          # Remove agent record
clawctl agent edit <name>            # Edit agent record in $EDITOR

clawctl agent configure <name>       # Configure agent (all stages)
clawctl agent configure <name> --stage <stage>  # Single stage
clawctl agent start <name>           # Start agent service
clawctl agent stop <name>            # Stop agent service
clawctl agent restart <name>         # Restart agent service
clawctl agent sync <name>            # Flush control-plane state to host
clawctl agent upgrade <name>         # Upgrade to manifest's max version
clawctl agent doctor <name>          # Diagnose render bundle
clawctl agent logs <name>            # Stream agent logs
```

> `configure`, `sync`, and `restart` all rotate the gateway bearer token
> and overwrite `hosts.json.gateway.auth` atomically (issue #437).

### Interaction

```bash
clawctl agent chat <name>            # Chat with an agent
clawctl agent open <name>            # Open agent web UI in browser
clawctl agent port-forward <name>    # Forward local port to agent
clawctl agent exec <name> -- <args>  # Run command against agent's native CLI
```

### Provider attachments

```bash
clawctl agent provider attach <agent> --provider <provider-name>
clawctl agent provider detach <agent> --provider <provider-name>
clawctl agent provider get <agent>
```

### Channel attachments

```bash
clawctl agent channel attach <agent> --channel <channel-name>
clawctl agent channel detach <agent> --channel <channel-name>
clawctl agent channel get <agent>
```

### Integration attachments

```bash
clawctl agent integration attach <agent> --integration <integration-name>
clawctl agent integration detach <agent> --integration <integration-name>
clawctl agent integration get <agent>
```

### Skills (local, agent-native)

```bash
clawctl agent skill list <agent>
clawctl agent skill add <agent> --from-template <registry>/<name>
clawctl agent skill edit <agent> <skill-name>
clawctl agent skill remove <agent> <skill-name>
# After any skill change, push to host:
clawctl agent sync <agent>
```

Skill references use `<registry>/<name>` (e.g. `clawrium/tdd`) when
copying from the catalog. Once local, the bare name is used (`tdd`).

### Secrets

```bash
clawctl agent secret create <agent> <key> --value <val>   # or prompts
clawctl agent secret create <agent> <key> --stdin          # read from stdin
clawctl agent secret get <agent>                           # List keys
clawctl agent secret describe <agent> <key>                # Metadata only
clawctl agent secret delete <agent> <key>
clawctl agent secret import <agent> --file <dotenv-file>   # Bulk import
```

### Memory

```bash
clawctl agent memory get <agent>               # List memory files
clawctl agent memory get <agent> <file>        # Print one file's content
clawctl agent memory describe <agent> <file>   # Metadata
clawctl agent memory edit <agent> <file> --content <text>
clawctl agent memory delete <agent> <file>
```

### Registry (read-only)

```bash
clawctl agent registry get
clawctl agent registry describe <type>
```

---

## `clawctl provider`

Register inference backends. Providers use Pattern A (attachable).

```bash
clawctl provider registry create <name> --type <type> [flags]
clawctl provider registry get                         # List all providers
clawctl provider registry get --types                 # List supported types
clawctl provider registry describe <name>
clawctl provider registry delete <name>
clawctl provider registry edit <name>
clawctl provider registry refresh <name>              # Refresh Ollama models
```

**Common provider types**: `anthropic`, `openai`, `ollama`, `litellm`

**LiteLLM/custom OpenAI-compatible proxy**:
```bash
clawctl provider registry create myproxy \
  --type litellm \
  --litellm-url http://localhost:8000/v1 \
  --model gpt-4o \
  --api-key <bearer>
```

---

## `clawctl channel`

Register chat surfaces (Discord, Slack). Uses Pattern A.

```bash
clawctl channel registry create <name> --type <type> [flags]
clawctl channel registry get
clawctl channel registry describe <name>
clawctl channel registry delete <name>
clawctl channel registry edit <name>
```

---

## `clawctl integration`

Register external service integrations. Uses Pattern A.

```bash
clawctl integration registry create <name> --type <type> --credential KEY=VALUE
clawctl integration registry get
clawctl integration registry get --types           # List supported types
clawctl integration registry describe <name>
clawctl integration registry delete <name>
clawctl integration registry edit <name>
```

Credentials are never printed. `clawctl agent describe` / `clawctl integration registry describe` shows `Credentials: set` only.

---

## `clawctl skill`

Skills catalog and user overlay management (operator-side; distinct from `clawctl agent skill`).

```bash
clawctl skill add ./my-skill-dir --registry <registry>
clawctl skill registry get
clawctl skill registry get --registry <registry>   # Filter by registry
clawctl skill registry describe <registry>/<name>
```

User overlay lives at `~/.config/clawrium/skills/<registry>/<name>/`.
Overlay entries win over bundled catalog entries for the same slug.

---

## `clawctl mcp`

MCP server management (placeholder — commands exist but are not yet functional).

```bash
clawctl mcp registry get
clawctl mcp registry describe <name>
```

---

## Common Workflows

### First host + first agent

```bash
clawctl service init
clawctl host create 192.168.1.100 --user xclm --alias mybox
clawctl agent create myassistant --type openclaw --host mybox
clawctl agent configure myassistant
clawctl agent start myassistant
clawctl agent chat myassistant
```

### Add a provider and attach it

```bash
clawctl provider registry create myanthropic --type anthropic --api-key $KEY
clawctl agent provider attach myassistant --provider myanthropic
clawctl agent sync myassistant
```

### Install a skill

```bash
clawctl skill registry get                                    # Browse
clawctl skill registry describe clawrium/tdd                  # Inspect
clawctl agent skill add myassistant --from-template clawrium/tdd
clawctl agent sync myassistant
```

### Check fleet health

```bash
clawctl agent get
clawctl agent doctor myassistant
clawctl agent logs myassistant
```

### Manage secrets

```bash
clawctl agent secret create myassistant ANTHROPIC_API_KEY --stdin <<< "$KEY"
clawctl agent secret get myassistant
```

### Open the web UI

```bash
clawctl agent open myassistant    # opens in browser via SSH tunnel
clawctl gui                        # local web dashboard for the whole fleet
```

---

## Key Rules

1. **Always use `clawctl`** — the legacy `clm` CLI was removed in v26.6.3.
2. **After any local state change, run `clawctl agent sync <agent>`** to push to the host.
3. **`configure`, `sync`, and `restart` rotate the bearer token** — remote chat sessions will get a 401 and must reconnect.
4. **Never push directly to `main`** — all changes go via feature branch and PR.
5. **`clawctl agent skill add` writes control-plane only**; `sync` pushes to the host.
6. **Secret values are never printed** — `describe` shows `set`/`unset` only.
7. **Host `~` in on-host paths is the agent unix user's home**, not the operator's.

---

## Maintenance Note

This skill must be updated whenever the `clawctl` CLI surface changes — new commands, renamed flags, or deprecated sub-commands. Run `clawctl --help` and each group's `--help` to verify the current surface before updating.

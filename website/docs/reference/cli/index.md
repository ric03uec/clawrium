---
description: Complete CLI reference for the clawctl command. Root commands and command groups for managing your AI agent fleet.
keywords: [CLI, reference, commands, clawctl, usage, options]
---

# CLI Reference

Clawrium provides the `clawctl` command-line interface for managing your AI agent fleet.

## Installation

```bash
uv tool install clawrium
```

Or run without installing:

```bash
uvx --from clawrium clawctl --help
```

## Command Structure

```
clawctl <command> [options]
clawctl <group> <command> [options]
```

## Root Commands

| Command | Description |
|---------|-------------|
| [`clawctl service init`](#clawctl-service-init) | Initialize Clawrium and check dependencies |
| [`clawctl agent describe`](#clawctl-agent-describe) | Show fleet status across all hosts |
| [`clawctl agent create`](#clawctl-agent-create) | Install an agent on a host |

## Command Groups

|| Group | Description |
||-------|-------------|
|| [`clawctl host`](host.md) | Manage hosts in your fleet |
|| [`clawctl agent registry`](registry.md) | Browse available agent types |
|| [`clawctl agent secret`](secret.md) | Manage secrets for agent instances |
|| [`clawctl agent context_length`](agent-context_length.mdx) | Set and view the maximum context length for an agent's LLM inference |

---

## clawctl service init

Initialize Clawrium configuration directory and check dependencies.

```bash
clawctl service init
```

Creates the configuration directory at `~/.config/clawrium/` (or `$XDG_CONFIG_HOME/clawrium/` if set) and verifies that all required dependencies are available.

### Example

```bash
$ clawctl service init
Clawrium initialized!
Config directory: /home/user/.config/clawrium

┏━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Dependency    ┃ Status  ┃ Version/Path   ┃ Action Required          ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ansible       │ OK      │ 2.15.0         │ -                        │
│ ssh           │ OK      │ /usr/bin/ssh   │ -                        │
│ python        │ OK      │ 3.11.0         │ -                        │
└───────────────┴─────────┴────────────────┴──────────────────────────┘
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All dependencies found |
| 1 | One or more dependencies missing |

---

## clawctl agent describe

Show fleet status across all hosts.

```bash
clawctl agent describe [--host HOST]
```

Displays agent instances grouped by agent type with live health checks. Shows name, version, host, and status for each installed agent.

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--host` | `-H` | Filter to specific host (hostname or alias) |

### Example

```bash
$ clawctl agent describe
                         zeroclaw
┏━━━━━━━━━━┳━━━━━━━━━┳━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Host     ┃ Version ┃ User ┃ Status   ┃ Installed  ┃
┡━━━━━━━━━━╇━━━━━━━━━╇━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━┩
│ pi-lab   │ 0.1.0   │ zc   │ running  │ 2026-04-01 │
│ nuc-01   │ 0.1.0   │ zc   │ degraded │ 2026-03-28 │
└──────────┴─────────┴──────┴──────────┴────────────┘
```

Filter to a specific host:

```bash
$ clawctl agent describe --host pi-lab
```

### Status Values

| Status | Meaning |
|--------|---------|
| `running` | Agent is healthy and operational |
| `degraded` | Agent is running but missing required secrets |
| `stopped` | Agent service is not running |
| `not installed` | Agent record exists but service not found |
| `install failed` | Installation did not complete successfully |
| `installing...` | Installation in progress |

---

## clawctl agent create

Install an agent on a host.

```bash
clawctl agent create [--type AGENT_TYPE] [--host HOST] [--yes]
```

Without flags, prompts for agent type and host selection interactively. With `--type` and `--host` flags, runs directly for scripting.

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--type` | `-t` | Agent type to install (e.g., `zeroclaw`) |
| `--host` | `-H` | Target host (hostname or alias) |
| `--yes` | `-y` | Skip confirmation prompt |

### Interactive Example

```bash
$ clawctl agent create

Available agent types:
  1. zeroclaw (v0.1.0) - Zero-config Claude assistant
  2. openclaw (v0.2.0) - OpenAI-powered assistant

Select agent type: 1

Available hosts:
  1. pi-lab (aarch64, 4.0GB)
  2. nuc-01 (x86_64, 16.0GB)

Select host: 1

╭─────────────────────────────────────────╮
│          Installation Summary           │
├─────────────────────────────────────────┤
│ Agent Type: zeroclaw                    │
│ Version: 0.1.0                          │
│ Host: pi-lab                            │
│ Architecture: aarch64                   │
│ Memory: 4.0GB                           │
╰─────────────────────────────────────────╯

Proceed with installation? [y/N]: y

Success! zeroclaw v0.1.0 installed on pi-lab
```

### Non-Interactive Example

```bash
$ clawctl agent create --type zeroclaw --host pi-lab --yes
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Installation successful |
| 1 | Installation failed or cancelled |

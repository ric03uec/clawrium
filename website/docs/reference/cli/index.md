---
description: Complete CLI reference for the clm command. Root commands and command groups for managing your AI claw fleet.
keywords: [CLI, reference, commands, clm, usage, options]
---

# CLI Reference

Clawrium provides the `clm` command-line interface for managing your AI claw fleet.

## Installation

```bash
uv tool install clawrium
```

Or run without installing:

```bash
uvx --from clawrium clm --help
```

## Command Structure

```
clm <command> [options]
clm <group> <command> [options]
```

## Root Commands

| Command | Description |
|---------|-------------|
| [`clm init`](#clm-init) | Initialize Clawrium and check dependencies |
| [`clm status`](#clm-status) | Show fleet status across all hosts |
| [`clm install`](#clm-install) | Install a claw on a host |

## Command Groups

| Group | Description |
|-------|-------------|
| [`clm host`](host.md) | Manage hosts in your fleet |
| [`clm registry`](registry.md) | Browse available claw types |
| [`clm secret`](secret.md) | Manage secrets for claw instances |

---

## clm init

Initialize Clawrium configuration directory and check dependencies.

```bash
clm init
```

Creates the configuration directory at `~/.config/clawrium/` (or `$XDG_CONFIG_HOME/clawrium/` if set) and verifies that all required dependencies are available.

### Example

```bash
$ clm init
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

## clm status

Show fleet status across all hosts.

```bash
clm status [--host HOST]
```

Displays claw instances grouped by claw type with live health checks. Shows name, version, host, and status for each installed claw.

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--host` | `-H` | Filter to specific host (hostname or alias) |

### Example

```bash
$ clm status
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
$ clm status --host pi-lab
```

### Status Values

| Status | Meaning |
|--------|---------|
| `running` | Claw is healthy and operational |
| `degraded` | Claw is running but missing required secrets |
| `stopped` | Claw service is not running |
| `not installed` | Claw record exists but service not found |
| `install failed` | Installation did not complete successfully |
| `installing...` | Installation in progress |

---

## clm install

Install a claw on a host.

```bash
clm install [--claw CLAW] [--host HOST] [--yes]
```

Without flags, prompts for claw and host selection interactively. With `--claw` and `--host` flags, runs directly for scripting.

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--claw` | `-c` | Claw type to install (e.g., `zeroclaw`) |
| `--host` | `-H` | Target host (hostname or alias) |
| `--yes` | `-y` | Skip confirmation prompt |

### Interactive Example

```bash
$ clm install

Available claws:
  1. zeroclaw (v0.1.0) - Zero-config Claude assistant
  2. openclaw (v0.2.0) - OpenAI-powered assistant

Select claw: 1

Available hosts:
  1. pi-lab (aarch64, 4.0GB)
  2. nuc-01 (x86_64, 16.0GB)

Select host: 1

╭─────────────────────────────────────────╮
│          Installation Summary           │
├─────────────────────────────────────────┤
│ Claw: zeroclaw                          │
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
$ clm install --claw zeroclaw --host pi-lab --yes
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Installation successful |
| 1 | Installation failed or cancelled |

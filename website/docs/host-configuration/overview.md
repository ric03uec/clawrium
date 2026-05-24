---
sidebar_label: Overview
---

# Host Configuration

Configure how Clawrium connects to hosts in your fleet, including multi-address support for different network contexts.

## Architecture Overview

```
                    ┌─────────────────────┐
                    │   Control Machine   │
                    │      (clawctl CLI)      │
                    └──────────┬──────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
           │ LAN               │ LAN               │ Tailscale
           ▼                   │                   ▼
     ┌─────────┐               │            ┌─────────────┐
     │ Host A  │               │            │    Cloud    │
     │         │               │            │ (Tailscale) │
     │ LAN IP: │               │            └──────┬──────┘
     │ 10.0.0.5│               │                   │
     │         │               │                   │
     │ [1 addr]│               │                   │
     └─────────┘               │                   │
                               ▼                   ▼
                    ┌─────────────────────────────────────┐
                    │              Host B                 │
                    │                                     │
                    │  LAN IP: 192.168.1.50 ◄─── primary │
                    │  Tailscale: wolf.ts.net             │
                    │                                     │
                    │ [2 addresses]                       │
                    └─────────────────────────────────────┘
```

Your control machine (where you run `clawctl`) connects to hosts via SSH. Each host can have multiple addresses for different network contexts.

## Primary Address

Every host has exactly one **primary address**. This is the address Clawrium uses for all operations:

- Agent installation and configuration
- Status checks
- Command execution
- Secret delivery

When you add a host with `clawctl host create`, the hostname becomes the primary address.

## Multiple Addresses

Hosts often have multiple network paths depending on where you're connecting from:

| Context | Address Type | Example |
|---------|--------------|---------|
| Home LAN | Local IP | `192.168.1.50` |
| Corporate VPN | VPN IP | `10.0.100.50` |
| Tailscale | Magic DNS | `wolf.tail12345.ts.net` |
| WireGuard | Tunnel IP | `10.13.13.50` |
| Public | Domain/IP | `myserver.example.com` |

Add additional addresses with `clawctl host address add`:

```bash
# Host already added with LAN address
clawctl host create 192.168.1.50 --alias wolf

# Add Tailscale address for remote access
clawctl host address add wolf wolf.tail12345.ts.net --label tailscale

# Add VPN address for corporate network
clawctl host address add wolf 10.0.100.50 --label vpn
```

## Switching Primary Address

When your network context changes, switch the primary address:

```bash
# Working from home - use Tailscale
clawctl host address set-primary wolf wolf.tail12345.ts.net

# Back in the office - use LAN
clawctl host address set-primary wolf 192.168.1.50
```

All subsequent commands use the new primary address automatically.

## Viewing Addresses

List all addresses for a host:

```bash
$ clawctl host address list wolf
           Addresses for wolf
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Address                 ┃ Primary ┃ Label     ┃ Added            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ 192.168.1.50            │ *       │ lan       │ 2026-04-01 10:30 │
│ wolf.tail12345.ts.net   │         │ tailscale │ 2026-04-05 14:15 │
│ 10.0.100.50             │         │ vpn       │ 2026-04-06 09:00 │
└─────────────────────────┴─────────┴───────────┴──────────────────┘
```

The `clawctl host get` command shows a `[+N]` indicator for hosts with additional addresses:

```bash
$ clawctl host get
                    Registered Hosts
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━┓
┃ Alias   ┃ Host                  ┃ Architecture ┃ Cores ┃ Memory (GB) ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━┩
│ wolf    │ 192.168.1.50 [+2]     │ x86_64       │     8 │        16.0 │
└─────────┴───────────────────────┴──────────────┴───────┴─────────────┘
```

## Next Steps

- [Host Setup Guide](/docs/guides/host-setup) - Initial host configuration
- [OS Support](/docs/host-configuration/os-support) - Supported operating systems
- [CLI Reference: host address](/docs/reference/cli/host#address-subcommands) - Command details

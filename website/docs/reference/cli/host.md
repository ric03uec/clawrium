# Host Commands

Manage hosts in your Clawrium fleet.

```bash
clawctl host <command> [options]
```

## Commands

| Command | Description |
|---------|-------------|
| [`clawctl host create`](#clawctl-host-create) | Register a new host with the fleet |
| [`clawctl host get`](#clawctl-host-get) | List all registered hosts |
| [`clawctl host delete`](#clawctl-host-delete) | Remove a host from the fleet |
| [`clawctl host status`](#clawctl-host-status) | Check status of a host |
| [`clawctl host reset`](#clawctl-host-reset) | Reset a host, removing all claws and users |
| [`clawctl host address`](#address-subcommands) | Manage multiple addresses for a host |

---

## clawctl host create

Register a host with the fleet.

```bash
clawctl host create <hostname> --user xclm [--alias NAME] [--port PORT]
```

On first run for a hostname, this command generates a per-host SSH keypair
under `~/.config/clawrium/keys/<hostname>/` and tries to verify SSH access
as `xclm`. If that fails (typical on a fresh host where `xclm` does not
yet exist), it prints the Linux and macOS manual setup commands — with
your freshly-generated public key embedded inline — and exits non-zero.

Run those commands on the host (see [Host Preparation](../../guides/host-setup.md)),
then re-run `clawctl host create` to actually register the host.

The `--bootstrap` flag was removed in #547. It promised automatic xclm
setup but required the bootstrap user to already have passwordless sudo,
which was the same precondition manual setup ends with.

### Arguments

| Argument | Description |
|----------|-------------|
| `hostname` | Host IP address or hostname |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--port` | `-p` | SSH port (default: 22) |
| `--user` | `-u` | Management user on the host (must be `xclm`) |
| `--alias` | `-a` | Friendly name for this host |

### Example — first run (xclm not yet set up)

```bash
$ clawctl host create 192.168.1.100 --user xclm --alias pi-lab
Generating SSH keypair for '192.168.1.100'...
Keypair created: /home/user/.config/clawrium/keys/192.168.1.100/xclm_ed25519.pub
xclm SSH verification failed: Authentication failed - check SSH keys

Manual setup required. Log into the host with a sudo-capable user and
run the block that matches its OS:

## Linux
sudo useradd -m -s /bin/bash xclm
…

## macOS
sudo dscl . -create /Users/xclm
…
sudo dseditgroup -o edit -a xclm -t user com.apple.access_ssh

Then re-run: clawctl host create 192.168.1.100 --user xclm
```

### Example — re-run (xclm configured)

```bash
$ clawctl host create 192.168.1.100 --user xclm --alias pi-lab
host/pi-lab created on 192.168.1.100:22
```

### Host Key Verification

If the host key is unknown, the command surfaces a prompt and exits non-zero. Run `ssh -p <port> xclm@<hostname>` once to record the key, then re-run `clawctl host create`.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Host registered (or already exists with matching settings) |
| 1 | xclm SSH verification failed (manual setup needed), or host already exists with different settings |

---

## clawctl host get

List all registered hosts.

```bash
clawctl host get
```

### Example

```bash
$ clawctl host get
                    Registered Hosts
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Alias   ┃ Host            ┃ Architecture ┃ Cores ┃ Memory (GB) ┃ Tags       ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ pi-lab  │ 192.168.1.100   │ aarch64      │     4 │         4.0 │ production │
│ nuc-01  │ 192.168.1.101   │ x86_64       │     8 │        16.0 │ dev        │
│ -       │ 10.0.0.50       │ x86_64       │     4 │         8.0 │ -          │
└─────────┴─────────────────┴──────────────┴───────┴─────────────┴────────────┘
```

---

## clawctl host delete

Remove a host from the fleet.

```bash
clawctl host delete <hostname> [--force]
```

Prompts for confirmation unless `--force` is specified. Also deletes the host's SSH keypair.

### Arguments

| Argument | Description |
|----------|-------------|
| `hostname` | Host hostname or alias to remove |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--force` | `-f` | Skip confirmation prompt |

### Example

```bash
$ clawctl host delete pi-lab
Remove host 'pi-lab'? This cannot be undone. [y/N]: y
Host 'pi-lab' removed successfully.
Keypair for '192.168.1.100' deleted.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Host removed successfully or operation cancelled by user |
| 1 | Host not found or removal failed |

---

## clawctl host status

Check status of a host.

```bash
clawctl host status <hostname> [--refresh]
```

Shows connection status, hardware information, and metadata. Use `--refresh` to update hardware information.

### Arguments

| Argument | Description |
|----------|-------------|
| `hostname` | Host hostname or alias to check |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--refresh` | `-r` | Re-detect hardware capabilities |

### Example

```bash
$ clawctl host status pi-lab
Checking status of 'pi-lab'...
           Host Status: pi-lab
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Property     ┃ Value                       ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Connection   │ Connected                   │
│ Hostname     │ 192.168.1.100               │
│ Port         │ 22                          │
│ User         │ xclm                        │
│ Added        │ 2026-04-01T10:30:00Z        │
│ Last Seen    │ 2026-04-05T08:15:00Z        │
│ Tags         │ production                  │
│ Architecture │ aarch64                     │
│ CPU Cores    │ 4                           │
│ Memory       │ 4.0 GB                      │
│ GPU          │ None detected               │
└──────────────┴─────────────────────────────┘
```

Refresh hardware information:

```bash
$ clawctl host status pi-lab --refresh
Checking status of 'pi-lab'...
Refreshing hardware information...
Hardware information updated.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Host is connected |
| 1 | Host not found or disconnected |

---

## clawctl host reset

Reset a host, removing all claws and users.

```bash
clawctl host reset <hostname> [options]
```

This command will:
- Stop and remove all `*claw` services
- Remove all users with uid >= 1000 (except `xclm`)
- Clean clawrium configuration paths

### Arguments

| Argument | Description |
|----------|-------------|
| `hostname` | Host hostname or alias to reset |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--yes` | `-y` | Skip confirmation prompt |
| `--dry-run` | `-n` | Show what would be removed without executing |
| `--untrack` | | Also remove host from Clawrium tracking after reset |

### Example

Dry run to preview changes:

```bash
$ clawctl host reset pi-lab --dry-run
Scanning 'pi-lab' for targets...

Users to remove (2):
  - zc-work
  - oc-home

Services to remove (2):
  - zeroclaw-work.service
  - openclaw-home.service

Paths to clean (1):
  - /home/zc-work/.config/zeroclaw

Dry run - no changes made
```

Execute reset:

```bash
$ clawctl host reset pi-lab --yes
Scanning 'pi-lab' for targets...
Resetting 'pi-lab'...
Reset complete!
  Users removed: 2
  Services removed: 2
  Paths cleaned: 1
```

Reset and untrack:

```bash
$ clawctl host reset pi-lab --yes --untrack
...
Reset complete!
Untracking 'pi-lab'...
Host removed from tracking.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Reset completed successfully |
| 1 | Host not found, reset failed, or user aborted |

---

## Address Subcommands

Manage multiple network addresses for a single host. Useful when hosts are reachable via different addresses depending on network context (LAN, VPN, Tailscale, etc.).

```bash
clawctl host address <command> [options]
```

| Command | Description |
|---------|-------------|
| [`clawctl host address add`](#clawctl-host-address-add) | Add an address to a host |
| [`clawctl host address remove`](#clawctl-host-address-remove) | Remove an address from a host |
| [`clawctl host address list`](#clawctl-host-address-list) | List all addresses for a host |
| [`clawctl host address set-primary`](#clawctl-host-address-set-primary) | Set a different address as primary |

---

## clawctl host address add

Add an address to a host.

```bash
clawctl host address add <host> <address> [--label LABEL]
```

The first address added to a host is automatically the primary. Additional addresses can be used to reach the host from different network contexts.

### Arguments

| Argument | Description |
|----------|-------------|
| `host` | Host hostname or alias |
| `address` | Address as IPv4, IPv6, or hostname (e.g., 192.168.1.1, myhost.local) |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--label` | `-l` | Label for the address (e.g., lan, vpn, external) |

### Example

```bash
$ clawctl host address add pi-lab 100.64.0.50 --label tailscale
Address '100.64.0.50' (tailscale) added to host 'pi-lab'
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Address added successfully |
| 1 | Host not found or address already exists |

---

## clawctl host address remove

Remove an address from a host.

```bash
clawctl host address remove <host> <address>
```

Cannot remove the primary address. Use `set-primary` to switch to a different address first.

### Arguments

| Argument | Description |
|----------|-------------|
| `host` | Host hostname or alias |
| `address` | Address to remove |

### Example

```bash
$ clawctl host address remove pi-lab 100.64.0.50
Address '100.64.0.50' removed from host 'pi-lab'
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Address removed successfully |
| 1 | Host not found, address not found, or cannot remove primary |

---

## clawctl host address list

List all addresses for a host.

```bash
clawctl host address list <host>
```

Shows the primary address (used for all downstream commands) and any secondary addresses for different network contexts.

### Arguments

| Argument | Description |
|----------|-------------|
| `host` | Host hostname or alias |

### Example

```bash
$ clawctl host address list pi-lab
           Addresses for pi-lab
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Address         ┃ Primary ┃ Label     ┃ Added            ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ 192.168.1.100   │ *       │ lan       │ 2026-04-01 10:30 │
│ 100.64.0.50     │         │ tailscale │ 2026-04-05 14:15 │
└─────────────────┴─────────┴───────────┴──────────────────┘
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Addresses listed successfully |
| 1 | Host not found |

---

## clawctl host address set-primary

Set a different address as the primary for a host.

```bash
clawctl host address set-primary <host> <address>
```

The primary address is used for all downstream commands (agent install, configure, status checks, etc.). Changing the primary updates the host's hostname field.

### Arguments

| Argument | Description |
|----------|-------------|
| `host` | Host hostname or alias |
| `address` | Address to make primary |

### Example

```bash
$ clawctl host address set-primary pi-lab 100.64.0.50
Primary address for 'pi-lab' set to '100.64.0.50'
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Primary address updated successfully |
| 1 | Host not found or address not found |

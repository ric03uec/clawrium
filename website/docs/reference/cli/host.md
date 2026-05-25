# Host Commands

Manage hosts in your Clawrium fleet.

```bash
clawctl host <command> [options]
```

## Commands

| Command | Description |
|---------|-------------|
| [`clawctl host create --bootstrap`](#clawctl-host-create---bootstrap) | Initialize a host for Clawrium management |
| [`clawctl host create`](#clawctl-host-create) | Add a new host to the fleet |
| [`clawctl host get`](#clawctl-host-get) | List all registered hosts |
| [`clawctl host delete`](#clawctl-host-delete) | Remove a host from the fleet |
| [`clawctl host status`](#clawctl-host-status) | Check status of a host |
| [`clawctl host reset`](#clawctl-host-reset) | Reset a host, removing all claws and users |
| [`clawctl host address`](#address-subcommands) | Manage multiple addresses for a host |

---

## clawctl host create --bootstrap

Initialize a host for Clawrium management.

```bash
clawctl host create --bootstrap <hostname> [--user USER]
```

Generates a per-host SSH keypair and attempts to configure the `xclm` management user on the remote host. If SSH access fails, displays manual setup commands.

### Arguments

| Argument | Description |
|----------|-------------|
| `hostname` | Host IP or hostname to initialize |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--user` | `-u` | SSH user for initial connection (default: current user) |

### Example

```bash
$ clawctl host create --bootstrap 192.168.1.100
Generating SSH keypair for '192.168.1.100'...
Keypair created: /home/user/.config/clawrium/keys/192.168.1.100.pub

Attempting connection to 192.168.1.100 as user...
Connection successful!
Setting up xclm management user...

Verifying xclm access...
xclm user configured successfully!

Next step: clawctl host create 192.168.1.100
```

### Manual Setup

If automatic setup fails, the command displays manual instructions:

```bash
# Create xclm user
sudo useradd -m -s /bin/bash xclm

# Grant passwordless sudo
echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm
sudo chmod 440 /etc/sudoers.d/xclm

# Setup SSH access
sudo mkdir -p /home/xclm/.ssh
sudo chmod 700 /home/xclm/.ssh
echo 'ssh-ed25519 AAAA...' | sudo tee /home/xclm/.ssh/authorized_keys
sudo chmod 600 /home/xclm/.ssh/authorized_keys
sudo chown -R xclm:xclm /home/xclm/.ssh
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Host initialized successfully |
| 1 | Initialization failed or requires manual setup |

---

## clawctl host create

Add a new host to the fleet.

```bash
clawctl host create <hostname> [options]
```

Requires keypair to exist (run `clawctl host create --bootstrap` first). Tests SSH connection before saving and detects hardware capabilities automatically.

### Arguments

| Argument | Description |
|----------|-------------|
| `hostname` | Host IP address or hostname |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--port` | `-p` | SSH port (default: 22) |
| `--user` | `-u` | SSH user (default: xclm) |
| `--alias` | `-a` | Friendly name for this host |
| `--tags` | `-t` | Comma-separated tags |

### Example

```bash
$ clawctl host create 192.168.1.100 --alias pi-lab --tags production,arm
Testing connection to 192.168.1.100:22 as xclm...
Connection successful!
Detecting hardware capabilities...
Hardware detected: aarch64, 4 cores, 4096MB RAM

Host 'pi-lab' added successfully!
```

### Host Key Verification

On first connection to a new host, Clawrium prompts for host key verification:

```bash
Unknown host key for 192.168.1.100
  Key type: ssh-ed25519
  Fingerprint: SHA256:abc123...

Warning: Verify this fingerprint matches the host's actual key.

Accept this host key and continue? [y/N]:
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Host added successfully |
| 1 | Connection failed, host already exists, or keypair missing |

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

# Host Commands

Manage hosts in your Clawrium fleet.

```bash
clm host <command> [options]
```

## Commands

| Command | Description |
|---------|-------------|
| [`clm host init`](#clm-host-init) | Initialize a host for Clawrium management |
| [`clm host add`](#clm-host-add) | Add a new host to the fleet |
| [`clm host list`](#clm-host-list) | List all registered hosts |
| [`clm host remove`](#clm-host-remove) | Remove a host from the fleet |
| [`clm host status`](#clm-host-status) | Check status of a host |
| [`clm host reset`](#clm-host-reset) | Reset a host, removing all claws and users |

---

## clm host init

Initialize a host for Clawrium management.

```bash
clm host init <hostname> [--user USER]
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
$ clm host init 192.168.1.100
Generating SSH keypair for '192.168.1.100'...
Keypair created: /home/user/.config/clawrium/keys/192.168.1.100.pub

Attempting connection to 192.168.1.100 as user...
Connection successful!
Setting up xclm management user...

Verifying xclm access...
xclm user configured successfully!

Next step: clm host add 192.168.1.100
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

## clm host add

Add a new host to the fleet.

```bash
clm host add <hostname> [options]
```

Requires keypair to exist (run `clm host init` first). Tests SSH connection before saving and detects hardware capabilities automatically.

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
$ clm host add 192.168.1.100 --alias pi-lab --tags production,arm
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

## clm host list

List all registered hosts.

```bash
clm host list
```

### Example

```bash
$ clm host list
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

## clm host remove

Remove a host from the fleet.

```bash
clm host remove <hostname> [--force]
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
$ clm host remove pi-lab
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

## clm host status

Check status of a host.

```bash
clm host status <hostname> [--refresh]
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
$ clm host status pi-lab
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
$ clm host status pi-lab --refresh
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

## clm host reset

Reset a host, removing all claws and users.

```bash
clm host reset <hostname> [options]
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
$ clm host reset pi-lab --dry-run
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
$ clm host reset pi-lab --yes
Scanning 'pi-lab' for targets...
Resetting 'pi-lab'...
Reset complete!
  Users removed: 2
  Services removed: 2
  Paths cleaned: 1
```

Reset and untrack:

```bash
$ clm host reset pi-lab --yes --untrack
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

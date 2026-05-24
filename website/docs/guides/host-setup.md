---
sidebar_position: 2
description: Prepare hosts for Clawrium management. Automatic and manual setup options for the xclm management user.
keywords: [host setup, xclm, SSH, configuration, prepare host]
---

# Host Setup

Before adding a host to Clawrium, you must prepare it for management. This guide covers the setup process in detail.

## Prerequisites

- SSH access to the target host (as any user with sudo privileges)
- Clawrium installed (`clawctl` command available)
- **On the target host:**
  - Python 3 (required for hardware detection)
  - pciutils (optional, for GPU detection via `lspci`)

## Option A: Automatic Setup (Recommended)

The `clawctl host create --bootstrap` command generates a per-host SSH keypair and attempts to automatically configure the xclm management user:

```bash
clawctl host create --bootstrap 192.168.1.100 --user myuser
```

If you have SSH access to the target host, Clawrium will:
1. Generate a unique keypair for this host in `~/.config/clawrium/keys/<hostname>/`
2. Connect as the specified user
3. Create the `xclm` management user
4. Configure passwordless sudo
5. Add the public key to `authorized_keys`
6. Verify xclm access works

If auto-setup succeeds, skip to [Add Host to Clawrium](#add-host-to-clawrium). If it fails, follow Option B.

## Option B: Manual Setup

If `clawctl host create --bootstrap` couldn't connect automatically, it displays the public key and setup commands. Run these on the target host:

```bash
# SSH to host as your current user
ssh user@hostname

# Create xclm user
sudo useradd -m -s /bin/bash xclm

# Grant passwordless sudo (required for claw installation)
echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm
sudo chmod 440 /etc/sudoers.d/xclm

# Setup .ssh directory
sudo mkdir -p /home/xclm/.ssh
sudo chmod 700 /home/xclm/.ssh

# Paste the public key displayed by 'clawctl host create --bootstrap'
echo "ssh-ed25519 AAAA... clawrium" | sudo tee /home/xclm/.ssh/authorized_keys
sudo chmod 600 /home/xclm/.ssh/authorized_keys
sudo chown -R xclm:xclm /home/xclm/.ssh

# Exit back to your machine
exit
```

:::note Security
xclm has full root access via sudo but no password is set (key-auth only). The private key is stored in `~/.config/clawrium/keys/<hostname>/` with 0600 permissions. Claw instances run as separate unprivileged users created by Clawrium.
:::

## Add Host to Clawrium

Once the management user is configured, add the host:

```bash
# Basic - uses per-host keypair from init
clawctl host create 192.168.1.100

# With alias for friendly display name
clawctl host create 192.168.1.100 --alias myhost

# With custom port
clawctl host create 192.168.1.100 --alias myhost --port 2222
```

:::important
You must run `clawctl host create --bootstrap` before `clawctl host create`. The add command requires a keypair to exist for the host.
:::

Clawrium will:
1. Connect using the per-host keypair from `~/.config/clawrium/keys/<hostname>/`
2. Prompt to accept the host key (first connection only, saved to `~/.ssh/known_hosts`)
3. Attempt to detect hardware capabilities
4. Save the host configuration to `~/.config/clawrium/hosts.json`

:::note SSH Support
Clawrium uses paramiko for SSH connections. ProxyJump, ProxyCommand, and other advanced SSH config options are not supported. Ensure direct network access to the host.
:::

## Troubleshooting

### Permission denied (publickey)

The host's `authorized_keys` doesn't have the correct public key. Re-run:

```bash
clawctl host create --bootstrap 192.168.1.100 --user myuser
```

This will display the correct public key to add. If auto-setup fails, follow Option B to add it manually.

Required permissions on host:
- `/home/xclm/.ssh` - 700
- `/home/xclm/.ssh/authorized_keys` - 600

### Host key verification failed

The host's SSH key has changed since you last connected.

:::warning
Before removing the old key, verify the change is expected (OS reinstall, hardware replacement). If unexpected, this could indicate a man-in-the-middle attack. Verify the new fingerprint out-of-band (e.g., via console access) before proceeding.
:::

If the change is expected:

```bash
ssh-keygen -R hostname
```

Then retry `clawctl host create` and verify the new fingerprint.

### Hardware not detected

Hardware detection requires Python 3 on the remote host. Verify:

```bash
ssh user@hostname "python3 --version"
```

If Python is missing, install it:

```bash
ssh user@hostname "sudo apt-get install python3"
```

For GPU detection, install pciutils:

```bash
ssh user@hostname "sudo apt-get install pciutils"
```

Then refresh hardware info:

```bash
clawctl host status myhost --refresh
```

### Re-initialize a host

If you need to regenerate the keypair for a specific host:

```bash
# Remove the host (also deletes its keypair)
clawctl host delete hostname --force

# Re-initialize with fresh keypair
clawctl host create --bootstrap hostname --user myuser
```

This only affects the specified host. Other hosts retain their keypairs.

# Host Preparation

Before adding a host to Clawrium, you must prepare it for management. This guide walks through setting up the management user and SSH access.

## Prerequisites

- SSH access to the target host (as any user with sudo privileges)
- Clawrium installed (`clm` command available)
- **On the target host:**
  - Python 3 (required for hardware detection)
  - pciutils (optional, for GPU detection via `lspci`)

## P0. Initialize Host (Recommended)

The `clm host init` command generates a per-host SSH keypair and attempts to automatically configure the xclm management user:

```bash
# Auto-setup (requires SSH access with sudo privileges)
clm host init 192.168.1.100 --user myuser
```

If you have SSH access to the target host, Clawrium will:
1. Generate a unique keypair for this host in `~/.config/clawrium/keys/<hostname>/`
2. Connect as the specified user
3. Create the `xclm` management user
4. Configure passwordless sudo
5. Add the public key to `authorized_keys`
6. Verify xclm access works

If auto-setup succeeds, skip to P2. If it fails, follow P1 for manual setup.

## P1. Manual Setup (If Auto-Setup Failed)

If `clm host init` couldn't connect automatically, it displays the public key and setup commands. Run these on the target host:

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

# Paste the public key displayed by 'clm host init'
echo "ssh-ed25519 AAAA... clawrium" | sudo tee /home/xclm/.ssh/authorized_keys
sudo chmod 600 /home/xclm/.ssh/authorized_keys
sudo chown -R xclm:xclm /home/xclm/.ssh

# Exit back to your machine
exit
```

**Security note:** xclm has full root access via sudo but no password is set (key-auth only). The private key is stored in `~/.config/clawrium/keys/<hostname>/` with 0600 permissions. Claw instances run as separate unprivileged users created by Clawrium.

## P2. Add Host to Clawrium

Once the management user is configured (either via auto-setup or manual setup), add the host:

```bash
# Basic - uses per-host keypair from init
clm host add 192.168.1.100

# With alias for friendly display name
clm host add 192.168.1.100 --alias myhost

# With custom port or user
clm host add 192.168.1.100 --alias myhost --port 2222
```

**Note:** You must run `clm host init` before `clm host add`. The add command requires a keypair to exist for the host.

Clawrium will:
1. Connect using the per-host keypair from `~/.config/clawrium/keys/<hostname>/`
2. Prompt to accept the host key (first connection only, saved to `~/.ssh/known_hosts`)
3. Attempt to detect hardware capabilities (may be skipped if detection fails - rerun with `clm host status --refresh`)
4. Save the host configuration to `~/.config/clawrium/hosts.json`

**Note:** Clawrium uses paramiko for SSH connections. ProxyJump, ProxyCommand, and other advanced SSH config options are not supported in v1. Ensure direct network access to the host.

## Troubleshooting

### Permission denied (publickey)

The host's `authorized_keys` doesn't have the correct public key. Re-run:
```bash
clm host init 192.168.1.100 --user myuser
```

This will display the correct public key to add. If auto-setup fails, follow P1 to add it manually.

Required permissions on host:
- `/home/xclm/.ssh` - 700
- `/home/xclm/.ssh/authorized_keys` - 600

### Host key verification failed

The host's SSH key has changed since you last connected.

**Warning:** Before removing the old key, verify the change is expected (OS reinstall, hardware replacement). If unexpected, this could indicate a man-in-the-middle attack. Verify the new fingerprint out-of-band (e.g., via console access) before proceeding.

If the change is expected:
```bash
ssh-keygen -R hostname
```

Then retry `clm host add` and verify the new fingerprint.

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
clm host status myhost --refresh
```

### Re-initialize a host

If you need to regenerate the keypair for a specific host:
```bash
# Remove the host (also deletes its keypair)
clm host remove hostname --force

# Re-initialize with fresh keypair
clm host init hostname --user myuser
```

This only affects the specified host. Other hosts retain their keypairs.

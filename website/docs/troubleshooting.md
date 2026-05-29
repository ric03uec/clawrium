---
sidebar_position: 6
description: Common issues and solutions when using Clawrium
keywords: [troubleshooting, errors, debug, SSH, connection]
---

# Troubleshooting

This guide covers common issues you might encounter when using Clawrium and how to resolve them.

## SSH Connection Issues

### "Connection refused" Error

**Symptoms:**
```
Testing connection to 192.168.1.100:22 as xclm...
Connection failed: Connection refused
```

**Causes & Solutions:**

1. **SSH service not running on host**
   ```bash
   # On the target host, check SSH service status
   sudo systemctl status sshd
   # Start if not running
   sudo systemctl start sshd
   ```

2. **Wrong port number**
   ```bash
   # Specify the correct SSH port
   clawctl host create 192.168.1.100 --port 2222
   ```

3. **Firewall blocking connection**
   ```bash
   # On the target host, allow SSH
   sudo ufw allow ssh
   # Or for specific port
   sudo ufw allow 2222/tcp
   ```

### "Permission denied (publickey)" Error

**Symptoms:**
```
Permission denied (publickey)
```

**Causes & Solutions:**

1. **Keypair not initialized**

   Run `clawctl host create` once — it generates the per-host keypair
   and prints the manual setup commands you need to paste on the host
   (see [Host Preparation](guides/host-setup.md)):
   ```bash
   clawctl host create 192.168.1.100 --user xclm --alias <name>
   ```

2. **xclm user not configured**

   Configure the xclm user using the commands `clawctl` printed (or
   the reference block below):
   ```bash
   # Create xclm user
   sudo useradd -m -s /bin/bash xclm
   
   # Grant passwordless sudo
   echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm
   sudo chmod 440 /etc/sudoers.d/xclm
   
   # Add public key (from Clawrium's output)
   sudo mkdir -p /home/xclm/.ssh
   sudo chmod 700 /home/xclm/.ssh
   echo '<public-key-from-clm-host-init>' | sudo tee /home/xclm/.ssh/authorized_keys
   sudo chmod 600 /home/xclm/.ssh/authorized_keys
   sudo chown -R xclm:xclm /home/xclm/.ssh
   ```

3. **Wrong SSH user**
   
   For `clawctl host create`, Clawrium uses `xclm` by default. If you used a different user during init:
   ```bash
   clawctl host create 192.168.1.100 --user customuser
   ```

### Host Key Verification Failed

**Symptoms:**
```
Unknown host key for 192.168.1.100
  Key type: ssh-ed25519
  Fingerprint: SHA256:abc123...
```

**Solution:**

This is a security feature. Verify the fingerprint matches the host's actual key:

```bash
# On the target host
ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub
```

If the fingerprints match, accept the key when prompted by Clawrium.

To remove a saved host key (e.g., after host reinstallation):
```bash
ssh-keygen -R 192.168.1.100
```

## Host Management Issues

### "Host already exists" Error

**Symptoms:**
```
Error: Host '192.168.1.100' already exists in fleet
```

**Solution:**

Remove the existing host entry first:
```bash
clawctl host delete 192.168.1.100 --force
clawctl host create 192.168.1.100 --user xclm --alias <name>
```

Or use the alias to differentiate:
```bash
clawctl host create 192.168.1.100 --alias new-name
```

### "Keypair not found" Error

**Symptoms:**
```
Error: No keypair found for '192.168.1.100'. Run 'clawctl host create 192.168.1.100 --user xclm' first.
```

**Solution:**

Generate the keypair (and surface the manual setup commands) by running:
```bash
clawctl host create 192.168.1.100 --user xclm --alias <name>
```

### Hardware Detection Fails

**Symptoms:**
```
Detecting hardware capabilities...
Warning: Could not detect GPU
```

**Solution:**

Hardware detection requires certain commands on the host. Ensure the host has:
- `lscpu` for CPU info (usually pre-installed)
- `free` for memory info (usually pre-installed)
- `nvidia-smi` for NVIDIA GPU detection (only if GPU present)

For manual refresh:
```bash
clawctl host status 192.168.1.100 --refresh
```

## Host Reset Issues

### Reset Fails with "User has active processes"

**Symptoms:**
```
Error: Cannot remove user 'zc-work': user is currently logged in
```

**Solution:**

Kill active processes before reset:
```bash
# On the target host
sudo pkill -u zc-work
sudo pkill -u oc-home
```

Then retry the reset:
```bash
clawctl host reset 192.168.1.100 --yes
```

### Reset Doesn't Remove Everything

**Symptoms:**
Some files or users remain after reset.

**Solution:**

Check what the reset would remove first:
```bash
clawctl host reset 192.168.1.100 --dry-run
```

The reset only removes:
- Users with UID >= 1000 (except xclm)
- `*claw` systemd services
- Standard clawrium paths

Manual cleanup may be needed for custom installations.

## Configuration Issues

### "Config directory not writable"

**Symptoms:**
```
Error: Cannot write to ~/.config/clawrium/
```

**Solution:**

Check and fix permissions:
```bash
ls -la ~/.config/clawrium/
chmod 700 ~/.config/clawrium/
chmod 600 ~/.config/clawrium/*.json
chmod 600 ~/.config/clawrium/keys/*/*
```

### Corrupted hosts.json

**Symptoms:**
```
Error: Failed to parse hosts.json
```

**Solution:**

Backup and recreate the config:
```bash
# Backup existing config
cp ~/.config/clawrium/hosts.json ~/.config/clawrium/hosts.json.bak

# View the corrupted file
cat ~/.config/clawrium/hosts.json

# If unrecoverable, remove and re-add hosts
rm ~/.config/clawrium/hosts.json
clawctl host create 192.168.1.100  # Re-initialize each host
```

## Debug Logging

Enable verbose output for troubleshooting:

```bash
# Enable Ansible verbose mode
export ANSIBLE_VERBOSITY=3
clawctl host create 192.168.1.100 --user xclm --alias <name>
```

## Getting Help

If you can't resolve an issue:

1. **Search existing issues**: [GitHub Issues](https://github.com/ric03uec/clawrium/issues)
2. **Start a discussion**: [GitHub Discussions](https://github.com/ric03uec/clawrium/discussions)
3. **File a bug report**: Include:
   - Clawrium version (`clawctl --version`)
   - Full error message
   - Steps to reproduce
   - OS and architecture of both client and target host

---
sidebar_position: 2
description: Prepare hosts for Clawrium management. Manual setup of the xclm management user on Linux and macOS.
keywords: [host setup, xclm, SSH, configuration, prepare host, macOS, Linux]
---

<!-- Mirror of docs/host-preparation.md. Do not edit here directly — edit docs/host-preparation.md and copy the body verbatim. The Docusaurus frontmatter above and this comment are the only website-specific additions. -->

# Host Preparation

Before a host can be registered with Clawrium, it must have a dedicated `xclm`
management user with passwordless `sudo` and the Clawrium-managed public key
in `authorized_keys`. This guide walks through that setup.

The flow is **manual on purpose** (issue #547). An earlier version offered
`--bootstrap` for automatic setup, but it could not succeed without the
bootstrap user already having passwordless `sudo` over a non-interactive SSH
channel — which is the same precondition you would have at the end of manual
setup anyway. The flag was removed; the only supported path is below.

## Prerequisites

- SSH access to the target host as a user that can run `sudo` (password sudo
  is fine — you will run the commands interactively).
- `clawctl` installed on your management machine — see
  [Installation](installation.md).
- On the target host: Python 3 (used for hardware detection).

## Step 1 — Generate the keypair and surface the setup commands

From your management machine, run:

```bash
clawctl host create <hostname-or-ip> --user xclm --alias <friendly-name>
```

On first run for that hostname, `clawctl` will:

1. Generate a per-host ed25519 keypair at
   `~/.config/clawrium/keys/<hostname>/`.
2. Try to verify SSH access as `xclm@<hostname>` using that key. On a fresh
   host this will fail because `xclm` does not exist yet — that is expected.
3. Print the manual setup commands for both Linux and macOS, with your
   freshly-generated public key already embedded in the
   `authorized_keys` line.
4. Exit non-zero with a "re-run after manual setup" message.

:::note `key_id` is immutable (issue #448)
The first successful `clawctl host create` for an alias mints a stable
`key_id` that per-agent secrets (Discord tokens, provider API keys,
hermes `HERMES_API_SERVER_KEY`) are stored under. Re-running
`clawctl host create <new-ip-or-dns> --alias <existing-alias>` updates
the host's `hostname`, port, and address list **without** rotating the
`key_id` — every secret stays reachable. Renaming the alias is a
deliberate identity change and does invalidate secrets.
:::

## Step 2 — Run the setup commands on the host

SSH to the host as your existing sudo-capable user and paste the block that
matches its OS. Copy the exact commands that `clawctl` printed (the public
key is unique per host) — the blocks below are reference material.

### Linux

```bash
# Create xclm user
sudo useradd -m -s /bin/bash xclm

# Passwordless sudo (required for agent installation)
echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm
sudo chmod 440 /etc/sudoers.d/xclm

# Authorized key (use the line clawctl printed; pubkey shown is a placeholder)
sudo mkdir -p /home/xclm/.ssh && sudo chmod 700 /home/xclm/.ssh
echo "ssh-ed25519 AAAA...your-pubkey... clawrium" | sudo tee /home/xclm/.ssh/authorized_keys
sudo chmod 600 /home/xclm/.ssh/authorized_keys
sudo chown -R xclm:xclm /home/xclm/.ssh
```

### macOS

macOS user creation uses `dscl` rather than `useradd`, and there is one
non-obvious Mac-only step: adding `xclm` to the `com.apple.access_ssh` group.
Without it, `sshd` silently rejects connections from `xclm` with no useful
log entry — easy to misdiagnose as a key or firewall problem.

```bash
# Create xclm user via dscl
sudo dscl . -create /Users/xclm
sudo dscl . -create /Users/xclm UserShell /bin/bash
sudo dscl . -create /Users/xclm RealName "Clawrium Mgmt"
sudo dscl . -create /Users/xclm UniqueID 600
sudo dscl . -create /Users/xclm PrimaryGroupID 20
sudo dscl . -create /Users/xclm NFSHomeDirectory /Users/xclm
sudo mkdir -p /Users/xclm && sudo chown xclm:staff /Users/xclm

# Passwordless sudo
echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm
sudo chmod 440 /etc/sudoers.d/xclm

# Authorized key (use the line clawctl printed; pubkey shown is a placeholder)
sudo mkdir -p /Users/xclm/.ssh && sudo chmod 700 /Users/xclm/.ssh
echo "ssh-ed25519 AAAA...your-pubkey... clawrium" | sudo tee /Users/xclm/.ssh/authorized_keys
sudo chmod 600 /Users/xclm/.ssh/authorized_keys
sudo chown -R xclm:staff /Users/xclm/.ssh

# Critical Mac-only step: SSH ACL group
sudo dseditgroup -o edit -a xclm -t user com.apple.access_ssh
```

**Security note:** `xclm` has full root via `sudo` and no password is set —
key-auth only. The private key is stored under
`~/.config/clawrium/keys/<hostname>/` with `0600` permissions. Agent processes
run as separate unprivileged users that Clawrium creates as part of agent
installation.

## Step 3 — Register the host

Run the same `clawctl host create` command again:

```bash
clawctl host create <hostname-or-ip> --user xclm --alias <friendly-name>
```

This time the keypair already exists, SSH as `xclm` succeeds, and the host
record is persisted to `~/.config/clawrium/hosts.json`. The command is
idempotent — running it a third time is a no-op.

Clawrium uses paramiko for SSH connections. `ProxyJump`, `ProxyCommand`, and
other advanced SSH config options are not supported. Ensure direct network
access to the host.

## Troubleshooting

### Permission denied (publickey)

`xclm`'s `authorized_keys` does not contain the public key Clawrium expects.
Re-print the manual commands by re-running `clawctl host create` — it will
print the same pubkey it generated previously (the per-host keypair is
deterministic across re-runs).

Required permissions on the host:

- `/home/xclm/.ssh` (Linux) or `/Users/xclm/.ssh` (macOS) — `700`
- `authorized_keys` — `600`
- `/etc/sudoers.d/xclm` — `440`

On macOS, also confirm `xclm` is in `com.apple.access_ssh`:

```bash
dseditgroup -o checkmember -m xclm com.apple.access_ssh
```

### Host key verification failed

The host's SSH key has changed since you last connected.

:::warning
Before removing the old key, verify the change is expected (OS reinstall,
hardware replacement). If unexpected, this could indicate a man-in-the-middle
attack. Verify the new fingerprint out-of-band (e.g., via console access)
before proceeding.
:::

If the change is expected:

```bash
ssh-keygen -R <hostname>
```

Then retry `clawctl host create` and verify the new fingerprint.

### Hardware not detected

Hardware detection requires Python 3 on the remote host:

```bash
ssh xclm@<hostname> "python3 --version"
```

If Python is missing, install it:

```bash
ssh xclm@<hostname> "sudo apt-get install python3"   # Linux
```

macOS ships Python 3 by default at `/usr/bin/python3` (Command Line Tools).
For GPU detection on Linux, also install `pciutils`. After installing
missing prerequisites, re-register the host (`clawctl host delete <name>
--force` then `clawctl host create <ip> --user xclm --alias <name>`).

### Regenerate keypair for a host

If you need a fresh keypair for a specific host (e.g., compromised key,
rotating credentials):

```bash
clawctl host delete <hostname-or-alias> --force
clawctl host create <hostname-or-ip> --user xclm --alias <friendly-name>
```

The delete removes the host record and its keypair. The subsequent
`host create` generates a new keypair and prints fresh manual commands —
you will need to paste them on the host to install the new public key.
This affects only the specified host; other hosts retain their keypairs.

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
  is fine — you will run the commands interactively). **On a fresh macOS
  host, you must enable Remote Login first — see
  [Step 1.5](#step-15-enable-remote-login-macos-only).**
- `clawctl` installed on your management machine — see
  [Installation](installation.md).
- On the target host: Python 3 (used for hardware detection).

## Step 0 — Pin the host's IP address

Clawrium addresses hosts by IP in `~/.config/clawrium/hosts.json`. If the
host's address changes — a router reboot, a DHCP lease expiring, moving
between networks — `clawctl` can no longer reach it over SSH and every
lifecycle command against its agents fails until the record is updated.
Pin the address **before** registering the host.

### Router DHCP reservation (preferred)

A DHCP reservation keeps the host's networking configuration untouched: the
router always hands the same lease to the same machine. Steps vary by
vendor, but the shape is the same on every consumer router:

1. Find the host's MAC address for the interface it uses:

   ```bash
   ip link show                  # Linux — MAC is the `link/ether` value
   ipconfig getifaddr en0        # macOS — confirm the active interface
   networksetup -getmacaddress en0   # macOS — MAC for that interface
   ```

2. Open the router's admin UI (typically `http://192.168.1.1` — check your
   default gateway with `ip route | grep default` on Linux or
   `route -n get default` on macOS).
3. Find the DHCP settings — commonly under *LAN*, *Network*, or
   *Advanced → DHCP Server*. The reservation list is labeled *DHCP
   Reservation*, *Static Lease*, *Address Reservation*, or *DHCP Binding*.
4. Add an entry mapping the MAC address from step 1 to the address you want.
   Pick an address outside the router's dynamic DHCP pool where the router
   allows it — some firmware requires the reservation to sit inside the pool
   instead.
5. Reboot the host (or renew its lease) and confirm it came back on the
   reserved address.

### OS-level static IP (fallback)

Use this when you do not control the router. Configure the address on the
host itself, and exclude it from the router's DHCP pool if you can so
nothing else is handed the same address.

**Linux (netplan — Ubuntu Server).** Edit the file under `/etc/netplan/`
and apply:

```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: false
      addresses: [192.168.1.100/24]
      routes:
        - to: default
          via: 192.168.1.1
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
```

```bash
sudo netplan apply
```

**Linux (NetworkManager — desktop distros):**

```bash
nmcli con mod "<connection-name>" \
  ipv4.method manual \
  ipv4.addresses 192.168.1.100/24 \
  ipv4.gateway 192.168.1.1 \
  ipv4.dns "1.1.1.1,8.8.8.8"
nmcli con up "<connection-name>"
```

`nmcli con show` lists the connection names.

**macOS.** System Settings → Network → select the interface → *Details…* →
*TCP/IP* → set *Configure IPv4* to **Manually** and fill in the address,
subnet mask, and router. The CLI equivalent:

```bash
sudo networksetup -setmanual "Wi-Fi" 192.168.1.100 255.255.255.0 192.168.1.1
```

:::warning Applying a static IP over SSH drops your session
The connection breaks the moment the address changes. Run these commands
from a local console where you can, and reconnect on the new address.
:::

### If the address already changed

Point the existing host record at the new address — the `key_id`, and
therefore every secret stored under it, is preserved:

```bash
clawctl host edit <alias> --hostname <new-ip>
```

`clawctl` will remind you to confirm that `xclm`'s `authorized_keys` is
intact on the machine at the new address.

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

## Step 1.5: Enable Remote Login (macOS only)

:::note
Skip this step on Linux. On a fresh macOS install, `sshd` (Remote Login)
is **off by default**, so Step 2's SSH instructions cannot succeed until
you turn it on. Do this **locally on the Mac**, signed in as an
administrator — you will not have SSH access yet.
:::

**GUI path (recommended):** System Settings → General → Sharing → toggle
**Remote Login** on. When prompted "Allow access for":

- Choose **All users** for the simplest setup, OR
- Choose **Only these users** — the `dseditgroup ... com.apple.access_ssh`
  command in Step 2's macOS block is what lets `xclm` satisfy this rule.

**CLI path:** open Terminal locally on the Mac and run:

```bash
sudo systemsetup -setremotelogin on
```

On macOS 13+ (Ventura and later), `systemsetup` may fail with a Full Disk
Access error. If that happens, use the GUI path above — there is no flag
or workaround that avoids the FDA prompt.

Once Remote Login is on, switch to your management machine and continue
with Step 2.

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

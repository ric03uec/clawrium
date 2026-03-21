# Clawrium Documentation

Clawrium is a CLI tool for managing AI Claw fleets on local networks.

## Getting Started

1. [Host Preparation](host-preparation.md) - Prepare hosts for management (create xclm user, setup SSH)
2. Host Management - Add, list, and manage hosts with `clm host` (coming soon)
3. Claw Deployment - Deploy AI assistants to your fleet (coming soon)

## Quick Reference

```bash
# Initialize a host (generates keypair, attempts auto-setup of xclm user)
clm host init <hostname> --user <your-ssh-user>

# Add an initialized host to the fleet
clm host add <hostname>

# List all hosts
clm host list

# Check host status (exits with code 1 if unreachable - useful for scripting)
clm host status <hostname>

# Remove a host and its keypair
clm host remove <hostname>
clm host remove <hostname> --force
```

## User Data

Current files stored in `~/.config/clawrium/` (or `$XDG_CONFIG_HOME/clawrium/` if set):

| Path | Description |
|------|-------------|
| `hosts.json` | Registered hosts and their metadata. Written with `0600` permissions. Do not edit manually. |
| `keys/<hostname>/xclm_ed25519` | Private key for SSH to `<hostname>`. `0600` permissions. |
| `keys/<hostname>/xclm_ed25519.pub` | Public key added to host's `authorized_keys`. |

**Note:** Clawrium also modifies `~/.ssh/known_hosts` when accepting host keys on first connection (TOFU - Trust On First Use).

When a host is removed with `clm host remove`, both the host entry in `hosts.json` and the per-host keypair in `keys/<hostname>/` are deleted.

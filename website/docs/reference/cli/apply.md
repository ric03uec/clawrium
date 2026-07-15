---
sidebar_position: 3
description: Declarative fleet reconciliation via clawctl apply — fleet manifests, hosts, agents, and bootstrap keypair generation
keywords: [cli, apply, fleet, manifest, bootstrap, declarative, reconcile]
---

# clawctl apply

Apply a fleet manifest (declarative reconciliation).

```bash
clawctl apply [options]
```

Reads a fleet manifest file (YAML) and reconciles the actual state of your
fleet to match the declared desired state. New hosts are registered, new
agents are installed, and existing resources are updated where the manifest
differs from reality.

This is the **kubectl-style** entry point for managing your fleet — the
complement to the imperative `clawctl host create` / `clawctl agent create`
commands.

## Options

| Option | Short | Description |
|--------|-------|-------------|
| `--file` | `-f` | Fleet manifest file or directory (required unless a default exists) |
| `--kustomize` | `-k` | Directory of manifests (alias for `--file` with a directory) |
| `--dry-run` | | Preview changes without applying |
| `--yes` | `-y` | Skip confirmation on destructive changes |

## Fleet Manifest Format

A fleet manifest declares hosts, providers, agents, and their relationships
in a single YAML file:

```yaml
apiVersion: v1
kind: Fleet
metadata:
  name: my-fleet

hosts:
  - metadata:
      name: lab-pi
      alias: lab-pi
    spec:
      hostname: 192.168.1.100
      port: 22
      user: xclm
      bootstrap: true

agents:
  - metadata:
      name: opc-work
    spec:
      type: openclaw
      host: lab-pi

providers:
  - metadata:
      name: openai-prod
    spec:
      type: openai
```

## Bootstrap SSH Keypair Generation

When a `Host` resource declares `bootstrap: true`, `clawctl apply`
automatically generates an ed25519 SSH keypair under
`~/.config/clawrium/keys/<key_id>/` if one does not already exist. The
public key is printed to stdout with instructions to add it to
`authorized_keys` on the remote host — mirroring what `clawctl host create`
does interactively.

```bash
$ clawctl apply -f fleet.yaml
applying fleet manifest...
host/lab-pi: creating...
  [bootstrap] Generated SSH keypair for 192.168.1.100 (key_id: 192.168.1.100)
  [bootstrap] Add this public key to /home/xclm/.ssh/authorized_keys on the remote host:
    ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... 192.168.1.100
```

Hosts without `bootstrap: true` are unaffected — the key generation code
path is fully opt-in.

### Key Idempotency

Re-running `clawctl apply` never overwrites an existing keypair. The
generator checks `get_host_private_key` first and only creates a new key
when the key does not yet exist. Subsequent applies are no-ops for key
generation.

## Dry Run

Preview what changes would be made without applying them:

```bash
$ clawctl apply -f fleet.yaml --dry-run

Changes that would be applied:
  create host/lab-pi
  create provider/openai-prod
  create agent/opc-work
  no changes to host/nuc-01
```

## Examples

```bash
# Apply from a specific manifest file
clawctl apply -f fleet.yaml

# Apply from a directory of manifests
clawctl apply -k manifests/

# Preview without applying
clawctl apply -f fleet.yaml --dry-run

# Apply with automatic confirmation
clawctl apply -f fleet.yaml --yes
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Manifest applied successfully (or dry-run completed) |
| 1 | One or more resources failed to create/update |
| 2 | Invalid manifest or missing required options |

## Related

- [`clawctl diff`](#) — Preview changes a fleet manifest would make
- [`clawctl delete`](#) — Delete resources declared in a fleet manifest
- [`clawctl host create`](./host.md#clawctl-host-create) — Imperative host registration
- [Host Preparation](../../guides/host-setup.md) — Manual host setup steps

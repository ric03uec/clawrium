---
sidebar_position: 2
---

# Architecture

Clawrium manages AI assistant deployments across your network through three key concepts: **Hosts**, **Claws**, and the **Registry**.

## Key Concepts

```mermaid
graph TB
    subgraph "Your Network"
        subgraph "Clawrium CLI"
            CLM[clm]
            CONFIG[~/.config/clawrium/]
        end

        subgraph "Host A"
            CLAW1[ZeroClaw]
            CLAW2[OpenClaw]
        end

        subgraph "Host B"
            CLAW3[NemoClaw]
        end
    end

    REGISTRY[(Registry)]

    CLM --> |manages| CONFIG
    CLM --> |SSH| CLAW1
    CLM --> |SSH| CLAW2
    CLM --> |SSH| CLAW3
    CLM --> |reads| REGISTRY

    style CLM fill:#4a9eff,color:#fff
    style REGISTRY fill:#ff9f4a,color:#fff
```

### Host

A **Host** is any machine on your network that runs one or more claws. Clawrium connects to hosts via SSH using a dedicated management user (`xclm`).

**Characteristics:**
- Direct network access required (no ProxyJump support in v1)
- Per-host SSH keypair for security isolation
- Hardware capabilities detected automatically (CPU, GPU, memory)

### Claw

A **Claw** is an AI assistant instance. Each claw type (ZeroClaw, OpenClaw, NemoClaw, etc.) has its own configuration format, but Clawrium provides a normalized interface.

**Supported claws:**
- ZeroClaw
- OpenClaw
- NemoClaw
- NanoClaw
- IronClaw

### Registry

The **Registry** defines available claw types with their versions, dependencies, and installation templates. It's the source of truth for what can be deployed.

## Host Management Flow

```mermaid
sequenceDiagram
    participant User
    participant CLM as clm CLI
    participant Host as Target Host
    participant Config as ~/.config/clawrium/

    User->>CLM: clm host init hostname --user myuser
    CLM->>Config: Generate SSH keypair
    CLM->>Host: SSH as myuser (sudo)
    Host->>Host: Create xclm user
    Host->>Host: Configure passwordless sudo
    Host->>Host: Add public key
    CLM->>Config: Save host entry

    User->>CLM: clm host add hostname
    CLM->>Config: Read keypair
    CLM->>Host: SSH as xclm
    Host-->>CLM: Hardware capabilities
    CLM->>Config: Update hosts.json
```

**Steps:**

1. **Initialize** (`clm host init`): Generates per-host keypair, configures xclm user
2. **Add** (`clm host add`): Verifies connectivity, detects hardware, saves to config
3. **Manage**: List, check status, or remove hosts as needed

## Claw Installation Flow

```mermaid
sequenceDiagram
    participant User
    participant CLM as clm CLI
    participant Registry
    participant Host as Target Host

    User->>CLM: clm install zeroclaw --host myhost
    CLM->>Registry: Get ZeroClaw definition
    Registry-->>CLM: Version, dependencies, template
    CLM->>Host: SSH as xclm
    CLM->>Host: Install dependencies
    CLM->>Host: Create claw user
    CLM->>Host: Deploy configuration
    CLM->>Host: Start claw service
    Host-->>CLM: Claw running on port XXXX
```

**The installation process:**

1. Reads claw definition from registry
2. Installs system dependencies via Ansible
3. Creates unprivileged user for the claw instance
4. Deploys normalized configuration (translated to claw-native format)
5. Starts the claw as a systemd service

## Data Storage

All user data is stored locally in `~/.config/clawrium/`:

```
~/.config/clawrium/
├── hosts.json          # Host registry (0600 permissions)
├── secrets.json        # API keys and credentials (0600)
└── keys/
    └── <hostname>/
        ├── xclm_ed25519      # Private key (0600)
        └── xclm_ed25519.pub  # Public key
```

**Security notes:**
- Private keys are stored with `0600` permissions
- Each host has isolated keypairs (compromise of one doesn't affect others)
- Secrets are encrypted at rest (planned)

---
sidebar_position: 2
description: Clawrium system architecture, components, and data flows
keywords: [architecture, components, network topology, data flow, system design]
---

# Architecture

Clawrium manages AI assistant deployments across your network through three key concepts: **Hosts**, **Claws**, and the **Registry**.

![Clawrium architecture](/img/clawrium-architecture.png)

## Key Concepts

```mermaid
graph TB
    subgraph "Your Network"
        subgraph "Clawrium CLI"
            CLM[clawctl]
            CONFIG[~/.config/clawrium/]
        end

        subgraph "Host A"
            CLAW1[OpenClaw]
        end

        subgraph "Host B"
            CLAW2[OpenClaw]
        end
    end

    REGISTRY[(Registry)]

    CLM --> |manages| CONFIG
    CLM --> |SSH| CLAW1
    CLM --> |SSH| CLAW2
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

A **Claw** is an AI assistant instance. Today, Clawrium supports OpenClaw for end-to-end deployment and management.

**Current support:**
- OpenClaw

**Planned:**
- ZeroClaw and additional claw types

### Registry

The **Registry** defines available claw types with their versions, dependencies, and installation templates. It's the source of truth for what can be deployed.

## Host Management Flow

```mermaid
sequenceDiagram
    participant User
    participant CLM as clawctl CLI
    participant Host as Target Host
    participant Config as ~/.config/clawrium/

    User->>CLM: clawctl host create --bootstrap hostname --user myuser
    CLM->>Config: Generate SSH keypair
    CLM->>Host: SSH as myuser (sudo)
    Host->>Host: Create xclm user
    Host->>Host: Configure passwordless sudo
    Host->>Host: Add public key
    CLM->>Config: Save host entry

    User->>CLM: clawctl host create hostname
    CLM->>Config: Read keypair
    CLM->>Host: SSH as xclm
    Host-->>CLM: Hardware capabilities
    CLM->>Config: Update hosts.json
```

**Steps:**

1. **Initialize** (`clawctl host create --bootstrap`): Generates per-host keypair, configures xclm user
2. **Add** (`clawctl host create`): Verifies connectivity, detects hardware, saves to config
3. **Manage**: List, check status, or remove hosts as needed

## Claw Installation Flow

```mermaid
sequenceDiagram
    participant User
    participant CLM as clawctl CLI
    participant Registry
    participant Host as Target Host

    User->>CLM: clawctl agent create --type openclaw --host myhost
    CLM->>Registry: Get OpenClaw definition
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

## Network Topology

Clawrium operates on a flat network topology where the management station has direct SSH access to all hosts.

```mermaid
graph TB
    subgraph "Management Station"
        CLM[Clawrium CLI]
        CFG[~/.config/clawrium/]
        KEYS[SSH Keypairs]
    end

    subgraph "Local Network"
        switch[Network Switch]
        
        subgraph "Host Group A"
            H1[Host: 192.168.1.100<br/>pi-lab]
            H2[Host: 192.168.1.101<br/>nuc-01]
        end
        
        subgraph "Host Group B"
            H3[Host: 192.168.1.102<br/>dev-server]
        end
    end

    CLM --> CFG
    CFG --> KEYS
    CLM -->|SSH:22| switch
    switch --> H1
    switch --> H2
    switch --> H3

    style CLM fill:#0891b2,color:#fff
    style H1 fill:#22d3ee,color:#000
    style H2 fill:#22d3ee,color:#000
    style H3 fill:#22d3ee,color:#000
```

**Network Requirements:**
- Direct IP connectivity (no ProxyJump support in v1)
- SSH port 22 open on all hosts (or custom port with `--port`)
- Management station can reach all hosts

## Component Interaction

The following diagram shows how Clawrium components interact during typical operations.

```mermaid
flowchart LR
    subgraph "Clawrium"
        CLI[CLI Parser<br/>Typer]
        CORE[Core Logic]
        ANSIBLE[Ansible Runner]
        CONFIG[Config Manager]
    end

    subgraph "External"
        HOST[Remote Host]
        REGISTRY[(Claw Registry)]
    end

    CLI -->|commands| CORE
    CORE -->|read/write| CONFIG
    CORE -->|playbooks| ANSIBLE
    ANSIBLE -->|SSH| HOST
    CORE -->|fetch definitions| REGISTRY

    HOST -->|results| ANSIBLE
    ANSIBLE -->|status| CORE
    CORE -->|output| CLI

    style CLI fill:#0891b2,color:#fff
    style CORE fill:#0aa8cd,color:#fff
    style ANSIBLE fill:#077a97,color:#fff
    style CONFIG fill:#06657c,color:#fff
```

**Component Responsibilities:**

| Component | Responsibility |
|-----------|----------------|
| CLI Parser | Command parsing, argument validation, help text |
| Core Logic | Business logic, state management, orchestration |
| Ansible Runner | Executes playbooks on remote hosts |
| Config Manager | Reads/writes configuration files |
| Registry | Claw type definitions and templates |

## Data Flow

### Configuration to Deployment

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant Config
    participant Ansible
    participant Host

    User->>CLI: clawctl agent create --type zeroclaw --host pi-lab
    CLI->>Config: Load host info for pi-lab
    Config-->>CLI: SSH key, connection details
    CLI->>Ansible: Generate playbook
    Ansible->>Host: Connect via SSH
    Ansible->>Host: Install dependencies
    Ansible->>Host: Create user & deploy config
    Ansible->>Host: Start service
    Host-->>Ansible: Service running on port
    Ansible-->>CLI: Success
    CLI-->>User: Installation complete
```

### Secret Management Flow

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant Secrets
    participant Host

    User->>CLI: clawctl agent secret create API_KEY
    CLI->>CLI: Read value (hidden prompt)
    CLI->>Secrets: Store encrypted value
    User->>CLI: clawctl agent create --type zeroclaw
    CLI->>Secrets: Retrieve secrets
    Secrets-->>CLI: API_KEY value
    CLI->>Ansible: Inject into playbook
    Ansible->>Host: Deploy with secrets
```

## Security Model

### Principle of Least Privilege

Each component operates with minimal required permissions:

| Component | Privileges |
|-----------|------------|
| Clawrium CLI | User-level, reads/writes `~/.config/clawrium/` |
| xclm user | Passwordless sudo for specific commands |
| Claw instances | Unprivileged user, no sudo access |

### SSH Key Isolation

Each host has a dedicated SSH keypair:

```mermaid
graph LR
    subgraph "Management Station"
        K1[/Key for Host A/]
        K2[/Key for Host B/]
        K3[/Key for Host C/]
    end

    subgraph "Host A"
        A1[Authorized Keys]
    end
    subgraph "Host B"
        B1[Authorized Keys]
    end
    subgraph "Host C"
        C1[Authorized Keys]
    end

    K1 -->|only| A1
    K2 -->|only| B1
    K3 -->|only| C1

    style K1 fill:#0891b2,color:#fff
    style K2 fill:#0891b2,color:#fff
    style K3 fill:#0891b2,color:#fff
```

**Benefits:**
- Compromise of Host A's key doesn't affect Host B or C
- Easy key rotation per host
- Clear audit trail per connection

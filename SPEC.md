# Clawrium Technical Specification

## Overview

**Clawrium** — An aquarium for your claws.

CLI framework for managing AI Claw fleets (ZeroClaw, NemoClaw, OpenClaw) on local networks. Provides a unified abstraction over different claw implementations while handling hardware compatibility, agent configuration, and storage management.

### Problem Statement

Setting up a single Claw is straightforward. The problems start with:
- **Claw diversity** — ZeroClaw, NemoClaw, OpenClaw each have different configs, requirements, and formats
- **Hardware compatibility** — Not all claws run on all hardware (GPU requirements, architecture, etc.)
- **Agent portability** — Agent personas, objectives, tasks are locked to specific claw formats
- **Permission sprawl** — Each claw requests different filesystem/tool access
- **Fleet management** — Which machine runs what? What version? How to upgrade?

### Design Goals

1. **Claw-first workflow** — Pick what you want to run, then where
2. **Hardware validation** — Automatic compatibility checking before installation
3. **Unified agent config** — Normalize personas, objectives, tasks across claw types
4. **Minimal permissions** — Workspace-only access by default, explicit expansion
5. **Fleet visibility** — Health checks and status across all instances

### Target Users

1. Homelab enthusiasts running 2-5 machines with AI assistants
2. Startup engineers setting up local AI infrastructure
3. AI engineers who want to experiment with different claw implementations
4. Teams needing consistent agent configuration across different claw types

---

## Architecture

### Three-Layer Model (Top-Down)

```
┌─────────────────────────────────────────────────────────────┐
│                    Layer 1: CLI (clawrium)                  │
│                                                             │
│   User Interface — command parsing, interactive prompts,    │
│   progress display, error handling                          │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                 Layer 2: Claw Configuration                 │
│                                                             │
│   - Registry of supported claws (manifests, requirements)   │
│   - Normalized agent config (persona, objectives, tasks)    │
│   - Translation layer (normalize → claw-specific format)    │
│   - Storage configuration (permissions, workspace setup)    │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   Layer 3: Hardware/Host                    │
│                                                             │
│   - Host connection management (SSH, inventory)             │
│   - Hardware capability detection (GPU, arch, memory)       │
│   - Compatibility validation (claw requirements vs host)    │
│   - Installation execution (ansible-runner)                 │
└─────────────────────────────────────────────────────────────┘
```

### User Flow

```
1. Pick Claw          $ clm install
                      → Select claw type (zeroclaw, nemoclaw, openclaw)
                      → Select version
                           │
                           ▼
2. Pick Host          → Select target host from inventory
                      → Or add new host interactively
                           │
                           ▼
3. Validate           → Test SSH connection
                      → Detect hardware capabilities
                      → Check claw requirements vs host capabilities
                      → Report compatibility (✓ supported / ✗ unsupported)
                           │
                           ▼
4. Configure          → Name the instance
                      → Configure agent (persona, objectives, tasks)
                      → Set up storage (workspace-only by default)
                      → Configure secrets (API keys)
                           │
                           ▼
5. Install            → Execute installation via ansible-runner
                      → Stream progress
                      → Fail-fast on errors
```

### Framework Responsibilities

#### 1. Claw Registry
- Maintains manifests for each supported claw type
- Defines hardware requirements (GPU, memory, architecture)
- Defines dependencies (Rust, Node, Python, Postgres, etc.)
- Provides config templates for each claw

#### 2. Agent Normalization
The framework defines a **normalized agent schema** that works across all claws:

```yaml
# Normalized agent config (stored by clawrium)
agent:
  name: code-reviewer
  persona: "Senior engineer with focus on security"
  objectives:
    - "Review code for security vulnerabilities"
    - "Suggest performance improvements"
  tasks:
    - type: code_review
      scope: ["*.py", "*.js"]
  constraints:
    max_tokens: 4096
    temperature: 0.3
```

The framework translates this to claw-specific formats:
- ZeroClaw → `agents/<name>.md` + `config.toml` entries
- NemoClaw → `agent.yaml` configuration
- OpenClaw → `agent.json` configuration

#### 3. Storage Configuration
Follows minimum permissions approach:

| Level | Access | Use Case |
|-------|--------|----------|
| **workspace** (default) | Single project directory | Most common, safest |
| **home** | User's home directory | Multi-project work |
| **system** | Full filesystem | System administration |

Each claw implements storage differently:
- ZeroClaw: `allowed_dirs` in config.toml
- NemoClaw: Sandbox profiles
- OpenClaw: Permission manifest

#### 4. Hardware Compatibility
Detects and validates:
- CPU architecture (x86_64, arm64)
- GPU presence and type (NVIDIA, AMD, Apple Silicon)
- Available memory
- Disk space
- Network connectivity

### Differentiation from Individual Claws

| Aspect | Individual Claw | Clawrium |
|--------|----------------|----------|
| **Config format** | Claw-specific | Normalized, portable |
| **Hardware check** | Manual / trial-and-error | Automatic validation |
| **Agent portability** | Locked to claw format | Translatable across claws |
| **Permissions** | Claw default (often broad) | Minimal by default |
| **Multi-host** | Manual SSH | Fleet management |

---

## Directory Structure

### Project Structure (Repository)

```
clawrium/
├── src/clawrium/                # CLI application
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                   # Typer CLI entry point
│   ├── config.py                # Path helpers, config load/save
│   ├── models.py                # Pydantic models
│   ├── runner.py                # ansible-runner wrapper
│   ├── commands/                # CLI command modules
│   │   ├── install.py           # clm install (main flow)
│   │   ├── host.py              # clm host add/list/remove/status
│   │   └── secret.py            # clm secret set/list
│   └── services/
│       ├── registry.py          # Claw registry loader
│       ├── compatibility.py     # Hardware compatibility checker
│       ├── agent.py             # Agent config normalization
│       └── translator.py        # Normalize → claw-specific format
│
├── platform/
│   ├── registry/                # Claw type definitions
│   │   ├── zeroclaw/
│   │   │   ├── manifest.yml     # Requirements, dependencies
│   │   │   └── templates/       # Config templates
│   │   ├── nemoclaw/
│   │   └── openclaw/
│   │
│   ├── roles/                   # Ansible roles
│   │   ├── base/                # System dependencies
│   │   └── claw/                # Claw installation
│   │
│   └── playbooks/               # Ansible playbooks
│       ├── site.yml
│       ├── health-check.yml
│       └── cleanup.yml
│
├── tests/
└── pyproject.toml
```

### User Data Structure (~/.config/clawrium/)

```
~/.config/clawrium/
├── config.yml                   # Global config (version, defaults)
│
├── data/
│   ├── inventory.ini            # Generated Ansible inventory
│   ├── .secrets                 # Encrypted secrets (mode 600)
│   │
│   ├── hosts/                   # Host configurations
│   │   └── <host>/
│   │       ├── host.yml         # Host metadata, capabilities
│   │       └── claws/           # Claw instances on this host
│   │           └── <claw>.yml   # Instance config
│   │
│   └── agents/                  # Normalized agent definitions
│       └── <agent>.yml          # Portable agent config
│
└── artifacts/                   # Ansible run artifacts
```

---

## Configuration

### Claw Registry Manifest

Each claw type has a manifest defining its requirements:

```yaml
# platform/registry/zeroclaw/manifest.yml
name: zeroclaw
version: "0.5.2"
description: "Rust-based coding assistant"

source:
  type: cargo
  repo: https://github.com/zeroclaw-labs/zeroclaw
  crate: zeroclaw
  features: [memory-postgres]

requirements:
  hardware:
    architecture: [x86_64, aarch64]
    gpu: optional                    # Not required but can use
    min_memory_gb: 4
    min_disk_gb: 10

  system:
    packages: [build-essential, libssl-dev, pkg-config, curl, git]
    rust: "1.75"
    postgres:
      required: true
      extensions: [pgvector]

  user:
    node: null
    python: null

config:
  format: toml
  template: config.toml.j2

storage:
  default: workspace
  supported: [workspace, home, system]
  config_key: allowed_dirs

agent:
  format: markdown
  directory: agents/
  template: agent.md.j2
```

### Normalized Agent Configuration

Agents are defined in a portable format:

```yaml
# ~/.config/clawrium/data/agents/code-reviewer.yml
name: code-reviewer
version: "1.0.0"

persona: |
  You are a senior software engineer with 15 years of experience.
  Focus on security, performance, and maintainability.
  Be direct and concise in feedback.

objectives:
  - Review code for security vulnerabilities
  - Identify performance bottlenecks
  - Suggest maintainability improvements
  - Ensure consistent code style

tasks:
  - name: security_review
    description: "Scan for OWASP Top 10 vulnerabilities"
    scope: ["*.py", "*.js", "*.ts"]

  - name: performance_review
    description: "Identify N+1 queries, memory leaks"
    scope: ["*.py", "*.go"]

constraints:
  max_tokens: 4096
  temperature: 0.3

model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

### Claw Instance Configuration

```yaml
# ~/.config/clawrium/data/hosts/wolf/claws/espresso.yml
name: espresso
type: zeroclaw
version: "0.5.2"

# Networking
gateway_port: 8080
health_port: 8081

# Agent assignment (references normalized agent)
agents:
  - code-reviewer
  - quick-tasks

# Storage (minimal permissions by default)
storage:
  level: workspace
  paths:
    - /home/espresso/projects

# Model providers
providers:
  openrouter:
    api_key_ref: ESPRESSO_OPENROUTER_API_KEY
  local:
    base_url: http://192.168.1.17:11434/v1
    model: llama3.2:latest

# Database
database:
  name: zc_espresso
  user: espresso
```

### Host Configuration

```yaml
# ~/.config/clawrium/data/hosts/wolf/host.yml
name: wolf
ip: 192.168.1.10
user: admin
port: 22

# Detected capabilities (populated by clm)
capabilities:
  architecture: x86_64
  gpu: null
  memory_gb: 16
  disk_gb: 256

# Installed claws
claws:
  - espresso
  - mocha
```

### Generated Inventory

```ini
# ~/.config/clawrium/data/inventory.ini (auto-generated)
[clawrium]
wolf ansible_host=192.168.1.10 ansible_user=admin ansible_port=22
kevin ansible_host=192.168.1.15 ansible_user=pi ansible_port=22
```

---

## Workflows

### Primary Flow: Install a Claw

```bash
$ clm install

? Select claw type:
  ❯ zeroclaw (0.5.2) - Rust-based coding assistant
    nemoclaw (1.2.0) - NVIDIA secured sandbox
    openclaw (0.8.1) - Open-source multi-modal

? Select target host:
  ❯ wolf (192.168.1.10) - Intel i7, 16GB RAM
    kevin (192.168.1.15) - Raspberry Pi 5
    [+] Add new host...

Connecting to wolf...
  ✓ SSH connection established
  ✓ Detecting hardware capabilities...

Hardware Capabilities:
  Architecture: x86_64
  GPU: None
  Memory: 16 GB
  Disk: 256 GB available

Checking compatibility with zeroclaw...
  ✓ Architecture supported (x86_64)
  ✓ Memory sufficient (16 GB >= 4 GB required)
  ✓ Disk sufficient (256 GB >= 10 GB required)
  ⚠ No GPU (optional, will use CPU inference)

? Instance name: espresso

? Configure agent:
  ❯ Create new agent
    Use existing: code-reviewer
    Use existing: quick-tasks
    Skip for now

? Storage access level:
  ❯ workspace (single directory, recommended)
    home (user's home directory)
    system (full filesystem)

? Workspace path: /home/espresso/projects

? Set secrets:
  OPENROUTER_API_KEY: ****

Installing zeroclaw on wolf as 'espresso'...
  [base] Installing system packages... ✓
  [base] Setting up Rust 1.75... ✓
  [base] Setting up PostgreSQL... ✓
  [espresso] Creating user... ✓
  [espresso] Installing zeroclaw 0.5.2... ✓
  [espresso] Configuring storage... ✓
  [espresso] Starting service... ✓

✓ Installation complete!
  Gateway: http://192.168.1.10:8080
  Health:  http://192.168.1.10:8081/health
```

### Add Host (Pre-requisite)

```bash
$ clm host add

? Host name: wolf
? IP address: 192.168.1.10
? SSH user: admin
? SSH port (22): 22

Testing connection...
  ✓ SSH connection established

Detecting capabilities...
  Architecture: x86_64
  GPU: None
  Memory: 16 GB
  Disk: 256 GB

✓ Host 'wolf' added
```

### Define Agent (Portable)

```bash
$ clm agent create

? Agent name: code-reviewer
? Persona (brief description):
  Senior engineer focusing on security and performance

? Objectives (one per line, empty to finish):
  Review code for security vulnerabilities
  Identify performance bottlenecks
  Suggest maintainability improvements

? Temperature (0.0-1.0): 0.3
? Max tokens: 4096

✓ Agent 'code-reviewer' created at ~/.config/clawrium/data/agents/code-reviewer.yml

This agent can be assigned to any claw instance.
```

### Assign Agent to Instance

```bash
$ clm claw agent add wolf/espresso code-reviewer

Translating agent 'code-reviewer' for zeroclaw...
  ✓ Generated agents/code-reviewer.md
  ✓ Updated config.toml

Restarting espresso...
  ✓ Service restarted

✓ Agent 'code-reviewer' added to wolf/espresso
```

### Fleet Status

```bash
$ clm status

FLEET STATUS
============

wolf (192.168.1.10)
├── espresso (zeroclaw 0.5.2)
│   ├── Status: running
│   ├── Gateway: :8080
│   ├── Agents: code-reviewer, quick-tasks
│   └── Storage: workspace (/home/espresso/projects)
│
└── mocha (zeroclaw 0.5.2)
    ├── Status: running
    ├── Gateway: :8090
    └── Agents: none

kevin (192.168.1.15)
└── kevin (openclaw 0.8.1)
    ├── Status: stopped
    └── Storage: workspace (/home/pi/work)
```

### Upgrade Instance

```bash
$ clm claw upgrade wolf/espresso

Current: zeroclaw 0.5.2
Available: zeroclaw 0.6.0

? Proceed with upgrade? Yes

Upgrading wolf/espresso...
  [espresso] Backing up config... ✓
  [espresso] Stopping service... ✓
  [espresso] Installing zeroclaw 0.6.0... ✓
  [espresso] Starting service... ✓
  [espresso] Health check... ✓

✓ Upgraded to zeroclaw 0.6.0
```

---

## Security Considerations

### 1. Storage Permissions (Minimal by Default)

```
┌─────────────────────────────────────────────────────────────┐
│                    Permission Levels                        │
├─────────────────────────────────────────────────────────────┤
│  workspace    Most restrictive. Single project directory.  │
│               Claw can only read/write within this path.   │
│               DEFAULT for all new installations.           │
├─────────────────────────────────────────────────────────────┤
│  home         User's home directory access.                │
│               For multi-project workflows.                  │
│               Requires explicit user confirmation.          │
├─────────────────────────────────────────────────────────────┤
│  system       Full filesystem access.                       │
│               For system administration tasks.              │
│               Requires explicit warning acknowledgment.     │
└─────────────────────────────────────────────────────────────┘
```

Each claw implements permissions differently:
- **ZeroClaw**: `allowed_dirs` array in config.toml
- **NemoClaw**: Sandbox profile with bind mounts
- **OpenClaw**: Permission manifest JSON

### 2. Secrets Management
- Secrets stored in `~/.config/clawrium/data/.secrets` (mode 600)
- Namespaced: `HOST_CLAW_KEY=value` format
- Injected at deploy time, never in configs
- Never logged or displayed

### 3. SSH Access
- SSH keys only (no password auth)
- Dedicated user per claw instance
- Minimal sudo grants (service management only)

### 4. Network
- Gateway ports bound to local network interfaces
- Firewall rules recommended for multi-user hosts

---

## Trade-offs

| Consideration | Impact |
|---------------|--------|
| **Claw abstraction** | Some claw-specific features may not be exposed through normalized config |
| **Agent translation** | Translated agents may lose claw-specific capabilities |
| **Workspace-only default** | May need manual expansion for some use cases |
| **Hardware detection** | Limited to SSH-accessible information |
| **Learning curve** | New mental model (claw-first vs host-first) |

---

## Implementation Roadmap

### Phase 1: Core Framework
- [x] Create repository
- [ ] Project scaffolding (Typer CLI, Pydantic models)
- [ ] Config module (paths, load/save)
- [ ] `clm init` command

### Phase 2: Host Layer
- [ ] `clm host add` (interactive, SSH test, capability detection)
- [ ] `clm host list/status/remove`
- [ ] Hardware capability detection
- [ ] Inventory generation

### Phase 3: Registry & Compatibility
- [ ] Claw registry structure (manifests, templates)
- [ ] ZeroClaw manifest
- [ ] NemoClaw manifest
- [ ] OpenClaw manifest
- [ ] Compatibility checker (requirements vs capabilities)

### Phase 4: Agent Normalization
- [ ] Normalized agent schema
- [ ] `clm agent create/list/edit`
- [ ] Translator: normalized → zeroclaw
- [ ] Translator: normalized → nemoclaw
- [ ] Translator: normalized → openclaw

### Phase 5: Storage Configuration
- [ ] Storage level abstraction
- [ ] ZeroClaw storage config
- [ ] NemoClaw sandbox profiles
- [ ] OpenClaw permission manifest

### Phase 6: Installation Flow
- [ ] `clm install` command (main flow)
- [ ] Ansible roles (base, claw)
- [ ] ansible-runner integration
- [ ] Progress streaming

### Phase 7: Operations
- [ ] `clm claw upgrade`
- [ ] `clm status` (fleet view)
- [ ] Health check playbook

---

## References

- [ZeroClaw Documentation](https://github.com/zeroclaw-labs/zeroclaw)
- [NemoClaw (NVIDIA)](https://developer.nvidia.com/nemoclaw)
- [OpenClaw](https://github.com/openclaw/openclaw)
- [Ansible Documentation](https://docs.ansible.com/)

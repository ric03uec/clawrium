# Clawrium Implementation Plan

## Version: 26.3.0

## Overview

Clawrium is a CLI tool (`clm`) for managing AI Claw fleets (ZeroClaw, NemoClaw, OpenClaw) on local networks. It provides:

1. **Claw-first workflow** — Pick what to run, then where to run it
2. **Hardware compatibility checking** — Validate before installation
3. **Normalized agent configuration** — Portable across claw types
4. **Minimal permissions** — Workspace-only storage by default

**Philosophy:** Users interact only via CLI. Infrastructure complexity is hidden.

---

## Architecture Summary

### Three-Layer Model (Top-Down)

```
┌─────────────────────────────────────────────────────────────┐
│              LAYER 1: CLI (clawrium)                        │
│                                                             │
│   src/clawrium/cli.py                                       │
│   - User interface, prompts, progress display               │
│   - Commands: init, install, host, agent, claw, secret      │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           LAYER 2: Claw Configuration                       │
│                                                             │
│   src/clawrium/services/                                    │
│   - registry.py      → Claw manifests, requirements         │
│   - agent.py         → Normalized agent schema               │
│   - translator.py    → Normalize ↔ claw-specific format     │
│   - storage.py       → Permission levels, workspace config  │
│                                                             │
│   platform/registry/                                        │
│   - zeroclaw/, nemoclaw/, openclaw/                         │
│   - manifest.yml + templates/                               │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│            LAYER 3: Hardware/Host                           │
│                                                             │
│   src/clawrium/services/                                    │
│   - compatibility.py → Hardware detection, validation       │
│                                                             │
│   src/clawrium/runner.py                                    │
│   - ansible-runner wrapper                                  │
│   - SSH connection, execution, progress                     │
│                                                             │
│   platform/roles/ + playbooks/                              │
│   - base (system deps), claw (installation)                 │
└─────────────────────────────────────────────────────────────┘
```

### User Flow

```
  $ clm install
        │
        ▼
┌───────────────────┐
│ 1. Pick Claw      │ → Select type (zeroclaw/nemoclaw/openclaw)
│                   │ → Select version
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 2. Pick Host      │ → Select from inventory or add new
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 3. Validate       │ → Test SSH connection
│                   │ → Detect hardware capabilities
│                   │ → Check claw requirements vs capabilities
│                   │ → Report: ✓ supported / ✗ unsupported
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 4. Configure      │ → Name the instance
│                   │ → Configure agents (normalized schema)
│                   │ → Set storage level (workspace by default)
│                   │ → Set secrets
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 5. Install        │ → Execute via ansible-runner
│                   │ → Stream progress
│                   │ → Fail-fast on errors
└───────────────────┘
```

---

## Phase 1: Project Scaffolding

**Goal:** Set up project structure, packaging, and basic CLI skeleton.

### Tasks

- [ ] **1.1** Create directory structure
  ```
  clawrium/
  ├── src/clawrium/
  │   ├── __init__.py
  │   ├── __main__.py
  │   ├── cli.py
  │   ├── config.py
  │   ├── models.py
  │   ├── commands/
  │   │   ├── __init__.py
  │   │   ├── install.py
  │   │   ├── host.py
  │   │   ├── agent.py
  │   │   ├── claw.py
  │   │   └── secret.py
  │   └── services/
  │       ├── __init__.py
  │       ├── registry.py
  │       ├── compatibility.py
  │       ├── agent.py
  │       ├── translator.py
  │       └── storage.py
  ├── platform/
  │   ├── registry/
  │   │   ├── zeroclaw/
  │   │   ├── nemoclaw/
  │   │   └── openclaw/
  │   ├── roles/
  │   └── playbooks/
  ├── tests/
  │   └── conftest.py
  └── pyproject.toml
  ```

- [ ] **1.2** Create `pyproject.toml` with dependencies
  - typer >= 0.9.0
  - rich >= 13.0.0
  - pydantic >= 2.0.0
  - ansible-runner >= 2.3.0
  - pyyaml >= 6.0

- [ ] **1.3** Create basic CLI skeleton with Typer
  - Main app with version flag
  - Command groups: `install`, `host`, `agent`, `claw`, `secret`, `status`
  - Placeholder commands

- [ ] **1.4** Create Pydantic models
  - `Host`: name, ip, user, port, capabilities, claws list
  - `ClawInstance`: name, type, version, gateway_port, agents, storage
  - `Agent`: name, persona, objectives, tasks, constraints
  - `ClawManifest`: name, version, requirements, config format
  - `Capabilities`: architecture, gpu, memory_gb, disk_gb

- [ ] **1.5** Create config module
  - `CLAWRIUM_HOME = ~/.config/clawrium/`
  - Path helpers: data, hosts, agents, artifacts
  - Config load/save functions

- [ ] **1.6** Verify installation works
  ```bash
  uv pip install -e .
  clm --version
  clm --help
  ```

### Deliverables
- Working `clm --version` and `clm --help`
- Project installable via `uv pip install -e .`

### Tests
- `test_cli.py`: CLI loads, version displays

---

## Phase 2: `clm init` Command

**Goal:** Initialize Clawrium configuration directory and check dependencies.

### Tasks

- [ ] **2.1** Implement `clm init` command
  - Create `~/.config/clawrium/` directory structure
  - Create initial `config.yml`
  - Check Python version (>= 3.11)
  - Check Ansible installed (>= 2.15)
  - Check ansible-runner installed
  - Display missing dependencies with install instructions

- [ ] **2.2** Directory structure creation
  ```
  ~/.config/clawrium/
  ├── config.yml
  ├── data/
  │   ├── hosts/
  │   ├── agents/        # Normalized agent definitions
  │   ├── inventory.ini
  │   └── .secrets
  └── artifacts/
  ```

- [ ] **2.3** Config file initialization
  ```yaml
  version: "26.3.0"
  created_at: "2026-03-17T10:00:00Z"
  defaults:
    storage_level: workspace
  ```

- [ ] **2.4** Dependency check output
  ```
  Checking dependencies:
    ✓ Python 3.11+
    ✗ Ansible 2.15+ (not found)

  Install missing: pip install ansible>=2.15
  ```

### Deliverables
- `clm init` creates directory structure
- Dependency check with clear instructions

### Tests
- `test_init.py`:
  - Init creates correct directories (including agents/)
  - Init is idempotent (running twice doesn't break)
  - Dependency check reports missing deps
  - Config file created with correct version and defaults

---

## Phase 3: Host Management (Layer 3)

**Goal:** Add, list, remove hosts with hardware capability detection.

### Tasks

- [ ] **3.1** Implement `clm host add`
  - Interactive prompts: name, IP, user, port
  - Validate IP format
  - **Test SSH connection**
  - **Detect hardware capabilities** (via Ansible facts):
    - architecture (x86_64, aarch64)
    - gpu (nvidia, amd, apple, none)
    - memory_gb
    - disk_gb
  - Create `data/hosts/<name>/host.yml` with capabilities
  - Create `data/hosts/<name>/claws/` directory
  - Regenerate `data/inventory.ini`

- [ ] **3.2** Implement capability detection module
  - `src/clawrium/services/compatibility.py`
  - SSH to host, gather Ansible facts
  - Detect GPU: check `/proc/driver/nvidia`, `lspci`, etc.
  - Return `Capabilities` model

- [ ] **3.3** Implement `clm host list`
  - Read all hosts from `data/hosts/`
  - Display table: NAME, IP, ARCH, GPU, MEM, CLAWS count

- [ ] **3.4** Implement `clm host remove <host>`
  - Check if host exists
  - Warn if claws configured (show list)
  - On confirmation (`--yes` flag or interactive):
    - Run cleanup playbook (stop services, uninstall, delete users/dbs)
    - Delete secrets matching `HOST_*` pattern
    - Remove `data/hosts/<host>/` directory
    - Regenerate inventory

- [ ] **3.5** Implement `clm host status [host]`
  - If no host specified: show all hosts summary
  - Use Ansible `ping` module to check SSH
  - Use Ansible `systemd` module to check service status
  - Display table with SSH status, claw services, health

- [ ] **3.6** Inventory generation
  - Generate `data/inventory.ini` from hosts
  - Only called by `host add` and `host remove`

### Deliverables
- Full host CRUD operations
- Hardware capability detection
- Health status via Ansible

### Tests
- `test_host.py`:
  - Add host creates correct files with capabilities
  - List shows all hosts with hardware info
  - Status checks SSH connectivity
- `test_capability.py`:
  - Capability detection parses Ansible facts
  - GPU detection works for nvidia/amd/none
  - Memory/disk parsed correctly

---

## Phase 4: Claw Registry & Compatibility (Layer 2)

**Goal:** Create claw registry with manifests and implement compatibility checking.

### Tasks

- [ ] **4.1** Create ZeroClaw registry
  - `platform/registry/zeroclaw/manifest.yml`
  - Define requirements:
    - architecture: [x86_64, aarch64]
    - gpu: optional
    - min_memory_gb: 4
    - min_disk_gb: 10
  - Define dependencies: rust, postgres
  - `platform/registry/zeroclaw/templates/config.toml.j2`
  - `platform/registry/zeroclaw/templates/systemd.service.j2`

- [ ] **4.2** Create NemoClaw registry
  - `platform/registry/nemoclaw/manifest.yml`
  - Define requirements:
    - architecture: [x86_64]
    - gpu: required (nvidia)
    - min_memory_gb: 16
  - `platform/registry/nemoclaw/templates/`

- [ ] **4.3** Create OpenClaw registry
  - `platform/registry/openclaw/manifest.yml`
  - Define requirements:
    - architecture: [x86_64, aarch64]
    - gpu: optional
    - min_memory_gb: 2
  - `platform/registry/openclaw/templates/`

- [ ] **4.4** Implement registry loader
  - `src/clawrium/services/registry.py`
  - Load all manifests from `platform/registry/`
  - Parse into `ClawManifest` models
  - List available claws with versions

- [ ] **4.5** Implement compatibility checker
  - `src/clawrium/services/compatibility.py`
  - `check_compatibility(manifest: ClawManifest, capabilities: Capabilities) -> CompatibilityResult`
  - Return: supported (bool), warnings (list), errors (list)
  - Example warnings: "No GPU (optional, will use CPU inference)"
  - Example errors: "Architecture aarch64 not supported by nemoclaw"

- [ ] **4.6** Implement `clm registry list`
  - Show available claw types with versions
  - Show requirements summary

### Deliverables
- Complete registry for 3 claw types
- Compatibility checking against host capabilities
- Registry listing command

### Tests
- `test_registry.py`:
  - All manifests load correctly
  - Manifest schema validation
  - Templates render without error
- `test_compatibility.py`:
  - zeroclaw compatible with x86_64 no-GPU host
  - nemoclaw incompatible with no-GPU host
  - nemoclaw incompatible with aarch64
  - Warnings generated for optional missing features

---

## Phase 5: Agent Normalization (Layer 2)

**Goal:** Create portable agent definitions that work across all claw types.

### Tasks

- [ ] **5.1** Define normalized agent schema
  - `src/clawrium/models.py` - `Agent` model
  ```yaml
  name: string
  version: string
  persona: string (multi-line)
  objectives: list[string]
  tasks:
    - name: string
      description: string
      scope: list[string]  # file patterns
  constraints:
    max_tokens: int
    temperature: float
  model:
    provider: string
    model: string
  ```

- [ ] **5.2** Implement `clm agent create`
  - Interactive prompts for each field
  - Save to `~/.config/clawrium/data/agents/<name>.yml`

- [ ] **5.3** Implement `clm agent list`
  - Show all agents with summary

- [ ] **5.4** Implement `clm agent edit <name>`
  - Open in `$EDITOR`
  - Validate schema after edit

- [ ] **5.5** Implement agent translators
  - `src/clawrium/services/translator.py`
  - `translate_to_zeroclaw(agent: Agent) -> dict` → agents/<name>.md format
  - `translate_to_nemoclaw(agent: Agent) -> dict` → agent.yaml format
  - `translate_to_openclaw(agent: Agent) -> dict` → agent.json format

- [ ] **5.6** Create agent templates for each claw
  - `platform/registry/zeroclaw/templates/agent.md.j2`
  - `platform/registry/nemoclaw/templates/agent.yaml.j2`
  - `platform/registry/openclaw/templates/agent.json.j2`

### Deliverables
- Normalized agent schema
- Agent CRUD commands
- Translation to each claw format

### Tests
- `test_agent.py`:
  - Create agent saves valid YAML
  - List shows all agents
  - Edit validates schema
- `test_translator.py`:
  - Translate to zeroclaw produces valid markdown
  - Translate to nemoclaw produces valid YAML
  - All fields are preserved in translation

---

## Phase 6: Storage Configuration (Layer 2)

**Goal:** Implement minimal-permissions storage access for claws.

### Tasks

- [ ] **6.1** Define storage levels
  - `src/clawrium/services/storage.py`
  - Levels: `workspace` (default), `home`, `system`
  - Each level maps to specific paths

- [ ] **6.2** Implement storage configuration per claw
  - ZeroClaw: `allowed_dirs` in config.toml
  - NemoClaw: sandbox profile with bind mounts
  - OpenClaw: permission manifest JSON

- [ ] **6.3** Create storage templates
  - `platform/registry/zeroclaw/templates/storage.toml.j2`
  - `platform/registry/nemoclaw/templates/sandbox.yaml.j2`
  - `platform/registry/openclaw/templates/permissions.json.j2`

- [ ] **6.4** Implement storage prompts in install flow
  - Default to `workspace`
  - Prompt for workspace path
  - Warn if selecting `home` or `system`

### Deliverables
- Storage level abstraction
- Per-claw storage configuration
- Warning system for elevated permissions

### Tests
- `test_storage.py`:
  - Workspace config limits to single directory
  - Home config includes home directory
  - System config has full access
  - Warnings generated for non-workspace levels

---

## Phase 7: Secrets Management

**Goal:** Manage secrets for claws.

### Tasks

- [ ] **7.1** Implement `clm secret set <host>.<claw>.<KEY> <value>`
  - Parse key format: `wolf.espresso.OPENROUTER_API_KEY`
  - Store as `WOLF_ESPRESSO_OPENROUTER_API_KEY=<value>` in `.secrets`
  - Set file permissions to 600

- [ ] **7.2** Implement `clm secret list [--host <host>]`
  - Read `.secrets` file
  - Display keys only (not values)
  - Optional filter by host

- [ ] **7.3** Secrets file format
  ```bash
  # ~/.config/clawrium/data/.secrets
  WOLF_ESPRESSO_OPENROUTER_API_KEY=sk-or-v1-xxx
  WOLF_FORTRESS_NVIDIA_API_KEY=nvapi-xxx
  ```

- [ ] **7.4** Secret loading for deployment
  - Parse `.secrets` file
  - Filter by host/claw
  - Pass to Ansible as environment variables

### Deliverables
- Secure secrets storage
- CLI for secret management

### Tests
- `test_secret.py`:
  - Set creates/updates secret
  - Set validates host.claw.KEY format
  - List shows keys without values
  - Secrets file has correct permissions (600)

---

## Phase 8: Ansible Platform - Roles (Layer 3)

**Goal:** Create Ansible roles for base setup and claw deployment.

### Tasks

- [ ] **8.1** Create `base` role
  - `platform/roles/base/tasks/main.yml` - orchestrator
  - `platform/roles/base/tasks/packages.yml` - system packages
  - `platform/roles/base/tasks/rust.yml` - Rust to /opt/rust
  - `platform/roles/base/tasks/golang.yml` - Go to /opt/go
  - `platform/roles/base/tasks/postgres.yml` - PostgreSQL + extensions
  - `platform/roles/base/defaults/main.yml` - default variables

- [ ] **8.2** Create `claw` role
  - `platform/roles/claw/tasks/main.yml` - orchestrator
  - `platform/roles/claw/tasks/user.yml` - create system user
  - `platform/roles/claw/tasks/deps.yml` - install claw-specific deps (node, python)
  - `platform/roles/claw/tasks/install.yml` - install binary (cargo/binary/npm)
  - `platform/roles/claw/tasks/database.yml` - create database and user
  - `platform/roles/claw/tasks/configure.yml` - render config, agents, storage
  - `platform/roles/claw/defaults/main.yml` - default variables

- [ ] **8.3** Create playbooks
  - `platform/playbooks/site.yml` - full deployment (base + claws)
  - `platform/playbooks/health-check.yml` - check service status
  - `platform/playbooks/cleanup.yml` - stop, uninstall, delete

- [ ] **8.4** Role logic
  - Base role aggregates system deps from all claws on host
  - Claw role reads manifest from registry
  - Claw role renders translated agent configs
  - Claw role configures storage per claw type
  - Fail-fast: `any_errors_fatal: true`

### Deliverables
- Working Ansible roles
- Playbooks for deploy, health-check, cleanup

### Tests
- Manual testing against local VM
- `test_roles.py` (integration):
  - Site playbook syntax check
  - Role variable defaults correct

---

## Phase 9: ansible-runner Integration (Layer 3)

**Goal:** Wrap Ansible execution with proper event handling.

### Tasks

- [ ] **9.1** Create `runner.py` module
  - `ClawriumRunner` class
  - Configure `private_data_dir` paths
  - Load secrets as environment variables

- [ ] **9.2** Implement `deploy()` method
  - Call `ansible_runner.run()` with site.yml
  - Stream events for progress output
  - Handle status: successful, failed, timeout
  - Return result with details

- [ ] **9.3** Implement `health_check()` method
  - Call health-check.yml
  - Parse service status from results
  - Return structured status

- [ ] **9.4** Implement `cleanup()` method
  - Call cleanup.yml for host/claw removal
  - Handle partial failures

- [ ] **9.5** Event handling for CLI output
  - Progress callback for real-time output
  - Format task names and status
  - Show errors clearly

### Deliverables
- Working ansible-runner wrapper
- Real-time CLI output during operations

### Tests
- `test_runner.py`:
  - Runner initializes with correct paths
  - Deploy calls correct playbook
  - Events are processed
  - Failures are reported

---

## Phase 10: Install Command (Main Flow)

**Goal:** Full claw-first installation flow via CLI.

### Tasks

- [ ] **10.1** Implement `clm install` (main interactive flow)
  1. **Pick Claw**: List registry, prompt selection
  2. **Pick Host**: List hosts, prompt selection (or add new)
  3. **Validate**: Test SSH, detect capabilities, check compatibility
  4. **Configure**: Name instance, assign agents, set storage, set secrets
  5. **Install**: Execute via ansible-runner with progress

- [ ] **10.2** Progress output
  ```
  Installing zeroclaw on wolf as 'espresso'...

  [base] Installing system packages... ✓
  [base] Setting up Rust 1.75... ✓
  [espresso] Creating user... ✓
  [espresso] Installing zeroclaw 0.5.2... ✗ FAILED

  Error: cargo install failed
    Exit code: 101

  Installation stopped.
  ```

- [ ] **10.3** Fail-fast behavior
  - Ansible `any_errors_fatal: true`
  - CLI stops on first error
  - Clear error message with context

- [ ] **10.4** Implement `clm claw agent add <host>/<claw> <agent>`
  - Translate agent to claw format
  - Update claw config
  - Restart service

- [ ] **10.5** Implement `clm status`
  - Fleet-wide status view
  - Show all hosts, claws, agents, storage levels

### Deliverables
- Working install command (claw-first flow)
- Agent assignment command
- Fleet status view
- Real-time progress output
- Fail-fast with clear errors

### Tests
- `test_install.py`:
  - Install validates compatibility before proceeding
  - Install fails on incompatible host
  - Install streams progress
  - Install stops on failure

---

## Phase 11: Testing & Documentation

**Goal:** Comprehensive tests and user documentation.

### Tasks

- [ ] **11.1** Unit tests
  - All commands tested
  - Config load/save tested
  - Models validated
  - Translators tested
  - Compatibility checker tested

- [ ] **11.2** Integration tests
  - Full flow: init → host add → install (claw-first)
  - Agent flow: agent create → claw agent add
  - Cleanup flow: claw remove → host remove
  - Use mock Ansible or local VM

- [ ] **11.3** Update README.md
  - Installation instructions (uvx)
  - Quick start guide (claw-first workflow)
  - Command reference

- [ ] **11.4** Update SPEC.md
  - Three-layer architecture
  - Agent normalization
  - Storage configuration
  - Registry format

- [ ] **11.5** Add examples
  - `examples/single-host/` - minimal setup
  - `examples/multi-claw/` - multiple claws on one host
  - `examples/portable-agent/` - agent definition used across claws

### Deliverables
- >80% test coverage
- Complete documentation
- Working examples

---

## Phase Summary

| Phase | Layer | Description |
|-------|-------|-------------|
| 1 | CLI | Project Scaffolding |
| 2 | CLI | `clm init` Command |
| 3 | Host | Host Management + Capability Detection |
| 4 | Config | Claw Registry + Compatibility |
| 5 | Config | Agent Normalization + Translation |
| 6 | Config | Storage Configuration |
| 7 | CLI | Secrets Management |
| 8 | Host | Ansible Roles + Playbooks |
| 9 | Host | ansible-runner Integration |
| 10 | CLI | Install Command (Main Flow) |
| 11 | - | Testing & Documentation |

---

## Dependencies Between Phases

```
                    Phase 1 (Scaffolding)
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
        Phase 2       Phase 3       Phase 4
        (init)        (host +       (registry +
                      capability)   compatibility)
              │            │            │
              │            │            ├────┐
              │            │            │    │
              │            │            ▼    │
              │            │       Phase 5   │
              │            │       (agent)   │
              │            │            │    │
              │            │            ▼    │
              │            │       Phase 6   │
              │            │       (storage) │
              │            │            │    │
              ▼            │            │    │
        Phase 7            │            │    │
        (secrets)          │            │    │
              │            │            │    │
              │            ▼            ▼    ▼
              │       Phase 8      Phase 8 uses
              │       (roles)      manifests
              │            │
              │            ▼
              └──────► Phase 9
                      (runner)
                           │
                           ▼
                      Phase 10
                      (install flow)
                           │
                           ▼
                      Phase 11
                      (testing/docs)
```

**Layer Key:**
- **CLI (Layer 1)**: User interface, commands
- **Config (Layer 2)**: Registry, agents, storage, translation
- **Host (Layer 3)**: Hardware, Ansible, execution

---

## Success Criteria

### MVP (v26.3.0)

**Core Flow (Claw-First)**
- [ ] `clm install` works end-to-end:
  - Pick claw → Pick host → Validate → Configure → Install
- [ ] Hardware capability detection works (arch, gpu, memory, disk)
- [ ] Compatibility checking prevents invalid installations
- [ ] Installation fails fast with clear errors

**Agent Normalization**
- [ ] Can create/list/edit normalized agents
- [ ] Agents translate correctly to zeroclaw format
- [ ] Agents can be assigned to claw instances

**Storage Configuration**
- [ ] Default to workspace-only permissions
- [ ] Warn when expanding to home/system
- [ ] Storage configured correctly per claw type

**Supporting Commands**
- [ ] `clm init` creates directory structure
- [ ] `clm host add/list/remove/status` work
- [ ] `clm secret set/list` work
- [ ] `clm status` shows fleet view

### Quality Gates
- All tests pass
- No hardcoded paths (use config module)
- Secrets never logged or displayed
- CLI has consistent output format
- Errors are user-friendly
- Agents portable across claw types
- Storage defaults to minimal permissions

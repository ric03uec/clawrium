# Roadmap: Clawrium

## Overview

Clawrium v1 delivers a CLI tool for managing OpenClaw instances on single Ubuntu hosts. The journey progresses from foundation setup through host management, registry and compatibility checking, secrets handling, and culminates in the full installation flow with fleet status visibility. Each phase delivers complete, verifiable capabilities that build toward the core value: managing AI assistants from one place with consistent configuration and security practices.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation Setup** - Initialize Clawrium configuration and verify dependencies
- [ ] **Phase 2: Host Management** - Add, list, remove hosts with hardware capability detection
- [ ] **Phase 3: Registry & Compatibility** - Load claw manifests and validate hardware compatibility
- [ ] **Phase 4: Secrets Management** - Secure storage and retrieval of API keys and credentials
- [ ] **Phase 5: Installation & Fleet Status** - Install OpenClaw instances and view fleet status

## Phase Details

### Phase 1: Foundation Setup
**Goal**: Users can initialize Clawrium and verify all dependencies are met
**Depends on**: Nothing (first phase)
**Requirements**: INIT-01, INIT-02
**Success Criteria** (what must be TRUE):
  1. User runs `clm init` and configuration directory is created at ~/.config/clawrium/
  2. User sees clear status of all dependencies (Python, Ansible, ansible-runner)
  3. User receives actionable install instructions for any missing dependencies
**Plans**: TBD

Plans:
- [ ] 01-01: TBD

### Phase 2: Host Management
**Goal**: Users can manage hosts with automatic hardware capability detection
**Depends on**: Phase 1
**Requirements**: HOST-01, HOST-02, HOST-03, HOST-04, HOST-05
**Success Criteria** (what must be TRUE):
  1. User can add a host and SSH connection is tested before saving
  2. User sees detected hardware capabilities (architecture, GPU, memory, disk) when adding host
  3. User can list all hosts with hardware information displayed
  4. User can check status of any host (SSH connectivity, service health)
  5. User can remove a host and all associated resources are cleaned up
**Plans**: TBD

Plans:
- [ ] 02-01: TBD

### Phase 3: Registry & Compatibility
**Goal**: Users can browse available claw types and validate compatibility before installation
**Depends on**: Phase 2
**Requirements**: REG-01, REG-02, REG-03
**Success Criteria** (what must be TRUE):
  1. User runs `clm registry list` and sees OpenClaw with version and requirements
  2. System loads OpenClaw manifest from platform/registry/openclaw/ directory
  3. System validates host capabilities against claw requirements and reports compatibility (supported/unsupported with specific reasons)
**Plans**: TBD

Plans:
- [ ] 03-01: TBD

### Phase 4: Secrets Management
**Goal**: Users can securely store and manage secrets for claw instances
**Depends on**: Phase 1
**Requirements**: SEC-01, SEC-02, SEC-03
**Success Criteria** (what must be TRUE):
  1. User can set a secret with `clm secret set` and it's stored with mode 600
  2. User can list secret keys with `clm secret list` and values are never displayed
  3. Secrets file is created with correct permissions (600) on first write
**Plans**: TBD

Plans:
- [ ] 04-01: TBD

### Phase 5: Installation & Fleet Status
**Goal**: Users can install OpenClaw on Ubuntu hosts and view fleet status
**Depends on**: Phase 2, Phase 3, Phase 4
**Requirements**: INST-01, INST-02, INST-03, INST-04, STAT-01
**Success Criteria** (what must be TRUE):
  1. User runs `clm install` and flows through: pick claw → pick host → validate compatibility → configure → install
  2. Installation validates compatibility before proceeding and fails fast if host is incompatible
  3. User sees real-time progress during installation (base setup, dependencies, claw installation)
  4. Installation fails fast with clear error messages if any step fails
  5. User runs `clm status` and sees all hosts with their claw instances, agents, and status
**Plans**: TBD

Plans:
- [ ] 05-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation Setup | 0/0 | Not started | - |
| 2. Host Management | 0/0 | Not started | - |
| 3. Registry & Compatibility | 0/0 | Not started | - |
| 4. Secrets Management | 0/0 | Not started | - |
| 5. Installation & Fleet Status | 0/0 | Not started | - |

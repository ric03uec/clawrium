# Requirements: Clawrium

**Defined:** 2026-03-20
**Core Value:** Users can manage all their AI assistants from one place with consistent configuration and security practices.

## v1 Requirements

Requirements for initial release: OpenClaw on single Ubuntu host.

### Initialization

- [x] **INIT-01**: User can initialize Clawrium config directory (`clm init`)
- [x] **INIT-02**: User sees dependency check (Python, Ansible) with install instructions

### Host Management

- [x] **HOST-01**: User can add a host with SSH details (`clm host add`)
- [x] **HOST-02**: User can list all hosts with hardware info (`clm host list`)
- [x] **HOST-03**: User can remove a host (`clm host remove`)
- [x] **HOST-04**: User can check host status (`clm host status`)
- [x] **HOST-05**: System detects hardware capabilities (arch, GPU, memory, disk)

### Claw Registry

- [x] **REG-01**: System loads claw manifests from registry
- [x] **REG-02**: User can list available claw types (`clm registry list`)
- [x] **REG-03**: System validates claw compatibility against host capabilities

### Claw Installation

- [x] **INST-01**: User can install OpenClaw via interactive flow (`clm install`)
- [x] **INST-02**: Installation validates compatibility before proceeding
- [x] **INST-03**: Installation streams progress in real-time
- [x] **INST-04**: Installation fails fast with clear error messages

### Secrets Management

- [ ] **SEC-01**: User can set secrets (`clm secret set`)
- [ ] **SEC-02**: User can list secret keys (`clm secret list`)
- [ ] **SEC-03**: Secrets stored with mode 600, never displayed

### Fleet Status

- [x] **STAT-01**: User can view fleet status (`clm status`)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Agent Normalization

- **AGENT-01**: User can create portable agent definitions (`clm agent create`)
- **AGENT-02**: User can list agents (`clm agent list`)
- **AGENT-03**: User can edit agents (`clm agent edit`)
- **AGENT-04**: System translates agents to claw-specific format

### Claw Operations

- **CLAW-01**: User can upgrade claw instances (`clm claw upgrade`)
- **CLAW-02**: User can remove claw instances (`clm claw remove`)
- **CLAW-03**: User can assign agents to claws (`clm claw agent add`)

### Multi-Host Fleet

- **FLEET-01**: User can manage multiple hosts
- **FLEET-02**: User can sync configs across hosts

### Additional Claw Types

- **TYPE-01**: ZeroClaw support
- **TYPE-02**: NemoClaw support

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| TUI interface | CLI first, TUI later |
| Cloud services | Fully local, no external dependencies |
| Non-Ubuntu distros | Ubuntu only for v1, other distros later |
| Security hardening (airgap, sandboxing) | Table stakes first, hardening in v2+ |
| GUI/web interface | CLI/TUI only |
| Multi-user auth | Single user for v1 |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INIT-01 | Phase 1 | Complete |
| INIT-02 | Phase 1 | Complete |
| HOST-01 | Phase 2 | Complete |
| HOST-02 | Phase 2 | Complete |
| HOST-03 | Phase 2 | Complete |
| HOST-04 | Phase 2 | Complete |
| HOST-05 | Phase 2 | Complete |
| REG-01 | Phase 3 | Complete |
| REG-02 | Phase 3 | Complete |
| REG-03 | Phase 3 | Complete |
| INST-01 | Phase 4 | Complete |
| INST-02 | Phase 4 | Complete |
| INST-03 | Phase 4 | Complete |
| INST-04 | Phase 4 | Complete |
| STAT-01 | Phase 4 | Complete |
| SEC-01 | Phase 5 | Pending |
| SEC-02 | Phase 5 | Pending |
| SEC-03 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-20*
*Last updated: 2026-03-21 after phase 4 planning*

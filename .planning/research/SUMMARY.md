# Research Summary: Clawrium

**Source:** Existing project documents (SPEC.md, IMPLEMENTATION_PLAN.md, security_hardening.md)

## Stack

**Chosen:**
- **CLI Framework:** Python + Typer
- **Execution Engine:** ansible-runner
- **Packaging:** uv/uvx
- **Data Models:** Pydantic
- **Config Format:** YAML
- **Automation:** Ansible roles + playbooks

**Rationale:**
- Typer provides modern CLI with type hints and auto-documentation
- ansible-runner abstracts Ansible execution with event streaming
- Pydantic enforces schema validation for all configs
- YAML is human-readable and widely understood

## Architecture

**Three-Layer Model:**

1. **Layer 1: CLI (clawrium)** — User interface, command parsing, progress display
2. **Layer 2: Claw Configuration** — Registry, agent normalization, translation, storage config
3. **Layer 3: Hardware/Host** — SSH, hardware detection, compatibility, Ansible execution

**Key Patterns:**
- Claw-first workflow (pick what to run, then where)
- Normalized agent schema portable across claw types
- Minimal permissions by default (workspace-only storage)
- Central config store at `~/.config/clawrium/`

## Features

**Table Stakes:**
- Host management (add/remove/list/status)
- Claw installation via Ansible
- Hardware capability detection
- Compatibility checking before install
- Config sync from central store to hosts
- Secrets management (namespaced, file permissions)
- Fleet status view

**Differentiators:**
- Normalized agent schema (portable across claw types)
- Agent translation (normalized → claw-specific format)
- Storage level abstraction (workspace/home/system)
- Claw registry with manifests, versions, dependencies

**v2/Future:**
- Multi-host fleet management
- Multiple claw types (ZeroClaw, NemoClaw)
- TUI interface
- Airgapped deployment bundles
- Network policy enforcement
- Sandbox runtime for claws

## Security Considerations

**Threat Model Focus:**
- Primary: Agent-specific abuse (data exfiltration, prompt injection)
- Secondary: Lateral movement, control-plane compromise

**Design Principles:**
1. No sudo — Clawrium never takes root, prompts user
2. Minimal permissions — workspace-only storage by default
3. Secrets in `.secrets` file with mode 600
4. SSH key-only auth
5. Dedicated user per claw instance

**Future Hardening:**
- Deny-by-default egress policy
- Per-instance sandbox (rootless containers)
- Inference routing controls
- Secret isolation (tmpfs injection)
- Audit logging

## Pitfalls

1. **Agent translation lossy** — Some claw-specific features won't map to normalized schema
2. **Hardware detection limits** — Only SSH-accessible information available
3. **Workspace-only friction** — Users may need manual expansion for some use cases
4. **Learning curve** — New mental model (claw-first vs host-first)

---
*Synthesized from: SPEC.md, IMPLEMENTATION_PLAN.md, security_hardening.md*

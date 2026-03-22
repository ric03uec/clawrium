# Phase 4: Installation & Fleet Status - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Install OpenClaw on Ubuntu hosts and view fleet status. Users run `clm install`, flow through claw selection → host selection → compatibility validation → installation. They can view fleet-wide claw status with `clm status`. Configuration of secrets/API keys is deferred to Phase 5.

</domain>

<decisions>
## Implementation Decisions

### Install Flow UX
- **D-01:** Hybrid invocation — flags override prompts. `clm install` prompts for missing values, `clm install --claw openclaw --host kevin` runs directly.
- **D-02:** Step-by-step progress with Rich spinners — show each phase: "Installing dependencies...", "Creating user...", "Configuring OpenClaw..."
- **D-03:** Confirmation required before install — display summary (claw, version, host, capabilities) and ask "Proceed? [y/N]"

### Ansible Playbook Structure
- **D-04:** Two-layer playbook architecture:
  - Base layer: OS/hardware packages (Node.js, Rust, etc.) — runs as `xclm` with sudo
  - Claw layer: Claw-specific setup (npm install, workspace) — runs as claw user (`opc-<hostname>`)
- **D-05:** Single base playbook with Ansible conditionals handles OS+arch variations via `when:` conditions based on facts
- **D-06:** Playbook directory structure:
  - `platform/playbooks/base.yaml` — shared base system setup
  - `platform/registry/<claw>/playbooks/install.yaml` — claw-specific installation
- **D-07:** Dedicated user per claw — create `opc-<hostname>` user for OpenClaw (isolates claw from system)
- **D-08:** xclm user assumed to have passwordless sudo on hosts (pre-configured by user)

### Error Handling
- **D-09:** Fail fast, no rollback — stop on first error, leave system in partial state. Playbooks are idempotent so user can retry.
- **D-10:** Error display: summary message + path to full Ansible log for debugging
- **D-11:** Track install state in host record — mark as 'install_failed' or 'partial'. `clm status` shows it.

### Fleet Status Display
- **D-12:** Claw-centric view — list claws across all hosts, grouped by claw type
- **D-13:** Live health check — SSH to hosts and check if claw process is running (not cached)
- **D-14:** Essential info per claw: name, version, host, status (running/stopped/unknown)

### Claude's Discretion
- Exact Ansible task structure and module choices
- Progress spinner styling and timing
- Table column layout and widths
- Log file location and format

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — INST-01 through INST-04, STAT-01 specifications

### Existing Code
- `src/clawrium/core/registry.py` — `check_compatibility()` for pre-install validation
- `src/clawrium/core/hosts.py` — Host storage, will need install state tracking
- `src/clawrium/core/hardware.py` — `gather_hardware()` pattern for Ansible facts
- `src/clawrium/platform/registry/openclaw/manifest.yaml` — OpenClaw requirements

### Prior Context
- `.planning/phases/02-host-management/02-CONTEXT.md` — D-12 (two-user model), D-14 (Ansible facts pattern)
- `.planning/phases/03-registry-compatibility/03-CONTEXT.md` — D-10 (binary compatibility), D-13 (no separate check command)

### Project Constraints
- `.planning/PROJECT.md` — Tech stack (Typer, ansible-runner), no-sudo policy in Clawrium itself, Ubuntu only

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/registry.py`: `check_compatibility()` — validates host against manifest before install
- `core/hosts.py`: `load_hosts()`, `save_hosts()`, `update_host()` — extend for install state
- `core/hardware.py`: `gather_hardware()` — Ansible facts pattern to reuse for process checks
- `cli/host.py`: Rich table output pattern for status display

### Established Patterns
- Typer subcommand structure: `clm <command>` (e.g., `clm install`, `clm status`)
- ansible-runner for remote execution
- Rich spinners and tables for CLI output
- JSON for user data storage

### Integration Points
- New `core/install.py` for installation orchestration
- New `cli/install.py` command with hybrid prompts
- New `cli/status.py` command for fleet view
- Extend `core/hosts.py` with install state fields
- New `platform/playbooks/base.yaml` for system setup
- New `platform/registry/openclaw/playbooks/install.yaml` for OpenClaw setup

</code_context>

<specifics>
## Specific Ideas

- Two-layer playbook keeps concerns separate: OS team can update base.yaml, claw maintainers update their install.yaml
- Base playbook is idempotent — safe to rerun if installing second claw on same host
- Install state tracking prevents "is it installed?" confusion in multi-claw scenarios
- Claw-centric status view answers "what's running in my fleet?" at a glance

</specifics>

<deferred>
## Deferred Ideas

- Secrets/API key configuration — Phase 5
- `--yes` flag to skip confirmation — v2 feature for scripting
- Rollback on failure — complexity not worth it for v1, playbooks are idempotent
- Uptime/restart tracking — nice-to-have, not essential for v1
- Install from specific version — use latest for v1

</deferred>

---

*Phase: 04-installation-fleet-status*
*Context gathered: 2026-03-21*

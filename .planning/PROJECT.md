# Clawrium

## What This Is

Clawrium is a CLI/TUI tool for managing AI assistant fleets on local networks. It provides a centralized command center for installing, configuring, and maintaining multiple "claws" (AI assistants like OpenClaw, ZeroClaw, NemoClaw) across hosts, solving the chaos of configuration drift, scattered secrets, and inconsistent management.

## Core Value

Users can manage all their AI assistants from one place with consistent configuration and security practices, regardless of which claw types they run.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Add/remove hosts in the fleet
- [ ] Install OpenClaw on Ubuntu hosts via Ansible
- [ ] Manage claw configs (SOUL.md, IDENTITY.md, AGENTS.md, etc.) from central store
- [ ] Sync configs from central store to hosts
- [ ] Check claw status on hosts
- [ ] Rotate API keys across claws
- [ ] Switch model providers for claws
- [ ] Add/remove agents within a claw

### Out of Scope

- Cloud services — fully local, no external dependencies
- Non-Ubuntu distros — Ubuntu only for v1, other distros later
- Other claw types — OpenClaw only for v1, ZeroClaw/NemoClaw later
- GUI — CLI/TUI only, no web interface
- Multi-user/auth — single user for v1

## Context

**Problem space:**
- AI assistants (claws) proliferate — users don't know which to install
- Each claw has different config files, formats, and locations
- Configuration drift when managing multiple instances
- Secrets (API keys) scattered across config files
- Upgrades risk breaking existing config
- No unified way to manage fleet health

**OpenClaw specifics:**
- Config lives in `~/.openclaw/workspace/`
- Key files: SOUL.md, IDENTITY.md, AGENTS.md, USER.md, MEMORY.md, HEARTBEAT.md
- Global config: `~/.openclaw/openclaw.json`

**Clawrium approach:**
- Central store at `~/.config/clawrium/`
- Registry of claw types with versions, dependencies, templates
- Ansible playbooks for installation and config sync
- Never takes sudo — prompts user for privileged operations

## Constraints

- **Tech stack**: Python + Typer CLI, ansible-runner for execution, uv/uvx for packaging
- **Security**: No sudo permissions — Clawrium prompts user when privileged commands needed
- **Platform**: Ubuntu only for v1
- **Claw support**: OpenClaw only for v1
- **Deployment**: Fully local, no cloud dependencies

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Ansible for execution | Standard automation tool, no agent needed on hosts, SSH-based | — Pending |
| No sudo policy | Security-first, user controls privileged operations | — Pending |
| Central store in ~/.config/clawrium/ | Standard XDG location, single source of truth | — Pending |
| Start with OpenClaw | Well-documented, clear file structure, good test case | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-20 after initialization*

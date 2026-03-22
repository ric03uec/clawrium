# Phase 4: Installation & Fleet Status - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-21
**Phase:** 04-installation-fleet-status
**Areas discussed:** Install flow UX, Ansible playbook structure, Error handling, Fleet status display

---

## Install Flow UX

| Option | Description | Selected |
|--------|-------------|----------|
| Fully interactive | Run `clm install`, get prompted for claw type and host. | |
| Flags only | `clm install --claw openclaw --host kevin`. Fails if missing required args. | |
| Hybrid | Flags override prompts. `clm install --claw openclaw` prompts only for host. | ✓ |

**User's choice:** Hybrid
**Notes:** Allows both scripting and exploration.

| Option | Description | Selected |
|--------|-------------|----------|
| Step-by-step with spinners | Show each phase with Rich spinners. | ✓ |
| Single progress bar | One progress bar with percentage. | |
| Verbose log stream | Show all Ansible output in real-time. | |

**User's choice:** Step-by-step with spinners

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, show summary and confirm | Display summary and ask 'Proceed? [y/N]' | ✓ |
| No confirmation | Start immediately after validation. | |
| Only with --yes flag to skip | Default confirms, `--yes` bypasses. | |

**User's choice:** Yes, show summary and confirm

---

## Ansible Playbook Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Full setup | Install deps, create user, install claw, create workspace. | ✓ |
| Minimal — deps only | Just install dependencies. | |
| Deps + claw only | No user creation or workspace setup. | |

**User's choice:** Full setup

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated user per claw | Create `opc-<hostname>` for OpenClaw. | ✓ |
| Use existing xclm user | Run claw under system admin user. | |
| User provides username | Prompt for username during install. | |

**User's choice:** Dedicated user per claw

**User clarification on playbook structure:**
- Two-layer architecture: base (OS/hardware packages) + claw (claw-specific setup)
- Base layer runs as xclm with sudo, claw layer runs as claw user
- Node.js install differs by OS+arch (e.g., Ubuntu x86 vs arm/Raspberry Pi)
- Single base playbook with Ansible conditionals handles variations via `when:` conditions

| Option | Description | Selected |
|--------|-------------|----------|
| Assume xclm has sudo | xclm expected to have passwordless sudo. | ✓ |
| Prompt user when needed | Pause and ask user to run commands manually. | |
| Separate privileged playbook | Generate script user runs with sudo first. | |

**User's choice:** Assume xclm has sudo

---

## Error Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Fail fast, no rollback | Stop on first error. Leave system in partial state. | ✓ |
| Fail fast with rollback | Stop on error, attempt to undo completed steps. | |
| Retry then fail | Retry failed tasks 2-3 times before giving up. | |

**User's choice:** Fail fast, no rollback

| Option | Description | Selected |
|--------|-------------|----------|
| Summary + log path | Show summary + path to full Ansible log. | ✓ |
| Full Ansible output | Stream all Ansible output including errors. | |
| Summary only | Just 'Installation failed'. | |

**User's choice:** Summary + log path

| Option | Description | Selected |
|--------|-------------|----------|
| Record in host state | Mark host as 'install_failed' or 'partial'. | ✓ |
| No tracking | Don't track failures. | |
| Separate failed installs list | Keep a `failed_installs.json` log. | |

**User's choice:** Record in host state

---

## Fleet Status Display

| Option | Description | Selected |
|--------|-------------|----------|
| Host-centric view | List hosts, each showing installed claws. | |
| Claw-centric view | List claws across all hosts, group by claw type. | ✓ |
| Combined dashboard | Summary stats + detailed table. | |

**User's choice:** Claw-centric view

| Option | Description | Selected |
|--------|-------------|----------|
| Process check only | Check if claw process is running. | |
| SSH + process check | Verify SSH connectivity, then check process. | ✓ |
| Cached status | Show last-known status, use --refresh for live. | |

**User's choice:** SSH + process check

| Option | Description | Selected |
|--------|-------------|----------|
| Essential only | Claw name, version, host, status. | ✓ |
| With uptime | Add uptime, last restart time. | |
| Full details | Include user, install path, port, PID. | |

**User's choice:** Essential only

---

## Claude's Discretion

- Exact Ansible task structure and module choices
- Progress spinner styling and timing
- Table column layout and widths
- Log file location and format

## Deferred Ideas

- Secrets/API key configuration — Phase 5
- `--yes` flag to skip confirmation — v2 feature
- Rollback on failure — not needed for v1
- Uptime/restart tracking — nice-to-have
- Install from specific version — use latest for v1

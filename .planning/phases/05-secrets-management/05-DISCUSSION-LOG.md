# Phase 5: Secrets Management - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-22
**Phase:** 05-secrets-management
**Areas discussed:** Storage approach, Secret scoping, CLI command design, Secret injection

---

## Storage Approach

### Encryption at rest
| Option | Description | Selected |
|--------|-------------|----------|
| Mode 600 only (Recommended) | Simple, no key management complexity. Secrets in plaintext JSON readable only by user. Consistent with hosts.json approach. | ✓ |
| Encrypt at rest | Adds encryption layer. Requires unlock mechanism (passphrase, keychain, or master key). More secure but more complex. | |
| You decide | Claude chooses based on v1 constraints and security trade-offs. | |

**User's choice:** Mode 600 only (Recommended)
**Notes:** Consistent with existing hosts.json security model.

### File layout
| Option | Description | Selected |
|--------|-------------|----------|
| Single secrets.json (Recommended) | Consistent with hosts.json pattern. All secrets in one file with structured keys. Simpler to backup/restore. | ✓ |
| Directory structure | ~/.config/clawrium/secrets/<scope>/<key>.txt. More granular permissions, easier to share individual secrets. | |
| You decide | Claude chooses based on implementation simplicity. | |

**User's choice:** Single secrets.json (Recommended)
**Notes:** Follows established pattern from Phase 2.

### Metadata
| Option | Description | Selected |
|--------|-------------|----------|
| Key + value + metadata (Recommended) | Each secret has: key, value, created_at, updated_at, description. Helps track when keys were last rotated. | ✓ |
| Key + value only | Minimal schema. User tracks rotation externally. Simpler but less auditable. | |

**User's choice:** Key + value + metadata (Recommended)
**Notes:** Enables audit trail for secret rotation.

---

## Secret Scoping

### Scope levels
| Option | Description | Selected |
|--------|-------------|----------|
| Global only (Recommended) | Single pool of secrets. Simpler for v1. Most API keys (Anthropic, OpenAI) are shared across all claws anyway. | ✓ |
| Global + per-claw | Secrets can be scoped to a specific claw type (e.g., openclaw). Claw-specific secrets override global. | |
| Global + per-host + per-claw | Full hierarchy. Most flexible but adds complexity. Useful if different hosts need different keys. | |

**User's choice:** Global only (Recommended)
**Notes:** Simplicity for v1.

### Key names
| Option | Description | Selected |
|--------|-------------|----------|
| All user-defined | User chooses key names: `clm secret set ANTHROPIC_API_KEY`. No assumptions about what providers they use. | |
| Suggested conventions | Document standard names (ANTHROPIC_API_KEY, OPENAI_API_KEY) but allow any key. Help text suggests conventions. | |
| Enforced schema (Recommended) | Registry manifests declare required secrets per claw. `clm secret set` validates against known keys. Unknown keys rejected. | ✓ |

**User's choice:** Enforced schema (Recommended)
**Notes:** Manifests define required secrets per claw type.

### Schema location
| Option | Description | Selected |
|--------|-------------|----------|
| In manifest.yaml (Recommended) | Add `required_secrets` field to existing manifest structure. Secrets tied to claw version. Single source of truth. | ✓ |
| Separate secrets-schema.yaml | Dedicated file per claw type. More separation but another file to maintain. | |

**User's choice:** In manifest.yaml (Recommended)
**Notes:** Single source of truth.

### Optional secrets
| Option | Description | Selected |
|--------|-------------|----------|
| Yes, required + optional (Recommended) | Manifest has `required_secrets` and `optional_secrets`. Install fails without required. Optional enables extra features. | ✓ |
| Required only | All declared secrets are required. Simplifies validation. User can always add extra via env vars. | |

**User's choice:** Yes, required + optional (Recommended)
**Notes:** Flexibility for optional features.

### Missing secrets display
| Option | Description | Selected |
|--------|-------------|----------|
| Yes, show gaps (Recommended) | List all stored secrets + highlight missing required secrets per installed claw. Helps user complete setup. | ✓ |
| Just list stored | Only show what's stored. User runs separate validation command to check completeness. | |

**User's choice:** Yes, show gaps (Recommended)
**Notes:** User-friendly setup flow.

---

## CLI Command Design

### Input method
| Option | Description | Selected |
|--------|-------------|----------|
| Prompt only (Recommended) | `clm secret set ANTHROPIC_API_KEY` prompts for value with masked input (no echo). Safest — value never in shell history. | ✓ |
| Prompt + --value flag | Flag for scripting: `clm secret set KEY --value VAL`. Convenient but value visible in history/process list. | |
| Prompt + stdin | `echo $KEY | clm secret set KEY --stdin`. Good for piping from password managers. No history exposure. | |

**User's choice:** Prompt only (Recommended)
**Notes:** Security first.

### Overwrite confirmation
| Option | Description | Selected |
|--------|-------------|----------|
| Yes, confirm (Recommended) | Show existing key metadata (created_at, description) and ask 'Overwrite? [y/N]'. Prevents accidents. | ✓ |
| Silent overwrite | Overwrite without confirmation. Faster for scripting. Add `--force` flag if confirmation needed. | |

**User's choice:** Yes, confirm (Recommended)
**Notes:** Consistent with other destructive actions.

### Get command
| Option | Description | Selected |
|--------|-------------|----------|
| No get command (Recommended) | Secrets are write-only from CLI. List shows keys but never values. Values only revealed when injected to claws. | ✓ |
| Get with warning | `clm secret get KEY` outputs value. Shows warning about security. Useful for debugging/rotation. | |
| Get requires confirmation | `clm secret get KEY` prompts 'This will display the secret. Continue? [y/N]' before revealing. | |

**User's choice:** No get command (Recommended)
**Notes:** Security first — write-only CLI.

### Remove confirmation
| Option | Description | Selected |
|--------|-------------|----------|
| Yes, confirm (Recommended) | Ask 'Remove secret KEY? This cannot be undone. [y/N]'. Consistent with `clm host remove` pattern. | ✓ |
| No confirmation | Remove immediately. Add `--yes` flag to suppress confirmation if needed. | |

**User's choice:** Yes, confirm (Recommended)
**Notes:** Consistent with existing patterns.

---

## Secret Injection

### Delivery mechanism
| Option | Description | Selected |
|--------|-------------|----------|
| Env vars in systemd unit (Recommended) | Write secrets to /etc/systemd/system/openclaw.service.d/secrets.conf. Claw process reads env vars. Standard pattern. | |
| Dotenv file | Write .env file in claw home directory. Claw reads on startup. Simple but file permissions must be tight. | |
| Ansible Vault | Encrypt secrets with Ansible Vault, decrypt during playbook run. Most secure but adds vault password management. | |

**User's choice:** Ansible template substitution (custom)
**Notes:** Secrets stored locally in secrets.json, Ansible reads and populates templates on target hosts during playbook runs.

### Target path
| Option | Description | Selected |
|--------|-------------|----------|
| Claw user home (Recommended) | Template outputs to ~opc-kevin/.openclaw/secrets.env or similar. Owned by claw user, mode 600. | |
| Systemd drop-in | Template to /etc/systemd/system/openclaw.service.d/. Requires sudo, managed by xclm user. | |
| You decide | Claude chooses based on OpenClaw conventions and security. | |

**User's choice:** Depends on service/claw (custom)
**Notes:** Target location varies — systemd needs secrets in drop-in, claw needs secrets in its config directory. Template per destination.

### Sync behavior
| Option | Description | Selected |
|--------|-------------|----------|
| Auto-sync on any run | Every playbook run updates secrets on hosts. Ensures hosts always have latest. Simple but may be unexpected. | ✓ |
| Explicit command only (Recommended) | `clm secret sync` pushes secrets to hosts. Install doesn't auto-sync. User controls when secrets propagate. | |
| Sync on install, explicit otherwise | Initial install syncs secrets. Updates require explicit `clm secret sync`. Balance of convenience and control. | |

**User's choice:** Auto-sync on any run
**Notes:** Secrets always propagated, no explicit sync needed.

### Missing secrets validation
| Option | Description | Selected |
|--------|-------------|----------|
| Fail if missing (Recommended) | Install validates required secrets exist before proceeding. User must set secrets first. Prevents broken installs. | ✓ |
| Warn and continue | Install proceeds with warnings about missing secrets. Claw may fail to start but user can add secrets later. | |

**User's choice:** Fail if missing (Recommended)
**Notes:** Fail fast to prevent broken installations.

---

## Claude's Discretion

- Exact JSON schema field names and types
- getpass library for masked input vs alternative
- Error message wording
- Template file structure in registry/<claw>/templates/

## Deferred Ideas

- Encryption at rest — adds key management complexity, defer to v2
- Per-host or per-claw secret scoping — global sufficient for v1
- `clm secret get` command — security concern, keep write-only for v1
- Secret rotation automation — manual for v1
- `--stdin` flag for piping secrets — prompt-only for v1

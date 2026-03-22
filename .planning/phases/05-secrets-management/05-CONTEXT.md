# Phase 5: Secrets Management - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Securely store and retrieve secrets (API keys, credentials) for claw instances. Users can set, list, and remove secrets via `clm secret` commands. Secrets are stored locally with restrictive permissions and injected to target hosts via Ansible template substitution during playbook runs.

</domain>

<decisions>
## Implementation Decisions

### Storage Approach
- **D-01:** File-permission-based security (mode 600), no encryption at rest for v1
- **D-02:** Single `secrets.json` file in `~/.config/clawrium/` (consistent with hosts.json pattern)
- **D-03:** Each secret has metadata: key, value, created_at, updated_at, description
- **D-04:** Use fcntl file locking pattern from hosts.py for concurrent access safety

### Secret Scoping
- **D-05:** Global scope only for v1 — single pool of secrets shared across all claws
- **D-06:** Enforced schema — registry manifests declare required/optional secrets per claw type
- **D-07:** Add `required_secrets` and `optional_secrets` fields to manifest.yaml
- **D-08:** `clm secret list` shows gaps — highlights missing required secrets per installed claw

### CLI Command Design
- **D-09:** `clm secret set KEY` prompts for value with masked input (no echo) — never in shell history
- **D-10:** Confirm before overwriting existing secret — show metadata, ask "Overwrite? [y/N]"
- **D-11:** No `clm secret get` command — secrets are write-only from CLI, values never revealed
- **D-12:** `clm secret remove KEY` requires confirmation — consistent with `clm host remove` pattern
- **D-13:** `clm secret list` shows stored secrets (keys only) + missing required secrets per claw

### Secret Injection
- **D-14:** Ansible template substitution — secrets read from local secrets.json, populated into templates during playbook runs
- **D-15:** Target location depends on claw/service — systemd drop-ins, claw config files, etc. based on what each claw expects
- **D-16:** Auto-sync on any playbook run — secrets always propagated to hosts, no explicit sync command needed
- **D-17:** Install fails if required secrets missing — validate before proceeding, prevents broken installs

### Claude's Discretion
- Exact JSON schema field names and types
- getpass library for masked input vs alternative
- Error message wording
- Template file structure in registry/<claw>/templates/

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — SEC-01, SEC-02, SEC-03 specifications

### Existing Code
- `src/clawrium/core/config.py` — Config directory management, mode 600 pattern
- `src/clawrium/core/hosts.py` — JSON file storage with fcntl locking pattern to reuse
- `src/clawrium/core/registry.py` — Manifest loading to extend with required_secrets
- `src/clawrium/cli/host.py` — Confirmation and table output patterns

### Prior Context
- `.planning/phases/02-host-management/02-CONTEXT.md` — D-01 (JSON format), D-18 (confirmation pattern)
- `.planning/phases/03-registry-compatibility/03-CONTEXT.md` — D-01 (manifest structure)
- `.planning/phases/04-installation-fleet-status/04-CONTEXT.md` — D-01 (hybrid invocation)

### Project Constraints
- `.planning/PROJECT.md` — Tech stack (Typer, ansible-runner), no-sudo policy, Ubuntu only

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/config.py`: `get_config_dir()`, `init_config_dir()` with mode 700 permissions
- `core/hosts.py`: `_hosts_lock()` context manager for fcntl file locking
- `core/hosts.py`: JSON load/save pattern with corruption handling
- `cli/host.py`: Rich table output, typer.confirm() for confirmation prompts
- `core/registry.py`: Manifest loading with `load_manifest()`, ManifestEntry TypedDict

### Established Patterns
- Typer subcommand structure: `clm <group> <command>`
- JSON for user data, YAML for bundled config
- Rich tables for structured CLI output
- fcntl advisory locking for file safety

### Integration Points
- New `core/secrets.py` for secret storage and validation
- New `cli/secret.py` command module with set, list, remove subcommands
- Extend `platform/registry/<claw>/manifest.yaml` with secrets schema
- Extend playbook templates to read from secrets.json

</code_context>

<specifics>
## Specific Ideas

- Masked input via getpass.getpass() for secret value entry
- Missing secrets shown in `clm secret list` grouped by claw type
- Install validation reads manifest required_secrets, checks against stored secrets
- Ansible templates use Jinja2 syntax to inject secrets from inventory vars

</specifics>

<deferred>
## Deferred Ideas

- Encryption at rest — adds key management complexity, defer to v2
- Per-host or per-claw secret scoping — global sufficient for v1
- `clm secret get` command — security concern, keep write-only for v1
- Secret rotation automation — manual for v1
- `--stdin` flag for piping secrets — prompt-only for v1

</deferred>

---

*Phase: 05-secrets-management*
*Context gathered: 2026-03-22*

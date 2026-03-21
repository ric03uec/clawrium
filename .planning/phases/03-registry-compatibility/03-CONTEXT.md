# Phase 3: Registry & Compatibility - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Load claw manifests from bundled registry and validate compatibility against host capabilities. Users can browse available claw types via `clm registry list` and see detailed info with `clm registry show <claw>`. The compatibility checking function is internal (used by Phase 5 install flow), not exposed as a CLI command.

</domain>

<decisions>
## Implementation Decisions

### Manifest Structure
- **D-01:** Manifests stored in package as `platform/registry/<claw-name>/manifest.yaml`
- **D-02:** YAML format (requires PyYAML dependency)
- **D-03:** Claw compatibility is a **sparse matrix** — only explicitly supported combinations are valid
- **D-04:** Each manifest entry specifies: `version`, `os`, `os_version`, `arch`, `requirements`
- **D-05:** Requirements include: `min_memory_mb`, `gpu_required`, `dependencies` (key-value semver strings)
- **D-06:** Dependencies use simple version strings: `nodejs: ">=20.0.0"` format

Example manifest entry:
```yaml
name: openclaw
entries:
  - version: "1.2.0"
    os: ubuntu
    os_version: "24.04"
    arch: x86_64
    requirements:
      min_memory_mb: 1024
      gpu_required: false
      dependencies:
        nodejs: ">=20.0.0"
```

### OS Detection
- **D-07:** Use Ansible facts (ansible_distribution, ansible_distribution_version) via existing hardware.py pattern
- **D-08:** Store OS info in host record at add time (extend HardwareInfo)
- **D-09:** OS info refreshed via `clm host status --refresh` (existing pattern from Phase 2)

### Compatibility Rules
- **D-10:** Binary pass/fail — host matches manifest entry = supported, else unsupported
- **D-11:** Dependency version check failure = fail (strict, no "warn and continue")
- **D-12:** Specific failure reasons: "Requires Ubuntu 24.04, host has 22.04" or "Needs 2GB RAM, host has 1GB"
- **D-13:** No separate `clm registry check` command — compatibility validated during install (Phase 5)

### Registry CLI
- **D-14:** `clm registry list` shows simple table: claw name, latest version, brief description
- **D-15:** `clm registry show <claw>` shows full manifest details: all versions, requirements, platforms
- **D-16:** Rich table output consistent with Phase 1/2 patterns

### Extensibility
- **D-17:** New claws added via package releases only (no user-added manifests for v1)
- **D-18:** Directory per claw type: `platform/registry/openclaw/`, `platform/registry/zeroclaw/`, etc.
- **D-19:** Room for future templates and playbooks in claw directories

### Claude's Discretion
- Exact YAML schema field names
- Table column layout and widths
- Error message wording for compatibility failures
- Semver comparison library choice (packaging.version recommended)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — REG-01, REG-02, REG-03 specifications

### Existing Code
- `src/clawrium/core/hardware.py` — HardwareInfo TypedDict to extend with OS info, gather_hardware() pattern
- `src/clawrium/core/hosts.py` — Host storage, update_host() for adding OS to existing hosts
- `src/clawrium/cli/main.py` — Pattern for registering new subcommand app

### Prior Context
- `.planning/phases/02-host-management/02-CONTEXT.md` — D-14 (Ansible facts pattern), D-17 (Rich table output)

### Project Constraints
- `.planning/PROJECT.md` — Tech stack (Typer, ansible-runner, uv/uvx), no-sudo policy, Ubuntu only

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/hardware.py`: `gather_hardware()` function to extend for OS detection, `extract_hardware_from_facts()` pattern
- `core/hardware.py`: `HardwareInfo` TypedDict — add os, os_version fields
- `core/hosts.py`: `load_hosts()`, `save_hosts()`, `update_host()` for host record management
- `cli/main.py`: `app.add_typer()` pattern for registering `registry` subcommand

### Established Patterns
- Typer subcommand structure: `clm <group> <command>` (e.g., `clm host add`)
- Rich tables for structured CLI output
- Ansible facts via ansible_runner for remote host inspection
- JSON for user data, YAML for bundled config (consistent with industry norms)

### Integration Points
- New `core/registry.py` for manifest loading and compatibility checking
- New `cli/registry.py` command module with `list` and `show` subcommands
- Extend `core/hardware.py` HardwareInfo to include `os`, `os_version` fields
- New `platform/registry/openclaw/manifest.yaml` bundled with package

</code_context>

<specifics>
## Specific Ideas

- Manifest is a sparse matrix — if host doesn't match an explicit entry, it's unsupported (fail fast)
- OpenClaw is the only claw for v1 — manifest covers Ubuntu 24.04 on x86_64
- Future phases will add ZeroClaw, NemoClaw manifests
- Compatibility function is internal — exposed via install flow, not as standalone command

</specifics>

<deferred>
## Deferred Ideas

- User-added manifests in ~/.config/clawrium/registry/ — v2 feature
- Plugin system for claw types — out of scope
- GPU driver version detection (presence + vendor sufficient for v1)
- Non-Ubuntu platforms — v2+

</deferred>

---

*Phase: 03-registry-compatibility*
*Context gathered: 2026-03-21*

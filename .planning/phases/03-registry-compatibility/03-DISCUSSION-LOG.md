# Phase 3: Registry & Compatibility - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-21
**Phase:** 03-registry-compatibility
**Areas discussed:** Manifest structure, Compatibility rules, Registry CLI output, Extensibility model

---

## Manifest structure

### Location

| Option | Description | Selected |
|--------|-------------|----------|
| Bundled in package (Recommended) | platform/registry/<claw-name>/manifest.yaml shipped with Clawrium. Simple, versioned with code. | ✓ |
| User config directory | ~/.config/clawrium/registry/<claw-name>/. User-editable but more complex. | |
| Both locations | Package provides defaults, user dir can add/override. Flexible but more complex. | |

**User's choice:** Bundled in package + explained sparse matrix concept for claw/hardware/OS combinations
**Notes:** User clarified that each claw MUST be supported on specific hardware and OS combinations. The manifest is a sparse matrix — only explicitly supported combinations are valid.

### Format

| Option | Description | Selected |
|--------|-------------|----------|
| YAML (Recommended) | Human-readable, good for sparse matrix with nested structure. Needs PyYAML dep. | ✓ |
| JSON | No extra deps (Python stdlib), but verbose for multi-entry matrix. | |
| TOML | Rust/Python ecosystem standard, readable, needs tomli dep. | |

**User's choice:** YAML (Recommended)

### OS Detection

| Option | Description | Selected |
|--------|-------------|----------|
| Ansible facts (Recommended) | Use ansible_distribution, ansible_distribution_version from existing hardware.py. | ✓ |
| Extend hardware detection | Add OS info to HardwareInfo and re-gather. More consistent but duplicates work. | |
| Detect on-demand | Query OS only during compatibility check. Slower per-check but always fresh. | |

**User's choice:** Ansible facts (Recommended)

### OS Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Store in host record (Recommended) | Extend HardwareInfo in Phase 3 to include OS. Check is instant, data from add-time. | ✓ |
| Detect each time | Fresh check per compatibility query. Accurate if OS upgraded, but slower. | |
| Store + refresh option | Store on add, allow refresh via status command. Best of both. | |

**User's choice:** Store in host record (Recommended)

### Dependencies

| Option | Description | Selected |
|--------|-------------|----------|
| Simple version strings (Recommended) | nodejs: ">=20.0.0" format. Easy to write, standard semver comparisons. | ✓ |
| Package manager format | Specify via apt/npm packages. More precise but OS-specific. | |
| Binary presence only | Just check if node, python3 exist. Simplest but no version enforcement. | |

**User's choice:** Simple version strings (Recommended)

---

## Compatibility rules

### Compatibility Mode

| Option | Description | Selected |
|--------|-------------|----------|
| Binary pass/fail (Recommended) | Host matches manifest entry = supported. Doesn't match = unsupported. | ✓ |
| Graded support levels | supported/degraded/unsupported. Soft requirements cause degraded. | |
| Strict with warnings | Pass/fail but show warnings for near-misses. | |

**User's choice:** Binary pass/fail (Recommended)

### Version Check Failure

| Option | Description | Selected |
|--------|-------------|----------|
| Warn and continue | Show warning, allow install to proceed. | |
| Fail the check | Can't verify = incompatible. Strict but may block valid installs. | ✓ |
| Ask user (Recommended) | Prompt for decision. Interactive. | |

**User's choice:** Fail the check

### Failure Reasons

| Option | Description | Selected |
|--------|-------------|----------|
| Specific failure (Recommended) | Show exactly what failed with values. | ✓ |
| Category only | Just say 'OS mismatch' or 'Memory insufficient'. | |
| Full diff | Show all requirements vs host capabilities table. | |

**User's choice:** Specific failure (Recommended)

---

## Registry CLI output

### List Output

| Option | Description | Selected |
|--------|-------------|----------|
| Simple list (Recommended) | Claw name, latest version, brief description. Clean table. | ✓ |
| Matrix view | Show all supported combinations. Many rows, full detail. | |
| Grouped by claw | Claw name header, then indented list of supported versions/platforms. | |

**User's choice:** Simple list (Recommended)

### Detail Command

| Option | Description | Selected |
|--------|-------------|----------|
| `clm registry show <claw>` (Recommended) | Separate command shows full manifest details. | ✓ |
| `clm registry list --verbose` | Flag on list command shows more details inline. | |
| No detail command for v1 | Simple list only. | |

**User's choice:** `clm registry show <claw>` (Recommended)

### Compatibility Check Location

| Option | Description | Selected |
|--------|-------------|----------|
| `clm registry check <claw> <host>` (Recommended) | Explicit command to validate before install. | |
| Show in `clm registry list` | Add compat column if host specified via flag. | |
| Only in install flow | No separate check command. Discover compat during install. | ✓ |

**User's choice:** Only in install flow
**Notes:** Compatibility validation is internal, called by install (Phase 5), not exposed as standalone command.

---

## Extensibility model

### Adding Claws

| Option | Description | Selected |
|--------|-------------|----------|
| Package release only (Recommended) | New claws added via Clawrium code updates. | ✓ |
| Drop-in manifests | User can add YAML files to user config. | |
| Plugin system | Entry points or plugin packages. | |

**User's choice:** Package release only (Recommended)

### Registry Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Directory per claw (Recommended) | platform/registry/openclaw/, zeroclaw/, etc. Room for templates. | ✓ |
| Single registry file | platform/registry.yaml with all claws. | |
| Flat structure | platform/registry/openclaw.yaml, zeroclaw.yaml. Files only. | |

**User's choice:** Directory per claw (Recommended)

---

## Claude's Discretion

- Exact YAML schema field names
- Table column layout and widths
- Error message wording for compatibility failures
- Semver comparison library choice

## Deferred Ideas

- User-added manifests in ~/.config/clawrium/registry/ — v2 feature
- Plugin system for claw types — out of scope
- GPU driver version detection — presence + vendor sufficient for v1
- Non-Ubuntu platforms — v2+

# Issue 348: Atlassian Integration for Hermes Agent (MCP)

## Summary

Enable the hermes agent to interact with Atlassian Cloud (Jira + Confluence) via
the `mcp-atlassian` MCP server. Additionally, merge the existing separate `jira`
and `confluence` integration types into a single unified `atlassian` type across
all agent types.

This is a headless, no-UI workflow that uses API token authentication — no
browser-based OAuth approval is required at any point.

## Problem Statement

1. Hermes agents have no way to interact with Atlassian services
2. Hermes `config.yaml.j2` doesn't produce the `mcp_servers:` section
3. The existing `jira` and `confluence` integration types are redundant — on
   Atlassian Cloud they share the same account, instance URL, and API token
4. Maintaining two types creates confusion and doubles credential entry

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single `atlassian` integration type | Same account, same token, same instance for Jira + Confluence on Cloud |
| Remove `jira` and `confluence` types | Eliminates redundancy; single source of truth for Atlassian credentials |
| API Token auth (not OAuth) | OAuth requires browser approval — incompatible with headless remote agents |
| `uvx mcp-atlassian` stdio transport | Hermes manages subprocess lifecycle; no separate service to run |
| Pre-install via `uv tool install` | Avoids download latency on every agent restart |
| Derive `CONFLUENCE_URL` as `ATLASSIAN_URL + /wiki` | Atlassian Cloud standard; simplifies credential collection |
| Update openclaw template for new type | Openclaw gets same credential simplification benefit |

## Auth Strategy

The `mcp-atlassian` server (v0.21.1) supports three authentication methods:

| Method | Headless? | Use Case |
|--------|-----------|----------|
| API Token (`USERNAME` + `API_TOKEN`) | Yes | Atlassian Cloud (recommended) |
| Personal Access Token (PAT) | Yes | Server/Data Center |
| OAuth 2.0 (`--oauth-setup`) | No (needs browser) | Not applicable |

**This feature uses API Token auth exclusively.**

Credentials required from the user (one-time, collected by `clm integration add`):

- `ATLASSIAN_URL` — Instance URL (e.g., `https://company.atlassian.net`)
- `ATLASSIAN_EMAIL` — Account email
- `ATLASSIAN_API_TOKEN` — Token from https://id.atlassian.com/manage-profile/security/api-tokens

Optional:
- `CONFLUENCE_SPACES_FILTER` — Comma-separated space keys
- `JIRA_PROJECTS_FILTER` — Comma-separated project keys

## Architecture

```
clm integration add work-atlassian --type atlassian
clm agent integration add vand work-atlassian
clm agent configure vand
    │
    ▼
configure_agent() [lifecycle.py — no changes needed]
    │
    ├── Loads integration: {"work-atlassian": {type: "atlassian", credentials: {...}}}
    ├── Passes to Ansible as `integrations` var
    │
    ▼
configure.yaml playbook [UPDATED]
    │
    ├── Pre-installs mcp-atlassian via `uv tool install`
    ├── Renders config.yaml.j2 → ~/.hermes/config.yaml
    │       └── NEW: mcp_servers section
    └── Restarts hermes service
    │
    ▼
Hermes at startup reads config.yaml, launches mcp-atlassian subprocess:
    uvx mcp-atlassian  (with env vars for auth)
    │
    ▼
Tools registered as: mcp_work_atlassian_jira_search, mcp_work_atlassian_confluence_get_page, etc.
```

## Rendered Config Example (Hermes)

After `clm agent configure vand`, the deployed `~/.hermes/config.yaml`:

```yaml
model:
  provider: bedrock
  default: us.anthropic.claude-sonnet-4-20250514-v1:0

mcp_servers:
  work_atlassian:
    command: "uvx"
    args: ["mcp-atlassian"]
    env:
      JIRA_URL: "https://company.atlassian.net"
      JIRA_USERNAME: "dev@company.com"
      JIRA_API_TOKEN: "ATATT3xFf..."
      CONFLUENCE_URL: "https://company.atlassian.net/wiki"
      CONFLUENCE_USERNAME: "dev@company.com"
      CONFLUENCE_API_TOKEN: "ATATT3xFf..."
      JIRA_PROJECTS_FILTER: "PROJ,OPS"
      CONFLUENCE_SPACES_FILTER: "ENG,PLATFORM"
```

## Changes Required

### 1. `src/clawrium/core/integrations.py` — Replace `jira` + `confluence` with `atlassian`

**Remove** the `jira` and `confluence` entries from `INTEGRATION_TYPES`.

**Add** the unified `atlassian` type:

```python
"atlassian": {
    "description": "Atlassian Cloud (Jira + Confluence) via API token",
    "credentials": [
        {
            "key": "ATLASSIAN_URL",
            "description": "Atlassian instance URL (e.g., https://company.atlassian.net)",
            "required": True,
        },
        {
            "key": "ATLASSIAN_EMAIL",
            "description": "Account email for authentication",
            "required": True,
        },
        {
            "key": "ATLASSIAN_API_TOKEN",
            "description": "API token (create at https://id.atlassian.com/manage-profile/security/api-tokens)",
            "required": True,
        },
        {
            "key": "CONFLUENCE_SPACES_FILTER",
            "description": "Comma-separated Confluence space keys to filter (optional)",
            "required": False,
        },
        {
            "key": "JIRA_PROJECTS_FILTER",
            "description": "Comma-separated Jira project keys to filter (optional)",
            "required": False,
        },
    ],
},
```

### 2. `src/clawrium/platform/registry/hermes/templates/config.yaml.j2` — Render MCP servers

Append after the existing `model:` block:

```jinja2
{# --- MCP Servers (from assigned integrations) --- #}
{% if integrations is defined and integrations | length > 0 %}
{% set mcp_entries = [] %}
{% for name, integration in integrations.items() %}
{% if integration.type == 'atlassian' %}{% if mcp_entries.append(name) %}{% endif %}{% endif %}
{% endfor %}
{% if mcp_entries | length > 0 %}

mcp_servers:
{% for name in mcp_entries %}
{% set intg = integrations[name] %}
{% set server_name = name | replace('-', '_') %}
  {{ server_name }}:
    command: "uvx"
    args: ["mcp-atlassian"]
    env:
      JIRA_URL: "{{ intg.credentials.ATLASSIAN_URL }}"
      JIRA_USERNAME: "{{ intg.credentials.ATLASSIAN_EMAIL }}"
      JIRA_API_TOKEN: "{{ intg.credentials.ATLASSIAN_API_TOKEN }}"
      CONFLUENCE_URL: "{{ intg.credentials.ATLASSIAN_URL }}/wiki"
      CONFLUENCE_USERNAME: "{{ intg.credentials.ATLASSIAN_EMAIL }}"
      CONFLUENCE_API_TOKEN: "{{ intg.credentials.ATLASSIAN_API_TOKEN }}"
{% if intg.credentials.CONFLUENCE_SPACES_FILTER is defined and intg.credentials.CONFLUENCE_SPACES_FILTER %}
      CONFLUENCE_SPACES_FILTER: "{{ intg.credentials.CONFLUENCE_SPACES_FILTER }}"
{% endif %}
{% if intg.credentials.JIRA_PROJECTS_FILTER is defined and intg.credentials.JIRA_PROJECTS_FILTER %}
      JIRA_PROJECTS_FILTER: "{{ intg.credentials.JIRA_PROJECTS_FILTER }}"
{% endif %}
{% endfor %}
{% endif %}
{% endif %}
```

### 3. `src/clawrium/platform/registry/hermes/manifest.yaml` — Add `uv` dependency

```yaml
requirements:
  dependencies:
    - python: ">=3.11"
    - ripgrep: "latest"
    - ffmpeg: "latest"
    - uv: "latest"
```

### 4. `src/clawrium/platform/registry/hermes/playbooks/configure.yaml` — Install MCP package

Add task before service restart:

```yaml
- name: Pre-install mcp-atlassian for Atlassian integrations
  ansible.builtin.command:
    cmd: "uv tool install mcp-atlassian"
  become: true
  become_user: "{{ agent_user }}"
  when: >
    integrations is defined and
    (integrations | dict2items | selectattr('value.type', 'equalto', 'atlassian') | list | length > 0)
  register: mcp_install_result
  changed_when: "'Installed' in mcp_install_result.stdout"
  failed_when: mcp_install_result.rc != 0
```

### 5. `src/clawrium/platform/registry/openclaw/templates/.env.j2` — Update for `atlassian` type

Replace the separate `jira` and `confluence` blocks (lines 73-92) with a single
`atlassian` block that renders the same env vars openclaw expects:

```jinja2
{% elif integration.type == 'atlassian' %}
{% if integration.ATLASSIAN_URL is defined %}
JIRA_URL={{ shell_quote(integration.ATLASSIAN_URL) }}
CONFLUENCE_URL={{ shell_quote(integration.ATLASSIAN_URL + '/wiki') }}
{% endif %}
{% if integration.ATLASSIAN_EMAIL is defined %}
JIRA_EMAIL={{ shell_quote(integration.ATLASSIAN_EMAIL) }}
CONFLUENCE_EMAIL={{ shell_quote(integration.ATLASSIAN_EMAIL) }}
{% endif %}
{% if integration.ATLASSIAN_API_TOKEN is defined %}
JIRA_API_TOKEN={{ shell_quote(integration.ATLASSIAN_API_TOKEN) }}
CONFLUENCE_API_TOKEN={{ shell_quote(integration.ATLASSIAN_API_TOKEN) }}
{% endif %}
```

### 6. `docs/agent-support/hermes.md` — Update support matrix

- MCP server registration: Supported (atlassian)
- Document the headless auth flow

### 7. Tests — Update all references

**`tests/test_core_integrations.py`:**
- Update `expected_types` set: remove `jira`, `confluence`, add `atlassian`
- Update all test fixtures using `type: "jira"` → `type: "atlassian"`
- Update credential key assertions

**`tests/test_lifecycle_integrations.py`:**
- Update fixture `type: "jira"` → `type: "atlassian"`

**`tests/test_cli_integration.py`:**
- Update assertions checking for "jira"/"confluence" in output → "atlassian"
- Update fixture types

**`tests/test_hermes_configure.py` (new tests):**
- `test_config_template_renders_mcp_servers_with_atlassian_integration`
- `test_config_template_no_mcp_servers_without_integrations`
- `test_config_template_mcp_server_name_sanitization`
- `test_config_template_mcp_optional_filters`
- `test_config_template_multiple_atlassian_integrations`

## Migration Impact

### Breaking Change: `jira` and `confluence` types removed (no auto-migration)

Any existing integrations stored as `type: "jira"` or `type: "confluence"` in
`~/.config/clawrium/integrations.json` are invalid after this change. There is
**no automatic migration** — by design, the codebase keeps a single source of
truth for Atlassian credentials and does not carry compatibility shims.

**Required user steps:**
1. `clm integration remove <old-jira-name>` and `clm integration remove <old-confluence-name>`
2. `clm integration add <new-name> --type atlassian` with the unified credentials

CLI commands that hit a stale type (manual JSON edit, downgrade/upgrade cross)
print a clean remediation message instead of a traceback (`clm integration show`
/ `credentials`), but no automatic rewrite is performed.

## User Workflow

```bash
# One-time: generate API token (from any browser, any machine)
# https://id.atlassian.com/manage-profile/security/api-tokens

# Register integration (headless CLI)
clm integration add work-atlassian --type atlassian
# Prompts for: ATLASSIAN_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN
# Optionally: CONFLUENCE_SPACES_FILTER, JIRA_PROJECTS_FILTER

# Assign to agent
clm agent integration add vand work-atlassian

# Deploy configuration (renders MCP config, installs package, restarts)
clm agent configure vand

# Verify
clm agent chat vand
> list my open jira tickets
> search confluence for onboarding docs
```

## Headless Guarantees

| Concern | Resolution |
|---------|-----------|
| OAuth needs browser | Not used. API token auth only. |
| Token refresh | Not needed. API tokens are long-lived (until manually revoked). |
| `--oauth-setup` flag | Never invoked. |
| MCP server startup | `uvx mcp-atlassian` with env vars. No interactive prompts. |
| Package installation | `uv tool install` is non-interactive. |

## Out of Scope

- Atlassian Server/Data Center PAT auth (future: add `ATLASSIAN_PERSONAL_TOKEN` field)
- OAuth 2.0 support (requires browser; fundamentally incompatible with headless)
- HTTP/SSE transport for mcp-atlassian (stdio is simpler for single-agent use)
- Tool filtering (`--enabled-tools`, `--toolsets`) — can be added later as optional credentials

## Dependencies

- `mcp-atlassian` >= 0.21.1 (PyPI, installed via `uvx`)
- `uv` >= 0.1.0 (for `uvx` subprocess runner)
- Hermes >= 2026.5.7 (native `mcp_servers:` config support)

## Risks

| Risk | Mitigation |
|------|-----------|
| `mcp-atlassian` breaking changes | Pin version in `uv tool install mcp-atlassian==0.21.1` |
| `uvx` not in PATH for agent user | Install playbook ensures `uv` is available system-wide |
| Large tool surface (72 tools) | Use `TOOLSETS` env var to limit to core set in future iteration |
| API token permissions too broad | Document minimum required Atlassian permissions |
| Breaking existing `jira`/`confluence` integrations | Auto-migration in `load_integrations()` |

## File Change Summary

| File | Change |
|------|--------|
| `src/clawrium/core/integrations.py` | Remove `jira`+`confluence`, add `atlassian`, add migration |
| `src/clawrium/platform/registry/hermes/templates/config.yaml.j2` | Add `mcp_servers:` rendering |
| `src/clawrium/platform/registry/hermes/manifest.yaml` | Add `uv` dependency |
| `src/clawrium/platform/registry/hermes/playbooks/configure.yaml` | Add mcp-atlassian install task |
| `src/clawrium/platform/registry/openclaw/templates/.env.j2` | Replace jira/confluence blocks with atlassian |
| `docs/agent-support/hermes.md` | Update MCP support status |
| `tests/test_core_integrations.py` | Update for new type |
| `tests/test_lifecycle_integrations.py` | Update fixtures |
| `tests/test_cli_integration.py` | Update assertions |
| `tests/test_hermes_configure.py` | Add MCP rendering tests |

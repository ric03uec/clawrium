# Integration Commands

Manage external service integrations (GitHub, Atlassian, etc.) for agents.

```bash
clm integration <command> [options]
```

Integrations connect your agents to external services like GitHub and Atlassian (Jira + Confluence). Credentials are stored securely in `~/.config/clawrium/secrets.json` keyed by integration name, isolated from per-agent and provider secrets.

## Commands

| Command | Description |
|---------|-------------|
| [`clm integration types`](#clm-integration-types) | List supported integration types |
| [`clm integration list`](#clm-integration-list) | List all configured integrations |
| [`clm integration add`](#clm-integration-add) | Add a new integration |
| [`clm integration show`](#clm-integration-show) | Show details of a configured integration |
| [`clm integration remove`](#clm-integration-remove) | Remove an integration |
| [`clm integration credentials`](#clm-integration-credentials) | View or update credentials |

---

## clm integration types

List supported integration types.

```bash
clm integration types
```

### Example

```bash
$ clm integration types
Supported integration types:

  atlassian   - Atlassian Cloud (Jira + Confluence) via API token
    Required credentials: 3
  github      - GitHub for code hosting, PRs, and issues
    Required credentials: 1
  gitlab      - GitLab for code hosting, MRs, and issues
    Required credentials: 1
  linear      - Linear for issue tracking and project management
    Required credentials: 1
  notion      - Notion for documentation and workspace management
    Required credentials: 1
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Types listed successfully |

---

## clm integration list

List all configured integrations.

```bash
clm integration list
```

### Example

```bash
$ clm integration list
                       Configured Integrations
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name              ┃ Type       ┃ Credentials    ┃ Added      ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ my-github         │ github     │ 1 configured   │ 2026-04-01 │
│ work-atlassian    │ atlassian  │ 3 configured   │ 2026-05-14 │
└───────────────────┴────────────┴────────────────┴────────────┘
```

Stale records (e.g. a `jira` or `confluence` row left over from a previous release) are surfaced with a `(unknown)` indicator in the Type column so they're easy to spot during a fleet audit. See the [Atlassian integration migration notes](../../agent-support/integrations/atlassian.md#migrating-from-the-old-jira--confluence-types).

No integrations configured:

```bash
$ clm integration list
No integrations configured. Use 'clm integration add' to add one.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Integrations listed successfully |
| 1 | Configuration file corrupted |

---

## clm integration add

Add a new external service integration.

```bash
clm integration add <name> --type <type>
```

Credentials are collected securely via interactive prompts.

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Unique name for this integration |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--type` | `-t` | Integration type (required): atlassian, github, gitlab, linear, notion |

### Examples

Add a GitHub integration:

```bash
$ clm integration add my-github --type github
Enter GitHub personal access token: ********
Integration 'my-github' added successfully!
```

Add an Atlassian integration (single record covers both Jira and Confluence):

```bash
$ clm integration add work-atlassian --type atlassian
Atlassian instance URL (e.g., https://company.atlassian.net): https://mycompany.atlassian.net
Account email for authentication: user@company.com
API token (create at https://id.atlassian.com/manage-profile/security/api-tokens): ********
Comma-separated Confluence space keys to filter (optional):
Comma-separated Jira project keys to filter (optional):

Integration 'work-atlassian' added successfully!
```

See [Atlassian integration](../../agent-support/integrations/atlassian.md) for the end-to-end flow (creating the API token, assigning the integration to an agent, and the MCP wiring on Hermes).

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Integration added successfully |
| 1 | Invalid name, invalid type, or duplicate integration |

---

## clm integration show

Show details of a configured integration.

```bash
clm integration show <name>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Integration name to show |

### Example

```bash
$ clm integration show my-github
Integration: my-github
Type: github
Added: 2026-04-01T10:30:00Z
Credential: ghp_...abc (masked)

Used by agents:
  - opc-work
  - opc-home
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Integration details shown |
| 1 | Integration not found |

---

## clm integration remove

Remove an integration configuration.

```bash
clm integration remove <name> [--force]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Integration name to remove |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--force` | `-f` | Skip confirmation prompt |

### Examples

```bash
$ clm integration remove old-github
Remove integration 'old-github'? This cannot be undone. [y/N]: y
Integration 'old-github' removed successfully.
```

Force removal:

```bash
$ clm integration remove old-github --force
Integration 'old-github' removed successfully.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Integration removed successfully or operation cancelled |
| 1 | Integration not found or removal failed |

---

## clm integration credentials

View or update credentials for an integration.

```bash
clm integration credentials <name> [--update]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Integration name |

### Options

| Option | Description |
|--------|-------------|
| `--update` | Update credentials (will prompt for new values) |

### Examples

View credentials (masked):

```bash
$ clm integration credentials my-github
Integration: my-github
Type: github
Credential: ghp_...abc (masked)
Last updated: 2026-04-01T10:30:00Z
```

Update credentials:

```bash
$ clm integration credentials my-github --update
Enter new GitHub personal access token: ********
Credentials updated for 'my-github'.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Credentials shown or updated |
| 1 | Integration not found or update failed |

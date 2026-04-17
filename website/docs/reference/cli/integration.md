# Integration Commands

Manage external service integrations (GitHub, Jira, etc.) for agents.

```bash
clm integration <command> [options]
```

Integrations connect your agents to external services like GitHub, Jira, and Confluence. Credentials are stored securely in `~/.config/clawrium/secrets.yml`.

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

  github      - GitHub repositories, issues, and PRs
  gitlab      - GitLab repositories and merge requests
  jira        - Jira issues and projects
  confluence  - Confluence pages and spaces
  linear      - Linear issues and projects
  notion      - Notion pages and databases
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
┏━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name         ┃ Type     ┃ Credential          ┃ Added      ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ my-github    │ github   │ ghp_...abc          │ 2026-04-01 │
│ work-jira    │ jira     │ https://...         │ 2026-04-02 │
└──────────────┴──────────┴─────────────────────┴────────────┘
```

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
| `--type` | `-t` | Integration type (required): github, gitlab, jira, confluence, linear, notion |

### Examples

Add a GitHub integration:

```bash
$ clm integration add my-github --type github
Enter GitHub personal access token: ********
Integration 'my-github' added successfully!
```

Add a Jira integration:

```bash
$ clm integration add work-jira --type jira
Enter Jira instance URL: https://mycompany.atlassian.net
Enter Jira email: user@company.com
Enter Jira API token: ********
Integration 'work-jira' added successfully!
```

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

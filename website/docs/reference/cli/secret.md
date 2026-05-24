# Secret Commands

Manage secrets for claw instances.

```bash
clawctl agent secret <command> [options]
```

Secrets are stored locally in `~/.config/clawrium/secrets.yml` and are never transmitted to remote hosts in plain text. Each claw instance has its own isolated secret namespace.

## Commands

| Command | Description |
|---------|-------------|
| [`clawctl agent secret create`](#clawctl-agent-secret-create) | Set a secret value for a claw instance |
| [`clawctl agent secret get --agent`](#clawctl-agent-secret-get---agent) | List secrets for a claw instance |
| [`clawctl agent secret delete`](#clawctl-agent-secret-delete) | Remove a secret from a claw instance |

---

## clawctl agent secret create

Set a secret value for a claw instance.

```bash
clawctl agent secret create <claw_name> <key> [options]
```

Prompts for the value using masked input (not visible on screen).

### Arguments

| Argument | Description |
|----------|-------------|
| `claw_name` | Claw instance name (e.g., `zc-work`) |
| `key` | Secret key name (e.g., `ANTHROPIC_API_KEY`) |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--description` | `-d` | Description of the secret |
| `--yes` | `-y` | Skip overwrite confirmation |

### Example

```bash
$ clawctl agent secret create zc-work ANTHROPIC_API_KEY -d "Claude API key for work"
Enter value for ANTHROPIC_API_KEY: ********
Secret 'ANTHROPIC_API_KEY' created for 'zc-work'.
```

Overwriting an existing secret:

```bash
$ clawctl agent secret create zc-work ANTHROPIC_API_KEY
Secret 'ANTHROPIC_API_KEY' already exists for 'zc-work'
  Description: Claude API key for work
  Last updated: 2026-04-01T10:30:00Z
Overwrite this secret? [y/N]: y
Enter value for ANTHROPIC_API_KEY: ********
Secret 'ANTHROPIC_API_KEY' updated for 'zc-work'.
```

### Key Naming Rules

Secret keys must follow environment variable naming conventions:
- Uppercase letters only
- Digits allowed (but not as first character)
- Underscores allowed
- No spaces or special characters

Valid examples: `ANTHROPIC_API_KEY`, `OPENAI_KEY`, `AWS_ACCESS_KEY_ID`

Invalid examples: `my-api-key`, `apiKey`, `123_KEY`

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Secret set successfully or operation cancelled |
| 1 | Claw not found, invalid key name, or empty value |

---

## clawctl agent secret get --agent

List secrets for a claw instance.

```bash
clawctl agent secret get --agent <claw_name>
```

Shows secret keys and metadata. Values are never displayed. Also shows missing required secrets defined in the claw's manifest.

### Arguments

| Argument | Description |
|----------|-------------|
| `claw_name` | Claw instance name (e.g., `zc-kevin`) |

### Example

```bash
$ clawctl agent secret get --agent zc-work

Claw: zc-work (192.168.1.100)
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Key                ┃ Description                ┃ Updated    ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ ANTHROPIC_API_KEY  │ Claude API key for work    │ 2026-04-01 │
│ GITHUB_TOKEN       │ GitHub personal access     │ 2026-04-02 │
└────────────────────┴────────────────────────────┴────────────┘
```

With missing required secrets:

```bash
$ clawctl agent secret get --agent zc-work

Claw: zc-work (192.168.1.100)
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Key                ┃ Description                ┃ Updated    ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ ANTHROPIC_API_KEY  │ Claude API key for work    │ 2026-04-01 │
└────────────────────┴────────────────────────────┴────────────┘
  Missing: GITHUB_TOKEN (GitHub access for repository features)
```

No secrets configured:

```bash
$ clawctl agent secret get --agent zc-new

Claw: zc-new (192.168.1.100)
  No secrets set
  Missing: ANTHROPIC_API_KEY (Required for Claude API access)
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Secrets listed successfully |
| 1 | Claw not found or secrets file corrupted |

---

## clawctl agent secret delete

Remove a secret from a claw instance.

```bash
clawctl agent secret delete <claw_name> <key> [--force]
```

Prompts for confirmation unless `--force` is specified.

### Arguments

| Argument | Description |
|----------|-------------|
| `claw_name` | Claw instance name |
| `key` | Secret key to remove |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--force` | `-f` | Skip confirmation prompt |

### Example

```bash
$ clawctl agent secret delete zc-work GITHUB_TOKEN
Remove secret 'GITHUB_TOKEN' from 'zc-work'? This cannot be undone. [y/N]: y
Secret 'GITHUB_TOKEN' removed from 'zc-work'.
```

Force removal without confirmation:

```bash
$ clawctl agent secret delete zc-work GITHUB_TOKEN --force
Secret 'GITHUB_TOKEN' removed from 'zc-work'.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Secret removed successfully or operation cancelled |
| 1 | Claw not found, secret not found, or removal failed |

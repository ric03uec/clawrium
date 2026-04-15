---
sidebar_position: 3
description: Manage secrets and API keys for claw instances securely with Clawrium's secret management commands.
keywords: [secrets, API keys, credentials, encryption, security]
---

# Secret Management

Claws often require secrets like API keys to function. Clawrium provides commands to securely manage these secrets per claw instance.

## Understanding Secrets

Each claw type defines two categories of secrets in its manifest:

| Category | Description |
|----------|-------------|
| **Required** | Claw installation fails if these are missing |
| **Optional** | Claw works without them but with reduced functionality |

## Viewing Secret Requirements

### Check Registry Manifest

Use `clm registry show` to see what secrets a claw type expects:

```bash
clm registry show zeroclaw
```

Example output shows:
```
Required Secrets:
  LLM_PROVIDER_URL    LLM API endpoint URL (e.g., http://192.168.1.100:11434)
  LLM_MODEL           Model name to use (e.g., llama3, gpt-4)

Optional Secrets:
  LLM_API_KEY         API key for LLM provider (optional for local)
```

### Check Claw Instance

For an existing claw instance, list configured secrets and identify missing required ones:

```bash
clm secret list zc-homelab
```

Example output:
```
Secrets for zc-homelab:

Configured:
  LLM_PROVIDER_URL    (set 2026-04-01)

Missing Required:
  LLM_MODEL           Model name to use (e.g., llama3, gpt-4)

Optional (not set):
  LLM_API_KEY         API key for LLM provider (optional for local)
```

:::note
Secret values are never displayed. Only keys, descriptions, and metadata are shown.
:::

## Setting Secrets

Use `clm secret set` to configure a secret:

```bash
clm secret set <claw-name> <key>
```

The value is entered via masked prompt (not visible on screen):

```bash
$ clm secret set zc-homelab LLM_PROVIDER_URL
Enter value for LLM_PROVIDER_URL: ********
Secret set successfully.
```

### Options

```bash
# Add a description
clm secret set zc-homelab LLM_PROVIDER_URL -d "Production Ollama server"

# Skip confirmation when overwriting
clm secret set zc-homelab LLM_PROVIDER_URL -y
```

## Removing Secrets

Remove a secret from a claw instance:

```bash
clm secret remove zc-homelab LLM_API_KEY
```

:::warning
Removing a required secret will cause the claw to fail on next restart. You'll need to set it again before the claw can run.
:::

## Secret Storage

Secrets are stored in `~/.config/clawrium/secrets/<claw-name>/<key>`:

```
~/.config/clawrium/
└── secrets/
    └── zc-homelab/
        ├── LLM_PROVIDER_URL
        └── LLM_MODEL
```

Each secret file:
- Has 0600 permissions (readable only by owner)
- Contains the encrypted value
- Is synced to the host during claw deployment

## Common Secrets by Claw Type

### zeroclaw

| Secret | Required | Description |
|--------|----------|-------------|
| `LLM_PROVIDER_URL` | Yes | LLM API endpoint (e.g., `http://192.168.1.100:11434` for Ollama) |
| `LLM_MODEL` | Yes | Model to use (e.g., `llama3`, `mistral`) |
| `LLM_API_KEY` | No | API key if your LLM provider requires authentication |

### openclaw

| Secret | Required | Description |
|--------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for LLM requests |
| `ANTHROPIC_API_KEY` | No | Anthropic API key for Claude models |

## Best Practices

1. **Set secrets before installing** - Required secrets must exist before `clm agent install` succeeds
2. **Use descriptive comments** - Add `-d` descriptions to remember what each secret is for
3. **Rotate periodically** - Update secrets if you rotate API keys
4. **One claw, one set** - Each claw instance has its own secrets; they're not shared

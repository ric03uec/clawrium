# Provider Commands

Manage inference providers (LLM APIs) for claw instances.

```bash
clawctl provider <command> [options]
```

Providers are configured locally in `~/.config/clawrium/providers.json`. API keys and AWS credentials are stored securely in `~/.config/clawrium/secrets.yml` and are never transmitted in plain text.

> **Provider Types:** Most providers use API keys for authentication. AWS Bedrock requires AWS Access Key and Secret Key instead.

## Commands

| Command | Description |
|---------|-------------|
| [`clawctl provider registry create`](#clawctl-provider-registry-create) | Add a new inference provider |
| [`clawctl provider registry get`](#clawctl-provider-registry-get) | List all configured providers |
| [`clawctl provider registry edit`](#clawctl-provider-registry-edit) | Edit an existing provider |
| [`clawctl provider registry delete`](#clawctl-provider-registry-delete) | Remove a provider |
| [`clawctl provider registry get --types`](#clawctl-provider-registry-get---types) | List provider types or show models for a type |
| [`clawctl provider registry refresh`](#clawctl-provider-registry-refresh) | Refresh Ollama models |

---

## clawctl provider registry create

Add a new inference provider.

```bash
clawctl provider registry create <name> --type <type> [options]
```

API keys are collected securely via interactive prompt (not visible in process listing).

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Unique name for this provider configuration |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--type` | `-t` | Provider type (required): openai, anthropic, openrouter, bedrock, vertex, zai, ollama |
| `--model` | `-m` | Default model to use |
| `--url` | `-u` | Server URL (required for Ollama) |

### Examples

Add an OpenAI provider:

```bash
$ clawctl provider registry create myopenai --type openai
API key: ********
Available models for openai:
  1. gpt-4o
  2. gpt-4o-mini
  3. gpt-4-turbo
Select default model (number or name): 1
Provider 'myopenai' added successfully!
```

Add an Anthropic provider with a specific model:

```bash
$ clawctl provider registry create work-claude --type anthropic --model claude-sonnet-4-20250514
API key: ********
Provider 'work-claude' added successfully!
```

Add a local Ollama provider:

```bash
$ clawctl provider registry create local-llm --type ollama --url http://myserver.example.com:11434
Connecting to Ollama server at http://myserver.example.com:11434...
Found 3 models
Available models:
  1. llama3.2:latest
  2. mistral:latest
  3. codellama:latest
Select default model (number or name): 1
Provider 'local-llm' added successfully!
```

Add an AWS Bedrock provider:

```bash
$ clawctl provider registry create my-bedrock --type bedrock
AWS Bedrock requires Access Key and Secret Key
AWS Access Key ID: ********
**
AWS Secret Access Key: ********
**
Available models for bedrock:
  1. anthropic.claude-opus-4-20250514-v1:0
  2. anthropic.claude-sonnet-4-20250514-v1:0
  3. anthropic.claude-3-5-sonnet-20241022-v2:0
Select default model (number or name): 2
Provider 'my-bedrock' added successfully!
```

> **Note:** The `**` shown after entering credentials provides visual confirmation that the paste was successful, since the input is hidden.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Provider added successfully or operation cancelled |
| 1 | Invalid name, invalid type, duplicate provider, or connection failed |

---

## clawctl provider registry get

List all configured providers.

```bash
clawctl provider registry get
```

Displays a table of all configured providers with masked API keys.

### Example

```bash
$ clawctl provider registry get
                    Configured Providers
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name         ┃ Type      ┃ Model            ┃ API Key           ┃ Added      ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ myopenai     │ openai    │ gpt-4o           │ sk-p...4xYz       │ 2026-04-01 │
│ work-claude  │ anthropic │ claude-sonnet-4  │ sk-a...9abc       │ 2026-04-02 │
│ local-llm    │ ollama    │ llama3.2:latest  │ http://myserver.. │ 2026-04-03 │
└──────────────┴───────────┴──────────────────┴───────────────────┴────────────┘
```

No providers configured:

```bash
$ clawctl provider registry get
No providers configured. Use 'clawctl provider registry create' to add a provider.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Providers listed successfully |
| 1 | Providers file corrupted |

---

## clawctl provider registry edit

Edit an existing provider configuration.

```bash
clawctl provider registry edit <name> [options]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Provider name to edit |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--model` | `-m` | New default model |
| `--url` | `-u` | New server URL (Ollama only) |
| `--update-key` | | Update API key (will prompt securely) |

### Examples

Change default model:

```bash
$ clawctl provider registry edit myopenai --model gpt-4o-mini
Provider 'myopenai' updated successfully!
```

Update Ollama server URL:

```bash
$ clawctl provider registry edit local-llm --url http://newserver.example.com:11434
Connecting to Ollama server at http://newserver.example.com:11434...
Found 5 models
Provider 'local-llm' updated successfully!
```

Update API key:

```bash
$ clawctl provider registry edit myopenai --update-key
New API key: ********
API key updated.
Provider 'myopenai' updated successfully!
```

Update AWS Bedrock credentials:

```bash
$ clawctl provider registry edit my-bedrock --update-key
AWS Bedrock requires Access Key and Secret Key
New AWS Access Key ID: ********
**
New AWS Secret Access Key: ********
**
AWS credentials updated.
Provider 'my-bedrock' updated successfully!
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Provider updated successfully or no changes specified |
| 1 | Provider not found, invalid URL, or connection failed |

---

## clawctl provider registry delete

Remove a provider configuration.

```bash
clawctl provider registry delete <name> [--force]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Provider name to remove |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--force` | `-f` | Skip confirmation prompt |

### Examples

```bash
$ clawctl provider registry delete myopenai
Remove provider 'myopenai'? This cannot be undone. [y/N]: y
Provider 'myopenai' removed successfully.
```

Force removal:

```bash
$ clawctl provider registry delete old-provider --force
Provider 'old-provider' removed successfully.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Provider removed successfully or operation cancelled |
| 1 | Provider not found or removal failed |

---

## clawctl provider registry get --types

List supported provider types or show models for a specific type.

```bash
clawctl provider registry get --types [<type>] [models]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `type` | (Optional) Provider type to inspect (openai, anthropic, etc.) |
| `models` | (Optional) Action to show available models for the type |

### Examples

List all supported provider types:

```bash
$ clawctl provider registry get --types
Supported provider types:

  anthropic - 7 models
  bedrock - 8 models (SDK-based)
  ollama - Self-hosted (dynamic model discovery)
  openai - 51 models
  openrouter - 200+ models
  vertex - 6 models (SDK-based)
  zai - 8 models
```

Show available actions for a type:

```bash
$ clawctl provider registry get --types openai
Provider type: openai

Available actions:
  clawctl provider registry get --types openai models  # List available models
```

List models for a provider type:

```bash
$ clawctl provider registry get --types openai models
Available models for openai (51 models)

  ID                   Name             Lab       Context
  gpt-4o               GPT-4o           OpenAI    128K
  gpt-4o-mini          GPT-4o mini      OpenAI    128K
  gpt-4-turbo          GPT-4 Turbo      OpenAI    128K
  ...
```

List models for multi-lab provider (grouped by lab):

```bash
$ clawctl provider registry get --types openrouter models
Available models for openrouter (200+ models from 8 labs)

Anthropic (5 models)
  ID                          Name                Lab         Context
  anthropic/claude-opus-4     Claude Opus 4       Anthropic   200K
  ...

OpenAI (10 models)
  ID                          Name                Lab         Context
  openai/gpt-4o               GPT-4o              OpenAI      128K
  ...
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Types or models listed successfully |
| 1 | Invalid provider type or unknown action |

---

## clawctl provider registry refresh

Refresh available models from an Ollama server.

```bash
clawctl provider registry refresh <name>
```

Re-fetches the model list from the Ollama server and updates the saved configuration.

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Ollama provider name to refresh |

### Example

```bash
$ clawctl provider registry refresh local-llm
Connecting to Ollama server at http://myserver.example.com:11434...
Found 5 models

Provider 'local-llm' updated with 5 models:
  llama3.2:latest
  mistral:latest
  codellama:latest
  phi3:latest
  gemma:latest
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Provider refreshed successfully |
| 1 | Provider not found, not Ollama type, or connection failed |

# Provider Commands

Manage inference providers (LLM APIs) for claw instances.

```bash
clm provider <command> [options]
```

Providers are configured locally in `~/.config/clawrium/providers.json`. API keys and AWS credentials are stored securely in `~/.config/clawrium/secrets.yml` and are never transmitted in plain text.

> **Provider Types:** Most providers use API keys for authentication. AWS Bedrock requires AWS Access Key and Secret Key instead.

## Commands

| Command | Description |
|---------|-------------|
| [`clm provider add`](#clm-provider-add) | Add a new inference provider |
| [`clm provider list`](#clm-provider-list) | List all configured providers |
| [`clm provider edit`](#clm-provider-edit) | Edit an existing provider |
| [`clm provider remove`](#clm-provider-remove) | Remove a provider |
| [`clm provider types`](#clm-provider-types) | List provider types or show models for a type |
| [`clm provider refresh`](#clm-provider-refresh) | Refresh Ollama models |

---

## clm provider add

Add a new inference provider.

```bash
clm provider add <name> --type <type> [options]
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
$ clm provider add myopenai --type openai
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
$ clm provider add work-claude --type anthropic --model claude-sonnet-4-20250514
API key: ********
Provider 'work-claude' added successfully!
```

Add a local Ollama provider:

```bash
$ clm provider add local-llm --type ollama --url http://myserver.example.com:11434
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
$ clm provider add my-bedrock --type bedrock
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

## clm provider list

List all configured providers.

```bash
clm provider list
```

Displays a table of all configured providers with masked API keys.

### Example

```bash
$ clm provider list
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
$ clm provider list
No providers configured. Use 'clm provider add' to add a provider.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Providers listed successfully |
| 1 | Providers file corrupted |

---

## clm provider edit

Edit an existing provider configuration.

```bash
clm provider edit <name> [options]
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
$ clm provider edit myopenai --model gpt-4o-mini
Provider 'myopenai' updated successfully!
```

Update Ollama server URL:

```bash
$ clm provider edit local-llm --url http://newserver.example.com:11434
Connecting to Ollama server at http://newserver.example.com:11434...
Found 5 models
Provider 'local-llm' updated successfully!
```

Update API key:

```bash
$ clm provider edit myopenai --update-key
New API key: ********
API key updated.
Provider 'myopenai' updated successfully!
```

Update AWS Bedrock credentials:

```bash
$ clm provider edit my-bedrock --update-key
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

## clm provider remove

Remove a provider configuration.

```bash
clm provider remove <name> [--force]
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
$ clm provider remove myopenai
Remove provider 'myopenai'? This cannot be undone. [y/N]: y
Provider 'myopenai' removed successfully.
```

Force removal:

```bash
$ clm provider remove old-provider --force
Provider 'old-provider' removed successfully.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Provider removed successfully or operation cancelled |
| 1 | Provider not found or removal failed |

---

## clm provider types

List supported provider types or show models for a specific type.

```bash
clm provider types [<type>] [models]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `type` | (Optional) Provider type to inspect (openai, anthropic, etc.) |
| `models` | (Optional) Action to show available models for the type |

### Examples

List all supported provider types:

```bash
$ clm provider types
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
$ clm provider types openai
Provider type: openai

Available actions:
  clm provider types openai models  # List available models
```

List models for a provider type:

```bash
$ clm provider types openai models
Available models for openai (51 models)

  ID                   Name             Lab       Context
  gpt-4o               GPT-4o           OpenAI    128K
  gpt-4o-mini          GPT-4o mini      OpenAI    128K
  gpt-4-turbo          GPT-4 Turbo      OpenAI    128K
  ...
```

List models for multi-lab provider (grouped by lab):

```bash
$ clm provider types openrouter models
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

## clm provider refresh

Refresh available models from an Ollama server.

```bash
clm provider refresh <name>
```

Re-fetches the model list from the Ollama server and updates the saved configuration.

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Ollama provider name to refresh |

### Example

```bash
$ clm provider refresh local-llm
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

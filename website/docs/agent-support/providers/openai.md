# OpenAI

**Status:** ✅ Supported

Official OpenAI API integration for GPT models.

## Supported Models

<!-- MODEL-TABLE:START -->
| Model ID | Name | Context |
|----------|------|---------|
| `codex-mini-latest` | Codex Mini | 200K |
| `gpt-3.5-turbo` | GPT-3.5-turbo | 16K |
| `gpt-4` | GPT-4 | 8K |
| `gpt-4-turbo` | GPT-4 Turbo | 128K |
| `gpt-4.1` | GPT-4.1 | 1M |
| `gpt-4.1-mini` | GPT-4.1 mini | 1M |
| `gpt-4.1-nano` | GPT-4.1 nano | 1M |
| `gpt-4o` | GPT-4o | 128K |
| `gpt-4o-2024-05-13` | GPT-4o (2024-05-13) | 128K |
| `gpt-4o-2024-08-06` | GPT-4o (2024-08-06) | 128K |
| `gpt-4o-2024-11-20` | GPT-4o (2024-11-20) | 128K |
| `gpt-4o-mini` | GPT-4o mini | 128K |
| `gpt-5` | GPT-5 | 400K |
| `gpt-5-chat-latest` | GPT-5 Chat (latest) | 400K |
| `gpt-5-mini` | GPT-5 Mini | 400K |
| `gpt-5-nano` | GPT-5 Nano | 400K |
| `gpt-5-pro` | GPT-5 Pro | 400K |
| `gpt-5-codex` | GPT-5-Codex | 400K |
| `gpt-5.1` | GPT-5.1 | 400K |
| `gpt-5.1-chat-latest` | GPT-5.1 Chat | 128K |
| `gpt-5.1-codex` | GPT-5.1 Codex | 400K |
| `gpt-5.1-codex-max` | GPT-5.1 Codex Max | 400K |
| `gpt-5.1-codex-mini` | GPT-5.1 Codex mini | 400K |
| `gpt-5.2` | GPT-5.2 | 400K |
| `gpt-5.2-chat-latest` | GPT-5.2 Chat | 128K |
| `gpt-5.2-codex` | GPT-5.2 Codex | 400K |
| `gpt-5.2-pro` | GPT-5.2 Pro | 400K |
| `gpt-5.3-chat-latest` | GPT-5.3 Chat (latest) | 128K |
| `gpt-5.3-codex` | GPT-5.3 Codex | 400K |
| `gpt-5.3-codex-spark` | GPT-5.3 Codex Spark | 128K |
| `gpt-5.4` | GPT-5.4 | 1M |
| `gpt-5.4-pro` | GPT-5.4 Pro | 1M |
| `gpt-5.4-mini` | GPT-5.4 mini | 400K |
| `gpt-5.4-nano` | GPT-5.4 nano | 400K |
| `chatgpt-image-latest` | chatgpt-image-latest | - |
| `gpt-image-1` | gpt-image-1 | - |
| `gpt-image-1-mini` | gpt-image-1-mini | - |
| `gpt-image-1.5` | gpt-image-1.5 | - |
| `o1` | o1 | 200K |
| `o1-mini` | o1-mini | 128K |
| `o1-preview` | o1-preview | 128K |
| `o1-pro` | o1-pro | 200K |
| `o3` | o3 | 200K |
| `o3-deep-research` | o3-deep-research | 200K |
| `o3-mini` | o3-mini | 200K |
| `o3-pro` | o3-pro | 200K |
| `o4-mini` | o4-mini | 200K |
| `o4-mini-deep-research` | o4-mini-deep-research | 200K |
| `text-embedding-3-large` | text-embedding-3-large | 8K |
| `text-embedding-3-small` | text-embedding-3-small | 8K |
| `text-embedding-ada-002` | text-embedding-ada-002 | 8K |
<!-- MODEL-TABLE:END -->

## Setup

### 1. Get API Key

1. Visit [OpenAI Platform](https://platform.openai.com/)
2. Create or log in to your account
3. Go to **API keys** → **Create new secret key**
4. Copy the key (starts with `sk-`)

### 2. Add to Clawrium

```bash
clm provider add my-openai --type openai
```

You will be prompted to enter your API key securely.

### 3. Select Model

Choose a default model during setup:
- `gpt-4o` (recommended for most use cases)
- `gpt-4o-mini` (faster, cheaper)
- `gpt-4-turbo` (if you need specific features)

## Configuration

```bash
# View provider details
clm provider list

# Change default model
clm provider edit my-openai --model gpt-4o-mini

# Update API key
clm provider edit my-openai --update-key

# Remove provider
clm provider remove my-openai
```

## Pricing Considerations

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| gpt-4o | $5.00 | $15.00 |
| gpt-4o-mini | $0.15 | $0.60 |
| gpt-4-turbo | $10.00 | $30.00 |
| gpt-3.5-turbo | $0.50 | $1.50 |

*Prices subject to change. Check [OpenAI pricing](https://openai.com/pricing) for current rates.*

## Usage in Agents

During agent onboarding:

```bash
clm agent configure my-agent
# Select my-openai when prompted for provider
```

Or change later:

```bash
clm agent configure my-agent --stage providers
```

## Troubleshooting

**"Invalid API key"**
- Verify the key starts with `sk-`
- Ensure the key hasn't been revoked
- Check your OpenAI account has available credits

**"Rate limit exceeded"**
- Check your OpenAI usage dashboard
- Consider upgrading your account tier
- Implement retry logic in your agent

**"Model not found"**
- Verify the model name is correct
- Some models may require beta access
- Check [OpenAI model documentation](https://platform.openai.com/docs/models)

---

[Back to Providers](index.md)

# OpenRouter

**Status:** ✅ Supported

OpenRouter provides unified access to multiple AI models through a single API.

## Supported Models

OpenRouter supports 100+ models including:

- `anthropic/claude-opus-4`
- `anthropic/claude-sonnet-4`
- `openai/gpt-4o`
- `openai/o1`
- `google/gemini-2.5-pro`
- `meta-llama/llama-4-maverick`
- `deepseek/deepseek-chat-v3`
- `deepseek/deepseek-r1`
- `qwen/qwen3-235b`

## Setup

### 1. Get API Key

1. Visit [OpenRouter](https://openrouter.ai/)
2. Create or log in to your account
3. Go to **Keys** → **Create Key**
4. Copy the key

### 2. Add to Clawrium

```bash
clm provider add my-router --type openrouter
```

You will be prompted to enter your API key securely.

### 3. Select Model

Choose from OpenRouter's extensive model list:
- `anthropic/claude-opus-4` (best quality)
- `google/gemini-2.5-pro` (competitive pricing)
- `openai/gpt-4o` (familiar API)

## Configuration

```bash
# View provider details
clm provider list

# Change default model
clm provider edit my-router --model anthropic/claude-sonnet-4

# Update API key
clm provider edit my-router --update-key

# Remove provider
clm provider remove my-router
```

## Benefits

- **Model fallback:** Automatically route to available models
- **Unified billing:** One account for multiple providers
- **Competitive pricing:** Often cheaper than direct provider access
- **Model variety:** Access to open-source and proprietary models

## Pricing

OpenRouter adds a small fee on top of provider costs. Check [OpenRouter pricing](https://openrouter.ai/docs#pricing) for current rates.

## Usage in Agents

During agent onboarding:

```bash
clm agent configure my-agent
# Select my-router when prompted for provider
```

## Model Routing

You can switch models without changing providers:

```bash
clm provider edit my-router --model deepseek/deepseek-chat-v3
```

Then restart your agent to use the new model.

## Troubleshooting

**"Model not available"**
- Check OpenRouter model status page
- Some models may have temporary outages
- Try a fallback model

**"Credits exhausted"**
- Add credits in OpenRouter dashboard
- Set up auto-recharge for production use

---

[Back to Providers](index.md)

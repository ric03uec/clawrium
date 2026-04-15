# OpenAI Provider

**Status:** ✅ Supported

Official OpenAI API integration for GPT models.

## Supported Models

- `gpt-4o` - Latest flagship model
- `gpt-4o-mini` - Fast, cost-effective
- `gpt-4-turbo` - Previous generation
- `gpt-4` - Original GPT-4
- `gpt-3.5-turbo` - Cost-optimized
- `o1` - Reasoning model
- `o1-mini` - Fast reasoning
- `o1-preview` - Reasoning preview

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

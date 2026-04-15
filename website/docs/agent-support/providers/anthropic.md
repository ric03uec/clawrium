# Anthropic

**Status:** ✅ Supported

Official Anthropic Claude API integration.

## Supported Models

- `claude-opus-4-20250514` - Most capable
- `claude-sonnet-4-20250514` - Balanced performance
- `claude-3-5-sonnet-20241022` - Previous generation
- `claude-3-5-haiku-20241022` - Fast, cost-effective
- `claude-3-opus-20240229` - Original Opus
- `claude-3-sonnet-20240229` - Original Sonnet
- `claude-3-haiku-20240307` - Original Haiku

## Setup

### 1. Get API Key

1. Visit [Anthropic Console](https://console.anthropic.com/)
2. Create or log in to your account
3. Go to **API keys** → **Create Key**
4. Copy the key (starts with `sk-ant-`)

### 2. Add to Clawrium

```bash
clm provider add my-claude --type anthropic
```

You will be prompted to enter your API key securely.

### 3. Select Model

Choose a default model during setup:
- `claude-opus-4-20250514` (best quality)
- `claude-sonnet-4-20250514` (recommended balance)
- `claude-3-5-haiku-20241022` (fastest)

## Configuration

```bash
# View provider details
clm provider list

# Change default model
clm provider edit my-claude --model claude-sonnet-4-20250514

# Update API key
clm provider edit my-claude --update-key

# Remove provider
clm provider remove my-claude
```

## Pricing Considerations

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| Claude Opus 4 | $15.00 | $75.00 |
| Claude Sonnet 4 | $3.00 | $15.00 |
| Claude 3.5 Haiku | $0.25 | $1.25 |

*Prices subject to change. Check [Anthropic pricing](https://www.anthropic.com/pricing) for current rates.*

## Why Claude?

- **Longer context:** Up to 200K tokens on some models
- **Strong reasoning:** Excellent for complex tasks
- **Constitutional AI:** Built-in safety measures
- **Vision support:** Some models support image input

## Usage in Agents

During agent onboarding:

```bash
clm agent configure my-agent
# Select my-claude when prompted for provider
```

## Troubleshooting

**"Invalid API key"**
- Verify the key starts with `sk-ant-`
- Check your Anthropic console for active keys

**"Rate limit exceeded"**
- Check your Anthropic usage dashboard
- Contact Anthropic for rate limit increases

---

[Back to Providers](index.md)

# Anthropic

**Status:** ✅ Supported

Official Anthropic Claude API integration.

## Supported Models

<!-- MODEL-TABLE:START -->
| Model ID | Name | Context |
|----------|------|---------|
| `claude-3-haiku-20240307` | Claude Haiku 3 | 200K |
| `claude-3-5-haiku-20241022` | Claude Haiku 3.5 | 200K |
| `claude-3-5-haiku-latest` | Claude Haiku 3.5 (latest) | 200K |
| `claude-haiku-4-5-20251001` | Claude Haiku 4.5 | 200K |
| `claude-haiku-4-5` | Claude Haiku 4.5 (latest) | 200K |
| `claude-3-opus-20240229` | Claude Opus 3 | 200K |
| `claude-opus-4-20250514` | Claude Opus 4 | 200K |
| `claude-opus-4-0` | Claude Opus 4 (latest) | 200K |
| `claude-opus-4-1-20250805` | Claude Opus 4.1 | 200K |
| `claude-opus-4-1` | Claude Opus 4.1 (latest) | 200K |
| `claude-opus-4-5-20251101` | Claude Opus 4.5 | 200K |
| `claude-opus-4-5` | Claude Opus 4.5 (latest) | 200K |
| `claude-opus-4-6` | Claude Opus 4.6 | 1M |
| `claude-opus-4-7` | Claude Opus 4.7 | 1M |
| `claude-3-sonnet-20240229` | Claude Sonnet 3 | 200K |
| `claude-3-5-sonnet-20240620` | Claude Sonnet 3.5 | 200K |
| `claude-3-5-sonnet-20241022` | Claude Sonnet 3.5 v2 | 200K |
| `claude-3-7-sonnet-20250219` | Claude Sonnet 3.7 | 200K |
| `claude-sonnet-4-20250514` | Claude Sonnet 4 | 200K |
| `claude-sonnet-4-0` | Claude Sonnet 4 (latest) | 200K |
| `claude-sonnet-4-5-20250929` | Claude Sonnet 4.5 | 200K |
| `claude-sonnet-4-5` | Claude Sonnet 4.5 (latest) | 200K |
| `claude-sonnet-4-6` | Claude Sonnet 4.6 | 1M |
<!-- MODEL-TABLE:END -->

## Setup

### 1. Get API Key

1. Visit [Anthropic Console](https://console.anthropic.com/)
2. Create or log in to your account
3. Go to **API keys** → **Create Key**
4. Copy the key (starts with `sk-ant-`)

### 2. Add to Clawrium

```bash
clawctl provider registry create my-claude --type anthropic
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
clawctl provider registry get

# Change default model
clawctl provider registry edit my-claude --model claude-sonnet-4-20250514

# Update API key
clawctl provider registry edit my-claude --update-key

# Remove provider
clawctl provider registry delete my-claude
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
clawctl agent configure my-agent
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

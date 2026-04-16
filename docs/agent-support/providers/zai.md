# ZAI / BigModel

**Status:** ✅ Supported

Zhipu AI (ZAI) BigModel platform provides access to GLM (General Language Model) series.

## Supported Models

- `glm-4` - General purpose
- `glm-4-plus` - Enhanced capabilities
- `glm-4-air` - Fast inference
- `glm-4-airx` - Extended context
- `glm-4-flash` - Ultra-fast
- `glm-4-long` - Long context
- `glm-4v` - Vision capable
- `glm-4v-plus` - Enhanced vision

## Setup

### 1. Get API Key

1. Visit [BigModel Platform](https://open.bigmodel.cn/)
2. Create or log in to your account
3. Go to **API Keys** → **Create API Key**
4. Copy the key

### 2. Add to Clawrium

```bash
clm provider add my-zai --type zai
```

You will be prompted to enter your API key securely.

### 3. Select Model

Choose a default model during setup:
- `glm-4` (general purpose)
- `glm-4-plus` (enhanced)
- `glm-4-flash` (fastest)

## Configuration

```bash
# View provider details
clm provider list

# Change default model
clm provider edit my-zai --model glm-4-plus

# Update API key
clm provider edit my-zai --update-key

# Remove provider
clm provider remove my-zai
```

## Pricing

ZAI offers competitive pricing, especially for the China region. Check [BigModel pricing](https://open.bigmodel.cn/pricing) for current rates.

## Benefits

- **China region:** Optimized for China-based deployments
- **GLM models:** Strong Chinese language support
- **Vision models:** GLM-4V supports image understanding
- **Competitive pricing:** Often cheaper than western providers

## Usage in Agents

During agent onboarding:

```bash
clm agent configure my-agent
# Select my-zai when prompted for provider
```

## Region Considerations

- API endpoint: `https://open.bigmodel.cn/api/paas/v4`
- Optimized for China region
- May have higher latency from other regions

## Troubleshooting

**"Invalid API key"**
- Verify the key is active in BigModel console
- Check account has available credits

**"High latency"**
- Expected if connecting from outside China
- Consider using a different provider for non-China deployments

---

[Back to Providers](index.md)

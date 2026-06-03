# AWS Bedrock

**Status:** ✅ Supported

Amazon Bedrock provides managed access to foundation models through AWS infrastructure.

## Supported Models

<!-- MODEL-TABLE:START -->
| Model ID | Name | Context |
|----------|------|---------|
| `au.anthropic.claude-opus-4-6-v1` | AU Anthropic Claude Opus 4.6 | 1M |
| `au.anthropic.claude-sonnet-4-6` | AU Anthropic Claude Sonnet 4.6 | 1M |
| `anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 | 200K |
| `au.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 (AU) | 200K |
| `eu.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 (EU) | 200K |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 (Global) | 200K |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 (US) | 200K |
| `anthropic.claude-opus-4-1-20250805-v1:0` | Claude Opus 4.1 | 200K |
| `us.anthropic.claude-opus-4-1-20250805-v1:0` | Claude Opus 4.1 (US) | 200K |
| `anthropic.claude-opus-4-5-20251101-v1:0` | Claude Opus 4.5 | 200K |
| `eu.anthropic.claude-opus-4-5-20251101-v1:0` | Claude Opus 4.5 (EU) | 200K |
| `global.anthropic.claude-opus-4-5-20251101-v1:0` | Claude Opus 4.5 (Global) | 200K |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | Claude Opus 4.5 (US) | 200K |
| `anthropic.claude-opus-4-6-v1` | Claude Opus 4.6 | 1M |
| `eu.anthropic.claude-opus-4-6-v1` | Claude Opus 4.6 (EU) | 1M |
| `global.anthropic.claude-opus-4-6-v1` | Claude Opus 4.6 (Global) | 1M |
| `us.anthropic.claude-opus-4-6-v1` | Claude Opus 4.6 (US) | 1M |
| `anthropic.claude-opus-4-7` | Claude Opus 4.7 | 1M |
| `eu.anthropic.claude-opus-4-7` | Claude Opus 4.7 (EU) | 1M |
| `global.anthropic.claude-opus-4-7` | Claude Opus 4.7 (Global) | 1M |
| `jp.anthropic.claude-opus-4-7` | Claude Opus 4.7 (JP) | 1M |
| `us.anthropic.claude-opus-4-7` | Claude Opus 4.7 (US) | 1M |
| `anthropic.claude-opus-4-8` | Claude Opus 4.8 | 1M |
| `au.anthropic.claude-opus-4-8` | Claude Opus 4.8 (AU) | 1M |
| `eu.anthropic.claude-opus-4-8` | Claude Opus 4.8 (EU) | 1M |
| `global.anthropic.claude-opus-4-8` | Claude Opus 4.8 (Global) | 1M |
| `jp.anthropic.claude-opus-4-8` | Claude Opus 4.8 (JP) | 1M |
| `us.anthropic.claude-opus-4-8` | Claude Opus 4.8 (US) | 1M |
| `anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude Sonnet 4.5 | 200K |
| `au.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude Sonnet 4.5 (AU) | 200K |
| `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude Sonnet 4.5 (EU) | 200K |
| `global.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude Sonnet 4.5 (Global) | 200K |
| `jp.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude Sonnet 4.5 (JP) | 200K |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude Sonnet 4.5 (US) | 200K |
| `anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 | 1M |
| `eu.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 (EU) | 1M |
| `global.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 (Global) | 1M |
| `jp.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 (JP) | 1M |
| `us.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 (US) | 1M |
| `deepseek.r1-v1:0` | DeepSeek-R1 | 128K |
| `us.deepseek.r1-v1:0` | DeepSeek-R1 (US) | 128K |
| `deepseek.v3-v1:0` | DeepSeek-V3.1 | 163K |
| `deepseek.v3.2` | DeepSeek-V3.2 | 163K |
| `mistral.devstral-2-123b` | Devstral 2 123B | 256K |
| `zai.glm-4.7` | GLM-4.7 | 204K |
| `zai.glm-4.7-flash` | GLM-4.7-Flash | 200K |
| `zai.glm-5` | GLM-5 | 202K |
| `openai.gpt-oss-safeguard-120b` | GPT OSS Safeguard 120B | 128K |
| `openai.gpt-oss-safeguard-20b` | GPT OSS Safeguard 20B | 128K |
| `google.gemma-3-4b-it` | Gemma 3 4B IT | 128K |
| `google.gemma-3-12b-it` | Google Gemma 3 12B | 131K |
| `google.gemma-3-27b-it` | Google Gemma 3 27B Instruct | 202K |
| `moonshot.kimi-k2-thinking` | Kimi K2 Thinking | 262K |
| `moonshotai.kimi-k2.5` | Kimi K2.5 | 262K |
| `meta.llama3-1-70b-instruct-v1:0` | Llama 3.1 70B Instruct | 128K |
| `meta.llama3-1-8b-instruct-v1:0` | Llama 3.1 8B Instruct | 128K |
| `meta.llama3-3-70b-instruct-v1:0` | Llama 3.3 70B Instruct | 128K |
| `meta.llama4-maverick-17b-instruct-v1:0` | Llama 4 Maverick 17B Instruct | 1M |
| `us.meta.llama4-maverick-17b-instruct-v1:0` | Llama 4 Maverick 17B Instruct (US) | 1M |
| `meta.llama4-scout-17b-instruct-v1:0` | Llama 4 Scout 17B Instruct | 3M |
| `us.meta.llama4-scout-17b-instruct-v1:0` | Llama 4 Scout 17B Instruct (US) | 3M |
| `mistral.magistral-small-2509` | Magistral Small 1.2 | 128K |
| `minimax.minimax-m2` | MiniMax M2 | 204K |
| `minimax.minimax-m2.1` | MiniMax M2.1 | 204K |
| `minimax.minimax-m2.5` | MiniMax M2.5 | 196K |
| `mistral.ministral-3-14b-instruct` | Ministral 14B 3.0 | 128K |
| `mistral.ministral-3-3b-instruct` | Ministral 3 3B | 256K |
| `mistral.ministral-3-8b-instruct` | Ministral 3 8B | 128K |
| `mistral.mistral-large-3-675b-instruct` | Mistral Large 3 | 256K |
| `nvidia.nemotron-super-3-120b` | NVIDIA Nemotron 3 Super 120B A12B | 262K |
| `nvidia.nemotron-nano-12b-v2` | NVIDIA Nemotron Nano 12B v2 VL BF16 | 128K |
| `nvidia.nemotron-nano-3-30b` | NVIDIA Nemotron Nano 3 30B | 128K |
| `nvidia.nemotron-nano-9b-v2` | NVIDIA Nemotron Nano 9B v2 | 128K |
| `amazon.nova-2-lite-v1:0` | Nova 2 Lite | 128K |
| `amazon.nova-lite-v1:0` | Nova Lite | 300K |
| `amazon.nova-micro-v1:0` | Nova Micro | 128K |
| `amazon.nova-pro-v1:0` | Nova Pro | 300K |
| `writer.palmyra-x4-v1:0` | Palmyra X4 | 122K |
| `writer.palmyra-x5-v1:0` | Palmyra X5 | 1M |
| `mistral.pixtral-large-2502-v1:0` | Pixtral Large (25.02) | 128K |
| `qwen.qwen3-next-80b-a3b` | Qwen/Qwen3-Next-80B-A3B-Instruct | 262K |
| `qwen.qwen3-vl-235b-a22b` | Qwen/Qwen3-VL-235B-A22B-Instruct | 262K |
| `qwen.qwen3-235b-a22b-2507-v1:0` | Qwen3 235B A22B 2507 | 262K |
| `qwen.qwen3-32b-v1:0` | Qwen3 32B (dense) | 16K |
| `qwen.qwen3-coder-30b-a3b-v1:0` | Qwen3 Coder 30B A3B Instruct | 262K |
| `qwen.qwen3-coder-480b-a35b-v1:0` | Qwen3 Coder 480B A35B Instruct | 131K |
| `qwen.qwen3-coder-next` | Qwen3 Coder Next | 131K |
| `mistral.voxtral-mini-3b-2507` | Voxtral Mini 3B 2507 | 128K |
| `mistral.voxtral-small-24b-2507` | Voxtral Small 24B 2507 | 32K |
| `openai.gpt-oss-120b-1:0` | gpt-oss-120b | 128K |
| `openai.gpt-oss-20b-1:0` | gpt-oss-20b | 128K |
<!-- MODEL-TABLE:END -->

## Setup

### 1. AWS Credentials

You need AWS credentials with Bedrock access:

1. Go to [AWS IAM Console](https://console.aws.amazon.com/iam/)
2. Create or use an existing user
3. Attach policy: `AmazonBedrockFullAccess`
4. Create access key (Access Key ID + Secret Access Key)

### 2. Enable Model Access

1. Go to [Amazon Bedrock Console](https://console.aws.amazon.com/bedrock/)
2. Navigate to **Model access**
3. Request access for desired models (Claude, Llama, etc.)
4. Wait for approval (usually instant)

### 3. Add to Clawrium

```bash
clawctl provider registry create my-bedrock --type bedrock
```

You will be prompted to enter:
- AWS Access Key ID
- AWS Secret Access Key

### 4. Select Model

Choose a default model during setup:
- `anthropic.claude-opus-4-20250514-v1:0` (best quality)
- `anthropic.claude-sonnet-4-20250514-v1:0` (recommended)

## Configuration

```bash
# View provider details
clawctl provider registry get

# Change default model
clawctl provider registry edit my-bedrock --model anthropic.claude-sonnet-4-20250514-v1:0

# Update AWS credentials
clawctl provider registry edit my-bedrock --update-key

# Remove provider
clawctl provider registry delete my-bedrock
```

## Pricing

Bedrock uses on-demand pricing per 1K tokens. Check [AWS Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) for current rates.

Example approximate costs:
- Claude Sonnet 4: ~$3/1M input tokens, ~$15/1M output tokens
- Llama 3 70B: ~$0.72/1M input tokens

## Benefits

- **AWS ecosystem:** Integrates with existing AWS infrastructure
- **Compliance:** SOC 2, HIPAA, GDPR compliant
- **Private connectivity:** VPC endpoints available
- **No API keys:** Uses AWS IAM for authentication

## Security

- Credentials stored securely (not in plain text)
- IAM policies control access
- CloudTrail logs API calls
- No data leaves your AWS account

## Usage in Agents

During agent onboarding:

```bash
clawctl agent configure my-agent
# Select my-bedrock when prompted for provider
```

## Troubleshooting

**"Access denied"**
- Verify IAM user has `AmazonBedrockFullAccess`
- Check model access is enabled in Bedrock console
- Ensure credentials are correct

**"Model not available"**
- Request model access in Bedrock console
- Some models require approval (can take 24-48 hours)
- Check your AWS region supports the model

**"Rate limit exceeded"**
- Request quota increase in AWS Support Center
- Consider using provisioned throughput

---

[Back to Providers](index.md)

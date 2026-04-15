# AWS Bedrock Provider

**Status:** ✅ Supported

Amazon Bedrock provides managed access to foundation models through AWS infrastructure.

## Supported Models

- `anthropic.claude-opus-4-20250514-v1:0` - Most capable Claude
- `anthropic.claude-sonnet-4-20250514-v1:0` - Balanced Claude
- `anthropic.claude-3-5-sonnet-20241022-v2:0` - Previous generation
- `anthropic.claude-3-5-haiku-20241022-v1:0` - Fast Claude
- `anthropic.claude-3-haiku-20240307-v1:0` - Original Haiku
- `amazon.titan-text-express-v1` - Amazon Titan
- `amazon.titan-text-lite-v1` - Lightweight Titan
- `meta.llama3-70b-instruct-v1:0` - Meta Llama 3

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
clm provider add my-bedrock --type bedrock
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
clm provider list

# Change default model
clm provider edit my-bedrock --model anthropic.claude-sonnet-4-20250514-v1:0

# Update AWS credentials
clm provider edit my-bedrock --update-key

# Remove provider
clm provider remove my-bedrock
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
clm agent configure my-agent
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

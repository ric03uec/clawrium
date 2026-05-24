# Google Vertex AI

**Status:** ✅ Supported

Google Cloud Vertex AI provides access to Gemini models.

## Supported Models

<!-- MODEL-TABLE:START -->
| Model ID | Name | Context |
|----------|------|---------|
| `deepseek-ai/deepseek-v3.1-maas` | DeepSeek V3.1 | 163K |
| `deepseek-ai/deepseek-v3.2-maas` | DeepSeek V3.2 | 163K |
| `zai-org/glm-4.7-maas` | GLM-4.7 | 200K |
| `zai-org/glm-5-maas` | GLM-5 | 202K |
| `openai/gpt-oss-120b-maas` | GPT OSS 120B | 131K |
| `openai/gpt-oss-20b-maas` | GPT OSS 20B | 131K |
| `gemini-2.0-flash` | Gemini 2.0 Flash | 1M |
| `gemini-2.0-flash-lite` | Gemini 2.0 Flash Lite | 1M |
| `gemini-2.5-flash` | Gemini 2.5 Flash | 1M |
| `gemini-2.5-flash-lite` | Gemini 2.5 Flash Lite | 1M |
| `gemini-2.5-flash-lite-preview-06-17` | Gemini 2.5 Flash Lite Preview 06-17 | 65K |
| `gemini-2.5-flash-lite-preview-09-2025` | Gemini 2.5 Flash Lite Preview 09-25 | 1M |
| `gemini-2.5-flash-preview-04-17` | Gemini 2.5 Flash Preview 04-17 | 1M |
| `gemini-2.5-flash-preview-05-20` | Gemini 2.5 Flash Preview 05-20 | 1M |
| `gemini-2.5-flash-preview-09-2025` | Gemini 2.5 Flash Preview 09-25 | 1M |
| `gemini-2.5-pro` | Gemini 2.5 Pro | 1M |
| `gemini-2.5-pro-preview-05-06` | Gemini 2.5 Pro Preview 05-06 | 1M |
| `gemini-2.5-pro-preview-06-05` | Gemini 2.5 Pro Preview 06-05 | 1M |
| `gemini-3-flash-preview` | Gemini 3 Flash Preview | 1M |
| `gemini-3-pro-preview` | Gemini 3 Pro Preview | 1M |
| `gemini-3.1-pro-preview` | Gemini 3.1 Pro Preview | 1M |
| `gemini-3.1-pro-preview-customtools` | Gemini 3.1 Pro Preview Custom Tools | 1M |
| `gemini-embedding-001` | Gemini Embedding 001 | 2K |
| `gemini-flash-latest` | Gemini Flash Latest | 1M |
| `gemini-flash-lite-latest` | Gemini Flash-Lite Latest | 1M |
| `moonshotai/kimi-k2-thinking-maas` | Kimi K2 Thinking | 262K |
| `meta/llama-3.3-70b-instruct-maas` | Llama 3.3 70B Instruct | 128K |
| `meta/llama-4-maverick-17b-128e-instruct-maas` | Llama 4 Maverick 17B 128E Instruct | 524K |
| `qwen/qwen3-235b-a22b-instruct-2507-maas` | Qwen3 235B A22B Instruct | 262K |
<!-- MODEL-TABLE:END -->

## Setup

### 1. Google Cloud Setup

1. Create or select a [Google Cloud project](https://console.cloud.google.com/)
2. Enable the Vertex AI API:
   ```bash
   gcloud services enable aiplatform.googleapis.com
   ```
3. Ensure billing is enabled

### 2. Authentication

Clawrium uses Application Default Credentials (ADC). Set up authentication:

```bash
# Install gcloud CLI if not already installed
# https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth application-default login
```

Or use a service account:

```bash
# Create service account
gcloud iam service-accounts create clawrium-provider \
  --display-name="Clawrium Provider"

# Grant Vertex AI User role
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:clawrium-provider@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Create and download key
gcloud iam service-accounts keys create key.json \
  --iam-account=clawrium-provider@PROJECT_ID.iam.gserviceaccount.com

# Set environment variable
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

### 3. Add to Clawrium

```bash
clawctl provider registry create my-vertex --type vertex
```

Note: Vertex AI uses Google Cloud authentication, not an API key.

### 4. Select Model

Choose a default model during setup:
- `gemini-2.5-pro` (best quality)
- `gemini-2.5-flash` (recommended balance)

## Configuration

```bash
# View provider details
clawctl provider registry get

# Change default model
clawctl provider registry edit my-vertex --model gemini-2.5-flash

# Remove provider
clawctl provider registry delete my-vertex
```

## Pricing

Vertex AI uses pay-per-use pricing. Check [Vertex AI pricing](https://cloud.google.com/vertex-ai/pricing) for current rates.

Approximate costs:
- Gemini 2.5 Pro: ~$1.25/1M input tokens, ~$10/1M output tokens
- Gemini 2.5 Flash: ~$0.15/1M input tokens, ~$0.60/1M output tokens

## Benefits

- **Google Cloud integration:** Works with GCP services
- **Enterprise features:** Fine-tuning, batch prediction
- **Global infrastructure:** Low latency worldwide
- **Gemini models:** Google's most capable models

## Usage in Agents

During agent onboarding:

```bash
clawctl agent configure my-agent
# Select my-vertex when prompted for provider
```

## Troubleshooting

**"Permission denied"**
- Verify Vertex AI API is enabled
- Check IAM permissions (needs `aiplatform.user`)
- Ensure billing is enabled

**"Authentication failed"**
- Run `gcloud auth application-default login`
- Check `GOOGLE_APPLICATION_CREDENTIALS` is set correctly
- Verify service account has proper roles

**"Model not found"**
- Check your region supports the model
- Verify the model name is correct
- Some models may be in preview/limited availability

---

[Back to Providers](index.md)

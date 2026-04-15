# Google Vertex AI

**Status:** ✅ Supported

Google Cloud Vertex AI provides access to Gemini models.

## Supported Models

- `gemini-2.5-pro` - Latest flagship model
- `gemini-2.5-flash` - Fast, efficient
- `gemini-2.5-flash-lite` - Lightweight version
- `gemini-2.0-flash` - Previous generation
- `gemini-1.5-pro` - Earlier pro model
- `gemini-1.5-flash` - Earlier flash model

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
clm provider add my-vertex --type vertex
```

Note: Vertex AI uses Google Cloud authentication, not an API key.

### 4. Select Model

Choose a default model during setup:
- `gemini-2.5-pro` (best quality)
- `gemini-2.5-flash` (recommended balance)

## Configuration

```bash
# View provider details
clm provider list

# Change default model
clm provider edit my-vertex --model gemini-2.5-flash

# Remove provider
clm provider remove my-vertex
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
clm agent configure my-agent
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

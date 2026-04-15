# Providers

LLM providers supply the AI models that power your agents. Clawrium supports multiple providers, allowing you to choose the best model for your use case.

## Supported Providers

| Provider | Type | Best For |
|----------|------|----------|
| **[OpenAI](openai.md)** | Cloud | GPT-4o, latest models |
| **[Anthropic](anthropic.md)** | Cloud | Claude, long context |
| **[OpenRouter](openrouter.md)** | Gateway | Multi-provider access |
| **[AWS Bedrock](bedrock.md)** | Cloud | AWS ecosystem, compliance |
| **[Google Vertex](vertex.md)** | Cloud | Gemini, Google Cloud |
| **[ZAI / BigModel](zai.md)** | Cloud | GLM models, China region |
| **[Ollama](ollama.md)** | Self-hosted | Local inference, privacy |

## Provider Comparison

| Feature | OpenAI | Anthropic | Ollama |
|---------|--------|-----------|--------|
| **Setup** | API key | API key | Server URL |
| **Cost** | Pay per token | Pay per token | Hardware only |
| **Latency** | Network | Network | Local/Network |
| **Privacy** | Cloud | Cloud | On-premise |
| **Model Choice** | Fixed list | Fixed list | Unlimited |

## Quick Setup

Add a provider in one command:

```bash
# Cloud provider (OpenAI, Anthropic, etc.)
clm provider add my-openai --type openai

# Self-hosted (Ollama)
clm provider add local-llm --type ollama --url http://192.168.1.50:11434
```

Then assign it to an agent during onboarding:

```bash
clm agent configure <agent-name>
# Select provider during the providers stage
```

## Managing Providers

```bash
# List all providers
clm provider list

# View available models
clm provider models <provider-name>

# Edit a provider
clm provider edit <provider-name> --model <new-model>

# Remove a provider
clm provider remove <provider-name>
```

## Security

- API keys are stored securely (not in plain text)
- Keys are never logged or displayed in full
- Per-provider isolation

## Troubleshooting

**"Provider connectivity failed"**
- Verify API key is valid
- Check network connectivity from the host
- Ensure provider service is operational

**"No models available"** (Ollama)
- SSH to the Ollama host
- Run: `ollama list` to verify models are pulled
- Pull models: `ollama pull <model-name>`

---

See individual provider pages for detailed setup instructions.

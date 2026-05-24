# Azure OpenAI

**Status:** 📋 Not Currently Planned

Azure OpenAI Service provides OpenAI models through Microsoft Azure infrastructure.

---

## Why Not Planned?

Azure OpenAI is not currently on the Clawrium roadmap for the following reasons:

1. **Overlap:** Standard OpenAI provider already covers GPT models
2. **Complexity:** Azure AD authentication adds setup friction
3. **Priority:** Community demand has been low compared to other providers
4. **Focus:** Development resources are focused on Ollama, Bedrock, and Vertex

---

## Want This Feature?

We welcome community contributions! If you need Azure OpenAI support:

### Option 1: Open an Issue

[Create a feature request](https://github.com/ric03uec/clawrium/issues/new?labels=enhancement,provider&title=Add+Azure+OpenAI+provider+support)

Include:
- Your use case
- Why existing providers don't meet your needs
- Whether you can contribute a PR

### Option 2: Submit a PR

We'd love your contribution! Implementation would involve:

1. Add Azure provider type to `src/clawrium/core/providers.py`
2. Handle Azure AD authentication (service principal or managed identity)
3. Support Azure-specific endpoints and model deployment names
4. Add tests and documentation

See [CONTRIBUTING.md](/docs/contributing) for guidelines.

### Option 3: Use OpenRouter

As a workaround, you can use [OpenRouter](openrouter.md) which may provide Azure-hosted models:

```bash
clawctl provider registry create my-router --type openrouter
# Select Azure-hosted models if available
```

---

## What Would Be Needed

If implementing Azure OpenAI support, the following would be required:

**Authentication Options:**
- Service Principal (Client ID, Client Secret, Tenant ID)
- Managed Identity (for Azure-hosted agents)
- Azure CLI credentials (for development)

**Configuration:**
- Azure OpenAI Endpoint (e.g., `https://<resource>.openai.azure.com/`)
- Deployment name (Azure uses custom deployment names, not model names)
- API version

**Differences from Standard OpenAI:**
- Model access controlled by Azure
- Different authentication flow
- Custom deployment names instead of model names
- Regional availability varies

---

## Vote for This Feature

Add a 👍 reaction to [this issue](https://github.com/ric03uec/clawrium/issues) to help us prioritize.

---

[Back to Providers](index.md)
